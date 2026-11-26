import copy

import httpx
import pytest

from mcp_annotation_check.github.rest import GitHubRest
from mcp_annotation_check.github.safety import SafetyRefusal, make_before_call, preflight
from mcp_annotation_check.pack import Pack

TOKEN = "github_pat_dummy0000000000000000"
LOGIN = "test-account"
ORG = "test-org"
READ, WRITE = f"{ORG}/read-repo", f"{ORG}/write-repo"


def pack(**overrides) -> Pack:
    values = dict(
        server="github",
        version="1",
        allowlist=[ORG],
        repositories={"read": READ, "write": WRITE},
        standard_read_only_fields=[],
        entries={},
        id_only_write_tools=["update_by_id"],
    )
    values.update(overrides)
    return Pack(**values)


def repo(full_name: str) -> dict:
    return {"full_name": full_name, "owner": {"login": full_name.split("/")[0]}}


class GitHub:
    """A MockTransport-backed GitHubRest that records every request.

    `routes` maps a path (or "path?affiliation=owner") to (status, json) or a json body.
    Anything else is a 404.
    """

    def __init__(self, routes: dict | None = None) -> None:
        self.routes = {
            "/user": {"login": LOGIN},
            "/user/repos": [repo(READ), repo(WRITE)],
            "/user/repos?affiliation=owner": [],
            "/user/orgs": [{"login": ORG}],
            **(routes or {}),
        }
        self.requests: list[httpx.Request] = []
        self.rest = GitHubRest(TOKEN, transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        affiliation = request.url.params.get("affiliation")
        key = f"{path}?affiliation={affiliation}" if affiliation else path
        if key not in self.routes:
            return httpx.Response(404, json={"message": "Not Found"})
        route = self.routes[key]
        if callable(route):
            return route(request)
        if isinstance(route, tuple):
            status, body = route
            return httpx.Response(status, json=body)
        return httpx.Response(200, json=route)

    @property
    def methods(self) -> set[str]:
        return {r.method for r in self.requests}


# --- preflight --------------------------------------------------------------


@pytest.mark.parametrize("prefix", ["ghp_", "gho_", "ghu_", "ghs_"])
async def test_classic_token_refused(prefix):
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="classic or app token; use a fine-grained token"):
        await preflight(gh.rest, prefix + "dummy000000000000", pack(), LOGIN)
    assert gh.requests == []


async def test_token_that_is_not_fine_grained_refused():
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="github_pat_"):
        await preflight(gh.rest, "some-other-dummy-token", pack(), LOGIN)
    assert gh.requests == []


async def test_wrong_login_refused():
    gh = GitHub({"/user": {"login": "someone-else"}})
    with pytest.raises(SafetyRefusal, match="someone-else"):
        await preflight(gh.rest, TOKEN, pack(), LOGIN)


async def test_repo_outside_allowlist_refused():
    gh = GitHub({"/user/repos": [repo(READ), repo(WRITE), repo("other-owner/thing")]})
    with pytest.raises(SafetyRefusal, match="other-owner/thing"):
        await preflight(gh.rest, TOKEN, pack(), LOGIN)


async def test_repo_outside_allowlist_on_a_later_page_refused():
    def first(request):
        return httpx.Response(
            200,
            json=[repo(READ), repo(WRITE)],
            headers={"Link": '<https://api.github.com/user/repos?page=2>; rel="next"'},
        )

    def paged(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[repo("other-owner/thing")])
        return first(request)

    gh = GitHub({"/user/repos": paged})
    with pytest.raises(SafetyRefusal, match="other-owner/thing"):
        await preflight(gh.rest, TOKEN, pack(), LOGIN)


async def test_missing_pack_repository_refused():
    gh = GitHub({"/user/repos": [repo(READ)]})
    with pytest.raises(SafetyRefusal, match=WRITE):
        await preflight(gh.rest, TOKEN, pack(), LOGIN)


async def test_extra_org_membership_refused():
    gh = GitHub({"/user/orgs": [{"login": ORG}, {"login": "real-company"}]})
    with pytest.raises(SafetyRefusal, match="real-company"):
        await preflight(gh.rest, TOKEN, pack(), LOGIN)


async def test_owned_repo_outside_allowlist_refused():
    gh = GitHub({"/user/repos?affiliation=owner": [repo(f"{LOGIN}/personal")]})
    with pytest.raises(SafetyRefusal, match=f"{LOGIN}/personal"):
        await preflight(gh.rest, TOKEN, pack(), LOGIN)


async def test_preflight_rest_failure_refused():
    gh = GitHub({"/user/orgs": (403, {"message": "Resource not accessible"})})
    with pytest.raises(SafetyRefusal, match="403"):
        await preflight(gh.rest, TOKEN, pack(), LOGIN)


