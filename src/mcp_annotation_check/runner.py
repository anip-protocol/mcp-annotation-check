"""Serial runner: plan every listed tool, then judge enabled ones one at a time.

Per judged tool: fixture, arguments, before-snapshot, call, settled after-snapshot
(taken even when the call errored), rules, a second call for the idempotent check,
and cleanup in a `finally`. A failure at any step is an ERROR for that tool only.
"""

import dataclasses
import hashlib
import importlib.metadata
import json
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from mcp import Client
from mcp.types import Tool

from mcp_annotation_check import __version__
from mcp_annotation_check.claims import SCHEMA_TEXT, Check, Claims, applicable_checks, claims_of
from mcp_annotation_check.pack import Pack, ToolEntry, render_arguments, supplied_values
from mcp_annotation_check.reader import StateReader
from mcp_annotation_check.redact import redact
from mcp_annotation_check.report import RunHeader, ToolResult
from mcp_annotation_check.rules import (
    diff_fields,
    judge_idempotent,
    judge_non_destructive,
    judge_read_only,
)
from mcp_annotation_check.settle import SettleTimeout, settle
from mcp_annotation_check.snapshot import FieldSpec, Outcome, Recorded, Verdict

__all__ = ["CUSTOM_SETUPS", "CUSTOM_VERDICTS", "RunHeader", "ToolResult", "run"]

BeforeCall = Callable[[str, dict], Awaitable[None]]

# A custom setup replaces reader.create_fixture for the entries that name it.
CUSTOM_SETUPS: dict[str, Callable[[StateReader, ToolEntry, str], Awaitable[dict[str, Any]]]] = {}
# A custom verdict replaces the general rule for an entry's first applicable check.
# It receives the same snapshot pair that rule would, the entry and the rendered arguments.
CUSTOM_VERDICTS: dict[str, Callable[[Recorded, Recorded, ToolEntry, dict[str, Any]], Verdict]] = {}

_SEVERITY = {
    Outcome.SKIPPED: 0,
    Outcome.PASS: 1,
    Outcome.OBSERVATION: 2,
    Outcome.FINDING: 3,
    Outcome.ERROR: 4,
}


class _HarnessError(Exception):
    """A failure whose message is reported as is, without a step prefix."""


async def run(
    client: Client,
    reader: StateReader,
    pack: Pack,
    header_context: dict[str, Any],
    before_call: BeforeCall | None = None,
    *,
    settle_interval_s: float = 1.0,
    settle_timeout_s: float = 20.0,
    secrets: Sequence[str] = (),
) -> tuple[RunHeader, list[ToolResult]]:
    """Run every listed tool. Every error text is redacted against `secrets`."""
    secrets = (secrets,) if isinstance(secrets, str) else tuple(secrets)
    listed = await _list_all_tools(client)
    header = _header(client, pack, header_context, listed)
    run_id = uuid.uuid4().hex[:8]
    results: list[ToolResult] = []
    for tool in listed:
        results.append(
            await _check_tool(
                client, reader, pack, tool, run_id, before_call,
                settle_interval_s, settle_timeout_s, secrets,
            )
        )
    listed_names = {t.name for t in listed}
    for name in pack.entries:
        if name not in listed_names:
            no_claims = Claims(None, None, None)
            results.append(
                _unjudged(name, "", no_claims, Outcome.ERROR, error="pack entry for unlisted tool")
            )
    return header, results


async def _list_all_tools(client: Client) -> list[Tool]:
    tools: list[Tool] = []
    cursor: str | None = None
    while True:
        page = await client.list_tools(cursor=cursor)
        tools.extend(page.tools)
        cursor = page.next_cursor
        if not cursor:
            return tools


def _header(
    client: Client, pack: Pack, context: dict[str, Any], listed: list[Tool]
) -> RunHeader:
    tools_list = [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in listed]
    canonical = json.dumps(tools_list, sort_keys=True, separators=(",", ":"))
    info = client.server_info
    return RunHeader(
        server_info=info.model_dump(mode="json", by_alias=True, exclude_none=True) if info else {},
        protocol_version=client.protocol_version,
        sdk_version=importlib.metadata.version("mcp"),
        harness_version=__version__,
        pack_version=pack.version,
        image=context.get("image"),
        image_digest=context.get("image_digest"),
        deployment=context["deployment"],
        toolsets=list(context.get("toolsets") or []),
        features=list(context.get("features") or []),
        date=datetime.now(UTC).isoformat(timespec="seconds"),
        tools_list=tools_list,
        tools_list_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
        standard_read_only_fields=[f.path for f in pack.standard_read_only_fields],
    )


