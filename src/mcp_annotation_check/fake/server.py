"""A deliberately mislabelled in-memory MCP server, for testing the harness."""

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations


@dataclass
class FakeIssue:
    labels: set[str] = field(default_factory=lambda: {"c", "d"})
    title: str | None = "fixture"
    notes: list[str] = field(default_factory=list)
    counter: int = 0
    updated_at: str = ""


class FakeStore:
    def __init__(self) -> None:
        self.issues: dict[str, FakeIssue] = {}
        self._ids = itertools.count(1)
        self._tick = itertools.count(1)

    def stamp(self) -> str:
        return f"{datetime.now(UTC).isoformat()}#{next(self._tick)}"

    def create_issue(self) -> str:
        issue_id = f"issue-{next(self._ids)}"
        self.issues[issue_id] = FakeIssue(updated_at=self.stamp())
        return issue_id

    def touch(self, issue_id: str) -> FakeIssue:
        issue = self.issues[issue_id]
        issue.updated_at = self.stamp()
        return issue


def build_fake_server(store: FakeStore) -> MCPServer:
    server = MCPServer("fake")

    def describe(issue_id: str) -> str:
        i = store.issues[issue_id]
        return f"{issue_id}: {i.title} labels={sorted(i.labels)} notes={len(i.notes)}"

    @server.tool(name="get_issue", annotations=ToolAnnotations(read_only_hint=True))
    def get_issue(issue_id: str) -> str:
        return describe(issue_id)

    @server.tool(name="peek_and_touch", annotations=ToolAnnotations(read_only_hint=True))
    def peek_and_touch(issue_id: str) -> str:
        store.touch(issue_id).notes.append("peeked")
        return describe(issue_id)

    @server.tool(name="set_labels", annotations=ToolAnnotations(destructive_hint=False))
    def set_labels(issue_id: str, labels: list[str]) -> str:
        store.touch(issue_id).labels = set(labels)
        return describe(issue_id)

    @server.tool(name="add_labels", annotations=ToolAnnotations(destructive_hint=False))
    def add_labels(issue_id: str, labels: list[str]) -> str:
        store.touch(issue_id).labels |= set(labels)
        return describe(issue_id)

    @server.tool(name="rename_issue", annotations=ToolAnnotations(destructive_hint=False))
    def rename_issue(issue_id: str, title: str) -> str:
        store.touch(issue_id).title = title
        return describe(issue_id)

    @server.tool(
        name="append_note",
        annotations=ToolAnnotations(destructive_hint=False, idempotent_hint=True),
    )
    def append_note(issue_id: str, text: str) -> str:
        store.touch(issue_id).notes.append(text)
        return describe(issue_id)

    @server.tool(name="bump_hidden_counter", annotations=ToolAnnotations(read_only_hint=True))
    def bump_hidden_counter(issue_id: str) -> str:
        store.issues[issue_id].counter += 1  # not compared; updated_at untouched
        return describe(issue_id)

    @server.tool(name="explode", annotations=ToolAnnotations(destructive_hint=False))
    def explode(issue_id: str, label: str) -> str:
        store.touch(issue_id).labels.discard(label)
        raise RuntimeError("explode: failed after removing the label")

    return server
