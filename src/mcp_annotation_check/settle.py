"""Poll a snapshot until it stops changing."""

import asyncio
import time
from collections.abc import Awaitable, Callable

from mcp_annotation_check.snapshot import Recorded


class SettleTimeout(Exception):
    pass


async def settle(
    read: Callable[[], Awaitable[Recorded]],
    interval_s: float = 1.0,
    timeout_s: float = 20.0,
    stable_reads: int = 2,
) -> tuple[Recorded, float]:
    """Read until `stable_reads` consecutive snapshots are equal.

    Only the compared snapshot counts; timestamps are recorded, never compared.
    Returns the last snapshot and the seconds waited.
    """
    start = time.monotonic()
    last = await read()
    streak = 1
    while streak < stable_reads:
        if time.monotonic() - start >= timeout_s:
            raise SettleTimeout(f"did not settle within {timeout_s:g}s")
        await asyncio.sleep(interval_s)
        current = await read()
        streak = streak + 1 if current.snapshot == last.snapshot else 1
        last = current
    return last, time.monotonic() - start
