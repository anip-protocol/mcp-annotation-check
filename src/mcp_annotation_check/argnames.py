"""Argument names that may name an owner or repository.

Since spec Amendment 1, name matching decides nothing for a tool's top-level
arguments: each pack entry declares their roles. These tables serve two purposes
that remain:
  - the safety checks' key walk inside `content` values (defence in depth);
  - `pack.pack_warnings`, which flags a top-level property with an owner- or
    repository-like name that is declared `content`, `other` or `id`.

Keys are matched on their words joined in lower case, so `Owner`, `owner_login`,
`ownerLogin` and `OWNER-LOGIN` are all "ownerlogin".
"""

import re

_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")

OWNER_KEYS = {
    "owner", "ownerlogin", "ownername", "repoowner", "repositoryowner",
    "org", "orglogin", "orgname", "organization", "organizationlogin", "organizationname",
    "organisation", "user", "userlogin", "username",
    "login", "namespace", "account",
}
REPO_KEYS = {"repo", "reponame", "repository", "repositoryname"}  # "owner/name" or bare
FULL_NAME_KEYS = {"fullname", "repofullname", "repositoryfullname", "namewithowner", "nwo"}
REPO_ID_KEYS = {"repoid", "repositoryid"}
# Any other key whose joined lower-case form contains one of these stems (so that
# `newowner` or `targetrepo`, written with no separator, are caught too) cannot be
# interpreted, unless it is one of the known-harmless keys below.
OWNER_STEMS = ("owner", "organi", "org", "repo", "user", "nwo", "login", "namespace", "account")
# Keys that contain a stem but name no owner or repository. Keep this minimal.
HARMLESS_KEYS = {"report", "reports", "reporter"}
# Any other key containing one of these words is uninterpretable too.
OWNER_WORDS = {
    "owner", "owners", "org", "orgs", "organization", "organizations", "organisation",
    "organisations", "user", "users", "username", "usernames",
    "repo", "repos", "repository", "repositories", "nwo",
}


def words(key: str) -> list[str]:
    """`repoName`, `repo_name`, `Repo-Name` -> ["repo", "name"]."""
    return [w.lower() for w in _WORD.findall(key)]


def may_name_owner_or_repository(key: str) -> bool:
    """True for a non-ASCII key, a known owner/repository key, or one with a stem."""
    if not key.isascii():
        return True
    parts = words(key)
    kind = "".join(parts)
    if kind in HARMLESS_KEYS:
        return False
    if kind in OWNER_KEYS | REPO_KEYS | FULL_NAME_KEYS | REPO_ID_KEYS:
        return True
    return bool(OWNER_WORDS.intersection(parts)) or any(stem in kind for stem in OWNER_STEMS)


def norm(key: str) -> str:
    return key.lower().replace("_", "").replace("-", "")


def looks_like_id(key: str) -> bool:
    return norm(key).endswith(("id", "number"))
