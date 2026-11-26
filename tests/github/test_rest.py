import httpx
import pytest

from mcp_annotation_check.cli import rest_for_run, rest_for_shakedown
from mcp_annotation_check.github.rest import GitHubRest, RestRefused
from mcp_annotation_check.pack import Pack

TOKEN = "github_pat_dummy0000000000000000"
WRITE, READ = "test-org/write-repo", "test-org/read-repo"


class Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"ok": True})


async def write(rest: GitHubRest, method: str, path: str) -> None:
    if method == "DELETE":
        await rest.delete(path)
    else:
        await getattr(rest, method.lower())(path, {"a": 1})


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize(
    "path",
    [
        "/repos/test-org/other-repo/issues",
        "/repos/outside-org/write-repo/issues",
        "/repos/test-org/write-repo-2/issues",
        "/repos/test-org/write-repo",  # the repository itself, not something inside it
        "/repos/test-org/write-repo/../other-repo/issues",
        "/repos/test-org/write-repo/./issues",
        "/repos/test-org/write-repo/%2e%2e/other-repo/issues",
        "/repos/test-org/write-repo//issues",
        "/repos/test-org/write-repo/issues?x=1",
        "/repos/test-org/write-repo/issues#x",
        "/repos/test-org/write-repo\\..\\other/issues",
        "/repos/test-ſrg/write-repo/issues",
        "/user/repos",
        "/orgs/test-org/repos",
        "repos/test-org/write-repo/issues",
        "https://api.github.com/repos/test-org/write-repo/issues",
        "//evil.example/repos/test-org/write-repo/issues",
    ],
)
async def test_rest_refuses_write_outside_pack_repositories(method, path):
    recorder = Recorder()
    rest = GitHubRest(TOKEN, transport=recorder.transport, write_repositories=[WRITE, READ])
    with pytest.raises(RestRefused, match=f"refusing {method} "):
        await write(rest, method, path)
    await rest.aclose()
    assert recorder.requests == []


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize(
    "path",
    [
        "/repos/test-org/write-repo/issues",
        "/repos/Test-Org/Write-Repo/issues/3/labels",
        "/repos/test-org/read-repo/labels/x",
    ],
)
async def test_rest_allows_write_inside(method, path):
    recorder = Recorder()
    rest = GitHubRest(TOKEN, transport=recorder.transport, write_repositories=[WRITE, READ])
    await write(rest, method, path)
    await rest.aclose()
    assert [(r.method, r.url.path) for r in recorder.requests] == [(method, path)]


@pytest.mark.parametrize("write_repositories", [None, [], [WRITE]])
async def test_rest_get_unrestricted(write_repositories):
    recorder = Recorder()
    rest = GitHubRest(TOKEN, transport=recorder.transport, write_repositories=write_repositories)
    for path in ("/user", "/user/repos", "/repos/outside-org/thing", "/repositories/5"):
        await rest.get(path)
    await rest.aclose()
    assert [r.method for r in recorder.requests] == ["GET"] * 4


def test_refusal_names_no_token():
    assert issubclass(RestRefused, Exception)
    assert TOKEN not in str(RestRefused("POST", "/x"))


def _pack() -> Pack:
    return Pack(
        server="github",
        version="1",
        allowlist=["test-org"],
        repositories={"write": WRITE, "read": READ},
        standard_read_only_fields=[],
        entries={},
    )


async def test_run_client_writes_only_to_the_write_repository():
    recorder = Recorder()
    rest = rest_for_run(TOKEN, _pack(), transport=recorder.transport)
    await rest.post(f"/repos/{WRITE}/issues", {"title": "t"})
    with pytest.raises(RestRefused):
        await rest.post("/repos/test-org/other-repo/issues", {"title": "t"})
    await rest.aclose()
    assert [r.url.path for r in recorder.requests] == [f"/repos/{WRITE}/issues"]


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_run_client_refuses_writes_to_the_read_repository(method):
    # The read repository holds fixed, hand-made fixtures; the harness never writes there.
    recorder = Recorder()
    rest = rest_for_run(TOKEN, _pack(), transport=recorder.transport)
    with pytest.raises(RestRefused, match=f"refusing {method} /repos/{READ}/"):
        await write(rest, method, f"/repos/{READ}/issues/1")
    await rest.get(f"/repos/{READ}/labels")  # reading it is fine
    await rest.aclose()
    assert [r.method for r in recorder.requests] == ["GET"]


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_shakedown_client_refuses_all_writes(method):
    recorder = Recorder()
    rest = rest_for_shakedown(TOKEN, transport=recorder.transport)
    for repository in (WRITE, READ):
        with pytest.raises(RestRefused):
            await write(rest, method, f"/repos/{repository}/issues")
    await rest.get(f"/repos/{READ}/labels")
    await rest.aclose()
    assert [r.method for r in recorder.requests] == ["GET"]


@pytest.mark.parametrize("fixture", ["issue_with_labels", "issue_with_comment", "open_pr"])
async def test_reader_fixture_lifecycle_passes_the_guard(fixture):
    from mcp_annotation_check.github.reader import GitHubReader
    from mcp_annotation_check.pack import ToolEntry

    sent: list[tuple[str, str]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append((request.method, request.url.path))
        path = request.url.path
        if request.method == "GET" and "/labels/" in path:
            return httpx.Response(404, json={})
        if path.endswith("/pulls"):
            return httpx.Response(201, json={"number": 2})
        if path.endswith("/issues"):
            return httpx.Response(201, json={"number": 1})
        if path.endswith("/comments"):
            return httpx.Response(201, json={"id": 3})
        return httpx.Response(200, json={"default_branch": "main", "object": {"sha": "s"}})

    pack = _pack()
    rest = rest_for_run(TOKEN, pack, transport=httpx.MockTransport(handle))
    reader = GitHubReader(rest, pack.repositories)
    entry = ToolEntry(tool="t", fixture=fixture)
    created = await reader.create_fixture(entry, "abcd1234")
    await reader.cleanup(entry, created)
    await rest.aclose()
    writes = [(m, p) for m, p in sent if m != "GET"]
    assert writes and all(p.startswith(f"/repos/{WRITE}/") for _, p in writes)
