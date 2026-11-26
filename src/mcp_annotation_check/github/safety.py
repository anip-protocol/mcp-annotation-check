"""Safety checks: a preflight before any tool runs, and a check before every call.

The token is the real boundary (see the spec's Safety section). These checks make
sure the harness is pointed at that boundary and refuse loudly when it is not. Any
failure raises `SafetyRefusal`; nothing here ever modifies a request or argument.

Preflight (`preflight`), in order, using only GET requests:
  1. The token must be fine-grained: `ghp_`, `gho_`, `ghu_` and `ghs_` tokens are
     refused, and anything else must start with `github_pat_`.
  2. `GET /user` must name the expected test account.
  3. `GET /user/repos` (every page): every owner must be on the pack's allowlist,
     and every pack repository must be listed.
  4. The compensating check, always run: `GET /user/orgs` must list only allowlisted
     organizations, and `GET /user/repos?affiliation=owner` must be empty or
     allowlisted. This guarantees the account itself reaches nothing outside the
     allowlist *only if these two endpoints report the account's memberships and
     repositories*. If GitHub filters them by the fine-grained token instead, step 4
     passes vacuously and proves nothing beyond step 3. Which case holds is an
     observation recorded in docs/verification.md, not something this code can tell.

Owners and logins are compared case-insensitively, as GitHub treats them.

Per-call checks (`make_before_call`):
  - The content rule (`pack.check_content`) is re-applied to the rendered arguments.
  - Owner and repository arguments, at any depth. Keys are matched on their words
    joined in lower case (`Owner`, `owner_login`, `ownerLogin` are the same key):
      * owner keys: `owner`, `org`, `organization`, `user`, `username` and their
        `…_login`/`…_name` forms, `repo_owner`/`repository_owner`, and `login`,
        `namespace` and `account`;
      * repository keys: `repo`, `repository`, `repo_name`, `repository_name`, as
        "owner/name" or as a bare name paired with the one owner given at the same
        level; full-name keys (`full_name`, `repository_full_name`, `name_with_owner`)
        must be "owner/name";
      * `repo_id`/`repository_id` are resolved through `GET /repositories/{id}` for
        every tool, not only ID-only ones.
    Every owner named must be allowlisted. Refused as uninterpretable: any key with a
    non-ASCII character; any other key whose joined lower-case form contains `owner`,
    `organi`, `org`, `repo`, `user`, `nwo`, `login`, `namespace` or `account`
    (`orgs`, `user_id`, `owner_type`, `newowner`, `targetrepo`, …), except the
    known-harmless `report`, `reports` and `reporter`; a non-string value; a bare
    name with no owner or several owners; and a malformed name.
  - Tools on the pack's `id_only_write_tools` list have their top-level ID arguments
    resolved to an owner through REST before the call:
      * global IDs resolve on their own: `repository_id`/`repo_id`
        (`/repositories/{id}`), `gist_id` (`/gists/{id}`), `thread_id`/
        `notification_id` (`/notifications/threads/{id}`); the owner found must be
        allowlisted;
      * repository-scoped IDs (`issue_number`, `pull_number`, `number`, `comment_id`)
        are only meaningful with a repository, so the arguments must name exactly one
        allowlisted repository, and the object found must report that same repository
        (a transferred issue's redirect does not, and is refused);
      * an argument that looks like an ID (`id`, `…id`, `…number`) with no resolver
        above is refused, as is an ID-only tool with no ID argument at all, or an ID
        value that is not a plain number or token of letters, digits, `_` and `-`.
    A failed lookup (any HTTP error) refuses the call.
  - Search queries are never rewritten or parsed: changing them would change what is
    being tested, and a search reads, it cannot write.
"""

import re
from collections.abc import Awaitable, Callable
from typing import Any

from mcp_annotation_check.github.rest import GitHubRest
from mcp_annotation_check.pack import Pack, PackError, check_content
from mcp_annotation_check.redact import redact

CLASSIC_PREFIXES = ("ghp_", "gho_", "ghu_", "ghs_")
FINE_GRAINED_PREFIX = "github_pat_"

_NAME = re.compile(r"[A-Za-z0-9_.-]+")
_ID_VALUE = re.compile(r"[A-Za-z0-9_-]+")
_API_REPO = re.compile(r"/repos/([^/]+)/([^/?#]+)")
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")

