import copy

import httpx
import pytest

from mcp_annotation_check.github.rest import GitHubRest
from mcp_annotation_check.github.safety import SafetyRefusal, make_before_call, preflight
from mcp_annotation_check.pack import Pack, ToolEntry

TOKEN = "github_pat_dummy0000000000000000"
LOGIN = "test-account"
ORG = "test-org"
READ, WRITE = f"{ORG}/read-repo", f"{ORG}/write-repo"


# Every tool the per-call tests call, with the role of each argument it may take.
ROLES = {
    "add_labels": {
        "owner": "owner", "repo": "repository", "issue_number": "id",
        "labels": "content", "body": "content", "state": "other",
    },
    "by_full_name": {"full_name": "full_name", "body": "content"},
    "get_repository": {"repository_id": "repository_id"},
    "search_issues": {"query": "other", "page": "other"},
    "fork_repository": {"owner": "owner", "repo": "repository", "organization": "owner"},
    "two_owners": {"owner": "owner", "org": "owner", "repo": "repository"},
    "with_payload": {"owner": "owner", "repo": "repository", "payload": "content"},
    "update_by_id": {
        "owner": "owner", "repo": "repository", "repository_id": "repository_id",
        "issue_number": "id", "gist_id": "id", "widget_id": "id", "repo_id": "id",
        "pull_number": "other", "body": "content",
    },
    "search_other": {
        "query": "other", "owner": "other", "repo": "content", "issue_number": "other",
        "page": "other", "perPage": "other", "sort": "other", "order": "other",
        "type": "other", "q": "other", "minimal_output": "other",
    },
    "search_code": {
        "query": "other", "payload": "content", "owner": "owner", "repo": "repository",
        "full_name": "full_name", "repository_id": "repository_id", "issue_number": "id",
    },
}


def pack(**overrides) -> Pack:
    values = dict(
        server="github",
        version="1",
        allowlist=[ORG],
        repositories={"read": READ, "write": WRITE},
        standard_read_only_fields=[],
        entries={t: ToolEntry(tool=t, argument_roles=r) for t, r in ROLES.items()},
        id_only_write_tools=["update_by_id"],
        no_target_tools=["search_code", "search_other"],
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


# --- per-call checks: every argument has a declared role (spec Amendment 1) ------


async def check(arguments: dict, tool: str = "add_labels", gh: "GitHub | None" = None, **kw):
    gh = gh or GitHub()
    await make_before_call(gh.rest, pack(**kw))(tool, arguments)
    return gh


@pytest.mark.parametrize(
    "key",
    ["newowner", "targetrepo", "forkorganization", "NEWOWNER", "ownér", "repository_slug",
     "accountid", "targetnamespace", "userlogins", "org2", "Owner", "rеpo", "owner ",
     "title", "report"],
)
@pytest.mark.parametrize("value", ["outside-org", "outside-org/x", ORG, WRITE, 5])
async def test_argument_without_declared_role_refused(key, value):
    # "rеpo" has a Cyrillic "е"; "owner " a trailing space: neither is the declared key.
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="has no declared role"):
        await check({"owner": ORG, "repo": "write-repo", key: value}, gh=gh)
    assert gh.requests == []


async def test_tool_without_an_enabled_pack_entry_refused():
    skipped = {"add_labels": ToolEntry(tool="add_labels", status="skipped", skip_reason="x")}
    for kw in ({}, {"entries": skipped}):
        with pytest.raises(SafetyRefusal, match="no enabled pack entry"):
            await check({"body": "x"}, tool="not_in_pack" if not kw else "add_labels", **kw)


async def test_arguments_must_be_a_mapping():
    with pytest.raises(SafetyRefusal, match="not a mapping"):
        await check(["owner", ORG])


@pytest.mark.parametrize(
    ("arguments", "tool"),
    [
        ({"owner": "other-owner", "repo": "thing"}, "add_labels"),
        ({"owner": "other-owner"}, "add_labels"),
        ({"owner": ORG, "repo": "write-repo", "organization": "other-owner"}, "fork_repository"),
        ({"full_name": "other-owner/thing"}, "by_full_name"),
    ],
)
async def test_owner_not_on_the_allowlist_refused(arguments, tool):
    with pytest.raises(SafetyRefusal, match="other-owner"):
        await check(arguments, tool)


