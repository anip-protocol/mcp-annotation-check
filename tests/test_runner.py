from dataclasses import replace

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from mcp_annotation_check.claims import SCHEMA_TEXT, Check
from mcp_annotation_check.fake.reader import FakeReader
from mcp_annotation_check.fake.server import FakeStore, build_fake_server
from mcp_annotation_check.pack import load_pack
from mcp_annotation_check.report import write_reports
from mcp_annotation_check.rules import Outcome
from mcp_annotation_check.runner import CUSTOM_SETUPS, CUSTOM_VERDICTS, ToolResult
from mcp_annotation_check.settle import SettleTimeout, settle
from mcp_annotation_check.snapshot import Recorded, Verdict
from support import FAKE_PACK, run_fake, with_entries

EXPECTED = {
    "get_issue": Outcome.PASS,
    "peek_and_touch": Outcome.FINDING,
    "set_labels": Outcome.FINDING,
    "add_labels": Outcome.PASS,
    "rename_issue": Outcome.OBSERVATION,
    "append_note": Outcome.FINDING,
    "bump_hidden_counter": Outcome.PASS,
    "explode": Outcome.FINDING,
}


def by_tool(results: list[ToolResult]) -> dict[str, ToolResult]:
    return {r.tool: r for r in results}


# --- settle ---------------------------------------------------------------


async def test_settle_returns_once_reads_are_stable():
    values = iter([1, 2, 3, 3, 3])

    async def read() -> Recorded:
        return Recorded({"x": next(values)})

    recorded, waited = await settle(read, interval_s=0.001, timeout_s=1.0)
    assert recorded.snapshot == {"x": 3}
    assert waited >= 0


async def test_settle_ignores_timestamps():
    n = iter(range(100))

    async def read() -> Recorded:
        return Recorded({"x": 1}, {"issue": str(next(n))})

    recorded, _ = await settle(read, interval_s=0.001, timeout_s=1.0)
    assert recorded.snapshot == {"x": 1}


async def test_settle_raises_when_state_keeps_changing():
    n = iter(range(10_000))

    async def read() -> Recorded:
        return Recorded({"x": next(n)})

    with pytest.raises(SettleTimeout, match="did not settle within 0.05s"):
        await settle(read, interval_s=0.001, timeout_s=0.05)


# --- run against the fake server -----------------------------------------


async def test_self_test_outcomes():
    header, results = await run_fake()
    outcomes = {r.tool: r.outcome for r in results}
    assert outcomes == EXPECTED
    got = by_tool(results)
    assert got["peek_and_touch"].private is True
    assert all(not r.private for r in results if r.tool != "peek_and_touch")
    assert all(r.review == "unreviewed" for r in results)


async def test_two_checks_feed_one_outcome():
    _, results = await run_fake()
    note = by_tool(results)["append_note"]
    verdicts = {v.check: v.outcome for v in note.verdicts}
    assert verdicts == {Check.NON_DESTRUCTIVE: Outcome.PASS, Check.IDEMPOTENT: Outcome.FINDING}
    assert len(note.calls) == 2
    assert note.calls[0]["arguments"] == note.calls[1]["arguments"]


async def test_read_only_uses_standard_fields():
    _, results = await run_fake()
    get = by_tool(results)["get_issue"]
    (verdict,) = get.verdicts
    assert verdict.check is Check.READ_ONLY
    assert "issue.labels" in verdict.detail and "issue.notes" in verdict.detail


async def test_calls_are_recorded():
    _, results = await run_fake()
    call = by_tool(results)["set_labels"].calls[0]
    assert call["tool"] == "set_labels"
    assert call["arguments"]["labels"] == ["x"]
    assert call["is_error"] is False
    assert "labels=['x']" in call["content"]


async def test_error_with_state_change_is_finding():
    _, results = await run_fake()
    explode = by_tool(results)["explode"]
    assert explode.outcome is Outcome.FINDING
    assert explode.error is not None and "Error executing tool explode" in explode.error
    assert explode.calls[0]["is_error"] is True
    (verdict,) = explode.verdicts
    assert verdict.changed["issue.labels"] == (frozenset({"c", "d"}), frozenset({"d"}))


async def test_additive_pass_carries_its_diff():
    _, results = await run_fake()
    (verdict,) = by_tool(results)["add_labels"].verdicts
    assert verdict.outcome is Outcome.PASS
    assert verdict.diff == {"issue.labels": (frozenset({"c", "d"}), frozenset({"c", "d", "x"}))}
    assert verdict.detail.startswith("nothing removed or overwritten in issue.labels")


