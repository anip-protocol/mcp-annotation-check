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


@dataclass(frozen=True)
class Verdict:
    check: Check
    outcome: Outcome
    detail: str
    changed: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    schema_text: str = ""
