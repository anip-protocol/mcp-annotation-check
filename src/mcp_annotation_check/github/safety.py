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

Owners and logins are compared case-insensitively, as GitHub treats them, with
`.lower()` and only after checking that they are ASCII names (letters, digits, `_`,
`.`, `-`): `casefold()` or `lower()` on other text maps look-alikes such as U+017F
(`ſ`, which casefolds to `s`) or U+212A (the Kelvin sign, which lowers to `k`) onto
allowlisted names. An owner, login or allowlist entry that is not an ASCII name never
matches anything.

Per-call checks (`make_before_call`). Each pack entry declares the role of every
argument (spec Amendment 1; see pack.py); `pack.validate_pack` has already checked
those declarations against tools/list before the first call. Per call:
  - The tool must have an enabled pack entry, and the arguments must be a mapping.
  - The content rule (`pack.check_content`) is re-applied to the rendered arguments,
    keys and values, at every depth.
  - Every top-level argument must have a declared role; one without is refused. Keys
    are compared exactly, so a look-alike (`rеpo` with a Cyrillic `е`, `Owner`,
    `owner `) is simply undeclared. Each value is then checked by its role:
      * `owner`: an ASCII name on the allowlist;
      * `repository`: a bare ASCII name (not `.` or `..`), paired with the call's one
        `owner` argument (none or several is refused); the pair must be one of the
        pack's repositories;
      * `full_name`: "owner/name" with ASCII parts, naming one of the pack's
        repositories (so its owner is allowlisted too);
      * `repository_id`: a plain ID, resolved through `GET /repositories/{id}` for
        every tool; the owner found must be allowlisted;
      * `id`: a plain number or token of letters, digits, `_` and `-`;
      * `content`: anything the content rule accepts. Inside a mapping or list, the
        key walk below still applies, as defence in depth;
      * `other`: a scalar (string, number, boolean or null); a mapping or list is
        refused, since only content may nest.
  - The key walk inside `content` values. Keys are matched on their words joined in
    lower case (`Owner`, `owner_login`, `ownerLogin` are the same key; the tables are
    in argnames.py):
      * owner keys: `owner`, `org`, `organization`, `user`, `username` and their
        `…_login`/`…_name` forms, `repo_owner`/`repository_owner`, and `login`,
        `namespace` and `account`;
      * repository keys: `repo`, `repository`, `repo_name`, `repository_name`, as
        "owner/name" or as a bare name paired with the one owner given at the same
        level; full-name keys (`full_name`, `repository_full_name`, `name_with_owner`)
        must be "owner/name";
      * `repo_id`/`repository_id` are resolved through `GET /repositories/{id}`.
    Every owner named must be allowlisted. Refused as uninterpretable: any key with a
    non-ASCII character; any other key whose joined lower-case form contains `owner`,
    `organi`, `org`, `repo`, `user`, `nwo`, `login`, `namespace` or `account`
    (`orgs`, `user_id`, `owner_type`, `newowner`, `targetrepo`, …), except the
    known-harmless `report`, `reports` and `reporter`; a non-string value; a bare
    name with no owner or several owners; and a malformed name.
  - Tools on the pack's `no_target_tools` list name no repository by declaration
    (`get_me`, a query-only search): every top-level argument must have the
    `content` or `other` role, and one with any other role is refused before any REST
    request, even if it names an allowlisted owner or a pack repository. Content
    values are still walked as above. `validate_pack` already checked the declared
    roles; this re-checks the rendered arguments.
  - Tools on the pack's `id_only_write_tools` list have their `id`-role arguments
    resolved to an owner through REST before the call:
      * global IDs resolve on their own: `repository_id`/`repo_id`
        (`/repositories/{id}`), `gist_id` (`/gists/{id}`), `thread_id`/
        `notification_id` (`/notifications/threads/{id}`); the owner found must be
        allowlisted;
      * repository-scoped IDs (`issue_number`, `pull_number`, `number`, `comment_id`)
        are only meaningful with a repository, so the arguments must name exactly one
        allowlisted repository (through `owner`/`repository` or `full_name` roles),
        and the object found must report that same repository (a transferred issue's
        redirect does not, and is refused);
      * an `id`-role argument with no resolver above is refused, as is an ID-only
        tool with no `id` or `repository_id` argument at all (`validate_pack` already
        refuses an ID-only entry with no such role, so this catches an entry whose ID
        argument is declared but not passed), and an argument whose name looks like an
        ID (`id`, `…id`, `…number`) declared with any other role.
    A failed lookup (any HTTP error) refuses the call.
  - Search queries are never rewritten or parsed: changing them would change what is
    being tested, and a search reads, it cannot write.