async def test_cleanup_runs_for_every_fixture():
    store = FakeStore()
    await run_fake(store=store)
    assert store.issues == {}


async def test_unlisted_tool_is_skipped_with_reason():
    store = FakeStore()
    server = build_fake_server(store)

    @server.tool(name="extra", annotations=ToolAnnotations(destructive_hint=False))
    def extra(issue_id: str) -> str:
        return issue_id

    _, results = await run_fake(store=store, server=server)
    extra_result = by_tool(results)["extra"]
    assert extra_result.outcome is Outcome.SKIPPED
    assert extra_result.skip_reason == "no pack entry yet"
    assert extra_result.calls == []


async def test_tool_without_explicit_claim_is_skipped():
    store = FakeStore()
    server = build_fake_server(store)

    @server.tool(name="unclaimed")
    def unclaimed(issue_id: str) -> str:
        return issue_id

    _, results = await run_fake(store=store, server=server)
    assert by_tool(results)["unclaimed"].outcome is Outcome.SKIPPED
    assert by_tool(results)["unclaimed"].skip_reason == "no explicit claim"


async def test_pack_skipped_tool_keeps_its_reason():
    pack = load_pack(FAKE_PACK)
    pack = with_entries(
        pack,
        set_labels=replace(pack.entries["set_labels"], status="skipped", skip_reason="later"),
    )
    _, results = await run_fake(pack=pack)
    result = by_tool(results)["set_labels"]
    assert result.outcome is Outcome.SKIPPED
    assert result.skip_reason == "later"
    assert result.calls == []


async def test_pack_entry_for_missing_tool_is_error():
    pack = load_pack(FAKE_PACK)
    pack = with_entries(pack, ghost=replace(pack.entries["get_issue"], tool="ghost"))
    _, results = await run_fake(pack=pack)
    ghost = by_tool(results)["ghost"]
    assert ghost.outcome is Outcome.ERROR
    assert ghost.error == "pack entry for unlisted tool"
    assert {r.tool: r.outcome for r in results if r.tool != "ghost"} == EXPECTED


class ChurningReader(FakeReader):
    """Changes the snapshot on every read for one tool's fixture."""

    def __init__(self, store: FakeStore, tool: str) -> None:
        super().__init__(store)
        self.tool = tool
        self.issue_id: str | None = None
        self.reads = 0

    async def create_fixture(self, entry, run_id):
        fixture = await super().create_fixture(entry, run_id)
        if entry.tool == self.tool:
            self.issue_id = fixture["issue_id"]
        return fixture

    async def snapshot(self, fields, fixture):
        recorded = await super().snapshot(fields, fixture)
        if fixture["issue_id"] == self.issue_id:
            self.reads += 1
            return Recorded({**recorded.snapshot, "issue.title": f"t{self.reads}"})
        return recorded


async def test_settle_timeout_is_error_and_run_continues():
    store = FakeStore()
    _, results = await run_fake(store=store, reader=ChurningReader(store, "get_issue"))
    got = by_tool(results)
    assert got["get_issue"].outcome is Outcome.ERROR
    assert "did not settle within 0.3s" in got["get_issue"].error
    assert got["get_issue"].verdicts == []
    later = {t: o for t, o in EXPECTED.items() if t != "get_issue"}
    assert {t: got[t].outcome for t in later} == later
    assert store.issues == {}


class FailingFixtureReader(FakeReader):
    def __init__(self, store: FakeStore, tool: str) -> None:
        super().__init__(store)
        self.tool = tool
        self.cleaned: list[str] = []

    async def create_fixture(self, entry, run_id):
        if entry.tool == self.tool:
            raise RuntimeError("rate limited")
        return await super().create_fixture(entry, run_id)

    async def cleanup(self, entry, fixture):
        self.cleaned.append(entry.tool)
        if fixture:
            await super().cleanup(entry, fixture)


async def test_fixture_failure_is_error_cleanup_attempted_and_run_continues():
    store = FakeStore()
    reader = FailingFixtureReader(store, "set_labels")
    _, results = await run_fake(store=store, reader=reader)
    got = by_tool(results)
    assert got["set_labels"].outcome is Outcome.ERROR
    assert "rate limited" in got["set_labels"].error
    assert "set_labels" in reader.cleaned
    assert got["add_labels"].outcome is Outcome.PASS


