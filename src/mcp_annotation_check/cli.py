"""Command line: `mcp-annotation-check self-test` (more commands follow)."""

import argparse
import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path

from mcp import Client

from mcp_annotation_check.fake.reader import FakeReader
from mcp_annotation_check.fake.server import FakeStore, build_fake_server
from mcp_annotation_check.pack import load_pack
from mcp_annotation_check.report import WITHHELD, ToolResult, write_reports
from mcp_annotation_check.runner import run

FAKE_PACK = Path(__file__).resolve().parents[2] / "packs" / "fake.yaml"

# The fake server's `explode` tool raises on purpose; the SDK logs that traceback.
# The error is already captured in the report, so the console stays quiet.
_SERVER_LOGGER = "mcp.server.mcpserver.server"


async def _self_test(out: Path) -> list[ToolResult]:
    store = FakeStore()
    context = {
        "image": None,
        "image_digest": None,
        "deployment": "in-memory",
        "toolsets": [],
        "features": [],
    }
    async with Client(build_fake_server(store)) as client:
        header, results = await run(
            client,
            FakeReader(store),
            load_pack(FAKE_PACK),
            context,
            settle_interval_s=0.01,
            settle_timeout_s=0.5,
        )
    write_reports(header, results, out)
    return results


def _summary(results: list[ToolResult]) -> list[str]:
    lines = []
    withheld = 0
    for r in results:
        if r.private:
            withheld += 1
            continue
        reason = r.skip_reason or (r.error if r.outcome.value == "error" else None)
        lines.append(f"  {r.tool}: {r.outcome.value}" + (f" ({reason})" if reason else ""))
    if withheld:
        lines.append(f"  {withheld} {WITHHELD}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcp-annotation-check",
        description="Check whether MCP server tools behave as their annotations claim.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    st = sub.add_parser("self-test", help="run against the built-in mislabelled fake server")
    st.add_argument("--out", type=Path, default=Path("out/self-test"), help="report directory")
    args = parser.parse_args(argv)

    if args.command == "self-test":
        server_logger = logging.getLogger(_SERVER_LOGGER)
        previous = server_logger.disabled
        server_logger.disabled = True
        try:
            results = asyncio.run(_self_test(args.out))
        finally:
            server_logger.disabled = previous
        for name in ("report.md", "report.json", "private-findings.md"):
            print(args.out / name)
        print("outcomes:")
        print("\n".join(_summary(results)))
    return 0
