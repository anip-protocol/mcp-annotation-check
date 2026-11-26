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
from mcp_annotation_check.runner import CUSTOM_SETUPS, CUSTOM_VERDICTS, ToolResult, run
from mcp_annotation_check.settle import SettleTimeout, settle
from mcp_annotation_check.snapshot import (
    COMPOSITE_FIELDS,
    FieldKind,
    FieldSpec,
    Recorded,
    Verdict,
)
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


async def test_skipped_pack_entry_for_missing_tool_is_error():
    pack = load_pack(FAKE_PACK)
    ghost = replace(pack.entries["get_issue"], tool="ghost", status="skipped", skip_reason="x")
    _, results = await run_fake(pack=with_entries(pack, ghost=ghost))
    got = by_tool(results)["ghost"]
    assert got.outcome is Outcome.ERROR
    assert got.error == "pack entry for unlisted tool"
    assert {r.tool: r.outcome for r in results if r.tool != "ghost"} == EXPECTED


async def test_enabled_pack_entry_for_missing_tool_stops_the_run():
    pack = load_pack(FAKE_PACK)
    pack = with_entries(pack, ghost=replace(pack.entries["get_issue"], tool="ghost"))
    store = FakeStore()
    header, results = await run_fake(pack=pack, store=store)
    assert header.pack_problems == ["ghost: not in the server's tools/list"]
    got = by_tool(results)
    assert got["ghost"].outcome is Outcome.ERROR
    assert got["ghost"].error == "pack entry for unlisted tool"
    for name in EXPECTED:
        assert got[name].outcome is Outcome.SKIPPED
        assert got[name].skip_reason == "pack validation failed: 1 problem(s)"
    assert store.issues == {}


class RecordingReader(FakeReader):
    def __init__(self, store: FakeStore) -> None:
        super().__init__(store)
        self.fixtures: list[str] = []

    async def create_fixture(self, entry, run_id):
        self.fixtures.append(entry.tool)
        return await super().create_fixture(entry, run_id)


class RecordingClient:
    """Delegates to a real client and records every tools/call."""

    def __init__(self, client) -> None:
        self._client = client
        self.called: list[str] = []

    def __getattr__(self, name):
        return getattr(self._client, name)

    async def call_tool(self, name, arguments):
        self.called.append(name)
        return await self._client.call_tool(name, arguments)


async def test_validation_problem_stops_before_any_fixture(tmp_path):
    import json

    from mcp import Client

    from support import HEADER_CONTEXT

    pack = load_pack(FAKE_PACK)
    labels = pack.entries["set_labels"]
    no_role = replace(
        labels, argument_roles={"issue_id": "id"}, arguments={"issue_id": "{fixture.issue_id}"}
    )
    title = pack.entries["rename_issue"]
    extra_role = replace(title, argument_roles={**title.argument_roles, "owner": "owner"})
    pack = with_entries(pack, set_labels=no_role, rename_issue=extra_role)
    problems = [
        "set_labels: input-schema property 'labels' has no declared role",
        "rename_issue: role declared for 'owner', which is not an input-schema property",
    ]
    store = FakeStore()
    reader = RecordingReader(store)
    async with Client(build_fake_server(store)) as real:
        client = RecordingClient(real)
        header, results = await run(
            client,
            reader,
            pack,
            HEADER_CONTEXT,
            before_call=None,
            settle_interval_s=0.001,
            settle_timeout_s=0.3,
        )
    assert reader.fixtures == []
    assert client.called == []
    assert store.issues == {}
    assert sorted(header.pack_problems) == sorted(problems)
    assert {r.tool for r in results} == set(EXPECTED)
    for r in results:
        assert r.outcome is Outcome.SKIPPED
        assert r.skip_reason == "pack validation failed: 2 problem(s)"
        assert r.calls == [] and r.verdicts == []
    write_reports(header, results, tmp_path)
    md = (tmp_path / "report.md").read_text()
    assert "## Pack validation" in md
    for problem in problems:
        assert problem in md
    data = json.loads((tmp_path / "report.json").read_text())
    assert sorted(data["header"]["pack_problems"]) == sorted(problems)


