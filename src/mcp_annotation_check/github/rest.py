"""A small GitHub REST client. Errors carry the status and path, never headers."""

from typing import Any

import httpx


class GitHubError(Exception):
    def __init__(self, status: int, path: str, note: str = "") -> None:
        self.status = status
        self.path = path
        text = f"GitHub API returned {status} for {path}"
        super().__init__(f"{text} ({note})" if note else text)


class GitHubRest:
    def __init__(
        self,
        token: str,
        base_url: str = "https://api.github.com",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
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

    async def _send(
        self, method: str, url: str, path: str, **kwargs: Any
    ) -> httpx.Response:
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