"""

import re
from collections.abc import Awaitable, Callable
from typing import Any

from mcp_annotation_check.argnames import (
    FULL_NAME_KEYS,
    HARMLESS_KEYS,
    OWNER_KEYS,
    OWNER_STEMS,
    OWNER_WORDS,
    REPO_ID_KEYS,
    REPO_KEYS,
    looks_like_id,
    may_name_owner_or_repository,
    norm,
    words,
)
from mcp_annotation_check.github.rest import GitHubRest
from mcp_annotation_check.pack import ID_ROLES, NO_TARGET_ROLES, Pack, PackError, check_content
from mcp_annotation_check.redact import redact

CLASSIC_PREFIXES = ("ghp_", "gho_", "ghu_", "ghs_")
FINE_GRAINED_PREFIX = "github_pat_"

_NAME = re.compile(r"[A-Za-z0-9_.-]+")
_ID_VALUE = re.compile(r"[A-Za-z0-9_-]+")
_API_REPO = re.compile(r"/repos/([^/]+)/([^/?#]+)")

_REPOSITORY_BY_ID = ("/repositories/{id}",)
_GLOBAL_IDS = {
    "repositoryid": _REPOSITORY_BY_ID,
    "repoid": _REPOSITORY_BY_ID,
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
_SCALAR = (str, int, float, bool, type(None))


class SafetyRefusal(Exception):
    pass


def _ascii_name(value: Any) -> bool:
    return isinstance(value, str) and _NAME.fullmatch(value) is not None


def _key(value: Any) -> str | None:
    """The comparison form of an owner or login: lower case, or None if it is not
    an ASCII name (and so can never match)."""
    return value.lower() if _ascii_name(value) else None


def _allowed(pack: Pack) -> set[str]:
    return {a.lower() for a in pack.allowlist if _ascii_name(a)}


def _on_allowlist(owner: Any, allowed: set[str]) -> bool:
    key = _key(owner)
    return key is not None and key in allowed


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
    if _key(login) is None or _key(login) != _key(expected_login):
        raise SafetyRefusal(
            f"preflight 2: the token belongs to {login!r}, "
            f"not the dedicated test account {expected_login!r}"
        )

    # 3. Every repository the token can access.
    repos = _repo_entries(await _get(rest, "/user/repos", "preflight 3", token), "preflight 3")
    outside = sorted(name for name, owner in repos if not _on_allowlist(owner, allowed))
    if outside:
        raise SafetyRefusal(
            f"preflight 3: repositories outside the allowlist are reachable: {', '.join(outside)}"
        )
    if not pack.repositories:
        raise SafetyRefusal("preflight 3: the pack names no repositories")
    seen = {name.lower() for name, _ in repos if name.isascii()}
    missing = sorted(
        r for r in pack.repositories.values() if not r.isascii() or r.lower() not in seen
    )
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
    extra = [o for o in org_logins if not _on_allowlist(o, allowed)]
    if extra:
        raise SafetyRefusal(
            f"preflight 4: the account belongs to organizations outside the allowlist: "
            f"{', '.join(extra)}"
        )
    owned = _repo_entries(
        await _get(rest, "/user/repos", "preflight 4", token, affiliation="owner"), "preflight 4"
    )
    owned_outside = sorted(name for name, owner in owned if not _on_allowlist(owner, allowed))
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
    if not sep or not _ascii_name(owner) or not _ascii_name(name) or name in (".", ".."):
        raise SafetyRefusal(f"{tool}: cannot resolve {key}={value!r} to owner/name")
    return owner, name


def _plain_id(key: str, raw: Any, tool: str) -> str:
    plain = isinstance(raw, (int, str)) and not isinstance(raw, bool)
    if not plain or not _ID_VALUE.fullmatch(str(raw)):
        raise SafetyRefusal(f"{tool}: {key}={raw!r} is not a plain ID")
    return str(raw)


class _Named:
    """What the arguments name: owners, (owner, name) pairs from top-level roles,
    top-level `repository` names still to pair with the `owner` role, and repository
    IDs (top-level or inside content) still to be resolved through REST."""

    def __init__(self) -> None:
        self.owners: list[str] = []
        self.owner_args: list[str] = []
        self.bare_repos: list[tuple[str, str]] = []
        self.top_pairs: list[tuple[str, str]] = []
        self.repo_ids: list[tuple[str, str]] = []


def _level(d: dict, tool: str, named: _Named) -> None:
    """Classify the keys of one mapping inside a content value; refuse any it cannot
    interpret."""
    owners: list[str] = []
    repos: list[tuple[str, str, bool]] = []  # (key, value, bare name allowed)
    for key, value in d.items():
        if not isinstance(key, str):
            continue
        if not key.isascii():
            raise SafetyRefusal(f"{tool}: argument {key!r} has a non-ASCII name; refusing")
        parts = words(key)
        kind = "".join(parts)
        if kind in OWNER_KEYS:
            if not _ascii_name(value):
                raise SafetyRefusal(f"{tool}: {key}={value!r} is not an owner name")
            owners.append(value)
        elif kind in REPO_KEYS or kind in FULL_NAME_KEYS:
            if not isinstance(value, str) or not value:
                raise SafetyRefusal(f"{tool}: {key}={value!r} is not a repository name")
            repos.append((key, value, kind in REPO_KEYS))
        elif kind in REPO_ID_KEYS:
            named.repo_ids.append((key, _plain_id(key, value, tool)))
        elif kind in HARMLESS_KEYS:
            continue
        elif OWNER_WORDS.intersection(parts) or any(stem in kind for stem in OWNER_STEMS):
            raise SafetyRefusal(
                f"{tool}: cannot interpret argument {key!r}, which may name an owner or "
                "repository; refusing"
            )
    distinct = {o.lower(): o for o in owners}
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


def _walk(value: Any, tool: str, named: _Named) -> None:
    """The key walk, for the inside of a content value only."""
    if isinstance(value, dict):
        _level(value, tool, named)
        for child in value.values():
            _walk(child, tool, named)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _walk(child, tool, named)


def _by_role(tool: str, arguments: dict, roles: dict[str, str], named: _Named) -> None:
    """Check each top-level argument by its declared role; refuse an undeclared one.
    Owners and pairs are collected in `named`; the caller checks them."""
    for key, value in arguments.items():
        role = roles.get(key) if isinstance(key, str) else None
        if role is None:
            raise SafetyRefusal(f"{tool}: argument {key!r} has no declared role; refusing")
        if role == "owner":
            if not _ascii_name(value):
                raise SafetyRefusal(f"{tool}: owner {key}={value!r} is not an owner name")
            named.owner_args.append(value)
        elif role == "repository":
            if not _ascii_name(value) or value in (".", ".."):
                raise SafetyRefusal(f"{tool}: {key}={value!r} is not a bare repository name")
            named.bare_repos.append((key, value))
        elif role == "full_name":
            if not isinstance(value, str):
                raise SafetyRefusal(f"{tool}: {key}={value!r} is not \"owner/name\"")
            named.top_pairs.append(_split(value, key, tool))
        elif role == "repository_id":
            named.repo_ids.append((key, _plain_id(key, value, tool)))
        elif role == "id":
            _plain_id(key, value, tool)
        elif role == "content":
            _walk(value, tool, named)
        elif role == "other":
            if not isinstance(value, _SCALAR):
                raise SafetyRefusal(
                    f"{tool}: {key} has a nested value; only content arguments may nest"
                )
        else:
            raise SafetyRefusal(f"{tool}: argument {key!r} has unknown role {role!r}")


def _pair(tool: str, named: _Named) -> None:
    """Pair each `repository` argument with the call's one `owner` argument."""
    owners = named.owner_args
    for key, value in named.bare_repos:
        if len(owners) != 1:
            raise SafetyRefusal(
                f"{tool}: repository {key}={value!r} must pair with exactly one owner "
                f"argument, and the call has {len(owners)}"
            )
        named.top_pairs.append(_split(f"{owners[0]}/{value}", key, tool))


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


