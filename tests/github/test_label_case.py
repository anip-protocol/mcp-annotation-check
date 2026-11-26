"""The milestone-1 label reproduction, proven through the real GitHubReader.

An in-memory "GitHub" serves issues and labels in GitHub's real REST shape; the
server under test mutates that same store, so the verdict is reached only from
what the reader reads back over REST.
"""

import json
import re

import httpx

from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from mcp_annotation_check.claims import Check
from mcp_annotation_check.github.reader import GitHubReader
from mcp_annotation_check.github.rest import GitHubRest
from mcp_annotation_check.pack import Pack, ToolEntry
from mcp_annotation_check.runner import run
from mcp_annotation_check.snapshot import COMPOSITE_FIELDS, FieldKind, FieldSpec, Outcome
from support import HEADER_CONTEXT

REPOS = {"read": "o/read", "write": "o/write"}
ANNOTATIONS = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)
NOW = "2026-01-01T00:00:00Z"


def label_object(name: str, n: int) -> dict:
    return {
        "id": 1000 + n,
        "node_id": f"LA_{n}",
        "url": f"https://api.github.com/repos/o/write/labels/{name}",
        "name": name,
        "color": "ededed",
        "default": False,
        "description": None,
    }


class FakeGitHub:
    def __init__(self) -> None:
        self.labels: dict[str, dict] = {}
        self.issues: dict[int, dict] = {}
        self.reactions: dict[int, list[dict]] = {}

    def label(self, name: str) -> dict:
        return self.labels.setdefault(name, label_object(name, len(self.labels)))

    def set_labels(self, number: int, names: list[str]) -> None:
        issue = self.issues[number]
        issue["labels"] = [self.label(n) for n in names]
        issue["updated_at"] = NOW

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        if (m := re.fullmatch(r"/repos/o/write/labels/([^/]+)", path)) and method == "GET":
            if m[1] in self.labels:
                return httpx.Response(200, json=self.labels[m[1]])
            return httpx.Response(404, json={"message": "Not Found"})
        if path == "/repos/o/write/labels" and method == "POST":
            self.labels[body["name"]] = label_object(body["name"], len(self.labels))
            return httpx.Response(201, json=self.labels[body["name"]])
        if path == "/user" and method == "GET":
            return httpx.Response(200, json={"login": "bot"})
        if path == "/repos/o/write/issues" and method == "POST":
            number = len(self.issues) + 1
            self.issues[number] = {
                "number": number,
                "title": body["title"],
                "body": body["body"],
                "state": "open",
                "labels": [],
                "assignees": [{"login": a} for a in body.get("assignees", ["alice"])],
                "user": {"login": "tester"},
                "updated_at": NOW,
            }
            self.set_labels(number, body.get("labels", []))
            return httpx.Response(201, json=self.issues[number])
        if m := re.fullmatch(r"/repos/o/write/issues/(\d+)", path):
            issue = self.issues[int(m[1])]
            if method == "GET":
                return httpx.Response(200, json=issue)
            if method == "PATCH":
                issue.update(body)
                return httpx.Response(200, json=issue)
        if (m := re.fullmatch(r"/repos/o/write/issues/(\d+)/reactions", path)) and method == "GET":
            return httpx.Response(200, json=self.reactions.get(int(m[1]), []))
        if (m := re.fullmatch(r"/repos/o/write/issues/(\d+)/labels", path)) and method == "POST":
            number = int(m[1])
            have = [x["name"] for x in self.issues[number]["labels"]]
            self.set_labels(number, have + [n for n in body["labels"] if n not in have])
            return httpx.Response(200, json=self.issues[number]["labels"])
        return httpx.Response(404, json={"message": f"unexpected {method} {path}"})


def build(github: FakeGitHub) -> MCPServer:
    server = MCPServer("fake-github")

    @server.tool(name="update_issue_labels", annotations=ANNOTATIONS)
    def update_issue_labels(owner: str, repo: str, issue_number: int, labels: list[str]) -> str:
        github.set_labels(issue_number, labels)
        return "ok"

    @server.tool(name="add_issue_labels", annotations=ANNOTATIONS)
    def add_issue_labels(owner: str, repo: str, issue_number: int, labels: list[str]) -> str:
        have = [x["name"] for x in github.issues[issue_number]["labels"]]
        github.set_labels(issue_number, have + [n for n in labels if n not in have])
        return "ok"

    @server.tool(name="update_issue_assignees", annotations=ANNOTATIONS)
    def update_issue_assignees(owner: str, repo: str, issue_number: int, assignees: list[str]) -> str:
        github.issues[issue_number]["assignees"] = [{"login": a} for a in assignees]
        return "ok"

    @server.tool(name="add_issue_reaction", annotations=ANNOTATIONS)
    def add_issue_reaction(owner: str, repo: str, issue_number: int, content: str) -> str:
        github.reactions.setdefault(issue_number, []).append(
            {"id": 99, "user": {"login": "tester"}, "content": content}
        )
        return "ok"

    @server.tool(name="remove_issue_reaction", annotations=ANNOTATIONS)
    def remove_issue_reaction(owner: str, repo: str, issue_number: int, content: str) -> str:
        github.reactions[issue_number] = []
        return "ok"

    return server