def _unjudged(
    tool: str,
    description: str,
    claims: Claims,
    outcome: Outcome,
    *,
    skip_reason: str | None = None,
    error: str | None = None,
) -> ToolResult:
    return ToolResult(
        tool=tool,
        description=description,
        claims=claims,
        outcome=outcome,
        verdicts=[],
        skip_reason=skip_reason,
        error=error,
        calls=[],
        waited_s=0.0,
        custom=None,
        private=False,
    )


async def _check_tool(
    client: Client,
    reader: StateReader,
    pack: Pack,
    tool: Tool,
    run_id: str,
    before_call: BeforeCall | None,
    interval_s: float,
    timeout_s: float,
    secrets: tuple[str, ...],
) -> ToolResult:
    claims = claims_of(tool)
    checks = applicable_checks(claims)
    entry = pack.entries.get(tool.name)
    description = tool.description or ""
    if not checks:
        reason = "no explicit claim"
    elif entry is None:
        reason = "no pack entry yet"
    elif entry.status == "skipped":
        reason = entry.skip_reason or "skipped by the pack"
    else:
        return await _ToolCheck(
            client, reader, pack, tool, entry, claims, checks, run_id, before_call,
            interval_s, timeout_s, secrets,
        ).run()
    return _unjudged(tool.name, description, claims, Outcome.SKIPPED, skip_reason=reason)