async def test_preflight_returns_facts_and_only_gets():
    gh = GitHub()
    facts = await preflight(gh.rest, TOKEN, pack(), LOGIN)
    assert facts["login"] == LOGIN
    assert facts["repositories"] == sorted([READ, WRITE])
    assert facts["organizations"] == [ORG]
    assert gh.methods == {"GET"}
    assert TOKEN not in repr(facts)


async def test_owner_comparison_is_case_insensitive():
    gh = GitHub({"/user/repos": [repo("Test-Org/read-repo"), repo("TEST-ORG/Write-Repo")]})
    facts = await preflight(gh.rest, TOKEN, pack(), LOGIN)
    assert facts["login"] == LOGIN


# --- per-call checks ---------------------------------------------------------


@pytest.mark.parametrize(
    "arguments",
    [
        {"owner": "other-owner", "repo": "thing"},
        {"owner": "other-owner"},
        {"repo": "other-owner/thing"},
        {"repository": "other-owner/thing"},
        {"full_name": "other-owner/thing"},
        {"owner": ORG, "repo": "other-owner/thing"},
        {"nested": {"owner": "other-owner", "repo": "thing"}},
    ],
)
async def test_call_to_non_allowlisted_owner_refused(arguments):
    gh = GitHub()
    before_call = make_before_call(gh.rest, pack())
    with pytest.raises(SafetyRefusal, match="other-owner"):
        await before_call("add_labels", arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        {"owner": "Test-Org", "repo": "write-repo"},
        {"repository": "TEST-ORG/write-repo"},
        {"full_name": WRITE},
        {"owner": ORG, "repository": "write-repo"},
    ],
)
async def test_call_to_allowlisted_owner_allowed(arguments):
    gh = GitHub()
    await make_before_call(gh.rest, pack())("add_labels", arguments)
    assert gh.requests == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"repo": "write-repo"},
        {"repository": "write-repo"},
        {"owner": 42, "repo": "write-repo"},
        {"full_name": "a/b/c"},
        {"repository": "/write-repo"},
    ],
)
async def test_unresolvable_repository_argument_refused(arguments):
    gh = GitHub()
    with pytest.raises(SafetyRefusal):
        await make_before_call(gh.rest, pack())("add_labels", arguments)


async def test_id_only_write_unresolvable_refused():
    gh = GitHub()  # GET /repositories/123 is a 404
    before_call = make_before_call(gh.rest, pack())
    with pytest.raises(SafetyRefusal, match="update_by_id"):
        await before_call("update_by_id", {"repository_id": 123})
    assert [r.url.path for r in gh.requests] == ["/repositories/123"]
    assert gh.methods == {"GET"}


async def test_id_only_write_resolved_to_allowlisted_owner_allowed():
    gh = GitHub({"/repositories/123": {"full_name": WRITE, "owner": {"login": ORG}}})
    await make_before_call(gh.rest, pack())("update_by_id", {"repository_id": 123})


async def test_id_only_write_resolved_to_other_owner_refused():
    gh = GitHub({"/repositories/123": repo("other-owner/thing")})
    with pytest.raises(SafetyRefusal, match="other-owner"):
        await make_before_call(gh.rest, pack())("update_by_id", {"repository_id": 123})


async def test_id_only_issue_number_without_repository_refused():
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="repository"):
        await make_before_call(gh.rest, pack())("update_by_id", {"issue_number": 7})
    assert gh.requests == []


async def test_id_only_issue_number_resolved_within_repository():
    issue = {"repository_url": f"https://api.github.com/repos/{WRITE}"}
    gh = GitHub({f"/repos/{WRITE}/issues/7": issue})
    await make_before_call(gh.rest, pack())(
        "update_by_id", {"owner": ORG, "repo": "write-repo", "issue_number": 7}
    )
    assert [r.url.path for r in gh.requests] == [f"/repos/{WRITE}/issues/7"]


async def test_id_only_issue_that_moved_refused():
    # A transferred issue answers with a redirect body, not an issue: no owner to confirm.
    moved_to = "https://api.github.com/repositories/9/issues/7"
    moved = (301, {"message": "Moved Permanently", "url": moved_to})
    gh = GitHub({f"/repos/{WRITE}/issues/7": moved})
    with pytest.raises(SafetyRefusal):
        await make_before_call(gh.rest, pack())(
            "update_by_id", {"owner": ORG, "repo": "write-repo", "issue_number": 7}
        )


async def test_id_only_unknown_id_kind_refused():
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="widget_id"):
        await make_before_call(gh.rest, pack())(
            "update_by_id", {"owner": ORG, "repo": "write-repo", "widget_id": 5}
        )


async def test_id_only_without_any_id_refused():
    gh = GitHub()
    with pytest.raises(SafetyRefusal):
        await make_before_call(gh.rest, pack())(
            "update_by_id", {"owner": ORG, "repo": "write-repo"}
        )