# U+017F LATIN SMALL LETTER LONG S casefolds to "s"; U+212A KELVIN SIGN lowers to "k".
LONG_S_ORG = "teſt-org"
KELVIN_ORG = "test-org-\u212a"


@pytest.mark.parametrize(
    "arguments",
    [
        {"owner": LONG_S_ORG, "repo": "write-repo"},
        {"owner": LONG_S_ORG},
        {"owner": "test org"},
        {"owner": 42, "repo": "write-repo"},
        {"owner": ["test-org"]},
        {"owner": ORG, "repo": "wrіte-repo"},  # Cyrillic "і"
        {"owner": ORG, "repo": "write repo"},
    ],
)
async def test_non_ascii_or_malformed_owner_or_repository_value_refused(arguments):
    gh = GitHub()
    with pytest.raises(SafetyRefusal):
        await check(arguments, gh=gh)
    assert gh.requests == []


async def test_kelvin_sign_owner_does_not_match_lowercased_allowlist():
    with pytest.raises(SafetyRefusal):
        await check({"owner": KELVIN_ORG}, allowlist=[ORG, "test-org-k"])


async def test_non_ascii_allowlist_entry_never_matches():
    with pytest.raises(SafetyRefusal):
        await check({"owner": "test-org"}, allowlist=[LONG_S_ORG])


@pytest.mark.parametrize(
    "arguments",
    [
        {"owner": ORG, "repo": "write-repo"},
        {"owner": "Test-Org", "repo": "Write-Repo"},
        {"owner": ORG, "repo": "read-repo", "issue_number": 7, "labels": ["a"], "state": "open"},
        {"owner": ORG},
        {"body": "plain text", "state": None},
    ],
)
async def test_allowlisted_owner_and_pack_repository_allowed(arguments):
    gh = await check(arguments)
    assert gh.requests == []


@pytest.mark.parametrize(
    ("arguments", "match"),
    [
        ({"repo": "write-repo"}, "exactly one owner"),
        ({"owner": ORG, "repo": "other-repo"}, "not one of the pack's repositories"),
        ({"owner": ORG, "repo": f"{ORG}/write-repo"}, "not a bare repository name"),
        ({"owner": ORG, "repo": ".."}, "not a bare repository name"),
        ({"owner": ORG, "repo": ""}, "not a bare repository name"),
    ],
)
async def test_repository_pairs_with_one_owner_and_names_a_pack_repository(arguments, match):
    with pytest.raises(SafetyRefusal, match=match):
        await check(arguments)


async def test_repository_with_two_owner_arguments_refused():
    two = dict(allowlist=[ORG, "test-org-2"])
    with pytest.raises(SafetyRefusal, match="exactly one owner"):
        await check({"owner": ORG, "org": "test-org-2", "repo": "write-repo"}, "two_owners", **two)


@pytest.mark.parametrize("value", [WRITE, "TEST-ORG/write-repo", READ])
async def test_full_name_naming_a_pack_repository_allowed(value):
    await check({"full_name": value}, "by_full_name")


@pytest.mark.parametrize(
    "value",
    [f"{ORG}/other", "write-repo", "a/b/c", "/write-repo", f"{LONG_S_ORG}/write-repo",
     f"{ORG}/..", 5],
)
async def test_full_name_not_naming_a_pack_repository_refused(value):
    with pytest.raises(SafetyRefusal):
        await check({"full_name": value}, "by_full_name")


async def test_repository_id_resolved_for_any_tool():
    gh = GitHub({"/repositories/5": repo("outside-org/thing")})
    with pytest.raises(SafetyRefusal, match="outside-org"):
        await check({"repository_id": 5}, "get_repository", gh=gh)
    gh = GitHub({"/repositories/5": repo(WRITE)})
    await check({"repository_id": 5}, "get_repository", gh)
    assert [r.url.path for r in gh.requests] == ["/repositories/5"]


async def test_unresolvable_repository_id_refused():
    gh = GitHub()  # a 404
    with pytest.raises(SafetyRefusal, match="could not resolve"):
        await check({"repository_id": 5}, "get_repository", gh=gh)


@pytest.mark.parametrize("value", ["5/../x", True, {"id": 5}, "5 6"])
async def test_repository_id_must_be_a_plain_id(value):
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="not a plain ID"):
        await check({"repository_id": value}, "get_repository", gh=gh)
    assert gh.requests == []


