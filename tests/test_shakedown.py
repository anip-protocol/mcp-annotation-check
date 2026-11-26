import json
from contextlib import asynccontextmanager

import httpx
import pytest

from mcp import Client
from mcp_annotation_check.cli import main, shakedown
from mcp_annotation_check.fake.server import FakeStore, build_fake_server
from mcp_annotation_check.github.reader import GitHubReader
from mcp_annotation_check.github.rest import GitHubRest
from mcp_annotation_check.pack import Pack, load_pack
from mcp_annotation_check.snapshot import FieldKind, FieldSpec
from support import FAKE_PACK

TOKEN = "github_pat_dummy_secret_value"
LOGIN = "tester"


class SpyClient:
    def __init__(self, client):
        self._client = client
        self.calls = 0

    async def call_tool(self, *a, **k):
        self.calls += 1
        raise AssertionError("shakedown must not call tools")

    def __getattr__(self, name):
        return getattr(self._client, name)


class SpyReader(GitHubReader):
    created = 0

    async def create_fixture(self, *a, **k):
        type(self).created += 1
        raise AssertionError("shakedown must not create fixtures")

    async def cleanup(self, *a, **k):
        type(self).created += 1
        raise AssertionError("shakedown must not clean up")


def pack_for_github() -> Pack:
    from dataclasses import replace

    pack = load_pack(FAKE_PACK)
    return replace(
        pack,
        allowlist=["owner"],
        repositories={"read": "owner/read-repo", "write": "owner/write-repo"},
        standard_read_only_fields=[FieldSpec("repo.labels", FieldKind.COLLECTION)],
    )


def make_rest(requests):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        path = request.url.path
        if path == "/user":
            return httpx.Response(200, json={"login": LOGIN})
        if path == "/user/repos":
            return httpx.Response(
                200,
                json=[
                    {"full_name": "owner/read-repo", "owner": {"login": "owner"}},
                    {"full_name": "owner/write-repo", "owner": {"login": "owner"}},
                ],
            )
        if path == "/user/orgs":
            return httpx.Response(200, json=[{"login": "owner"}])
        if path == "/repos/owner/read-repo/issues/1":
            return httpx.Response(200, json={"title": "t", "updated_at": "2026-01-01T00:00:00Z"})
        if path == "/repos/owner/read-repo/labels":
            return httpx.Response(
                200, json=[{"name": "bug", "color": "f00", "description": "d"}]
            )
        return httpx.Response(404, json={})

    return GitHubRest(TOKEN, transport=httpx.MockTransport(handler))


async def run_shakedown(pack, tmp_path, rest_requests):
    spies = []

    @asynccontextmanager
    async def open_client():
        async with Client(build_fake_server(FakeStore())) as client:
            spy = SpyClient(client)
            spies.append(spy)
            yield spy

    rest = make_rest(rest_requests)
    reader = SpyReader(rest, pack.repositories)
    try:
        ok = await shakedown(
            open_client, rest, reader, pack, TOKEN, LOGIN, {"image": "img", "image_digest": "d"},
            tmp_path,
        )
    finally:
        await rest.aclose()
    return ok, spies


async def test_shakedown_never_calls_tools_or_creates_fixtures(tmp_path):
    requests = []
    SpyReader.created = 0
    ok, spies = await run_shakedown(pack_for_github(), tmp_path, requests)
    report = json.loads((tmp_path / "shakedown.json").read_text())
    assert all(s.calls == 0 for s in spies) and spies
    assert SpyReader.created == 0
    assert requests and all(method == "GET" for method, _ in requests)
    assert ok is True
    assert report["steps"]["snapshot"]["passed"] is True
    assert report["snapshot_fields"] == ["repo.labels"]
    assert "bug" not in json.dumps(report)  # field names, never values
    assert report["tool_names"] and len(report["tools_list_sha256"]) == 64
    assert report["server_info"] and report["image"] == "img"


async def test_shakedown_snapshot_uses_read_fixtures_for_issue_fields(tmp_path):
    from dataclasses import replace

    pack = replace(
        pack_for_github(),
        standard_read_only_fields=[FieldSpec("issue.title", FieldKind.SCALAR)],
        read_fixtures={"issue_number": 1},
    )
    requests = []
    ok, _ = await run_shakedown(pack, tmp_path, requests)
    report = json.loads((tmp_path / "shakedown.json").read_text())
    assert report["steps"]["snapshot"]["passed"] is True, report["steps"]["snapshot"]
    assert report["snapshot_fields"] == ["issue.title"]
    assert ok is True
    assert ("GET", "/repos/owner/read-repo/issues/1") in requests


