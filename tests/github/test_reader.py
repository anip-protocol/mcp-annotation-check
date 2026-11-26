import json

import httpx
import pytest

from mcp import Client
from mcp.types import ToolAnnotations
from mcp_annotation_check.fake.server import FakeStore, build_fake_server
from mcp_annotation_check.github.reader import GitHubReader
from mcp_annotation_check.github.rest import GitHubError, GitHubRest
from mcp_annotation_check.pack import Pack, ToolEntry
from mcp_annotation_check.runner import run
from mcp_annotation_check.snapshot import FieldKind, FieldSpec, Outcome
from support import HEADER_CONTEXT

REPOS = {"read": "o/read", "write": "o/write"}
TOKEN = "dummy-token-value"


def make(handler):
    calls: list[tuple[str, str, dict | None]] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        return handler(request)

    rest = GitHubRest(TOKEN, transport=httpx.MockTransport(wrapped))
    return GitHubReader(rest, REPOS), calls


def entry(fixture="issue_with_labels", tool="add_labels"):
    return ToolEntry(tool=tool, fixture=fixture)


async def test_snapshot_issue_fields():
    issue = {
        "labels": [{"name": "c"}, {"name": "d"}],
        "assignees": [{"login": "alice"}],
        "title": "T",
        "body": "B",
        "state": "open",
        "reactions": {"total_count": 3},
        "updated_at": "2026-01-01T00:00:00Z",
    }
    comments = [{"id": 9, "body": "hi", "reactions": {"total_count": 1}}]

    def handler(request):
        if request.url.path.endswith("/comments"):
            return httpx.Response(200, json=comments)
        assert request.url.path == "/repos/o/write/issues/7"
        return httpx.Response(200, json=issue)

    reader, _ = make(handler)
    fields = [
        FieldSpec("issue.labels", FieldKind.COLLECTION),
        FieldSpec("issue.assignees", FieldKind.COLLECTION),
        FieldSpec("issue.title", FieldKind.SCALAR),
        FieldSpec("issue.body", FieldKind.SCALAR),
        FieldSpec("issue.state", FieldKind.SCALAR),
        FieldSpec("issue.reactions", FieldKind.SCALAR),
        FieldSpec("issue.comments", FieldKind.COLLECTION),
    ]
    rec = await reader.snapshot(fields, {"repository": "o/write", "issue_number": 7})
    assert rec.snapshot == {
        "issue.labels": frozenset({"c", "d"}),
        "issue.assignees": frozenset({"alice"}),
        "issue.title": "T",
        "issue.body": "B",
        "issue.state": "open",
        "issue.reactions": 3,
        "issue.comments": frozenset({(9, "hi", 1)}),
    }
    assert rec.timestamps == {"issue": "2026-01-01T00:00:00Z"}


async def test_snapshot_requires_the_fixture_repository():
    reader, calls = make(lambda r: httpx.Response(200, json=[]))
    with pytest.raises(ValueError, match="names no 'repository'"):
        await reader.snapshot([FieldSpec("repo.labels", FieldKind.COLLECTION)], {})
    assert calls == []


async def test_write_repository_entry_without_fixture_snapshots_the_write_repo():
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json=[{"name": "bug", "color": "f00", "description": None}])

    rest = GitHubRest(TOKEN, transport=httpx.MockTransport(handler))
    server = build_fake_server(FakeStore())

    @server.tool(name="list_labels", annotations=ToolAnnotations(read_only_hint=True))
    def list_labels() -> str:
        return "bug"

    pack = Pack(
        server="s",
        version="0",
        allowlist=[],
        repositories=REPOS,
        standard_read_only_fields=[FieldSpec("repo.labels", FieldKind.COLLECTION)],
        no_target_tools=["list_labels"],  # takes no arguments, so names no repository
        entries={"list_labels": ToolEntry(tool="list_labels")},  # repository: write, no fixture
    )
    async with Client(server) as client:
        _, results = await run(
            client,
            GitHubReader(rest, REPOS),
            pack,
            HEADER_CONTEXT,
            settle_interval_s=0.01,
            settle_timeout_s=0.3,
        )
    result = next(r for r in results if r.tool == "list_labels")
    assert result.outcome is Outcome.PASS
    assert seen and set(seen) == {"/repos/o/write/labels"}


async def test_pagination_follows_link_header():
    def handler(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"n": 2}])
        return httpx.Response(
            200,
            json=[{"n": 1}],
            headers={"Link": '<https://api.github.com/things?page=2>; rel="next"'},
        )

    rest = GitHubRest(TOKEN, transport=httpx.MockTransport(handler))
    assert await rest.get("/things") == [{"n": 1}, {"n": 2}]


