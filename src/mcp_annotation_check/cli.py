"""Command line: `mcp-annotation-check self-test` (more commands follow)."""

import argparse
import asyncio
import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from mcp import Client

from mcp_annotation_check.fake.reader import FakeReader
from mcp_annotation_check.fake.server import FakeStore, build_fake_server
from mcp_annotation_check.github.launcher import TOKEN_ENV, image_digest, server_params
from mcp_annotation_check.github.reader import GitHubReader
from mcp_annotation_check.github.rest import GitHubRest
from mcp_annotation_check.github.safety import make_before_call, preflight
from mcp_annotation_check.pack import load_pack
from mcp_annotation_check.redact import redact
from mcp_annotation_check.report import WITHHELD, ToolResult, write_reports
from mcp_annotation_check.runner import list_all_tools, run

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


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _token() -> str:
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise RuntimeError(f"environment variable {TOKEN_ENV} is not set")
    return token


def _fail(error: BaseException, token: str | None) -> int:
    """Print an error through `redact` (never a raw traceback); return the exit code."""
    text = f"error: {type(error).__name__}: {error}"
    print(redact(text, [token] if token else []), file=sys.stderr)
    return 1


async def _run_github(args: argparse.Namespace, token: str) -> list[ToolResult]:
    pack = load_pack(args.pack)
    rest = GitHubRest(token)
    try:
        facts = await preflight(rest, token, pack, args.login)
        # The RunHeader has no field for these, so they are printed instead.
        print(redact(f"preflight passed: {json.dumps(facts, sort_keys=True)}", [token]))
        toolsets, features = _split(args.toolsets), _split(args.features)
        context = {
            "image": args.image,
            "image_digest": image_digest(args.image),
            "deployment": "local",
            "toolsets": toolsets,
            "features": features,
        }
        params = server_params(args.image, toolsets, features)
        async with Client(params) as client:
            header, results = await run(
                client,
                GitHubReader(rest, pack.repositories),
                pack,
                context,
                make_before_call(rest, pack),
                settle_interval_s=args.settle_interval,
                settle_timeout_s=args.settle_timeout,
                secrets=[token],
            )
        write_reports(header, results, args.out)
        return results
    finally:
        await rest.aclose()


async def _list_tools(args: argparse.Namespace) -> int:
    params = server_params(args.image, _split(args.toolsets), _split(args.features))
    async with Client(params) as client:
        tools = await list_all_tools(client)
    listing = [
        {
            "name": t.name,
            "description": t.description,
            "annotations": (
                t.annotations.model_dump(mode="json", by_alias=True, exclude_none=True)
                if t.annotations
                else None
            ),
            "inputSchema": t.input_schema,
        }
        for t in tools
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(listing, indent=2) + "\n")
    return len(listing)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcp-annotation-check",
        description="Check whether MCP server tools behave as their annotations claim.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    st = sub.add_parser("self-test", help="run against the built-in mislabelled fake server")
    st.add_argument("--out", type=Path, default=Path("out/self-test"), help="report directory")
    run_p = sub.add_parser("run", help="run against GitHub's MCP server in Docker")
    run_p.add_argument("--pack", type=Path, required=True)
    run_p.add_argument("--image", required=True)
    run_p.add_argument("--toolsets", required=True, help="comma-separated")
    run_p.add_argument("--features", default="", help="comma-separated")
    run_p.add_argument("--login", required=True, help="expected test-account login")
    run_p.add_argument("--out", type=Path, required=True)
    run_p.add_argument("--settle-interval", type=float, default=1.0)
    run_p.add_argument("--settle-timeout", type=float, default=20.0)
    lt = sub.add_parser("list-tools", help="write the server's tools/list to JSON")
    lt.add_argument("--image", required=True)
    lt.add_argument("--toolsets", required=True, help="comma-separated")
    lt.add_argument("--features", default="", help="comma-separated")
    lt.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command in ("run", "list-tools"):
        token = None
        try:
            token = _token()
            if args.command == "list-tools":
                count = asyncio.run(_list_tools(args))
                print(f"{count} tools written to {args.out}")
                return 0
            results = asyncio.run(_run_github(args, token))
        except KeyboardInterrupt:
            print("interrupted", file=sys.stderr)
            return 130
        except BaseException as error:  # noqa: BLE001 - everything is redacted, never a traceback
            return _fail(error, token)
        for name in ("report.md", "report.json", "private-findings.md"):
            print(args.out / name)
        print("outcomes:")
        print("\n".join(_summary(results)))
        return 0

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
