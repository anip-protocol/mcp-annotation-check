from dataclasses import replace
from pathlib import Path
from typing import Any

from mcp import Client

from mcp_annotation_check.fake.reader import FakeReader
from mcp_annotation_check.fake.server import FakeStore, build_fake_server
from mcp_annotation_check.pack import Pack, ToolEntry, load_pack
from mcp_annotation_check.runner import run

FAKE_PACK = Path(__file__).resolve().parent.parent / "packs" / "fake.yaml"

HEADER_CONTEXT = {
    "image": None,
    "image_digest": None,
    "deployment": "in-memory",
    "toolsets": [],
    "features": [],
}


def with_entries(pack: Pack, **entries: ToolEntry | None) -> Pack:
    """A copy of pack with entries replaced, added, or (None) removed."""
    merged = dict(pack.entries)
    for name, entry in entries.items():
        if entry is None:
            merged.pop(name, None)
        else:
            merged[name] = entry
    return replace(pack, entries=merged)


async def run_fake(
    pack: Pack | None = None,
    store: FakeStore | None = None,
    reader: Any = None,
    server: Any = None,
    before_call: Any = None,
):
    store = store or FakeStore()
    pack = pack or load_pack(FAKE_PACK)
    reader = reader or FakeReader(store)
    server = server or build_fake_server(store)
    async with Client(server) as client:
        return await run(
            client,
            reader,
            pack,
            HEADER_CONTEXT,
            before_call=before_call,
            settle_interval_s=0.01,
            settle_timeout_s=0.3,
        )