# Argument keys are matched on their words joined in lower case, so `Owner`,
# `owner_login`, `ownerLogin` and `OWNER-LOGIN` are all "ownerlogin".
_OWNER_KEYS = {
    "owner", "ownerlogin", "ownername", "repoowner", "repositoryowner",
    "org", "orglogin", "orgname", "organization", "organizationlogin", "organizationname",
    "organisation", "user", "userlogin", "username",
    "login", "namespace", "account",
}
_REPO_KEYS = {"repo", "reponame", "repository", "repositoryname"}  # "owner/name" or bare
_FULL_NAME_KEYS = {"fullname", "repofullname", "repositoryfullname", "namewithowner", "nwo"}
_REPO_ID_KEYS = {"repoid", "repositoryid"}
# Any other key whose joined lower-case form contains one of these stems (so that
# `newowner` or `targetrepo`, written with no separator, are caught too) cannot be
# interpreted, and is refused, unless it is one of the known-harmless keys below.
_OWNER_STEMS = ("owner", "organi", "org", "repo", "user", "nwo", "login", "namespace", "account")
# Keys that contain a stem but name no owner or repository. Keep this minimal.
_HARMLESS_KEYS = {"report", "reports", "reporter"}
# Any other key containing one of these words is refused too (kept alongside the stems).
_OWNER_WORDS = {
    "owner", "owners", "org", "orgs", "organization", "organizations", "organisation",
    "organisations", "user", "users", "username", "usernames",
    "repo", "repos", "repository", "repositories", "nwo",
}

_REPOSITORY_BY_ID = ("/repositories/{id}",)
_GLOBAL_IDS = {
    "gistid": ("/gists/{id}",),
    "threadid": ("/notifications/threads/{id}",),
    "notificationid": ("/notifications/threads/{id}",),
}
_SCOPED_IDS = {
    "issuenumber": ("/repos/{repo}/issues/{id}",),
    "number": ("/repos/{repo}/issues/{id}",),
    "pullnumber": ("/repos/{repo}/pulls/{id}",),
    "commentid": ("/repos/{repo}/issues/comments/{id}", "/repos/{repo}/pulls/comments/{id}"),
}


class SafetyRefusal(Exception):
    pass


def _allowed(pack: Pack) -> set[str]:
    return {a.casefold() for a in pack.allowlist if isinstance(a, str)}


async def _get(rest: GitHubRest, path: str, what: str, token: str = "", **params: Any) -> Any:
    try:
        return await rest.get(path, params or None)
    except Exception as e:
        # `from None`: the original exception is never chained into a printed traceback.
        text = redact(f"{what}: GET {path} failed: {type(e).__name__}: {e}", [token])
        raise SafetyRefusal(text) from None


def _repo_entries(data: Any, what: str) -> list[tuple[str, str]]:
    """(full_name, owner login) for each repository in a REST listing."""
    if not isinstance(data, list):
        raise SafetyRefusal(f"{what}: expected a list of repositories")
    out = []
    for item in data:
        try:
            full_name, owner = item["full_name"], item["owner"]["login"]
        except (KeyError, TypeError):
            raise SafetyRefusal(f"{what}: a repository has no full_name or owner") from None
        if not (isinstance(full_name, str) and isinstance(owner, str)):
            raise SafetyRefusal(f"{what}: a repository has a malformed full_name or owner")
        out.append((full_name, owner))
    return out


async def preflight(rest: GitHubRest, token: str, pack: Pack, expected_login: str) -> dict:
    """Run the preflight checks in order; return facts for the report header."""
    # 1. The token kind.
    if token.startswith(CLASSIC_PREFIXES):
        raise SafetyRefusal("preflight 1: classic or app token; use a fine-grained token")
    if not token.startswith(FINE_GRAINED_PREFIX):
        raise SafetyRefusal(
            "preflight 1: the token does not start with github_pat_; use a fine-grained token"
        )
    allowed = _allowed(pack)

    # 2. The account.
    user = await _get(rest, "/user", "preflight 2", token)
    login = user.get("login") if isinstance(user, dict) else None
    if not isinstance(login, str) or login.casefold() != expected_login.casefold():
        raise SafetyRefusal(
            f"preflight 2: the token belongs to {login!r}, "
            f"not the dedicated test account {expected_login!r}"
        )

    # 3. Every repository the token can access.
    repos = _repo_entries(await _get(rest, "/user/repos", "preflight 3", token), "preflight 3")
    outside = sorted(name for name, owner in repos if owner.casefold() not in allowed)
    if outside:
        raise SafetyRefusal(
            f"preflight 3: repositories outside the allowlist are reachable: {', '.join(outside)}"
        )
    if not pack.repositories:
        raise SafetyRefusal("preflight 3: the pack names no repositories")
    seen = {name.casefold() for name, _ in repos}
    missing = sorted(r for r in pack.repositories.values() if r.casefold() not in seen)
    if missing:
        raise SafetyRefusal(
            f"preflight 3: pack repositories the token cannot reach: {', '.join(missing)}"
        )

    # 4. The compensating check: the account itself reaches nothing else.
    orgs = await _get(rest, "/user/orgs", "preflight 4", token)
    if not isinstance(orgs, list) or not all(
        isinstance(o, dict) and isinstance(o.get("login"), str) for o in orgs
    ):
        raise SafetyRefusal("preflight 4: expected a list of organizations")
    org_logins = sorted(o["login"] for o in orgs)
    extra = [o for o in org_logins if o.casefold() not in allowed]
    if extra:
        raise SafetyRefusal(
            f"preflight 4: the account belongs to organizations outside the allowlist: "
            f"{', '.join(extra)}"
        )
    owned = _repo_entries(
        await _get(rest, "/user/repos", "preflight 4", token, affiliation="owner"), "preflight 4"
    )
    owned_outside = sorted(name for name, owner in owned if owner.casefold() not in allowed)
    if owned_outside:
        raise SafetyRefusal(
            f"preflight 4: the account owns repositories outside the allowlist: "
            f"{', '.join(owned_outside)}"
        )

    return {
        "login": login,
        "repositories": sorted(name for name, _ in repos),
        "organizations": org_logins,
    }


