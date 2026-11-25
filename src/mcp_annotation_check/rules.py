"""The three annotation rules, each judging recorded before/after state."""

from typing import Any

from mcp_annotation_check.claims import SCHEMA_TEXT, Check
from mcp_annotation_check.snapshot import FieldKind, FieldSpec, Outcome, Recorded, Verdict


def _names(fields: list[FieldSpec]) -> str:
    return ", ".join(f.path for f in fields)


def _diff(before: Recorded, after: Recorded, fields: list[FieldSpec]) -> dict[str, tuple[Any, Any]]:
    return {
        f.path: (before.snapshot.get(f.path), after.snapshot.get(f.path))
        for f in fields
        if before.snapshot.get(f.path) != after.snapshot.get(f.path)
    }


def _equality_verdict(
    check: Check, before: Recorded, after: Recorded, fields: list[FieldSpec]
) -> Verdict:
    changed = _diff(before, after, fields)
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
    return Verdict(check, outcome, detail, changed, warnings, SCHEMA_TEXT[check])


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
    findings: dict[str, tuple[Any, Any]] = {}
    observations: dict[str, tuple[Any, Any]] = {}
    for f in fields:
        b = before.snapshot.get(f.path)
        a = after.snapshot.get(f.path)
        if f.kind is FieldKind.COLLECTION:
            if (b or frozenset()) - (a or frozenset()):
                findings[f.path] = (b, a)
        elif b is not None and b != a:
            if f.path in supplied and a == supplied[f.path]:
                observations[f.path] = (b, a)
            else:
                findings[f.path] = (b, a)
    if findings:
        outcome, detail = Outcome.FINDING, f"lost or overwritten: {', '.join(findings)}"
    elif observations:
        outcome = Outcome.OBSERVATION
        detail = f"overwritten with the supplied value: {', '.join(observations)}"
    else:
        outcome, detail = Outcome.PASS, f"no change observed in {_names(fields)}"
    return Verdict(
        Check.NON_DESTRUCTIVE,
        outcome,
        detail,
        {**observations, **findings},
        [],
        SCHEMA_TEXT[Check.NON_DESTRUCTIVE],
    )