async def test_issue_with_labels_fixture_calls():
    def handler(request):
        p = request.url.path
        if request.method == "GET":
            return httpx.Response(200, json={"name": "x"})
        if p.endswith("/issues"):
            return httpx.Response(201, json={"number": 5})
        return httpx.Response(200, json={})

    reader, calls = make(handler)
    fixture = await reader.create_fixture(entry(), "abc")
    assert fixture == {"repository": "o/write", "issue_number": 5}
    assert [c for c in calls if c[0] == "POST"] == [
        (
            "POST",
            "/repos/o/write/issues",
            {"title": "mac-abc-add_labels", "body": "fixture", "labels": ["c", "d"]},
        )
    ]


async def test_missing_labels_are_created():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(404, json={})
        if request.url.path.endswith("/issues"):
            return httpx.Response(201, json={"number": 5})
        return httpx.Response(201, json={})

    reader, calls = make(handler)
    await reader.create_fixture(entry(), "abc")
    posts = [c for c in calls if c[0] == "POST" and c[1].endswith("/labels")]
    assert [c[2]["name"] for c in posts] == ["c", "d"]


async def test_cleanup_closes_and_labels_done_never_deletes_done_label():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(404, json={})
        if request.url.path.endswith("/issues"):
            return httpx.Response(201, json={"number": 5})
        return httpx.Response(200, json={})

    reader, calls = make(handler)
    e = entry()
    fixture = await reader.create_fixture(e, "abc")
    calls.clear()
    await reader.cleanup(e, fixture)
    assert ("PATCH", "/repos/o/write/issues/5", {"state": "closed"}) in calls
    assert (
        "POST",
        "/repos/o/write/issues/5/labels",
        {"labels": ["mcp-annotation-check:done"]},
    ) in calls
    deleted = [c[1] for c in calls if c[0] == "DELETE"]
    assert not any("mcp-annotation-check" in p for p in deleted)
    assert not any(p.endswith(("/labels/c", "/labels/d")) for p in deleted)


async def test_cleanup_with_nothing_created_is_a_no_op():
    reader, calls = make(lambda r: httpx.Response(500))
    await reader.cleanup(entry(), {})
    assert calls == []


async def test_open_pr_failure_still_deletes_the_branch():
    def handler(request):
        p, m = request.url.path, request.method
        if m == "GET" and p == "/repos/o/write":
            return httpx.Response(200, json={"default_branch": "main"})
        if m == "GET":
            return httpx.Response(200, json={"object": {"sha": "abc"}})
        if p.endswith("/pulls"):
            return httpx.Response(422, json={})
        return httpx.Response(201, json={})

    reader, calls = make(handler)
    e = entry("open_pr", "t")
    with pytest.raises(GitHubError):
        await reader.create_fixture(e, "r")
    await reader.cleanup(e, {})
    assert ("DELETE", "/repos/o/write/git/refs/heads/mac-r-t", None) in calls


async def test_rest_error_mid_fixture_is_reported_and_cleanup_attempted():
    cleaned: list[dict] = []

    class Spy(GitHubReader):
        async def cleanup(self, entry, fixture):
            cleaned.append(fixture)
            await super().cleanup(entry, fixture)

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"name": "x"})
        return httpx.Response(403, json={}, headers={"x-ratelimit-remaining": "0"})

    rest = GitHubRest(TOKEN, transport=httpx.MockTransport(handler))
    reader = Spy(rest, REPOS)
    pack = Pack(
        server="s",
        version="0",
        allowlist=[],
        repositories=REPOS,
        standard_read_only_fields=[],
        id_only_write_tools=["add_labels"],
        entries={
            "add_labels": ToolEntry(
                tool="add_labels",
                fixture="issue_with_labels",
                arguments={"issue_id": "{fixture.issue_number}", "labels": ["x"]},
                argument_roles={"issue_id": "id", "labels": "content"},
            )
        },
    )
    async with Client(build_fake_server(FakeStore())) as client:
        _, results = await run(
            client, reader, pack, HEADER_CONTEXT, settle_interval_s=0.01, settle_timeout_s=0.3
        )
    result = next(r for r in results if r.tool == "add_labels")
    assert result.outcome is Outcome.ERROR
    assert "403" in result.error
    assert cleaned == [{}]
    # the run continued past it
    assert {r.tool for r in results} > {"add_labels"}


async def test_github_error_message_has_no_headers():
    def handler(request):
        return httpx.Response(401, json={}, headers={"x-ratelimit-remaining": "0", "x-secret": "s3"})

    rest = GitHubRest(TOKEN, transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubError) as info:
        await rest.get("/user")
    text = str(info.value)
    assert info.value.status == 401
    assert "/user" in text
    assert TOKEN not in text and "Bearer" not in text and "s3" not in text


# --- repository and pull request fields, and the open_pr fixture (final fix wave) ---