def pack_for(tool: str) -> Pack:
    if "reaction" in tool:
        extra_args, extra_roles, supplies = {"content": "+1"}, {"content": "content"}, {}
    elif "assignees" in tool:
        extra_args, extra_roles, supplies = {"assignees": []}, {"assignees": "content"}, {}
    else:
        extra_args, extra_roles = {"labels": ["a"]}, {"labels": "content"}
        supplies = {"issue.labels": "labels"}
    return Pack(
        server="s",
        version="0",
        allowlist=[],
        repositories=REPOS,
        standard_read_only_fields=[],
        entries={
            tool: ToolEntry(
                tool=tool,
                fixture="issue_with_assignee" if "assignees" in tool else "issue_with_labels",
                arguments={
                    "owner": "{repo.owner}",
                    "repo": "{repo.name}",
                    "issue_number": "{fixture.issue_number}",
                    **extra_args,
                },
                argument_roles={
                    "owner": "owner",
                    "repo": "repository",
                    "issue_number": "id",
                    **extra_roles,
                },
                fields=[
                    FieldSpec("issue.labels", FieldKind.COLLECTION),
                    FieldSpec("issue.assignees", FieldKind.COLLECTION),
                    FieldSpec("issue.title", FieldKind.SCALAR),
                    FieldSpec("issue.body", FieldKind.SCALAR),
                    FieldSpec("issue.state", FieldKind.SCALAR),
                    FieldSpec("issue.reaction_set", FieldKind.COLLECTION),
                ],
                supplies=supplies,
            )
        },
    )


async def judged(tool: str, reactions: list[dict] | None = None):
    github = FakeGitHub()
    if reactions:
        github.reactions[1] = reactions
    rest = GitHubRest("dummy-token-value", transport=httpx.MockTransport(github.handler))
    async with Client(build(github)) as client:
        _, results = await run(
            client,
            GitHubReader(rest, REPOS),
            pack_for(tool),
            HEADER_CONTEXT,
            settle_interval_s=0.001,
            settle_timeout_s=0.05,
        )
    result = next(r for r in results if r.tool == tool)
    assert result.error is None, result.error
    verdict = next(v for v in result.verdicts if v.check is Check.NON_DESTRUCTIVE)
    return verdict, result, github


async def test_update_issue_labels_replacing_is_a_finding():
    verdict, result, _ = await judged("update_issue_labels")
    assert verdict.outcome is Outcome.FINDING
    assert result.outcome is Outcome.FINDING
    assert verdict.changed["issue.labels"] == (frozenset({"c", "d"}), frozenset({"a"}))


async def test_add_issue_labels_is_a_pass():
    verdict, result, github = await judged("add_issue_labels")
    assert verdict.outcome is Outcome.PASS
    assert result.outcome is Outcome.PASS
    names = {x["name"] for x in github.issues[1]["labels"]}
    assert {"a", "c", "d"} <= names  # the labels actually grew


async def test_add_reaction_is_a_pass_on_the_reaction_set():
    verdict, result, github = await judged("add_issue_reaction")
    assert verdict.outcome is Outcome.PASS
    assert github.reactions[1]


async def test_removing_a_reaction_is_a_finding():
    existing = [{"id": 5, "user": {"login": "bob"}, "content": "heart"}]
    verdict, result, _ = await judged("remove_issue_reaction", existing)
    assert verdict.outcome is Outcome.FINDING
    assert "issue.reaction_set" in verdict.changed


def test_issue_labels_is_not_composite():
    assert "issue.labels" not in COMPOSITE_FIELDS


async def test_update_issue_assignees_replacing_is_a_finding():
    verdict, result, _ = await judged("update_issue_assignees")
    assert result.outcome is Outcome.FINDING
    assert verdict.outcome is Outcome.FINDING
    assert verdict.changed["issue.assignees"] == (frozenset({"bot"}), frozenset())