async def test_resolved_repository_owner_must_be_an_ascii_name():
    gh = GitHub({"/repositories/5": repo(f"{LONG_S_ORG}/w")})
    with pytest.raises(SafetyRefusal, match="not on the allowlist"):
        await check({"repository_id": 5}, "get_repository", gh=gh)


@pytest.mark.parametrize("value", ["7; rm", True, [7], {"n": 7}, 1.5])
async def test_id_role_value_must_be_a_plain_id(value):
    with pytest.raises(SafetyRefusal):
        await check({"owner": ORG, "repo": "write-repo", "issue_number": value})


async def test_content_rule_reapplied_to_rendered_arguments():
    with pytest.raises(SafetyRefusal, match="@mention"):
        await check({"owner": ORG, "repo": "write-repo", "body": "hello @someone"})


@pytest.mark.parametrize("value", ["see a/b#1", "cc @someone", "https://github.com/x"])
async def test_content_rule_applies_to_other_values(value):
    with pytest.raises(SafetyRefusal):
        await check({"query": value}, "search_issues")


@pytest.mark.parametrize("value", [{"a": 1}, ["a"], [ORG]])
async def test_nested_value_refused_unless_content(value):
    with pytest.raises(SafetyRefusal, match="nested"):
        await check({"query": value}, "search_issues")


async def test_search_query_not_modified():
    arguments = {"query": "repo:test-org/read-repo is:open label:bug sort:updated", "page": 2}
    original = copy.deepcopy(arguments)
    gh = await check(arguments, "search_issues")
    assert arguments == original
    assert gh.requests == []


# --- inside content values, the nested key walk still applies (defence in depth) ---


@pytest.mark.parametrize(
    "payload",
    [
        {"owner": "outside-org", "repo": "thing"},
        {"org": "outside-org"},
        {"organization": "outside-org"},
        {"username": "outside-org"},
        {"Owner": "outside-org", "repo": "thing"},
        {"ownerLogin": "outside-org"},
        {"repo_owner": "outside-org"},
        {"login": "outside-org"},
        {"namespace": "outside-org"},
        {"repoName": "outside-org/thing"},
        {"nameWithOwner": "outside-org/thing"},
        {"org": "outside-org", "repo_name": "thing"},
        [{"Organization": "outside-org"}],
        {"a": [{"b": {"owner": "outside-org"}}]},
    ],
)
async def test_owner_inside_content_checked(payload):
    with pytest.raises(SafetyRefusal, match="outside-org"):
        await check({"owner": ORG, "repo": "write-repo", "payload": payload}, "with_payload")


@pytest.mark.parametrize(
    "payload",
    [
        {"owner_type": "Organization"},
        {"orgs": [ORG]},
        {"user_id": 5},
        {"organization": {"login": ORG}},
        {"repositories": [WRITE]},
        {"newowner": ORG},
        {"tïtle": "x"},
        {"repo": "write-repo"},
        {"owner": ORG, "org": "test-org-2", "repo": "write-repo"},
    ],
)
async def test_uninterpretable_key_inside_content_refused(payload):
    gh = GitHub()
    with pytest.raises(SafetyRefusal):
        await check(
            {"owner": ORG, "repo": "write-repo", "payload": payload},
            "with_payload",
            gh=gh,
            allowlist=[ORG, "test-org-2"],
        )
    assert gh.requests == []


@pytest.mark.parametrize(
    "payload",
    [
        {"Owner": ORG, "repoName": "write-repo"},
        {"organization": "Test-Org"},
        {"report": "weekly", "body": "text", "sort_order": "asc", "category": "x"},
        ["a", "b"],
        {"labels": ["x"], "text": "outside-org/thing"},
    ],
)
async def test_harmless_content_allowed(payload):
    gh = await check({"owner": ORG, "repo": "write-repo", "payload": payload}, "with_payload")
    assert gh.requests == []


