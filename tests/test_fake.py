from pathlib import Path

from mcp import Client

from mcp_annotation_check.fake.reader import FakeReader
from mcp_annotation_check.fake.server import FakeStore, build_fake_server
from mcp_annotation_check.pack import load_pack
from mcp_annotation_check.snapshot import FieldKind, FieldSpec

PACK = Path(__file__).resolve().parent.parent / "packs" / "fake.yaml"

EXPECTED = {
    "get_issue": {"read_only_hint": True},
    "peek_and_touch": {"read_only_hint": True},
    "set_labels": {"destructive_hint": False},
    "add_labels": {"destructive_hint": False},
    "rename_issue": {"destructive_hint": False},
    "append_note": {"destructive_hint": False, "idempotent_hint": True},
    "bump_hidden_counter": {"read_only_hint": True},
    "explode": {"destructive_hint": False},
}


async def test_fake_server_lists_all_tools_with_annotations():
    store = FakeStore()
    async with Client(build_fake_server(store)) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert set(tools) == set(EXPECTED)
    for name, hints in EXPECTED.items():
        ann = tools[name].annotations
        assert ann is not None
        for hint, value in hints.items():
            assert getattr(ann, hint) is value, (name, hint)


async def test_fake_reader_snapshot_reflects_store():
    store = FakeStore()
    reader = FakeReader(store)
    fields = [
        FieldSpec("issue.labels", FieldKind.COLLECTION),
        FieldSpec("issue.title", FieldKind.SCALAR),
        FieldSpec("issue.notes", FieldKind.COLLECTION),
    ]
    pack = load_pack(PACK)
    fixture = await reader.create_fixture(pack.entries["set_labels"], "run1")
    before = await reader.snapshot(fields, fixture)
    assert before.snapshot["issue.labels"] == frozenset({"c", "d"})
    assert before.snapshot["issue.title"] == "fixture"
    assert before.snapshot["issue.notes"] == frozenset()
    async with Client(build_fake_server(store)) as c:
        await c.call_tool("append_note", {"issue_id": fixture["issue_id"], "text": "hi"})
        await c.call_tool("append_note", {"issue_id": fixture["issue_id"], "text": "hi"})
    after = await reader.snapshot(fields, fixture)
    assert after.snapshot["issue.notes"] == frozenset({(0, "hi"), (1, "hi")})
    assert "issue" in after.timestamps
    await reader.cleanup(pack.entries["set_labels"], fixture)
    assert fixture["issue_id"] not in store.issues


def test_fake_pack_loads():
    pack = load_pack(PACK)
    assert set(pack.entries) == set(EXPECTED)
    counter_paths = {
        f.path
        for e in pack.entries.values()
        for f in e.fields
    } | {f.path for f in pack.standard_read_only_fields}
    assert "issue.counter" not in counter_paths
    assert pack.entries["bump_hidden_counter"].fields == []


async def test_fake_reader_cleanup_of_empty_fixture_is_noop():
    store = FakeStore()
    issue_id = store.create_issue()
    pack = load_pack(PACK)
    await FakeReader(store).cleanup(pack.entries["set_labels"], {})
    assert issue_id in store.issues
