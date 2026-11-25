"""StateReader over the in-memory FakeStore."""

from typing import Any

from mcp_annotation_check.fake.server import FakeStore
from mcp_annotation_check.pack import ToolEntry
from mcp_annotation_check.snapshot import FieldKind, FieldSpec, Recorded


class FakeReader:
    def __init__(self, store: FakeStore) -> None:
        self.store = store

    async def create_fixture(self, entry: ToolEntry, run_id: str) -> dict[str, Any]:
        return {"issue_id": self.store.create_issue()}

    async def snapshot(self, fields: list[FieldSpec], fixture: dict[str, Any]) -> Recorded:
        issue_id = fixture["issue_id"]
        issue = self.store.issues[issue_id]
        values: dict[str, Any] = {
            "issue.labels": frozenset(issue.labels),
            "issue.title": issue.title,
            "issue.notes": frozenset(enumerate(issue.notes)),
        }
        snap: dict[str, Any] = {}
        for f in fields:
            if f.path not in values:
                raise KeyError(f"fake reader cannot read field {f.path!r}")
            v = values[f.path]
            if f.kind is FieldKind.SCALAR and isinstance(v, frozenset):
                raise ValueError(f"{f.path} is a collection")
            snap[f.path] = v
        return Recorded(snap, {"issue": issue.updated_at})

    async def cleanup(self, entry: ToolEntry, fixture: dict[str, Any]) -> None:
        self.store.issues.pop(fixture["issue_id"], None)