async def test_shakedown_reports_validation_problems_and_exits_nonzero(tmp_path):
    from dataclasses import replace

    pack = pack_for_github()
    entry = next(iter(pack.entries.values()))
    pack = replace(pack, entries={**pack.entries, "no_such_tool": entry})
    ok, _ = await run_shakedown(pack, tmp_path, [])
    report = json.loads((tmp_path / "shakedown.json").read_text())
    assert ok is False
    assert report["validation_problems"]
    assert report["steps"]["validate"]["passed"] is False


class LeakyReader(SpyReader):
    async def snapshot(self, *a, **k):
        raise RuntimeError(f"boom with {TOKEN} inside")


async def test_shakedown_json_has_no_token(tmp_path, capsys):
    from mcp_annotation_check.redact import REDACTED

    pack = pack_for_github()

    @asynccontextmanager
    async def open_client():
        async with Client(build_fake_server(FakeStore())) as client:
            yield client

    rest = make_rest([])
    ok = await shakedown(open_client, rest, LeakyReader(rest, pack.repositories),
                         pack, TOKEN, LOGIN, {}, tmp_path)
    await rest.aclose()
    text = (tmp_path / "shakedown.json").read_text()
    steps = json.loads(text)["steps"]
    assert ok is False
    assert steps["snapshot"]["passed"] is False
    assert REDACTED in steps["snapshot"]["error"]
    assert TOKEN not in text
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err


async def test_shakedown_preflight_failure_message_with_token_is_redacted(tmp_path):
    from mcp_annotation_check.redact import REDACTED

    pack = pack_for_github()
    # The account login in the error comes from the response; make it carry the token.
    rest = GitHubRest(
        TOKEN,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"login": TOKEN})),
    )

    @asynccontextmanager
    async def open_client():
        raise AssertionError("must not start")
        yield

    ok = await shakedown(open_client, rest, GitHubReader(rest, pack.repositories),
                         pack, TOKEN, LOGIN, {}, tmp_path)
    await rest.aclose()
    text = (tmp_path / "shakedown.json").read_text()
    assert ok is False
    assert json.loads(text)["steps"]["preflight"]["passed"] is False
    assert REDACTED in text and TOKEN not in text


async def test_shakedown_records_failed_step_and_marks_rest_not_run(tmp_path):
    from dataclasses import replace

    pack = replace(pack_for_github(), repositories={"read": "owner/read-repo"})
    rest = GitHubRest(
        TOKEN, transport=httpx.MockTransport(lambda r: httpx.Response(500, json={}))
    )

    @asynccontextmanager
    async def open_client():
        raise AssertionError("server must not start after a failed preflight")
        yield

    ok = await shakedown(open_client, rest, GitHubReader(rest, pack.repositories),
                         pack, TOKEN, LOGIN, {}, tmp_path)
    await rest.aclose()
    steps = json.loads((tmp_path / "shakedown.json").read_text())["steps"]
    assert ok is False
    assert steps["preflight"]["passed"] is False
    assert steps["start"]["status"] == "not run"
    assert steps["snapshot"]["status"] == "not run"


def test_shakedown_cli_requires_token(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("MCP_ANNOTATION_CHECK_GITHUB_TOKEN", raising=False)
    code = main(["shakedown", "--pack", str(FAKE_PACK), "--login", LOGIN, "--image", "i",
                 "--toolsets", "default", "--out", str(tmp_path)])
    assert code == 1
    assert "MCP_ANNOTATION_CHECK_GITHUB_TOKEN" in capsys.readouterr().err


def test_shakedown_cli_client_may_write_nowhere(monkeypatch, tmp_path):
    from mcp_annotation_check import cli

    seen: dict = {}

    class FakeRest:
        def __init__(self, token, transport=None, write_repositories=None):
            seen["write_repositories"] = write_repositories

        async def aclose(self):
            seen["closed"] = True

    async def fake_shakedown(open_client, rest, reader, *a, **k):
        seen["rest"] = rest
        return True

    monkeypatch.setenv("MCP_ANNOTATION_CHECK_GITHUB_TOKEN", TOKEN)
    monkeypatch.setattr(cli, "GitHubRest", FakeRest)
    monkeypatch.setattr(cli, "image_digest", lambda image: "i@sha256:abc")
    monkeypatch.setattr(cli, "shakedown", fake_shakedown)
    code = main(["shakedown", "--pack", str(FAKE_PACK), "--login", LOGIN, "--image", "i",
                 "--toolsets", "default", "--out", str(tmp_path)])
    assert code == 0
    # An empty collection, not None: every write is refused.
    assert seen["write_repositories"] is not None
    assert list(seen["write_repositories"]) == []
    assert seen["closed"] is True
