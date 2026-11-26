"""A small GitHub REST client. Errors carry the status and path, never headers.

Write guard: a client built with `write_repositories` refuses, before sending, every
request other than GET whose path is not strictly inside one of those repositories
(`/repos/<owner>/<name>/...`, compared case-insensitively in ASCII). The path must
be a plain relative API path: no scheme or host, no query or fragment, no `%`
escapes or backslashes, and no empty, `.` or `..` segments, so it cannot be
normalised into another repository. The refusal is `RestRefused`, which is not a
`GitHubError` (nothing was sent, so there is no status). `run` builds its client with
the pack's repositories; `shakedown` with none, so it refuses every write. GET is
never restricted: preflight and the reader only read.
"""

import re
from collections.abc import Collection
from typing import Any

import httpx

_NAME = re.compile(r"[A-Za-z0-9_.-]+")


class GitHubError(Exception):
    def __init__(self, status: int, path: str, note: str = "") -> None:
        self.status = status
        self.path = path
        text = f"GitHub API returned {status} for {path}"
        super().__init__(f"{text} ({note})" if note else text)


class RestRefused(Exception):
    """A write the client refused to send; carries the method and path only."""

    def __init__(self, method: str, path: str) -> None:
        self.method = method
        self.path = path
        super().__init__(f"refusing {method} {path}: outside the pack's repositories")


def _repository_key(full_name: str) -> str | None:
    owner, sep, name = full_name.partition("/")
    if not sep or not _NAME.fullmatch(owner) or not _NAME.fullmatch(name):
        return None
    if name in (".", ".."):
        return None
    return f"{owner}/{name}".lower()


def _write_target(path: str) -> str | None:
    """The lower-case "owner/name" a write path is strictly inside, or None."""
    if any(c in path for c in "?#%\\") or not path.isascii():
        return None
    parts = path.split("/")
    # "", "repos", owner, name, then at least one more segment.
    if len(parts) < 5 or parts[0] != "" or parts[1] != "repos":
        return None
    if any(p in ("", ".", "..") for p in parts[1:]):
        return None
    return _repository_key(f"{parts[2]}/{parts[3]}")


class GitHubRest:
    def __init__(
        self,
        token: str,
        base_url: str = "https://api.github.com",
        transport: httpx.AsyncBaseTransport | None = None,
        write_repositories: Collection[str] | None = None,
    ) -> None:
        # None: writes are unrestricted (tests of the reader); a collection, even an
        # empty one, limits every non-GET request to those repositories.
        self._writable: frozenset[str] | None = None
        if write_repositories is not None:
            keys = {_repository_key(r) for r in write_repositories if isinstance(r, str)}
            self._writable = frozenset(k for k in keys if k is not None)
        self._http = httpx.AsyncClient(
            base_url=base_url,
            transport=transport,
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def _check_write(self, method: str, url: str) -> None:
        if method.upper() == "GET" or self._writable is None:
            return
        target = _write_target(url)
        if target is None or target not in self._writable:
            raise RestRefused(method, url)

    async def _send(
        self, method: str, url: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        self._check_write(method, url)
        response = await self._http.request(method, url, **kwargs)
        if response.status_code >= 400:
            note = ""
            if response.headers.get("x-ratelimit-remaining") == "0":
                note = "rate limit exhausted"
            raise GitHubError(response.status_code, path, note)
        return response

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET path; a list response is followed through its Link: rel=next pages."""
        response = await self._send("GET", path, path, params={"per_page": 100, **(params or {})})
        data = response.json()
        if not isinstance(data, list):
            return data
        items = list(data)
        while next_page := response.links.get("next"):
            response = await self._send("GET", next_page["url"], path)
            items.extend(response.json())
        return items

    async def post(self, path: str, json: Any) -> Any:
        return (await self._send("POST", path, path, json=json)).json()

    async def put(self, path: str, json: Any) -> Any:
        return (await self._send("PUT", path, path, json=json)).json()

    async def patch(self, path: str, json: Any) -> Any:
        return (await self._send("PATCH", path, path, json=json)).json()

    async def delete(self, path: str) -> None:
        await self._send("DELETE", path, path)