# --- per-call checks -----------------------------------------------------------


def _split(value: str, key: str, tool: str) -> tuple[str, str]:
    owner, sep, name = value.partition("/")
    if not sep or not owner or not _NAME.fullmatch(name) or name in (".", ".."):
        raise SafetyRefusal(f"{tool}: cannot resolve {key}={value!r} to owner/name")
    return owner, name


def _words(key: str) -> list[str]:
    """`repoName`, `repo_name`, `Repo-Name` -> ["repo", "name"]."""
    return [w.lower() for w in _WORD.findall(key)]


def _plain_id(key: str, raw: Any, tool: str) -> str:
    plain = isinstance(raw, (int, str)) and not isinstance(raw, bool)
    if not plain or not _ID_VALUE.fullmatch(str(raw)):
        raise SafetyRefusal(f"{tool}: {key}={raw!r} is not a plain ID")
    return str(raw)


class _Named:
    """What the arguments name: owners, (owner, name) pairs at the top level, and
    repository IDs (at any depth) still to be resolved through REST."""

    def __init__(self) -> None:
        self.owners: list[str] = []
        self.top_pairs: list[tuple[str, str]] = []
        self.repo_ids: list[tuple[str, str]] = []


def _level(d: dict, tool: str, named: _Named, top: bool) -> None:
    """Classify the keys of one mapping; refuse any it cannot interpret."""
    owners: list[str] = []
    repos: list[tuple[str, str, bool]] = []  # (key, value, bare name allowed)
    for key, value in d.items():
        if not isinstance(key, str):
            continue
        if not key.isascii():
            raise SafetyRefusal(f"{tool}: argument {key!r} has a non-ASCII name; refusing")
        words = _words(key)
        kind = "".join(words)
        if kind in _OWNER_KEYS:
            if not isinstance(value, str) or not value:
                raise SafetyRefusal(f"{tool}: {key}={value!r} is not an owner name")
            owners.append(value)
        elif kind in _REPO_KEYS or kind in _FULL_NAME_KEYS:
            if not isinstance(value, str) or not value:
                raise SafetyRefusal(f"{tool}: {key}={value!r} is not a repository name")
            repos.append((key, value, kind in _REPO_KEYS))
        elif kind in _REPO_ID_KEYS:
            named.repo_ids.append((key, _plain_id(key, value, tool)))
        elif kind in _HARMLESS_KEYS:
            continue
        elif _OWNER_WORDS.intersection(words) or any(stem in kind for stem in _OWNER_STEMS):
            raise SafetyRefusal(
                f"{tool}: cannot interpret argument {key!r}, which may name an owner or "
                "repository; refusing"
            )
    distinct = {o.casefold(): o for o in owners}
    named.owners.extend(owners)
    for key, value, bare_allowed in repos:
        if "/" in value:
            pair = _split(value, key, tool)
        elif not bare_allowed or not distinct:
            raise SafetyRefusal(
                f"{tool}: cannot resolve {key}={value!r} to owner/name (no owner given)"
            )
        elif len(distinct) > 1:
            raise SafetyRefusal(
                f"{tool}: {key}={value!r} is ambiguous: several owners are given "
                f"({', '.join(sorted(distinct.values()))})"
            )
        else:
            pair = _split(f"{next(iter(distinct.values()))}/{value}", key, tool)
        named.owners.append(pair[0])
        if top:
            named.top_pairs.append(pair)