async def test_content_rule_reapplied_to_rendered_arguments():
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="@mention"):
        await make_before_call(gh.rest, pack())(
            "add_comment", {"owner": ORG, "repo": "write-repo", "body": "hello @someone"}
        )


async def test_search_query_not_modified():
    gh = GitHub()
    arguments = {"query": "repo:test-org/read-repo is:open label:bug sort:updated"}
    original = copy.deepcopy(arguments)
    await make_before_call(gh.rest, pack())("search_issues", arguments)
    assert arguments == original
    assert gh.requests == []


# --- owner-naming arguments beyond the four basic keys (ruling R14) -------------


async def test_fork_into_outside_organization_refused():
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="outside-org"):
        await make_before_call(gh.rest, pack())(
            "fork_repository", {"owner": ORG, "repo": "write-repo", "organization": "outside-org"}
        )


@pytest.mark.parametrize(
    "arguments",
    [
        {"org": "outside-org"},
        {"organization": "outside-org"},
        {"user": "outside-org"},
        {"username": "outside-org"},
        {"Owner": "outside-org", "repo": "thing"},
        {"owner_login": "outside-org"},
        {"ownerLogin": "outside-org"},
        {"repo_owner": "outside-org"},
        {"owner": ORG, "repo_name": "outside-org/thing"},
        {"repoName": "outside-org/thing"},
        {"repository_name": "outside-org/thing"},
        {"repositoryFullName": "outside-org/thing"},
        {"nameWithOwner": "outside-org/thing"},
        {"org": "outside-org", "repo_name": "thing"},
        {"nested": [{"Organization": "outside-org"}]},
    ],
)
async def test_owner_key_variants_checked(arguments):
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="outside-org"):
        await make_before_call(gh.rest, pack())("some_tool", arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        {"Owner": ORG, "repoName": "write-repo"},
        {"organization": "Test-Org"},
        {"owner_login": ORG, "repository_name": "write-repo"},
        {"username": ORG},
        {"login": ORG},
        {"namespace": "Test-Org"},
        {"account": ORG},
        {"report": "weekly", "body": "text", "sort_order": "asc", "category": "x"},
    ],
)
async def test_owner_key_variants_allowed(arguments):
    gh = GitHub()
    await make_before_call(gh.rest, pack())("some_tool", arguments)
    assert gh.requests == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"owner_type": "Organization"},
        {"orgs": [ORG]},
        {"user_id": 5},
        {"organization": {"login": ORG}},
        {"repositories": [WRITE]},
    ],
)
async def test_uninterpretable_owner_or_repository_argument_refused(arguments):
    gh = GitHub()
    with pytest.raises(SafetyRefusal):
        await make_before_call(gh.rest, pack())("some_tool", arguments)
    assert gh.requests == []


async def test_bare_repository_with_two_owners_refused():
    gh = GitHub()
    two = pack(allowlist=[ORG, "test-org-2"])
    with pytest.raises(SafetyRefusal, match="ambiguous"):
        await make_before_call(gh.rest, two)(
            "some_tool", {"owner": ORG, "org": "test-org-2", "repo": "write-repo"}
        )


async def test_repository_id_resolved_for_any_tool():
    gh = GitHub({"/repositories/5": repo("outside-org/thing")})
    with pytest.raises(SafetyRefusal, match="outside-org"):
        await make_before_call(gh.rest, pack())("get_repository", {"repository_id": 5})
    gh = GitHub({"/repositories/5": repo(WRITE)})
    await make_before_call(gh.rest, pack())("get_repository", {"repoId": 5})
    assert [r.url.path for r in gh.requests] == ["/repositories/5"]


# --- keys that join an owner or repository word without a separator (fix round 2) ---


@pytest.mark.parametrize(
    "key",
    ["newowner", "targetrepo", "forkorganization", "NEWOWNER", "ownér", "repository_slug",
     "accountid", "targetnamespace", "userlogins", "org2"],
)
@pytest.mark.parametrize("value", ["outside-org", "outside-org/x", ORG, WRITE])
async def test_unrecognised_owner_like_key_refused(key, value):
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="cannot interpret|non-ASCII"):
        await make_before_call(gh.rest, pack())("some_tool", {key: value})
    assert gh.requests == []


@pytest.mark.parametrize("key", ["login", "namespace", "account", "Login", "NAMESPACE"])
async def test_login_namespace_account_are_owner_keys(key):
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="outside-org"):
        await make_before_call(gh.rest, pack())("some_tool", {key: "outside-org"})


@pytest.mark.parametrize("key", ["report", "reports", "reporter"])
async def test_known_harmless_keys_allowed(key):
    gh = GitHub()
    await make_before_call(gh.rest, pack())("some_tool", {key: "outside-org/thing"})
    assert gh.requests == []


async def test_non_ascii_key_refused_even_without_an_owner_word():
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="non-ASCII"):
        await make_before_call(gh.rest, pack())("some_tool", {"tïtle": "x"})
