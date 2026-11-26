"""Snapshot data model: fields to compare, recorded state, and verdicts."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from mcp_annotation_check.claims import Check


class FieldKind(StrEnum):
    COLLECTION = "collection"
    SCALAR = "scalar"


@dataclass(frozen=True)
class FieldSpec:
    path: str
    kind: FieldKind


# Collection fields whose elements are tuples, each describing one object (a comment,
# a ref, an issue, a label). Editing one object in place removes one tuple and adds
# another, which the non-destructive rule would read as a loss. Until elements are
# matched by identity, a non-destructive check judges only the other (plain) fields: a
# FINDING there is reported (naming the composite fields it did not judge), otherwise
# the check is UNJUDGED, which is not a failed call (ruling R17, amended). Read-only and
# idempotent checks compare for equality and still use them.
COMPOSITE_FIELDS = frozenset({"issue.comments", "repo.refs", "repo.issues", "repo.labels"})


# Keyed by FieldSpec.path. Collections are frozensets of hashables; scalars are hashable or None.
Snapshot = dict[str, Any]


@dataclass(frozen=True)
class Recorded:
    snapshot: Snapshot
    # updated_at values: recorded, never compared.
    timestamps: dict[str, str] = field(default_factory=dict)


class Outcome(StrEnum):
    PASS = "pass"
    FINDING = "finding"
    OBSERVATION = "observation"
    SKIPPED = "skipped"
    ERROR = "error"
    UNJUDGED = "unjudged"


@dataclass(frozen=True)
class Verdict:
    check: Check
    outcome: Outcome
    detail: str
    # The fields that count against the claim (for non-destructive: lost or overwritten).
    changed: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    schema_text: str = ""
    # Every compared field whose value differs between the two snapshots, additions included.
    diff: dict[str, tuple[Any, Any]] = field(default_factory=dict)