async def test_missing_fixture_value_is_error():
    pack = load_pack(FAKE_PACK)
    entry = replace(pack.entries["get_issue"], arguments={"issue_id": "{fixture.nope}"})
    _, results = await run_fake(pack=with_entries(pack, get_issue=entry))
    got = by_tool(results)["get_issue"]
    assert got.outcome is Outcome.ERROR
    assert "nope" in got.error
    assert got.calls == []


async def test_before_call_refusal_is_error_and_cleanup_runs():
    class Refused(Exception):
        pass

    seen: list[tuple[str, dict]] = []

    async def before_call(tool: str, arguments: dict) -> None:
        seen.append((tool, arguments))
        if tool == "set_labels":
            raise Refused("owner not allowlisted")

    store = FakeStore()
    _, results = await run_fake(store=store, before_call=before_call)
    got = by_tool(results)
    assert got["set_labels"].outcome is Outcome.ERROR
    assert "owner not allowlisted" in got["set_labels"].error
    assert got["set_labels"].calls == []
    # a refusal stops the run (spec Safety: failing any check stops the run)
    assert got["add_labels"].outcome is Outcome.SKIPPED
    assert seen[-1][0] == "set_labels"  # no call is checked after the refusal
    assert store.issues == {}


async def test_refusal_on_the_idempotent_second_call_stops_the_run():
    from mcp_annotation_check.github.safety import SafetyRefusal

    seen: list[str] = []

    async def before_call(tool: str, arguments: dict) -> None:
        seen.append(tool)
        if tool == "append_note" and seen.count("append_note") == 2:
            raise SafetyRefusal("refused on the second call")

    store = FakeStore()
    _, results = await run_fake(store=store, before_call=before_call)
    got = by_tool(results)
    note = got["append_note"]
    assert note.outcome is Outcome.ERROR
    assert "refused on the second call" in note.error
    assert len(note.calls) == 1  # the first call ran; the second was refused
    names = [r.tool for r in results]
    after = names[names.index("append_note") + 1 :]
    assert after  # the fake server lists tools after append_note
    for name in after:
        assert got[name].outcome is Outcome.SKIPPED
        assert got[name].skip_reason == "run stopped after a safety refusal on append_note"
        assert got[name].calls == []
    assert seen[-1] == "append_note"
    assert store.issues == {}


async def test_before_call_checks_the_idempotent_second_call():
    seen: list[str] = []

    async def before_call(tool: str, arguments: dict) -> None:
        seen.append(tool)

    await run_fake(before_call=before_call)
    assert seen.count("append_note") == 2


def _three_tool_server(store: FakeStore):
    server = MCPServer("three")
    for name in ("first", "second", "third"):

        def add(issue_id: str, labels: list[str]) -> str:
            store.touch(issue_id).labels |= set(labels)
            return issue_id

        server.tool(name=name, annotations=ToolAnnotations(destructive_hint=False))(add)
    return server


async def test_safety_refusal_stops_the_run_and_reports_are_written(tmp_path):
    from mcp_annotation_check.github.safety import SafetyRefusal

    calls: list[str] = []

    async def before_call(tool: str, arguments: dict) -> None:
        calls.append(tool)
        if tool == "second":
            raise SafetyRefusal("owner 'outside-org' is not on the allowlist")

    store = FakeStore()
    pack = load_pack(FAKE_PACK)
    template = pack.entries["add_labels"]
    pack = replace(
        pack, entries={n: replace(template, tool=n) for n in ("first", "second", "third")}
    )
    header, results = await run_fake(
        pack=pack, store=store, server=_three_tool_server(store), before_call=before_call
    )
    got = by_tool(results)
    assert [r.tool for r in results] == ["first", "second", "third"]
    assert got["first"].outcome is Outcome.PASS
    assert got["second"].outcome is Outcome.ERROR
    assert "outside-org" in got["second"].error
    assert got["third"].outcome is Outcome.SKIPPED
    assert got["third"].skip_reason == "run stopped after a safety refusal on second"
    assert got["third"].calls == []
    assert calls == ["first", "second"]
    assert store.issues == {}  # the refused tool's fixture was still cleaned up
    write_reports(header, results, tmp_path)
    for name in ("report.md", "report.json", "private-findings.md"):
        assert (tmp_path / name).exists()
    assert "run stopped after a safety refusal on second" in (tmp_path / "report.md").read_text()


