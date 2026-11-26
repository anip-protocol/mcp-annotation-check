"""The three annotation rules, each judging recorded before/after state."""

from typing import Any

from mcp_annotation_check.claims import SCHEMA_TEXT, Check
from mcp_annotation_check.snapshot import FieldKind, FieldSpec, Outcome, Recorded, Verdict


def _names(fields: list[FieldSpec]) -> str:
    return ", ".join(f.path for f in fields)


def _empty(value: Any) -> bool:
    """A scalar with nothing in it: setting it is additive, clearing to it is a loss."""
    return value is None or value == ""


def diff_fields(
    before: Recorded, after: Recorded, fields: list[FieldSpec]
) -> dict[str, tuple[Any, Any]]:
    """Every listed field whose value differs between the snapshots."""
    return {
        f.path: (before.snapshot.get(f.path), after.snapshot.get(f.path))
        for f in fields
        if before.snapshot.get(f.path) != after.snapshot.get(f.path)
    }


def _equality_verdict(
    check: Check, before: Recorded, after: Recorded, fields: list[FieldSpec]
) -> Verdict:
    changed = diff_fields(before, after, fields)
    warnings: list[str] = []
    if changed:
        outcome = Outcome.FINDING
        detail = f"changed: {', '.join(changed)}"
    else:
        outcome = Outcome.PASS
        detail = f"no change observed in {_names(fields)}"
        if before.timestamps != after.timestamps:
            warnings.append(
                "updated_at changed although the compared fields did not; "
                "updated_at is recorded but never compared"
            )
    return Verdict(check, outcome, detail, changed, warnings, SCHEMA_TEXT[check], dict(changed))


def judge_read_only(before: Recorded, after: Recorded, fields: list[FieldSpec]) -> Verdict:
    return _equality_verdict(Check.READ_ONLY, before, after, fields)


def judge_idempotent(
    after_first: Recorded, after_second: Recorded, fields: list[FieldSpec]
) -> Verdict:
    return _equality_verdict(Check.IDEMPOTENT, after_first, after_second, fields)


def judge_non_destructive(
    before: Recorded,
    after: Recorded,
    fields: list[FieldSpec],
    supplied: dict[str, Any],
) -> Verdict:
    diff = diff_fields(before, after, fields)
    findings: dict[str, tuple[Any, Any]] = {}
    observations: dict[str, tuple[Any, Any]] = {}
    for f in fields:
        b = before.snapshot.get(f.path)
        a = after.snapshot.get(f.path)
        if f.kind is FieldKind.COLLECTION:
            if (b or frozenset()) - (a or frozenset()):
                findings[f.path] = (b, a)
        elif not _empty(b) and b != a:
            # Clearing a value (to None or "") loses it without a replacement, even
            # when the caller asked for that: only a supplied non-empty value is an
            # OBSERVATION.
            if f.path in supplied and a == supplied[f.path] and not _empty(a):
                observations[f.path] = (b, a)
            else:
                findings[f.path] = (b, a)
    if findings:
        outcome, detail = Outcome.FINDING, f"lost or overwritten: {', '.join(findings)}"
    elif observations:
        outcome = Outcome.OBSERVATION
        detail = f"overwritten with the supplied value: {', '.join(observations)}"
    else:
        outcome = Outcome.PASS
        detail = f"nothing removed or overwritten in {_names(fields)}"
        if diff:
            detail += f"; additions in {', '.join(diff)}"
    return Verdict(
        Check.NON_DESTRUCTIVE,
        outcome,
        detail,
        {**observations, **findings},
        [],
        SCHEMA_TEXT[Check.NON_DESTRUCTIVE],
        diff,
    )