async def test_snapshot_repo_refs_reads_heads_and_tags():
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/repos/o/write/git/matching-refs/heads/":
            return httpx.Response(
                200,
                json=[
                    {"ref": "refs/heads/main", "object": {"sha": "a1"}},
                    {"ref": "refs/heads/topic", "object": {"sha": "b2"}},
                ],
            )
        if request.url.path == "/repos/o/write/git/matching-refs/tags/":
            return httpx.Response(200, json=[{"ref": "refs/tags/v1", "object": {"sha": "c3"}}])
        return httpx.Response(404, json={})

    reader, _ = make(handler)
    rec = await reader.snapshot(
        [FieldSpec("repo.refs", FieldKind.COLLECTION)], {"repository": "o/write"}
    )
    assert rec.snapshot == {
        "repo.refs": frozenset(
            {("refs/heads/main", "a1"), ("refs/heads/topic", "b2"), ("refs/tags/v1", "c3")}
        )
    }
    assert seen == [
        "/repos/o/write/git/matching-refs/heads/",
        "/repos/o/write/git/matching-refs/tags/",
    ]
    assert rec.timestamps == {}


async def test_snapshot_repo_issues_lists_every_state():
    params: list[dict] = []

    def handler(request):
        assert request.url.path == "/repos/o/read/issues"
        params.append(dict(request.url.params))
        return httpx.Response(
            200,
            json=[
                {
                    "number": 1,
                    "title": "open one",
                    "state": "open",
                    "labels": [{"name": "d"}, {"name": "c"}],
                    "reactions": {"total_count": 2},
                },
                {"number": 2, "title": "closed one", "state": "closed", "labels": []},
            ],
        )

    reader, _ = make(handler)
    rec = await reader.snapshot(
        [FieldSpec("repo.issues", FieldKind.COLLECTION)], {"repository": "o/read"}
    )
    assert rec.snapshot["repo.issues"] == frozenset(
        {(1, "open one", "open", ("c", "d"), 2), (2, "closed one", "closed", (), 0)}
    )
    assert params == [{"per_page": "100", "state": "all"}]


async def test_snapshot_pr_fields():
    pr = {
        "state": "open",
        "title": "PR title",
        "body": "PR body",
        "requested_reviewers": [{"login": "bob"}, {"login": "carol"}],
        "updated_at": "2026-02-02T00:00:00Z",
    }
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.path)
        assert request.url.path == "/repos/o/write/pulls/3"
        return httpx.Response(200, json=pr)

    reader, _ = make(handler)
    fields = [
        FieldSpec("pr.state", FieldKind.SCALAR),
        FieldSpec("pr.title", FieldKind.SCALAR),
        FieldSpec("pr.body", FieldKind.SCALAR),
        FieldSpec("pr.requested_reviewers", FieldKind.COLLECTION),
    ]
    rec = await reader.snapshot(fields, {"repository": "o/write", "pr_number": 3})
    assert rec.snapshot == {
        "pr.state": "open",
        "pr.title": "PR title",
        "pr.body": "PR body",
        "pr.requested_reviewers": frozenset({"bob", "carol"}),
    }
    assert rec.timestamps == {"pr": "2026-02-02T00:00:00Z"}
    assert seen == ["/repos/o/write/pulls/3"]  # read once, cached for every pr.* field


async def test_open_pr_fixture_happy_path_and_cleanup():
    def handler(request):
        p, m = request.url.path, request.method
        if m == "GET" and p == "/repos/o/write":
            return httpx.Response(200, json={"default_branch": "main"})
        if m == "GET" and p == "/repos/o/write/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": "abc123"}})
        if m == "POST" and p == "/repos/o/write/pulls":
            return httpx.Response(201, json={"number": 11})
        if m in ("POST", "PUT", "PATCH"):
            return httpx.Response(201, json={})
        if m == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404, json={})

    reader, calls = make(handler)
    e = entry("open_pr", "t")
    fixture = await reader.create_fixture(e, "r")
    assert fixture == {"repository": "o/write", "pr_number": 11, "branch": "mac-r-t"}
    assert [c for c in calls if c[0] != "GET"] == [
        ("POST", "/repos/o/write/git/refs", {"ref": "refs/heads/mac-r-t", "sha": "abc123"}),
        (
            "PUT",
            "/repos/o/write/contents/fixtures/mac-r-t.txt",
            {"message": "fixture mac-r-t", "content": "Zml4dHVyZQo=", "branch": "mac-r-t"},
        ),
        (
            "POST",
            "/repos/o/write/pulls",
            {"title": "mac-r-t", "head": "mac-r-t", "base": "main", "body": "fixture"},
        ),
    ]
    calls.clear()
    await reader.cleanup(e, fixture)
    assert calls == [
        ("PATCH", "/repos/o/write/pulls/11", {"state": "closed"}),
        ("POST", "/repos/o/write/issues/11/labels", {"labels": ["mcp-annotation-check:done"]}),
        ("DELETE", "/repos/o/write/git/refs/heads/mac-r-t", None),
    ]