async def test_read_repository_entry_without_fixture_uses_read_fixtures():
    store = FakeStore()
    issue_id = store.create_issue()
    pack = load_pack(FAKE_PACK)
    entry = replace(pack.entries["get_issue"], fixture=None, repository="read")
    pack = replace(with_entries(pack, get_issue=entry), read_fixtures={"issue_id": issue_id})
    _, results = await run_fake(pack=pack, store=store)
    got = by_tool(results)["get_issue"]
    assert got.outcome is Outcome.PASS
    assert got.calls[0]["arguments"] == {"issue_id": issue_id}
    assert issue_id in store.issues  # read fixtures are never cleaned up


async def test_custom_setup_replaces_create_fixture(monkeypatch):
    calls: list[str] = []

    async def setup(reader, entry, run_id):
        calls.append(entry.tool)
        return {"issue_id": reader.store.create_issue()}

    monkeypatch.setitem(CUSTOM_SETUPS, "own_issue", setup)
    pack = load_pack(FAKE_PACK)
    entry = replace(pack.entries["add_labels"], custom_setup="own_issue")
    _, results = await run_fake(pack=with_entries(pack, add_labels=entry))
    assert calls == ["add_labels"]
    assert by_tool(results)["add_labels"].outcome is Outcome.PASS


async def test_custom_verdict_is_flagged_with_reason(monkeypatch, tmp_path):
    def always_pass(before, after, entry, arguments) -> Verdict:
        return Verdict(Check.NON_DESTRUCTIVE, Outcome.PASS, "custom: accepted")

    monkeypatch.setitem(CUSTOM_VERDICTS, "always_pass", always_pass)
    pack = load_pack(FAKE_PACK)
    entry = replace(
        pack.entries["set_labels"], custom_verdict="always_pass", custom_reason="demo"
    )
    header, results = await run_fake(pack=with_entries(pack, set_labels=entry))
    got = by_tool(results)["set_labels"]
    assert got.custom == "demo"
    assert got.outcome is Outcome.PASS
    assert [v.detail for v in got.verdicts] == ["custom: accepted"]

    from mcp_annotation_check.report import write_reports

    write_reports(header, results, tmp_path)
    md = (tmp_path / "report.md").read_text()
    section = md.split("### set_labels", 1)[1].split("\n### ", 1)[0]
    assert "Custom verdict" in section and "demo" in section
    assert (
        "> If true, the tool may perform destructive updates to its environment. "
        "If false, the tool performs only additive updates." in section
    )
    assert "- c" in section and "+ x" in section  # harness-observed evidence
    assert "@@ issue.labels @@ not counted by the custom verdict" in section
    assert "additive" not in section.split("Diff", 1)[1]


async def test_custom_verdict_cannot_change_check_or_schema_text(monkeypatch):
    def wrong_check(before, after, entry, arguments) -> Verdict:
        return Verdict(Check.READ_ONLY, Outcome.PASS, "custom", schema_text="made up")

    monkeypatch.setitem(CUSTOM_VERDICTS, "wrong_check", wrong_check)
    pack = load_pack(FAKE_PACK)
    entry = replace(pack.entries["set_labels"], custom_verdict="wrong_check", custom_reason="r")
    _, results = await run_fake(pack=with_entries(pack, set_labels=entry))
    (verdict,) = by_tool(results)["set_labels"].verdicts
    assert verdict.check is Check.NON_DESTRUCTIVE
    assert verdict.schema_text == SCHEMA_TEXT[Check.NON_DESTRUCTIVE]
    assert verdict.diff == {"issue.labels": (frozenset({"c", "d"}), frozenset({"x"}))}


@pytest.mark.parametrize("key", ["custom_setup", "custom_verdict"])
async def test_unknown_custom_name_is_error(key):
    pack = load_pack(FAKE_PACK)
    extra = {key: "no_such_thing"}
    if key == "custom_verdict":
        extra["custom_reason"] = "demo"
    entry = replace(pack.entries["set_labels"], **extra)
    store = FakeStore()
    _, results = await run_fake(pack=with_entries(pack, set_labels=entry), store=store)
    got = by_tool(results)["set_labels"]
    assert got.outcome is Outcome.ERROR
    assert f"unknown {key}" in got.error and "no_such_thing" in got.error
    assert got.calls == []
    assert store.issues == {}


async def test_header_from_client_and_pack():
    header, _ = await run_fake()
    assert header.server_info["name"] == "fake"
    assert header.protocol_version
    assert header.pack_version == "0"
    assert header.deployment == "in-memory"
    assert header.standard_read_only_fields == ["issue.labels", "issue.title", "issue.notes"]
    assert [t["name"] for t in header.tools_list][0] == "get_issue"
    assert len(header.tools_list_sha256) == 64
