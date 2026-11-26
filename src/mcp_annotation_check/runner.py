"""Serial runner: plan every listed tool, then judge enabled ones one at a time.

Before anything else, the pack is validated against the server's tools/list
(`pack.validate_pack`). Any problem stops the run there: no fixture is created and
no tool is called; every listed tool with an enabled entry is SKIPPED with "pack
validation failed: <n> problem(s)", other listed tools keep their usual skip reason,
and the problems (and `pack.pack_warnings`) are recorded in the report header, so
the reports can still be written.

Per judged tool: fixture, arguments, settled before-snapshot, call, settled
after-snapshot (taken even when the call errored), rules, a second call for the
idempotent check, and cleanup in a `finally`. A call that errored is judged like any
other: a change against the claim is a FINDING (or OBSERVATION), but with no such
change the tool is an ERROR ("call failed; no change observed in ..."), never a PASS.
A non-destructive check over composite fields (snapshot.COMPOSITE_FIELDS) is UNJUDGED
unless its plain fields show a FINDING; a FINDING outranks every other outcome.
A failure at any step is an ERROR for that tool only, with one exception: a refusal
by `before_call` (the per-call safety check) stops the run. The refused tool is an
ERROR and every remaining tool is SKIPPED with "run stopped after a safety refusal
on <tool>"; the results are still returned so the reports can be written. Any
exception from `before_call` counts as a refusal, since a safety check that fails to
run has not passed.
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
from mcp_annotation_check.pack import (
    Pack,
    ToolEntry,
    pack_warnings,
    render_arguments,
    supplied_values,
    validate_pack,
)
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
from mcp_annotation_check.snapshot import (
    COMPOSITE_FIELDS,
    FieldSpec,
    Outcome,
    Recorded,
    Verdict,
)

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
    Outcome.UNJUDGED: 3,
    Outcome.ERROR: 4,
    Outcome.FINDING: 5,
}


class _HarnessError(Exception):
    """A failure whose message is reported as is, without a step prefix."""


class _CallRefused(_HarnessError):
    """before_call refused a call: the run stops after this tool."""


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
    listed = await list_all_tools(client)
    problems = [redact(p, secrets) for p in validate_pack(pack, listed)]
    warnings = [redact(w, secrets) for w in pack_warnings(pack)]
    header = _header(client, pack, header_context, listed, problems, warnings)
    run_id = uuid.uuid4().hex[:8]
    results: list[ToolResult] = []
    refused_on: str | None = None
    invalid = f"pack validation failed: {len(problems)} problem(s)" if problems else None
    for tool in listed:
        if invalid is not None:
            # Nothing is called and no fixture is created.
            claims = claims_of(tool)
            entry = pack.entries.get(tool.name)
            reason = invalid if entry is not None and entry.status == "enabled" else None
            reason = reason or _skip_reason(entry, applicable_checks(claims))
            results.append(
                _unjudged(
                    tool.name, tool.description or "", claims, Outcome.SKIPPED,
                    skip_reason=reason,
                )
            )
            continue
        if refused_on is not None:
            results.append(
                _unjudged(
                    tool.name,
                    tool.description or "",
                    claims_of(tool),
                    Outcome.SKIPPED,
                    skip_reason=f"run stopped after a safety refusal on {refused_on}",
                )
            )
            continue
        result, refused = await _check_tool(
            client, reader, pack, tool, run_id, before_call,
            settle_interval_s, settle_timeout_s, secrets,
        )
        results.append(result)
        if refused:
            refused_on = tool.name
    listed_names = {t.name for t in listed}
    for name in pack.entries:
        if name not in listed_names:
            no_claims = Claims(None, None, None)
            results.append(
                _unjudged(name, "", no_claims, Outcome.ERROR, error="pack entry for unlisted tool")
            )
    return header, results


async def list_all_tools(client: Client) -> list[Tool]:
    tools: list[Tool] = []
    cursor: str | None = None
    while True:
        page = await client.list_tools(cursor=cursor)
        tools.extend(page.tools)
        cursor = page.next_cursor
        if not cursor:
            return tools


def _header(
    client: Client,
    pack: Pack,
    context: dict[str, Any],
    listed: list[Tool],
    problems: list[str],
    warnings: list[str],
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
        pack_problems=problems,
        pack_warnings=warnings,
    )


def _skip_reason(entry: ToolEntry | None, checks: list[Check]) -> str | None:
    """Why a listed tool is not judged, or None if it is."""
    if not checks:
        return "no explicit claim"
    if entry is None:
        return "no pack entry yet"
    if entry.status == "skipped":
        return entry.skip_reason or "skipped by the pack"
    return None


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
) -> tuple[ToolResult, bool]:
    """The tool's result, and whether before_call refused one of its calls."""
    claims = claims_of(tool)
    checks = applicable_checks(claims)
    entry = pack.entries.get(tool.name)
    description = tool.description or ""
    reason = _skip_reason(entry, checks)
    if reason is None and entry is not None:
        check = _ToolCheck(
            client, reader, pack, tool, entry, claims, checks, run_id, before_call,
            interval_s, timeout_s, secrets,
        )
        return await check.run(), check.refused
    return _unjudged(tool.name, description, claims, Outcome.SKIPPED, skip_reason=reason), False


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
        self.call_failed = False
        self.waited_s = 0.0
        self.refused = False

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
            if self.entry.repository in self.pack.repositories:
                # The reader observes the entry's own repository, never a default one.
                self.fixture.setdefault(
                    "repository", self.pack.repositories[self.entry.repository]
                )
            step = "argument rendering"
            self.arguments = render_arguments(self.entry, self.fixture, self.pack.repositories)
            step = "before-snapshot"
            # Settled too: a read that lags behind fixture creation must not look like
            # a change made by the call.
            before = await self._settled()
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
            self.refused = isinstance(e, _CallRefused)
            self.errors.append(self._redact(_describe(step, e)))
        finally:
            if needs_cleanup:
                try:
                    await self.reader.cleanup(self.entry, self.fixture)
                except Exception as e:
                    self.errors.append(self._redact(f"cleanup failed: {type(e).__name__}: {e}"))
        outcome = Outcome.ERROR if failed else _most_severe(self.verdicts)
        if not failed and self.call_failed and not any(
            v.outcome in (Outcome.FINDING, Outcome.OBSERVATION) for v in self.verdicts
        ):
            # A failed call that changed nothing has not shown the claim true: it is an
            # ERROR, not a PASS. The verdicts stay as evidence.
            outcome = Outcome.ERROR
            self.errors.insert(0, self._no_change_text())
        return ToolResult(
            tool=self.tool.name,
            description=self.tool.description or "",
            claims=self.claims,
            outcome=outcome,
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

    def _no_change_text(self) -> str:
        """What the verdicts of a failed call observed, for its ERROR text."""
        compared = _union(self.fields[v.check] for v in self.verdicts)
        differing = [f.path for f in compared if any(f.path in v.diff for v in self.verdicts)]
        unchanged = [f.path for f in compared if f.path not in differing]
        text = "call failed"
        if unchanged:
            text += f"; no change observed in {', '.join(unchanged)}"
        if differing:
            text += f"; changed: {', '.join(differing)}"
        return text

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
                raise _CallRefused(f"call refused: {type(e).__name__}: {e}") from e
        try:
            result = await self.client.call_tool(name, arguments)
        except Exception as e:
            text = self._redact(f"{type(e).__name__}: {e}")
            self.calls.append(
                {"tool": name, "arguments": arguments, "is_error": True, "content": text}
            )
            self.errors.append(f"call raised {text}")
            self.call_failed = True
            return
        text = self._redact(_content_text(result.content))
        is_error = bool(result.is_error)
        self.calls.append(
            {"tool": name, "arguments": arguments, "is_error": is_error, "content": text}
        )
        if is_error:
            self.errors.append(f"tool returned an error: {text}")
            self.call_failed = True

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
            composite = [f.path for f in fields if f.path in COMPOSITE_FIELDS]
            plain = [f for f in fields if f.path not in COMPOSITE_FIELDS]
            supplied = supplied_values(self.entry, self.arguments, plain)
            verdict = judge_non_destructive(before, after, plain, supplied)
            if not composite:
                return verdict
            note = f"not judged yet (composite elements): {', '.join(composite)}"
            diff = diff_fields(before, after, fields)
            if verdict.outcome is Outcome.FINDING:
                return dataclasses.replace(
                    verdict, detail=f"{verdict.detail}; {note}", diff=diff
                )
            return Verdict(
                Check.NON_DESTRUCTIVE,
                Outcome.UNJUDGED,
                f"{note}; other fields: {verdict.detail}",
                verdict.changed,
                verdict.warnings,
                SCHEMA_TEXT[Check.NON_DESTRUCTIVE],
                diff,
            )
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