async def test_validation_failure_keeps_other_skip_reasons():
    store = FakeStore()
    server = build_fake_server(store)

    @server.tool(name="extra", annotations=ToolAnnotations(destructive_hint=False))
    def extra(issue_id: str) -> str:
        return issue_id

    pack = load_pack(FAKE_PACK)
    pack = with_entries(pack, ghost=replace(pack.entries["get_issue"], tool="ghost"))
    _, results = await run_fake(pack=pack, store=store, server=server)
    assert by_tool(results)["extra"].skip_reason == "no pack entry yet"


async def test_fake_pack_is_valid_against_the_fake_server():
    header, _ = await run_fake()
    assert header.pack_problems == []
    assert header.pack_warnings == []


async def test_validation_warnings_reach_the_header_and_the_run_continues(tmp_path):
    store = FakeStore()
    server = build_fake_server(store)

    @server.tool(name="note_for", annotations=ToolAnnotations(destructive_hint=False))
    def note_for(issue_id: str, target_owner: str) -> str:
        store.touch(issue_id).notes.append(target_owner)
        return issue_id

    pack = load_pack(FAKE_PACK)
    entry = replace(
        pack.entries["append_note"],
        tool="note_for",
        arguments={"issue_id": "{fixture.issue_id}", "target_owner": "someone"},
        argument_roles={"issue_id": "id", "target_owner": "content"},
    )
    pack = with_entries(pack, note_for=entry)
    header, results = await run_fake(pack=pack, store=store, server=server)
    warning = (
        "warning: note_for: property 'target_owner' may name an owner or repository but is "
        "declared 'content'; check it by hand"
    )
    assert header.pack_problems == []
    assert header.pack_warnings == [warning]
    assert by_tool(results)["note_for"].calls  # the run went ahead
    write_reports(header, results, tmp_path)
    assert warning in (tmp_path / "report.md").read_text()


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


class LaggingReader(FakeReader):
    """The first read after a fixture is created is stale, as REST reads can lag."""

    def __init__(self, store: FakeStore) -> None:
        super().__init__(store)
        self.fresh: set[str] = set()

    async def create_fixture(self, entry, run_id):
        fixture = await super().create_fixture(entry, run_id)
        self.fresh.add(fixture["issue_id"])
        return fixture

    async def snapshot(self, fields, fixture):
        recorded = await super().snapshot(fields, fixture)
        if fixture["issue_id"] in self.fresh:
            self.fresh.discard(fixture["issue_id"])
            stale = {**recorded.snapshot}
            if "issue.title" in stale:
                stale["issue.title"] = "not yet visible"
            return Recorded(stale, recorded.timestamps)
        return recorded