@pytest.mark.parametrize(
    "payload",
    [
        {"owner": ORG, "repo": "other-repo"},
        {"Owner": ORG, "repoName": "other-repo"},
        {"org": ORG, "repository_name": "other-repo"},
        {"repo": f"{ORG}/other-repo"},
        {"repoName": f"{ORG}/other-repo"},
        {"full_name": f"{ORG}/other-repo"},
        {"nameWithOwner": f"{ORG}/other-repo"},
        {"a": [{"b": {"owner": ORG, "repo": "other-repo"}}]},
        [{"repository": f"{ORG}/other-repo"}],
    ],
)
async def test_nested_pair_outside_pack_repositories_refused(payload):
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match=f"{ORG}/other-repo is not one of the pack's"):
        await check({"owner": ORG, "repo": "write-repo", "payload": payload}, "with_payload", gh=gh)
    assert gh.requests == []


@pytest.mark.parametrize(
    "payload",
    [
        {"owner": ORG, "repo": "write-repo"},
        {"Owner": "Test-Org", "repoName": "Read-Repo"},
        {"full_name": READ},
        {"a": [{"repository": WRITE}]},
        {"owner": ORG},  # an owner alone still only needs the allowlist
    ],
)
async def test_nested_pair_inside_pack_repositories_allowed(payload):
    gh = await check({"owner": ORG, "repo": "write-repo", "payload": payload}, "with_payload")
    assert gh.requests == []


async def test_nested_pair_does_not_count_as_the_call_repository_for_scoped_ids():
    # The nested pair is checked, but only top-level arguments say which repository
    # a repository-scoped ID belongs to: none here, so the ID cannot be resolved.
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="name 0 repositories"):
        await check({"issue_number": 3, "body": {"repository": WRITE}}, "update_by_id", gh=gh)
    assert gh.requests == []


async def test_repository_id_inside_content_resolved():
    gh = GitHub({"/repositories/5": repo("outside-org/thing")})
    with pytest.raises(SafetyRefusal, match="outside-org"):
        await check(
            {"owner": ORG, "repo": "write-repo", "payload": {"repo_id": 5}}, "with_payload", gh=gh
        )


# --- ID-only write tools: id-role arguments are resolved through REST ---------------


async def test_id_only_write_unresolvable_refused():
    gh = GitHub()  # GET /repositories/123 is a 404
    with pytest.raises(SafetyRefusal, match="update_by_id"):
        await check({"repository_id": 123}, "update_by_id", gh=gh)
    assert [r.url.path for r in gh.requests] == ["/repositories/123"]
    assert gh.methods == {"GET"}


async def test_id_only_write_resolved_to_allowlisted_owner_allowed():
    gh = GitHub({"/repositories/123": {"full_name": WRITE, "owner": {"login": ORG}}})
    await check({"repository_id": 123}, "update_by_id", gh=gh)


async def test_id_only_write_resolved_to_other_owner_refused():
    gh = GitHub({"/repositories/123": repo("other-owner/thing")})
    with pytest.raises(SafetyRefusal, match="other-owner"):
        await check({"repository_id": 123}, "update_by_id", gh=gh)


async def test_id_only_repo_id_declared_id_is_resolved_too():
    gh = GitHub({"/repositories/9": repo("other-owner/thing")})
    with pytest.raises(SafetyRefusal, match="other-owner"):
        await check({"repo_id": 9}, "update_by_id", gh=gh)


async def test_id_only_global_id_resolved():
    gh = GitHub({"/gists/abc": {"owner": {"login": "other-owner"}}})
    with pytest.raises(SafetyRefusal, match="other-owner"):
        await check({"gist_id": "abc"}, "update_by_id", gh=gh)
    gh = GitHub({"/gists/abc": {"owner": {"login": ORG}}})
    await check({"gist_id": "abc"}, "update_by_id", gh)


async def test_id_only_issue_number_without_repository_refused():
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="repository"):
        await check({"issue_number": 7}, "update_by_id", gh=gh)
    assert gh.requests == []


async def test_id_only_issue_number_resolved_within_repository():
    issue = {"repository_url": f"https://api.github.com/repos/{WRITE}"}
    gh = GitHub({f"/repos/{WRITE}/issues/7": issue})
    await check({"owner": ORG, "repo": "write-repo", "issue_number": 7}, "update_by_id", gh=gh)
    assert [r.url.path for r in gh.requests] == [f"/repos/{WRITE}/issues/7"]


