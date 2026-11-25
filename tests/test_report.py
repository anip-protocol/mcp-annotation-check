import json
from dataclasses import replace

from mcp_annotation_check.cli import main
from mcp_annotation_check.pack import load_pack
from mcp_annotation_check.report import write_reports
from support import FAKE_PACK, run_fake, with_entries


async def written(tmp_path, pack=None):
    header, results = await run_fake(pack=pack)
    write_reports(header, results, tmp_path)
    return (
        (tmp_path / "report.md").read_text(),
        json.loads((tmp_path / "report.json").read_text()),
        (tmp_path / "private-findings.md").read_text(),
    )


async def test_private_finding_withheld_from_public_report(tmp_path):
    md, data, private = await written(tmp_path)
    assert "peek_and_touch" in private
    assert "report privately" in private.lower()
    assert "peeked" in private  # the evidence lives in the private file
    assert "peek_and_touch" not in md
    assert "peeked" not in md
    assert "withheld: see private-findings.md" in md
    public_tools = {r["tool"] for r in data["results"]}
    assert "peek_and_touch" not in public_tools
    assert data["withheld"] == 1
    assert "peeked" not in json.dumps(data["results"])


async def test_private_findings_file_says_none_when_empty(tmp_path):
    pack = load_pack(FAKE_PACK)
    pack = with_entries(
        pack,
        peek_and_touch=replace(
            pack.entries["peek_and_touch"], status="skipped", skip_reason="not today"
        ),
    )
    md, data, private = await written(tmp_path, pack)
    assert "none" in private.lower()
    assert data["withheld"] == 0
    assert "withheld" not in md


async def test_report_json_has_header_fields(tmp_path):
    _, data, _ = await written(tmp_path)
    header = data["header"]
    assert len(header["tools_list_sha256"]) == 64
    assert header["sdk_version"]
    assert header["features"] == []
    assert header["deployment"] == "in-memory"
    assert header["harness_version"] == "0.1.0"
    assert {t["name"] for t in header["tools_list"]} >= {"get_issue", "explode"}
    results = {r["tool"]: r for r in data["results"]}
    assert results["set_labels"]["outcome"] == "finding"
    assert results["set_labels"]["review"] == "unreviewed"
    labels = results["set_labels"]["verdicts"][0]["changed"]["issue.labels"]
    assert labels == [["c", "d"], ["x"]]


async def test_markdown_sections(tmp_path):
    md, _, _ = await written(tmp_path)
    assert "Findings apply to this image and configuration only." in md
    assert "| in-memory |" in md
    # coverage counts
    assert "| finding | 3 |" in md
    assert "| pass | 3 |" in md
    assert "| observation | 1 |" in md
    # a judged tool: claim, schema text as a blockquote, calls, diff, scope line
    section = md.split("### set_labels", 1)[1].split("\n### ", 1)[0]
    assert "destructiveHint: false" in section
    assert (
        "> If true, the tool may perform destructive updates to its environment. "
        "If false, the tool performs only additive updates." in section
    )
    assert '"tool": "set_labels"' in section
    assert "- c" in section and "+ x" in section
    assert "unreviewed" in section
    # the "not observed" limit is visible for a passing tool
    counter = md.split("### bump_hidden_counter", 1)[1].split("\n### ", 1)[0]
    assert "no change observed in issue.labels, issue.title, issue.notes" in counter
    # an errored call that still changed state shows its error
    explode = md.split("### explode", 1)[1].split("\n### ", 1)[0]
    assert "Error executing tool explode" in explode


def test_cli_self_test_writes_reports(tmp_path, capsys):
    assert main(["self-test", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert str(tmp_path / "report.md") in out
    assert "finding" in out
    for name in ("report.md", "report.json", "private-findings.md"):
        assert (tmp_path / name).is_file()