def _no_target_declarations(tool: str, arguments: dict, roles: dict[str, str]) -> None:
    """A no-target tool may pass only content and other arguments."""
    for key in arguments:
        if looks_like_id(key) or may_name_owner_or_repository(key):
            raise SafetyRefusal(
                f"{tool}: on no_target_tools, so argument {key!r} may not be named like an "
                "owner, repository or ID, whatever its role; refusing"
            )
        if roles[key] not in NO_TARGET_ROLES:
            raise SafetyRefusal(
                f"{tool}: on no_target_tools, so argument {key!r} must be content or other, "
                f"not {roles[key]!r}; refusing"
            )


def _id_only_declarations(tool: str, arguments: dict, roles: dict[str, str]) -> None:
    """Before any REST lookup: an ID-only tool's IDs must all be declared as IDs."""
    for key in arguments:
        role = roles[key]
        if role not in ID_ROLES and looks_like_id(key):
            raise SafetyRefusal(
                f"{tool}: {key!r} looks like an ID of an ID-only write tool but is declared "
                f"{role!r}; refusing"
            )
    if not any(roles[k] in ID_ROLES for k in arguments):
        raise SafetyRefusal(f"{tool}: an ID-only write tool with no ID argument to resolve")


async def _resolve_ids(
    rest: GitHubRest,
    tool: str,
    arguments: dict,
    roles: dict[str, str],
    pairs: list[tuple[str, str]],
    allowed: set[str],
) -> None:
    repos = {f"{o}/{n}".lower(): f"{o}/{n}" for o, n in pairs}
    for key, raw in arguments.items():
        if roles[key] != "id":
            continue  # repository_id roles are resolved for every tool by before_call
        value, kind = _plain_id(key, raw, tool), norm(key)
        if kind in _GLOBAL_IDS:
            owner, _ = await _resolve(rest, tool, key, _GLOBAL_IDS[kind], None, value)
            if not _on_allowlist(owner, allowed):
                raise SafetyRefusal(
                    f"{tool}: {key}={value} belongs to {owner!r}, which is not on the allowlist"
                )
        elif kind in _SCOPED_IDS:
            if len(repos) != 1:
                raise SafetyRefusal(
                    f"{tool}: {key} is only meaningful with a repository, and the arguments "
                    f"name {len(repos)} repositories"
                )
            (repo,) = repos.values()
            owner, name = await _resolve(rest, tool, key, _SCOPED_IDS[kind], repo, value)
            if (
                name is None
                or not _ascii_name(owner)
                or not _ascii_name(name)
                or f"{owner}/{name}".lower() != repo.lower()
            ):
                raise SafetyRefusal(
                    f"{tool}: {key}={value} could not be confirmed to belong to {repo}"
                )
        else:
            raise SafetyRefusal(f"{tool}: no way to resolve ID argument {key!r} to an owner")


