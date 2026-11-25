from pathlib import Path

from mcp_annotation_check.fake.reader import FakeReader
from mcp_annotation_check.fake.server import FakeStore
from mcp_annotation_check.redact import REDACTED, redact
from mcp_annotation_check.report import write_reports
from support import run_fake

TOKEN = "github_pat_dummy0000000000000000"
# Matches no token shape or header pattern: only the secret list can catch it.
OPAQUE = "opaque-dummy-secret-value"


def test_redact_removes_token_and_authorization_header():
    out = redact("Authorization: Bearer github_pat_abc", ["github_pat_abc"])
    assert "github_pat_abc" not in out
    assert "Bearer github" not in out
    assert REDACTED == "[REDACTED]"
    assert REDACTED in out


def test_redact_headers_without_a_secret_list():
    for text in [
        "Authorization: Bearer opaque-value",
        "authorization: token opaque-value",
        "{'authorization': 'Bearer opaque-value', 'accept': 'json'}",
        'headers={"Authorization": "Bearer opaque-value"}',
        "sent Bearer opaque-value to the API",
        "url?access_token=opaque-value&x=1",
        "token opaque-value-123",
    ]:
        out = redact(text)
        assert "opaque-value" not in out, text
        assert REDACTED in out, text


def test_redact_github_token_shapes_without_a_secret_list():
    for token in ["ghp_" + "a1" * 18, "github_pat_" + "B2_" * 20, "ghs_" + "c3" * 18]:
        out = redact(f"failed with {token} in the body")
        assert token not in out
        assert out == f"failed with {REDACTED} in the body"


def test_redact_keeps_ordinary_text():
    for text in [
        "classic or app token; use a fine-grained token",
        "the token is invalid",
        "call refused: SafetyRefusal: owner other-owner is not on the allowlist",
    ]:
        assert redact(text) == text


def test_redact_replaces_every_secret_occurrence():
    out = redact("a SECRET1 b SECRET1 c secret2", ["SECRET1", "secret2", ""])
    assert out == f"a {REDACTED} b {REDACTED} c {REDACTED}"


def test_redact_never_raises():
    assert redact(None) == "None"  # type: ignore[arg-type]
    assert redact("x", [None, 3, "x"]) == REDACTED  # type: ignore[list-item]


class LeakyReader(FakeReader):
    """Raises errors whose text carries the token, as an httpx traceback might."""

    async def create_fixture(self, entry, run_id):
        if entry.tool == "set_labels":
            raise RuntimeError(f"request failed; headers: Authorization: Bearer {TOKEN}")
        if entry.tool == "add_labels":
            raise RuntimeError(f"bad credentials {OPAQUE}")
        return await super().create_fixture(entry, run_id)

    async def cleanup(self, entry, fixture):
        if entry.tool == "add_labels":
            raise RuntimeError(f"cleanup saw {OPAQUE}")
        await super().cleanup(entry, fixture)


async def test_runner_error_text_is_redacted(tmp_path: Path):
    store = FakeStore()
    header, results = await run_fake(
        store=store, reader=LeakyReader(store), secrets=[TOKEN, OPAQUE]
    )
    write_reports(header, results, tmp_path)
    texts = {p.name: p.read_text() for p in tmp_path.iterdir()}
    for name, text in texts.items():
        assert TOKEN not in text, name
        assert OPAQUE not in text, name
        assert "Bearer github" not in text, name
    assert REDACTED in texts["report.md"]
    assert REDACTED in texts["report.json"]
    errors = {r.tool: r.error for r in results if r.error}
    assert TOKEN not in repr(errors) and OPAQUE not in repr(errors)
    assert REDACTED in errors["set_labels"]
    assert "cleanup failed" in errors["add_labels"]
