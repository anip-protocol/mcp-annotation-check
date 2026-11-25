"""Live checks of GitHub's listing semantics. Excluded from the default run.

Run only with the owner's fine-grained token for the dedicated test account, limited
to the two test repositories:

    MCP_ANNOTATION_CHECK_GITHUB_TOKEN=… \\
    MCP_ANNOTATION_CHECK_TEST_REPOSITORIES=test-org/read-repo,test-org/write-repo \\
    pytest -m live tests/github/test_live_preflight.py -v -s

Record what they print in docs/verification.md, with the date. Nothing here prints the
token, and every request is a GET.
"""

import os

import pytest

from mcp_annotation_check.github.rest import GitHubError, GitHubRest

pytestmark = pytest.mark.live

TOKEN_VAR = "MCP_ANNOTATION_CHECK_GITHUB_TOKEN"
REPOS_VAR = "MCP_ANNOTATION_CHECK_TEST_REPOSITORIES"


@pytest.fixture
async def rest():
    token = os.environ.get(TOKEN_VAR)
    if not token:
        pytest.skip(f"{TOKEN_VAR} is not set")
    client = GitHubRest(token)
    try:
        yield client
    finally:
        await client.aclose()


def expected_repositories() -> set[str]:
    raw = os.environ.get(REPOS_VAR, "")
    repos = {r.strip().casefold() for r in raw.split(",") if r.strip()}
    if len(repos) != 2:
        pytest.skip(f"{REPOS_VAR} must name the two test repositories as owner/name,owner/name")
    return repos


async def test_user_repos_reflects_token_scope(rest):
    expected = expected_repositories()
    listed = {r["full_name"].casefold() for r in await rest.get("/user/repos")}
    assert expected <= listed, f"the token cannot see {sorted(expected - listed)}"
    if listed == expected:
        print("\nOBSERVED: /user/repos returns only the token's repositories")
    else:
        print(
            f"\nOBSERVED: /user/repos returns the account's wider set "
            f"({len(listed)} repositories, {len(listed - expected)} beyond the token's two)"
        )


async def test_compensating_check_endpoints_answer(rest):
    """Preflight step 4 needs these to answer for a repository-only token."""
    for path, params in [("/user/orgs", None), ("/user/repos", {"affiliation": "owner"})]:
        try:
            data = await rest.get(path, params)
        except GitHubError as e:
            print(f"\nOBSERVED: GET {path} {params or ''} failed with {e.status}")
            raise
        print(f"\nOBSERVED: GET {path} {params or ''} answered with {len(data)} entries")
