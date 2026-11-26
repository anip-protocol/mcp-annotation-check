"""StateReader over the GitHub REST API, read directly and never via the server under test."""

import base64
from typing import Any

from mcp_annotation_check.github.rest import GitHubError, GitHubRest
from mcp_annotation_check.pack import ToolEntry
from mcp_annotation_check.snapshot import FieldSpec, Recorded

KEEP_LABELS = {"c", "d", "mcp-annotation-check:done"}
DONE_LABEL = "mcp-annotation-check:done"
_LABEL_COLOR = "ededed"
_ISSUE_FIXTURES = {"issue_with_labels", "plain_issue", "issue_with_comment", "issue_with_assignee"}
_FIXTURES = _ISSUE_FIXTURES | {"open_pr", "none"}


class GitHubReader:
    def __init__(self, rest: GitHubRest, repositories: dict[str, str]) -> None:
        self.rest = rest
        self.repositories = repositories
        # Everything a fixture created, per tool, recorded as it is created so that
        # cleanup can undo a fixture whose setup failed part-way (fixture == {}).
        self._created: dict[str, dict[str, Any]] = {}

    # --- fixtures ---------------------------------------------------------

    async def create_fixture(self, entry: ToolEntry, run_id: str) -> dict[str, Any]:
        name = entry.fixture or "none"
        if name not in _FIXTURES:
            raise ValueError(f"unknown GitHub fixture {name!r}")
        repo = self.repositories[entry.repository]
        state = self._created[entry.tool] = {
            "repository": repo,
            "issue_number": None,
            "pr_number": None,
            "branch": None,
            "labels": [],
        }
        title = f"mac-{run_id}-{entry.tool}"
        fixture: dict[str, Any] = {"repository": repo}
        if name == "none":
            return fixture
        if name == "open_pr":
            default = (await self.rest.get(f"/repos/{repo}"))["default_branch"]
            ref = await self.rest.get(f"/repos/{repo}/git/ref/heads/{default}")
            await self.rest.post(
                f"/repos/{repo}/git/refs", {"ref": f"refs/heads/{title}", "sha": ref["object"]["sha"]}
            )
            state["branch"] = title
            await self.rest.put(
                f"/repos/{repo}/contents/fixtures/{title}.txt",
                {
                    "message": f"fixture {title}",
                    "content": base64.b64encode(b"fixture\n").decode(),
                    "branch": title,
                },
            )
            pr = await self.rest.post(
                f"/repos/{repo}/pulls",
                {"title": title, "head": title, "base": default, "body": "fixture"},
            )
            state["pr_number"] = pr["number"]
            return {**fixture, "pr_number": pr["number"], "branch": title}
        body: dict[str, Any] = {"title": title, "body": "fixture"}
        if name == "issue_with_labels":
            for label in ("c", "d"):
                await self._ensure_label(repo, label, state)
            body["labels"] = ["c", "d"]
        if name == "issue_with_assignee":
            # The token's own account: the only user guaranteed to be assignable in
            # the test organization.
            login = (await self.rest.get("/user"))["login"]
            body["assignees"] = [login]
            fixture["assignee"] = login
        issue = await self.rest.post(f"/repos/{repo}/issues", body)
        state["issue_number"] = issue["number"]
        fixture["issue_number"] = issue["number"]
        if name == "issue_with_assignee":
            # GitHub answers 201 and silently drops an assignee it can't assign. An
            # empty start would make a replacing tool look non-destructive.
            assigned = [a.get("login") for a in issue.get("assignees") or []]
            if fixture["assignee"] not in assigned:
                raise RuntimeError(
                    f"fixture setup: {fixture['assignee']} was not assigned to issue "
                    f"#{issue['number']}; GitHub dropped the assignee"
                )
        if name == "issue_with_comment":
            comment = await self.rest.post(
                f"/repos/{repo}/issues/{issue['number']}/comments", {"body": "fixture comment"}
            )
            fixture["comment_id"] = comment["id"]
        return fixture

    async def _ensure_label(self, repo: str, label: str, state: dict[str, Any]) -> None:
        try:
            await self.rest.get(f"/repos/{repo}/labels/{label}")
        except GitHubError as e:
            if e.status != 404:
                raise
            await self.rest.post(
                f"/repos/{repo}/labels", {"name": label, "color": _LABEL_COLOR}
            )
            state["labels"].append(label)

    async def cleanup(self, entry: ToolEntry, fixture: dict[str, Any]) -> None:
        state = self._created.pop(entry.tool, None)
        if state is None:
            return
        repo = state["repository"]
        number = state["issue_number"] or state["pr_number"]
        errors: list[Exception] = []

        async def attempt(coro: Any) -> None:
            try:
                await coro
            except Exception as e:  # keep going; every step is best effort
                errors.append(e)

        if state["issue_number"] is not None:
            await attempt(
                self.rest.patch(f"/repos/{repo}/issues/{state['issue_number']}", {"state": "closed"})
            )
        if state["pr_number"] is not None:
            await attempt(
                self.rest.patch(f"/repos/{repo}/pulls/{state['pr_number']}", {"state": "closed"})
            )
        if number is not None:
            await attempt(
                self.rest.post(f"/repos/{repo}/issues/{number}/labels", {"labels": [DONE_LABEL]})
            )
        if state["branch"] is not None:
            await attempt(self.rest.delete(f"/repos/{repo}/git/refs/heads/{state['branch']}"))
        for label in state["labels"]:
            if label not in KEEP_LABELS:
                await attempt(self.rest.delete(f"/repos/{repo}/labels/{label}"))
        if errors:
            raise errors[0]

    # --- snapshots --------------------------------------------------------

    async def snapshot(self, fields: list[FieldSpec], fixture: dict[str, Any]) -> Recorded:
        # The runner always sets the entry's repository (ruling R20); never guess one.
        repo = fixture.get("repository")
        if not repo:
            raise ValueError("snapshot fixture names no 'repository'")
        snap: dict[str, Any] = {}
        stamps: dict[str, str] = {}
        cache: dict[str, Any] = {}

        async def issue() -> dict[str, Any]:
            if "issue" not in cache:
                n = fixture["issue_number"]
                cache["issue"] = await self.rest.get(f"/repos/{repo}/issues/{n}")
                stamps["issue"] = cache["issue"]["updated_at"]
            return cache["issue"]

        async def pr() -> dict[str, Any]:
            if "pr" not in cache:
                n = fixture["pr_number"]
                cache["pr"] = await self.rest.get(f"/repos/{repo}/pulls/{n}")
                stamps["pr"] = cache["pr"]["updated_at"]
            return cache["pr"]

        for spec in fields:
            snap[spec.path] = await self._read(spec.path, repo, fixture, issue, pr)
        return Recorded(snap, stamps)

    async def _read(self, path: str, repo: str, fixture: dict[str, Any], issue: Any, pr: Any) -> Any:
        match path:
            case "issue.labels":
                return frozenset(x["name"] for x in (await issue())["labels"])
            case "issue.assignees":
                return frozenset(x["login"] for x in (await issue())["assignees"])
            case "issue.title" | "issue.body" | "issue.state":
                return (await issue())[path.removeprefix("issue.")]
            case "issue.reactions":
                return (await issue())["reactions"]["total_count"]
            case "issue.reaction_set":
                await issue()  # records the issue timestamp
                reactions = await self.rest.get(
                    f"/repos/{repo}/issues/{fixture['issue_number']}/reactions"
                )
                return frozenset((r["user"]["login"], r["content"]) for r in reactions)
            case "issue.comments":
                await issue()  # records the issue timestamp
                comments = await self.rest.get(
                    f"/repos/{repo}/issues/{fixture['issue_number']}/comments"
                )
                return frozenset(
                    (c["id"], c["body"], c.get("reactions", {}).get("total_count", 0))
                    for c in comments
                )
            case "pr.state" | "pr.title" | "pr.body":
                return (await pr())[path.removeprefix("pr.")]
            case "pr.requested_reviewers":
                return frozenset(x["login"] for x in (await pr())["requested_reviewers"])
            case "repo.refs":
                refs: list[dict[str, Any]] = []
                for prefix in ("heads/", "tags/"):
                    try:
                        refs += await self.rest.get(f"/repos/{repo}/git/matching-refs/{prefix}")
                    except GitHubError as error:
                        # 409 is GitHub's "Git Repository is empty": no refs at all.
                        if error.status != 409:
                            raise
                        return frozenset()
                return frozenset((r["ref"], r["object"]["sha"]) for r in refs)
            case "repo.labels":
                labels = await self.rest.get(f"/repos/{repo}/labels")
                return frozenset((x["name"], x["color"], x["description"]) for x in labels)
            case "repo.issues":
                issues = await self.rest.get(f"/repos/{repo}/issues", {"state": "all"})
                return frozenset(
                    (
                        i["number"],
                        i["title"],
                        i["state"],
                        tuple(sorted(label["name"] for label in i["labels"])),
                        i.get("reactions", {}).get("total_count", 0),
                    )
                    for i in issues
                )
        raise ValueError(f"unsupported GitHub field {path!r}")