def make_before_call(rest: GitHubRest, pack: Pack) -> Callable[[str, dict], Awaitable[None]]:
    allowed = _allowed(pack)
    id_only = set(pack.id_only_write_tools)
    no_target = set(pack.no_target_tools)
    repositories = {r.lower() for r in pack.repositories.values() if r.isascii()}

    async def before_call(tool: str, arguments: dict) -> None:
        if not isinstance(arguments, dict):
            raise SafetyRefusal(f"{tool}: arguments are not a mapping")
        entry = pack.entries.get(tool)
        if entry is None or entry.status != "enabled":
            raise SafetyRefusal(f"{tool}: no enabled pack entry declares its argument roles")
        roles = entry.argument_roles
        try:
            check_content(arguments, tool)
        except PackError as e:
            raise SafetyRefusal(str(e)) from None
        named = _Named()
        _by_role(tool, arguments, roles, named)
        if tool in no_target:
            _no_target_declarations(tool, arguments, roles)
        if tool in id_only:
            _id_only_declarations(tool, arguments, roles)
        for owner in [*named.owner_args, *(o for o, _ in named.top_pairs), *named.owners]:
            if not _on_allowlist(owner, allowed):
                raise SafetyRefusal(f"{tool}: owner {owner!r} is not on the allowlist")
        _pair(tool, named)
        for owner, name in named.top_pairs:
            if f"{owner}/{name}".lower() not in repositories:
                raise SafetyRefusal(
                    f"{tool}: {owner}/{name} is not one of the pack's repositories"
                )
        for key, value in named.repo_ids:
            owner, _ = await _resolve(rest, tool, key, _REPOSITORY_BY_ID, None, value)
            if not _on_allowlist(owner, allowed):
                raise SafetyRefusal(
                    f"{tool}: {key}={value} belongs to {owner!r}, which is not on the allowlist"
                )
        if tool in id_only:
            await _resolve_ids(rest, tool, arguments, roles, named.top_pairs, allowed)

    return before_call
