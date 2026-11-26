import json
from dataclasses import replace

from mcp_annotation_check.cli import main
from mcp_annotation_check.pack import load_pack
from mcp_annotation_check.report import write_reports
from mcp_annotation_check.rules import Outcome
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
    # an additive pass shows its evidence and says nothing was removed
    add = md.split("### add_labels", 1)[1].split("\n### ", 1)[0]
    assert (
        "nothing removed or overwritten in issue.labels; additions in issue.labels" in add
    )
    assert "@@ issue.labels @@ additive" in add
    assert "  c" in add and "+ x" in add
    assert "@@ issue.labels @@ lost or overwritten" in section
    # read-only and idempotent findings mark their fields as changed
    note = md.split("### append_note", 1)[1].split("\n### ", 1)[0]
    assert "@@ issue.notes @@ changed" in note
    # an errored call that still changed state shows its error
    explode = md.split("### explode", 1)[1].split("\n### ", 1)[0]
    assert "Error executing tool explode" in explode


def test_cli_self_test_writes_reports(tmp_path, capsys):
    assert main(["self-test", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert str(tmp_path / "report.md") in out
    assert "finding" in out
    assert "Do not publish this report until every withheld finding is fixed" in out
    for name in ("report.md", "report.json", "private-findings.md"):
        assert (tmp_path / name).is_file()


def test_unjudged_verdict_diff_is_marked_not_judged():
    from mcp_annotation_check.claims import Check
    from mcp_annotation_check.report import _diff_text
    from mcp_annotation_check.snapshot import Outcome, Verdict

    v = Verdict(
        Check.NON_DESTRUCTIVE,
        Outcome.ERROR,
        "field issue.comments can't be judged non-destructively yet (composite elements)",
        diff={"issue.comments": (frozenset({(1, "old")}), frozenset({(1, "new")}))},
    )
    text = _diff_text(v)
    assert "@@ issue.comments @@ not judged" in text
    assert "additive" not in text


async def test_withheld_results_block_publication(tmp_path):
    md, data, _ = await written(tmp_path)
    notice = "Do not publish this report until every withheld finding is fixed"
    assert data["publish_blocked"] is True
    assert data["publish_notice"] == (
        "Do not publish this report until every withheld finding is fixed by the server's "
        "maintainers or 90 days have passed since it was reported to them privately, "
        "whichever comes first. A reader can infer the withheld tool from this report (the "
        "full tools/list is in the header). Findings that are already public may be posted "
        "separately."
    )
    assert data["publish_notice"].startswith(notice)
    # prominent: the banner comes before the run header
    assert notice in md
    assert md.index(notice) < md.index("## Run")
    assert md.splitlines()[2].startswith(f"> **{notice}")


async def test_nothing_withheld_has_no_publish_banner(tmp_path):
    pack = load_pack(FAKE_PACK)
    pack = with_entries(
        pack,
        peek_and_touch=replace(
            pack.entries["peek_and_touch"], status="skipped", skip_reason="not today"
        ),
    )
    md, data, _ = await written(tmp_path, pack)
    assert data["publish_blocked"] is False
    assert data["publish_notice"] is None
    assert "Do not publish" not in md


def test_unjudged_counts_in_coverage():
    from mcp_annotation_check.claims import Check
    from mcp_annotation_check.report import ToolResult, coverage
    from mcp_annotation_check.rules import Outcome
    from mcp_annotation_check.snapshot import Verdict

    def result(tool, outcome, *verdict_outcomes):
        return ToolResult(
            tool=tool,
            description="",
            claims=None,
            outcome=outcome,
            verdicts=[Verdict(Check.NON_DESTRUCTIVE, o, "") for o in verdict_outcomes],
            skip_reason=None,
            error=None,
            calls=[],
            waited_s=0.0,
            custom=None,
            private=False,
        )

    counts = coverage(
        [
            result("a", Outcome.FINDING, Outcome.FINDING, Outcome.UNJUDGED),
            result("b", Outcome.UNJUDGED, Outcome.UNJUDGED),
        ]
    )
    assert counts["finding"] == 1
    assert counts["unjudged"] == 1
    assert counts["error"] == 0


def test_observation_under_unjudged_is_counted():
    from mcp_annotation_check.claims import Check
    from mcp_annotation_check.report import ToolResult, coverage, verdict_counts
    from mcp_annotation_check.rules import Outcome
    from mcp_annotation_check.snapshot import Verdict

    def result(tool, outcome, *verdict_outcomes, private=False):
        return ToolResult(
            tool=tool,
            description="",
            claims=None,
            outcome=outcome,
            verdicts=[Verdict(Check.NON_DESTRUCTIVE, o, "") for o in verdict_outcomes],
            skip_reason=None,
            error=None,
            calls=[],
            waited_s=0.0,
            custom=None,
            private=private,
        )

    a = result("a", Outcome.UNJUDGED, Outcome.UNJUDGED, Outcome.OBSERVATION)
    b = result("b", Outcome.FINDING, Outcome.FINDING, Outcome.PASS)
    c = result("c", Outcome.FINDING, Outcome.FINDING, private=True)
    results = [a, b]
    assert coverage(results)["unjudged"] == 1
    assert coverage(results)["observation"] == 0
    assert verdict_counts(results) == {
        "finding": 1,
        "observation": 1,
        "unjudged": 1,
        "pass": 1,
    }



async def test_withheld_tool_is_not_in_the_public_verdict_counts(tmp_path):
    header, results = await run_fake()
    template = next(r for r in results if r.verdicts)
    finding = replace(template, verdicts=[replace(template.verdicts[0], outcome=Outcome.FINDING)])
    public = replace(finding, tool="public_tool", outcome=Outcome.FINDING, private=False)
    secret = replace(finding, tool="secret_tool", outcome=Outcome.FINDING, private=True)
    write_reports(header, [public, secret], tmp_path)
    data = json.loads((tmp_path / "report.json").read_text())
    md = (tmp_path / "report.md").read_text()
    assert data["verdict_counts"]["finding"] == 1
    assert data["withheld"] == 1
    assert "| finding | 1 |" in md
    assert "secret_tool" not in md


EXPECTED_COUNTS = {"finding": 3, "observation": 1, "unjudged": 0, "pass": 4}


async def test_report_files_carry_verdict_counts(tmp_path):
    md, data, _ = await written(tmp_path)
    assert set(data["verdict_counts"]) == {"finding", "observation", "unjudged", "pass"}
    assert data["verdict_counts"] == EXPECTED_COUNTS
    for name, count in EXPECTED_COUNTS.items():
        assert f"| {name} | {count} |" in md.split("Tools with at least one verdict")[1]
    assert "Tools with at least one verdict of each kind" in md
    assert md.index("## Coverage") < md.index("Tools with at least one verdict") < md.index("## Tools")


def _unjudged_result():
    from mcp_annotation_check.claims import Check, Claims
    from mcp_annotation_check.report import ToolResult
    from mcp_annotation_check.rules import Outcome
    from mcp_annotation_check.snapshot import Verdict

    detail = "composite fields not judged: issue.comments"
    return ToolResult(
        tool="comment_tool",
        description="",
        claims=Claims(read_only=None, destructive=False, idempotent=None),
        outcome=Outcome.UNJUDGED,
        verdicts=[Verdict(Check.NON_DESTRUCTIVE, Outcome.UNJUDGED, detail)],
        skip_reason=None,
        error=None,
        calls=[],
        waited_s=0.0,
        custom=None,
        private=False,
    ), detail


def test_unjudged_tools_are_listed_with_reasons_in_summary():
    from mcp_annotation_check.cli import _summary

    result, detail = _unjudged_result()
    (line,) = _summary([result])
    assert "comment_tool: unjudged" in line and detail in line


async def test_unjudged_tools_are_listed_with_reasons_in_the_coverage_section(tmp_path):
    header, _ = await run_fake()
    result, detail = _unjudged_result()
    write_reports(header, [result], tmp_path)
    md = (tmp_path / "report.md").read_text()
    coverage_section = md.split("## Coverage", 1)[1].split("## Tools", 1)[0]
    assert "Unjudged:" in coverage_section
    assert f"- `comment_tool`: {detail}" in coverage_section


async def test_header_lists_no_target_tools(tmp_path):
    from mcp_annotation_check.fake.server import FakeStore, build_fake_server

    store = FakeStore()
    server = build_fake_server(store)

    # No annotations, so the tool is not called: the fake reader only knows issues.
    @server.tool(name="who_am_i")
    def who_am_i(query: str = "") -> str:
        return "me"

    pack = load_pack(FAKE_PACK)
    entry = replace(
        pack.entries["get_issue"],
        tool="who_am_i",
        fixture=None,
        arguments={"query": "me"},
        argument_roles={"query": "other"},
    )
    pack = replace(
        pack, entries={**pack.entries, "who_am_i": entry}, no_target_tools=["who_am_i"]
    )
    header, results = await run_fake(pack=pack, store=store, server=server)
    assert header.pack_problems == []
    assert header.no_target_tools == ["who_am_i"]
    write_reports(header, results, tmp_path)
    data = json.loads((tmp_path / "report.json").read_text())
    assert data["header"]["no_target_tools"] == ["who_am_i"]
    md = (tmp_path / "report.md").read_text()
    assert "| No-target tools | who_am_i |" in md


async def test_header_says_none_without_no_target_tools(tmp_path):
    md, data, _ = await written(tmp_path)
    assert data["header"]["no_target_tools"] == []
    assert "| No-target tools | none |" in md
