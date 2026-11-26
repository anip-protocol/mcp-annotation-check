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
    """Preflight step 4 needs these to answer for a repository-only token, and to report
    the account's memberships rather than only what the token can see.

    An empty or allowlisted answer alone cannot tell "the account has nothing else" from
    "the token hides it". To tell them apart, temporarily give the test account one
    membership outside the allowlist that the token was not granted, and name it:

      MCP_ANNOTATION_CHECK_KNOWN_EXTRA_ORG    a throwaway organization the account joined
      MCP_ANNOTATION_CHECK_KNOWN_OWNED_REPO   a throwaway repository the account owns
                                              (owner/name), not selected for the token

    Without them the test prints what was listed, and the comparison against the
    account's web UI (Settings > Organizations, and the account's repository list)
    must be done by hand.
    """
    probes = [
        ("/user/orgs", None, "login", os.environ.get("MCP_ANNOTATION_CHECK_KNOWN_EXTRA_ORG")),
        (
            "/user/repos",
            {"affiliation": "owner"},
            "full_name",
            os.environ.get("MCP_ANNOTATION_CHECK_KNOWN_OWNED_REPO"),
        ),
    ]
    for path, params, field, known in probes:
        label = f"GET {path}" + (f"?affiliation={params['affiliation']}" if params else "")
        try:
            data = await rest.get(path, params)
        except GitHubError as e:
            print(f"\nOBSERVED: {label} failed with {e.status}")
            raise
        listed = sorted(str(item.get(field)) for item in data)
        print(f"\nOBSERVED: {label} answered with {len(listed)} entries: {listed}")
        if not known:
            print(f"OBSERVED: {label}: no known extra entry named; compare with the web UI by hand")
        elif known.casefold() in {x.casefold() for x in listed}:
            print(f"OBSERVED: {label} lists {known}: it reports the account (step 4 is meaningful)")
        else:
            print(
                f"OBSERVED: {label} hides {known}: it is filtered by the token "
                "(step 4 passes vacuously)"
            )
