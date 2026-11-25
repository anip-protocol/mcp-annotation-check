"""The seam between the runner and whatever holds a server's state."""

from typing import Any, Protocol

from mcp_annotation_check.pack import ToolEntry
from mcp_annotation_check.snapshot import FieldSpec, Recorded


class StateReader(Protocol):
    async def create_fixture(self, entry: ToolEntry, run_id: str) -> dict[str, Any]:
        """Create fresh state for one tool check; return the fixture values."""
        ...

    async def snapshot(self, fields: list[FieldSpec], fixture: dict[str, Any]) -> Recorded:
        """Read the given fields for the fixture."""
        ...

    async def cleanup(self, entry: ToolEntry, fixture: dict[str, Any]) -> None:
        """Remove or close the fixture."""
        ...
