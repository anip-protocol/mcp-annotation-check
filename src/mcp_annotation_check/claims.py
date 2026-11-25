"""Extract explicit annotation claims from MCP tools and decide which checks apply."""

from dataclasses import dataclass
from enum import StrEnum

from mcp.types import Tool


class Check(StrEnum):
    READ_ONLY = "read_only"
    NON_DESTRUCTIVE = "non_destructive"
    IDEMPOTENT = "idempotent"


@dataclass(frozen=True)
class Claims:
    read_only: bool | None
    destructive: bool | None
    idempotent: bool | None


SCHEMA_TEXT: dict[Check, str] = {
    Check.READ_ONLY: "If true, the tool does not modify its environment.",
    Check.NON_DESTRUCTIVE: (
        "If true, the tool may perform destructive updates to its environment. "
        "If false, the tool performs only additive updates."
    ),
    Check.IDEMPOTENT: (
        "If true, calling the tool repeatedly with the same arguments "
        "will have no additional effect on its environment."
    ),
}


def claims_of(tool: Tool) -> Claims:
    a = tool.annotations
    if a is None:
        return Claims(None, None, None)
    return Claims(a.read_only_hint, a.destructive_hint, a.idempotent_hint)


def applicable_checks(claims: Claims) -> list[Check]:
    """Only explicit claims are tested; destructive/idempotent only when not read-only."""
    if claims.read_only is True:
        return [Check.READ_ONLY]
    checks: list[Check] = []
    if claims.destructive is False:
        checks.append(Check.NON_DESTRUCTIVE)
    if claims.idempotent is True:
        checks.append(Check.IDEMPOTENT)
    return checks