class _ToolCheck:
    """The judged path for one tool; holds the state its steps share."""

    def __init__(
        self,
        client: Client,
        reader: StateReader,
        pack: Pack,
        tool: Tool,
        entry: ToolEntry,
        claims: Claims,
        checks: list[Check],
        run_id: str,
        before_call: BeforeCall | None,
        interval_s: float,
        timeout_s: float,
        secrets: tuple[str, ...],
    ) -> None:
        self.client, self.reader, self.pack = client, reader, pack
        self.secrets = secrets
        self.tool, self.entry, self.claims, self.checks = tool, entry, claims, checks
        self.run_id, self.before_call = run_id, before_call
        self.interval_s, self.timeout_s = interval_s, timeout_s
        self.fields: dict[Check, list[FieldSpec]] = {
            c: pack.standard_read_only_fields if c is Check.READ_ONLY else entry.fields
            for c in checks
        }
        self.snapshot_fields = _union(self.fields.values())
        self.custom_verdict: Callable[..., Verdict] | None = None
        self.fixture: dict[str, Any] = {}
        self.arguments: dict[str, Any] = {}
        self.verdicts: list[Verdict] = []
        self.calls: list[dict] = []
        self.errors: list[str] = []
        self.waited_s = 0.0

    async def run(self) -> ToolResult:
        failed = False
        needs_cleanup = False
        step = "preparation"
        try:
            setup = _lookup(CUSTOM_SETUPS, "custom_setup", self.entry.custom_setup)
            self.custom_verdict = _lookup(
                CUSTOM_VERDICTS, "custom_verdict", self.entry.custom_verdict
            )
            step = "fixture setup"
            if setup is not None:
                needs_cleanup = True
                self.fixture = await setup(self.reader, self.entry, self.run_id)
            elif self.entry.fixture is not None:
                needs_cleanup = True
                self.fixture = await self.reader.create_fixture(self.entry, self.run_id)
            elif self.entry.repository == "read":
                self.fixture = dict(self.pack.read_fixtures)
            step = "argument rendering"
            self.arguments = render_arguments(self.entry, self.fixture, self.pack.repositories)
            step = "before-snapshot"
            before = await self._read()
            step = "call"
            await self._call()
            step = "after-snapshot"
            after = await self._settled()
            step = "judging"
            for check in self.checks:
                if check is not Check.IDEMPOTENT:
                    self.verdicts.append(self._judge(check, before, after))
            if Check.IDEMPOTENT in self.checks:
                step = "second call"
                await self._call()
                step = "second after-snapshot"
                after_second = await self._settled()
                step = "judging"
                self.verdicts.append(self._judge(Check.IDEMPOTENT, after, after_second))
        except Exception as e:
            failed = True
            self.errors.append(self._redact(_describe(step, e)))
        finally:
            if needs_cleanup:
                try:
                    await self.reader.cleanup(self.entry, self.fixture)
                except Exception as e:
                    self.errors.append(self._redact(f"cleanup failed: {type(e).__name__}: {e}"))
        return ToolResult(
            tool=self.tool.name,
            description=self.tool.description or "",
            claims=self.claims,
            outcome=Outcome.ERROR if failed else _most_severe(self.verdicts),
            verdicts=self.verdicts,
            skip_reason=None,
            error="; ".join(self.errors) or None,
            calls=self.calls,
            waited_s=self.waited_s,
            custom=self.entry.custom_reason if self.entry.custom_verdict else None,
            private=any(
                v.check is Check.READ_ONLY and v.outcome is Outcome.FINDING for v in self.verdicts
            ),
        )

    def _redact(self, text: str) -> str:
        return redact(text, self.secrets)

    async def _read(self) -> Recorded:
        return await self.reader.snapshot(self.snapshot_fields, self.fixture)

    async def _settled(self) -> Recorded:
        recorded, waited = await settle(self._read, self.interval_s, self.timeout_s)
        self.waited_s += waited
        return recorded

    async def _call(self) -> None:
        """Call the tool once. A refusal by before_call propagates; a failed call does not:
        it is recorded, and the after-snapshot is still taken and judged."""
        name, arguments = self.tool.name, self.arguments
        if self.before_call is not None:
            try:
                await self.before_call(name, arguments)
            except Exception as e:
                raise _HarnessError(f"call refused: {type(e).__name__}: {e}") from e
        try:
            result = await self.client.call_tool(name, arguments)
        except Exception as e:
            text = self._redact(f"{type(e).__name__}: {e}")
            self.calls.append(
                {"tool": name, "arguments": arguments, "is_error": True, "content": text}
            )
            self.errors.append(f"call raised {text}")
            return
        text = self._redact(_content_text(result.content))
        is_error = bool(result.is_error)
        self.calls.append(
            {"tool": name, "arguments": arguments, "is_error": is_error, "content": text}
        )
        if is_error:
            self.errors.append(f"tool returned an error: {text}")

    def _judge(self, check: Check, before: Recorded, after: Recorded) -> Verdict:
        fields = self.fields[check]
        if self.custom_verdict is not None and check is self.checks[0]:
            # The harness, not the custom function, decides which check this is,
            # quotes its schema text and records the observed evidence.
            verdict = self.custom_verdict(before, after, self.entry, self.arguments)
            return dataclasses.replace(
                verdict,
                check=check,
                schema_text=SCHEMA_TEXT[check],
                diff=diff_fields(before, after, fields),
            )
        if check is Check.READ_ONLY:
            return judge_read_only(before, after, fields)
        if check is Check.NON_DESTRUCTIVE:
            supplied = supplied_values(self.entry, self.arguments, fields)
            return judge_non_destructive(before, after, fields, supplied)
        return judge_idempotent(before, after, fields)


def _lookup(registry: dict[str, Any], key: str, name: str | None) -> Any:
    if name is None:
        return None
    if name not in registry:
        raise _HarnessError(f"unknown {key} {name!r}")
    return registry[name]


def _union(groups: Any) -> list[FieldSpec]:
    seen: dict[str, FieldSpec] = {}
    for group in groups:
        for f in group:
            seen.setdefault(f.path, f)
    return list(seen.values())


def _content_text(content: list[Any]) -> str:
    parts = []
    for item in content:
        text = getattr(item, "text", None)
        parts.append(text if isinstance(text, str) else item.model_dump_json(exclude_none=True))
    return "\n".join(parts)


def _describe(step: str, e: Exception) -> str:
    if isinstance(e, _HarnessError):
        return str(e)
    if isinstance(e, SettleTimeout):
        return f"{step}: {e}"
    return f"{step} failed: {type(e).__name__}: {e}"


def _most_severe(verdicts: list[Verdict]) -> Outcome:
    if not verdicts:
        return Outcome.ERROR
    return max((v.outcome for v in verdicts), key=_SEVERITY.__getitem__)