async def test_before_snapshot_is_settled_so_read_lag_cannot_fake_a_finding():
    store = FakeStore()
    _, results = await run_fake(store=store, reader=LaggingReader(store))
    got = by_tool(results)
    assert got["get_issue"].outcome is Outcome.PASS
    assert got["bump_hidden_counter"].outcome is Outcome.PASS
    assert {r.tool: r.outcome for r in results} == EXPECTED


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
    names = ("first", "second", "third")
    pack = replace(
        pack,
        entries={n: replace(template, tool=n) for n in names},
        id_only_write_tools=list(names),
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


class RefusingReader(FakeReader):
    """Its REST client refuses a write for one tool, at fixture setup or at cleanup."""

    def __init__(self, store: FakeStore, tool: str, at: str) -> None:
        super().__init__(store)
        self.tool, self.at = tool, at
        self.cleaned: list[str] = []

    async def create_fixture(self, entry, run_id):
        from mcp_annotation_check.github.rest import RestRefused

        if entry.tool == self.tool and self.at == "setup":
            raise RestRefused("POST", "/repos/owner/read-repo/issues")
        return await super().create_fixture(entry, run_id)

    async def cleanup(self, entry, fixture):
        from mcp_annotation_check.github.rest import RestRefused

        self.cleaned.append(entry.tool)
        await super().cleanup(entry, fixture)
        if entry.tool == self.tool and self.at == "cleanup":
            raise RestRefused("PATCH", "/repos/owner/read-repo/issues/1")


def _three_tool_pack():
    pack = load_pack(FAKE_PACK)
    template = pack.entries["add_labels"]
    names = ("first", "second", "third")
    return replace(
        pack,
        entries={n: replace(template, tool=n) for n in names},
        id_only_write_tools=list(names),
    )


@pytest.mark.parametrize("at", ["setup", "cleanup"])
async def test_rest_refusal_in_fixture_setup_or_cleanup_stops_the_run(tmp_path, at):
    store = FakeStore()
    reader = RefusingReader(store, "second", at)
    header, results = await run_fake(
        pack=_three_tool_pack(), store=store, reader=reader, server=_three_tool_server(store)
    )
    got = by_tool(results)
    assert [r.tool for r in results] == ["first", "second", "third"]
    assert got["first"].outcome is Outcome.PASS
    assert got["second"].outcome is Outcome.ERROR
    assert "RestRefused" in got["second"].error
    assert "refusing" in got["second"].error
    assert got["third"].outcome is Outcome.SKIPPED
    assert got["third"].skip_reason == "run stopped after a safety refusal on second"
    assert got["third"].calls == []
    assert reader.cleaned == ["first", "second"]  # the refused tool is still cleaned up
    write_reports(header, results, tmp_path)
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


async def test_every_snapshot_fixture_names_the_entry_repository():
    seen: dict[str, set] = {}

    class Recording(FakeReader):
        async def snapshot(self, fields, fixture):
            seen.setdefault(fixture["issue_id"], set()).add(fixture.get("repository"))
            return await super().snapshot(fields, fixture)

    store = FakeStore()
    issue_id = store.create_issue()
    pack = load_pack(FAKE_PACK)
    entry = replace(pack.entries["get_issue"], fixture=None, repository="read")
    pack = replace(with_entries(pack, get_issue=entry), read_fixtures={"issue_id": issue_id})
    await run_fake(pack=pack, store=store, reader=Recording(store))
    assert seen.pop(issue_id) == {"owner/read-repo"}
    assert seen and all(repos == {"owner/write-repo"} for repos in seen.values())


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


# --- a failed call that changed nothing is ERROR (ruling R19) -------------------


def _server_with(store: FakeStore, name: str, annotations: ToolAnnotations):
    server = build_fake_server(store)

    @server.tool(name=name, annotations=annotations)
    def failing(issue_id: str) -> str:
        raise RuntimeError(f"{name}: failed before changing anything")

    return server


def _pack_with(name: str, fields: list | None):
    pack = load_pack(FAKE_PACK)
    template = pack.entries["get_issue"]
    entry = replace(template, tool=name, fields=fields if fields is not None else [])
    return with_entries(pack, **{name: entry})


async def test_failed_non_destructive_call_with_no_change_is_error():
    store = FakeStore()
    server = _server_with(store, "fail_quietly", ToolAnnotations(destructive_hint=False))
    labels = load_pack(FAKE_PACK).entries["set_labels"].fields
    _, results = await run_fake(pack=_pack_with("fail_quietly", labels), store=store, server=server)
    got = by_tool(results)["fail_quietly"]
    assert got.outcome is Outcome.ERROR
    assert got.error.startswith("call failed; no change observed in issue.labels")
    assert "tool returned an error: Error executing tool fail_quietly" in got.error
    (verdict,) = got.verdicts  # kept as evidence
    assert verdict.check is Check.NON_DESTRUCTIVE and verdict.outcome is Outcome.PASS
    assert got.calls[0]["is_error"] is True


async def test_failed_read_only_call_with_no_change_is_error():
    store = FakeStore()
    server = _server_with(store, "fail_reading", ToolAnnotations(read_only_hint=True))
    _, results = await run_fake(pack=_pack_with("fail_reading", None), store=store, server=server)
    got = by_tool(results)["fail_reading"]
    assert got.outcome is Outcome.ERROR
    assert got.error.startswith(
        "call failed; no change observed in issue.labels, issue.title, issue.notes"
    )
    (verdict,) = got.verdicts
    assert verdict.check is Check.READ_ONLY and verdict.outcome is Outcome.PASS


class _RaisingClient:
    """Delegates to a real client, but call_tool raises for one tool."""

    def __init__(self, client, tool: str, secret: str) -> None:
        self._client, self._tool, self._secret = client, tool, secret

    def __getattr__(self, name):
        return getattr(self._client, name)

    async def call_tool(self, name, arguments):
        if name == self._tool:
            raise ConnectionError(f"transport dropped (token {self._secret})")
        return await self._client.call_tool(name, arguments)


async def test_call_tool_raising_with_no_change_is_error():
    from mcp import Client

    from support import HEADER_CONTEXT

    store = FakeStore()
    secret = "s3cret-token-value"
    async with Client(build_fake_server(store)) as client:
        _, results = await run(
            _RaisingClient(client, "set_labels", secret),
            FakeReader(store),
            load_pack(FAKE_PACK),
            HEADER_CONTEXT,
            settle_interval_s=0.01,
            settle_timeout_s=0.3,
            secrets=[secret],
        )
    got = by_tool(results)
    assert got["set_labels"].outcome is Outcome.ERROR
    error = got["set_labels"].error
    assert error.startswith("call failed; no change observed in issue.labels")
    assert "ConnectionError: transport dropped" in error
    assert secret not in error
    assert got["set_labels"].verdicts  # kept as evidence
    assert got["add_labels"].outcome is Outcome.PASS


# --- composite collection fields (ruling R17) -----------------------------------


class CommentsReader(FakeReader):
    """Adds `issue.comments`, a composite field whose elements are (index, text) tuples."""

    async def snapshot(self, fields, fixture):
        plain = [f for f in fields if f.path != "issue.comments"]
        recorded = await super().snapshot(plain, fixture)
        snap = dict(recorded.snapshot)
        if any(f.path == "issue.comments" for f in fields):
            notes = self.store.issues[fixture["issue_id"]].notes
            snap["issue.comments"] = frozenset(enumerate(notes))
        return Recorded(snap, recorded.timestamps)


COMMENTS = FieldSpec("issue.comments", FieldKind.COLLECTION)
COMPOSITE_DETAIL = "not judged yet (composite elements): issue.comments"


def test_composite_fields_are_defined_in_one_place():
    assert COMPOSITE_FIELDS == {"issue.comments", "repo.refs", "repo.issues", "repo.labels"}


async def test_composite_field_alone_is_unjudged_not_error():
    store = FakeStore()
    pack = load_pack(FAKE_PACK)
    entry = replace(pack.entries["append_note"], fields=[COMMENTS])
    entry_set = replace(pack.entries["set_labels"], fields=[COMMENTS], supplies={})
    pack = with_entries(pack, append_note=entry, set_labels=entry_set)
    _, results = await run_fake(pack=pack, store=store, reader=CommentsReader(store))
    got = by_tool(results)

    labels = got["set_labels"]
    assert labels.outcome is Outcome.UNJUDGED
    assert labels.error is None
    (verdict,) = labels.verdicts
    assert verdict.check is Check.NON_DESTRUCTIVE
    assert verdict.outcome is Outcome.UNJUDGED
    assert COMPOSITE_DETAIL in verdict.detail
    assert verdict.schema_text == SCHEMA_TEXT[Check.NON_DESTRUCTIVE]

    # the idempotent check still uses the composite field (equality is safe), and a
    # finding outranks the unjudged check
    note = got["append_note"]
    verdicts = {v.check: v for v in note.verdicts}
    assert verdicts[Check.NON_DESTRUCTIVE].outcome is Outcome.UNJUDGED
    assert verdicts[Check.IDEMPOTENT].outcome is Outcome.FINDING
    assert "issue.comments" in verdicts[Check.IDEMPOTENT].changed
    assert note.outcome is Outcome.FINDING
    assert note.error is None
    assert store.issues == {}


async def test_finding_on_plain_field_wins_over_composite():
    store = FakeStore()
    pack = load_pack(FAKE_PACK)
    plain = pack.entries["set_labels"].fields
    entry = replace(pack.entries["set_labels"], fields=[*plain, COMMENTS])
    pack = with_entries(pack, set_labels=entry)
    _, results = await run_fake(pack=pack, store=store, reader=CommentsReader(store))
    labels = by_tool(results)["set_labels"]
    assert labels.outcome is Outcome.FINDING
    (verdict,) = labels.verdicts
    assert verdict.outcome is Outcome.FINDING
    assert "issue.labels" in verdict.changed
    assert "lost or overwritten: issue.labels" in verdict.detail
    assert "; not judged yet (composite elements): issue.comments" in verdict.detail
    assert labels.error is None


async def test_finding_outranks_error():
    from mcp_annotation_check.runner import _most_severe

    store = FakeStore()
    _, results = await run_fake(store=store)
    explode = by_tool(results)["explode"]
    assert explode.calls[0]["is_error"] is True
    assert explode.outcome is Outcome.FINDING
    assert "tool returned an error" in explode.error  # the error text is still recorded

    check = Check.NON_DESTRUCTIVE
    mixed = [Verdict(check, o, "") for o in (Outcome.ERROR, Outcome.FINDING, Outcome.UNJUDGED)]
    assert _most_severe(mixed) is Outcome.FINDING
    mixed = [Verdict(check, o, "") for o in (Outcome.OBSERVATION, Outcome.UNJUDGED)]
    assert _most_severe(mixed) is Outcome.UNJUDGED


async def test_read_only_check_still_uses_composite_fields():
    store = FakeStore()
    pack = load_pack(FAKE_PACK)
    pack = replace(pack, standard_read_only_fields=[*pack.standard_read_only_fields, COMMENTS])
    _, results = await run_fake(pack=pack, store=store, reader=CommentsReader(store))
    got = by_tool(results)
    assert got["get_issue"].outcome is Outcome.PASS
    assert "issue.comments" in got["get_issue"].verdicts[0].detail
    assert got["peek_and_touch"].outcome is Outcome.FINDING
    assert "issue.comments" in got["peek_and_touch"].verdicts[0].changed


async def test_finding_survives_a_failed_later_step():
    from mcp_annotation_check.github.safety import SafetyRefusal

    store = FakeStore()
    server = build_fake_server(store)

    @server.tool(
        name="replace_labels",
        annotations=ToolAnnotations(destructive_hint=False, idempotent_hint=True),
    )
    def replace_labels(issue_id: str, labels: list[str]) -> str:
        store.issues[issue_id].labels = list(labels)
        return "ok"

    seen: list[str] = []

    async def before_call(tool: str, arguments: dict) -> None:
        seen.append(tool)
        if tool == "replace_labels" and seen.count("replace_labels") == 2:
            raise SafetyRefusal("refused on the second call")

    template = load_pack(FAKE_PACK).entries["set_labels"]
    pack = with_entries(load_pack(FAKE_PACK), replace_labels=replace(template, tool="replace_labels"))
    _, results = await run_fake(pack=pack, store=store, server=server, before_call=before_call)
    got = by_tool(results)["replace_labels"]
    assert any(v.outcome is Outcome.FINDING for v in got.verdicts)
    assert got.outcome is Outcome.FINDING
    assert "refused on the second call" in got.error  # the error text is kept
    names = [r.tool for r in results]
    for name in names[names.index("replace_labels") + 1 :]:  # a refusal still stops the run
        assert by_tool(results)[name].outcome is Outcome.SKIPPED