async def test_id_only_issue_that_moved_refused():
    # A transferred issue answers with a redirect body, not an issue: no owner to confirm.
    moved_to = "https://api.github.com/repositories/9/issues/7"
    moved = (301, {"message": "Moved Permanently", "url": moved_to})
    gh = GitHub({f"/repos/{WRITE}/issues/7": moved})
    with pytest.raises(SafetyRefusal):
        await check({"owner": ORG, "repo": "write-repo", "issue_number": 7}, "update_by_id", gh=gh)


async def test_id_only_unknown_id_kind_refused():
    with pytest.raises(SafetyRefusal, match="widget_id"):
        await check({"owner": ORG, "repo": "write-repo", "widget_id": 5}, "update_by_id")


async def test_id_only_without_any_id_refused():
    with pytest.raises(SafetyRefusal, match="no ID argument"):
        await check({"owner": ORG, "repo": "write-repo", "body": "x"}, "update_by_id")


async def test_id_only_id_declared_otherwise_refused():
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="pull_number"):
        await check(
            {"owner": ORG, "repo": "write-repo", "issue_number": 7, "pull_number": 3},
            "update_by_id",
            gh=gh,
        )
    assert gh.requests == []


# --- preflight: owners must be ASCII names, compared with .lower() ------------------


async def test_preflight_refuses_non_ascii_owner_that_casefolds_to_the_allowlist():
    gh = GitHub({"/user/repos": [repo(READ), repo(WRITE), repo(f"{LONG_S_ORG}/x")]})
    with pytest.raises(SafetyRefusal, match="preflight 3"):
        await preflight(gh.rest, TOKEN, pack(), LOGIN)


async def test_preflight_refuses_non_ascii_org_that_casefolds_to_the_allowlist():
    gh = GitHub({"/user/orgs": [{"login": ORG}, {"login": LONG_S_ORG}]})
    with pytest.raises(SafetyRefusal, match="preflight 4"):
        await preflight(gh.rest, TOKEN, pack(), LOGIN)


async def test_preflight_refuses_non_ascii_owned_repo_owner():
    gh = GitHub({"/user/repos?affiliation=owner": [repo(f"{LONG_S_ORG}/x")]})
    with pytest.raises(SafetyRefusal, match="preflight 4"):
        await preflight(gh.rest, TOKEN, pack(), LOGIN)


async def test_preflight_refuses_non_ascii_login_that_casefolds_to_the_expected_one():
    gh = GitHub({"/user": {"login": "teſt-account"}})
    with pytest.raises(SafetyRefusal, match="preflight 2"):
        await preflight(gh.rest, TOKEN, pack(), LOGIN)


# --- no-target tools: only content and other arguments, by declaration -------------


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "x", "owner": ORG},
        {"query": "x", "owner": ORG, "repo": "write-repo"},
        {"query": "x", "full_name": WRITE},
        {"query": "x", "repository_id": 5},
        {"query": "x", "issue_number": 7},
    ],
)
async def test_no_target_tool_with_a_non_content_argument_refused(arguments):
    # Even an allowlisted owner or a pack repository is refused: the pack said none.
    gh = GitHub({"/repositories/5": {"full_name": WRITE, "owner": {"login": ORG}}})
    with pytest.raises(SafetyRefusal, match="no_target_tools"):
        await check(arguments, "search_code", gh=gh)
    assert gh.requests == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "x", "owner": ORG},
        {"query": "x", "repo": "write-repo"},
        {"query": "x", "issue_number": 7},
    ],
)
async def test_no_target_tool_argument_named_like_a_target_refused_whatever_its_role(arguments):
    gh = GitHub()
    with pytest.raises(SafetyRefusal, match="no_target_tools"):
        await check(arguments, "search_other", gh=gh)
    assert gh.requests == []


async def test_no_target_tool_ordinary_search_arguments_allowed():
    arguments = {
        "query": "x", "q": "y", "sort": "created", "order": "desc", "page": 1, "perPage": 5,
        "type": "issue", "minimal_output": True,
    }
    gh = await check(arguments, "search_other")
    assert gh.requests == []


async def test_no_target_tool_with_content_and_other_arguments_allowed():
    gh = await check({"query": "is:open label:bug", "payload": {"text": "hi"}}, "search_code")
    assert gh.requests == []
    gh = await check({}, "search_code")
    assert gh.requests == []


async def test_no_target_tool_content_is_still_walked():
    with pytest.raises(SafetyRefusal, match="outside-org"):
        await check({"payload": {"owner": "outside-org"}}, "search_code")