def _walk(value: Any, tool: str, named: _Named, top: bool = True) -> None:
    if isinstance(value, dict):
        _level(value, tool, named, top)
        for child in value.values():
            _walk(child, tool, named, top=False)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _walk(child, tool, named, top=False)


def _norm(key: str) -> str:
    return key.lower().replace("_", "").replace("-", "")


def _looks_like_id(norm: str) -> bool:
    return norm.endswith(("id", "number"))


def _located(obj: Any) -> tuple[str, str | None] | None:
    """(owner, name or None) of the repository a REST object reports it belongs to."""
    if not isinstance(obj, dict):
        return None
    for key in ("repository_url", "url"):
        url = obj.get(key)
        if isinstance(url, str) and (m := _API_REPO.search(url)):
            return m.group(1), m.group(2)
    for parent in (obj, obj.get("repository")):
        if isinstance(parent, dict):
            owner = parent.get("owner")
            if isinstance(owner, dict) and isinstance(owner.get("login"), str):
                return owner["login"], None
    return None


async def _resolve(
    rest: GitHubRest, tool: str, key: str, paths: tuple[str, ...], repo: str | None, value: str
) -> tuple[str, str | None]:
    failures = []
    for template in paths:
        path = template.format(repo=repo, id=value)
        try:
            obj = await rest.get(path)
        except Exception as e:
            failures.append(f"{type(e).__name__}: {e}")
            continue
        located = _located(obj)
        if located is None:
            failures.append(f"GET {path} named no owner")
            continue
        return located
    raise SafetyRefusal(
        f"{tool}: could not resolve {key}={value!r} to an owner ({'; '.join(failures)})"
    )


async def _resolve_ids(
    rest: GitHubRest,
    tool: str,
    arguments: dict,
    pairs: list[tuple[str, str]],
    allowed: set[str],
) -> None:
    repos = {f"{o}/{n}".casefold(): f"{o}/{n}" for o, n in pairs}
    ids = [(k, v) for k, v in arguments.items() if isinstance(k, str) and _looks_like_id(_norm(k))]
    if not ids:
        raise SafetyRefusal(f"{tool}: an ID-only write tool with no ID argument to resolve")
    for key, raw in ids:
        value, norm = _plain_id(key, raw, tool), _norm(key)
        if norm in _REPO_ID_KEYS:
            continue  # resolved for every tool by before_call
        if norm in _GLOBAL_IDS:
            owner, _ = await _resolve(rest, tool, key, _GLOBAL_IDS[norm], None, value)
            if owner.casefold() not in allowed:
                raise SafetyRefusal(
                    f"{tool}: {key}={value} belongs to {owner!r}, which is not on the allowlist"
                )
        elif norm in _SCOPED_IDS:
            if len(repos) != 1:
                raise SafetyRefusal(
                    f"{tool}: {key} is only meaningful with a repository, and the arguments "
                    f"name {len(repos)} repositories"
                )
            (repo,) = repos.values()
            owner, name = await _resolve(rest, tool, key, _SCOPED_IDS[norm], repo, value)
            if name is None or f"{owner}/{name}".casefold() != repo.casefold():
                raise SafetyRefusal(
                    f"{tool}: {key}={value} could not be confirmed to belong to {repo}"
                )
        else:
            raise SafetyRefusal(f"{tool}: no way to resolve ID argument {key!r} to an owner")


def make_before_call(rest: GitHubRest, pack: Pack) -> Callable[[str, dict], Awaitable[None]]:
    allowed = _allowed(pack)
    id_only = set(pack.id_only_write_tools)

    async def before_call(tool: str, arguments: dict) -> None:
        if not isinstance(arguments, dict):
            raise SafetyRefusal(f"{tool}: arguments are not a mapping")
        try:
            check_content(arguments, tool)
        except PackError as e:
            raise SafetyRefusal(str(e)) from None
        named = _Named()
        _walk(arguments, tool, named)
        for owner in named.owners:
            if owner.casefold() not in allowed:
                raise SafetyRefusal(f"{tool}: owner {owner!r} is not on the allowlist")
        for key, value in named.repo_ids:
            owner, _ = await _resolve(rest, tool, key, _REPOSITORY_BY_ID, None, value)
            if owner.casefold() not in allowed:
                raise SafetyRefusal(
                    f"{tool}: {key}={value} belongs to {owner!r}, which is not on the allowlist"
                )
        if tool in id_only:
            await _resolve_ids(rest, tool, arguments, named.top_pairs, allowed)

    return before_call
