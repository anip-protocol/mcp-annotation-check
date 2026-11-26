"""Command line: `mcp-annotation-check self-test` (more commands follow)."""

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from pathlib import Path

from mcp import Client

from mcp_annotation_check.fake.reader import FakeReader
from mcp_annotation_check.fake.server import FakeStore, build_fake_server
from mcp_annotation_check.github.launcher import TOKEN_ENV, image_digest, server_params
from mcp_annotation_check.github.reader import GitHubReader
from mcp_annotation_check.github.rest import GitHubRest
from mcp_annotation_check.github.safety import make_before_call, preflight
from mcp_annotation_check.pack import Pack, load_pack, pack_warnings, validate_pack
from mcp_annotation_check.redact import redact
from mcp_annotation_check.report import (
    PUBLISH_BLOCKED,
    WITHHELD,
    RunHeader,
    ToolResult,
    write_reports,
)
from mcp_annotation_check.runner import list_all_tools, run, tools_list_digest

FAKE_PACK = Path(__file__).resolve().parents[2] / "packs" / "fake.yaml"

# The fake server's `explode` tool raises on purpose; the SDK logs that traceback.
# The error is already captured in the report, so the console stays quiet.
_SERVER_LOGGER = "mcp.server.mcpserver.server"


async def _self_test(out: Path) -> tuple[RunHeader, list[ToolResult]]:
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
    return header, results


def _validation(header: RunHeader) -> list[str]:
    """The pack validation problems and warnings, for stderr (they are in the reports too)."""
    lines = [f"pack validation problem: {p}" for p in header.pack_problems]
    return lines + list(header.pack_warnings)  # each warning starts "warning: "


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
        lines.append(PUBLISH_BLOCKED)
    return lines


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _token() -> str:
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise RuntimeError(f"environment variable {TOKEN_ENV} is not set")
    return token


def _causes(error: BaseException, depth: int = 0) -> list[str]:
    """One line per error: exception groups are unwrapped (recursively, indented), and
    a failed subprocess shows its stderr, which is where docker explains itself."""
    pad = "  " * depth
    if isinstance(error, BaseExceptionGroup):
        lines = [f"{pad}{type(error).__name__}: {error.message}"]
        for inner in error.exceptions:
            lines += _causes(inner, depth + 1)
        return lines
    text = f"{pad}{type(error).__name__}: {error}"
    if isinstance(error, subprocess.CalledProcessError) and error.stderr:
        stderr = error.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        text += f" (stderr: {' '.join(str(stderr).split())})"
    return [text]


def _fail(error: BaseException, token: str | None) -> int:
    """Print an error through `redact` (never a raw traceback); return the exit code."""
    text = "error: " + "\n".join(_causes(error))
    print(redact(text, [token] if token else []), file=sys.stderr)
    return 1


async def _run_github(
    args: argparse.Namespace, token: str
) -> tuple[RunHeader, list[ToolResult]]:
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
        return header, results
    finally:
        await rest.aclose()


SHAKEDOWN_STEPS = ("preflight", "start", "tools_list", "validate", "snapshot")


async def shakedown(
    open_client: Callable[[], AbstractAsyncContextManager[Client]],
    rest: GitHubRest,
    reader: GitHubReader,
    pack: Pack,
    token: str,
    login: str,
    context: dict,
    out: Path,
) -> bool:
    """Preflight, start the server, tools/list, validate the pack, one read-only snapshot.

    Never calls a tool, creates or cleans up a fixture, or sends a non-GET request. Each
    step's outcome goes to out/shakedown.json (a failed preflight, or a server that does
    not start, leaves the later ones "not run"; a failed validation does not stop the
    snapshot); the file is redacted. True only if every step passed with no validation
    problems.
    """
    secrets = [token]
    steps: dict[str, dict] = {n: {"status": "not run", "passed": False} for n in SHAKEDOWN_STEPS}
    report: dict = {
        "image": context.get("image"),
        "image_digest": context.get("image_digest"),
        "toolsets": context.get("toolsets", []),
        "features": context.get("features", []),
        "server_info": None,
        "protocol_version": None,
        "tools_list_sha256": None,
        "tool_names": [],
        "validation_problems": [],
        "validation_warnings": pack_warnings(pack),
        "snapshot_fields": [],
        "steps": steps,
    }

    def passed(name: str) -> None:
        steps[name] = {"status": "passed", "passed": True}

    def failed(name: str, error: BaseException) -> None:
        text = "\n".join(_causes(error))
        steps[name] = {"status": "failed", "passed": False, "error": redact(text, secrets)}

    try:
        try:
            report["preflight"] = await preflight(rest, token, pack, login)
        except Exception as error:  # noqa: BLE001 - recorded, not raised
            failed("preflight", error)
        else:
            passed("preflight")
            await _shakedown_server(open_client, reader, pack, report, passed, failed)
    finally:
        text = redact(json.dumps(report, indent=2, sort_keys=True, default=str), secrets)
        out.mkdir(parents=True, exist_ok=True)
        (out / "shakedown.json").write_text(text + "\n")
    return all(s["passed"] for s in steps.values()) and not report["validation_problems"]


async def _shakedown_server(open_client, reader, pack, report, passed, failed) -> None:
    started = False
    try:
        async with open_client() as client:
            started = True
            passed("start")
            info = client.server_info
            report["server_info"] = (
                info.model_dump(mode="json", by_alias=True, exclude_none=True) if info else {}
            )
            report["protocol_version"] = client.protocol_version
            try:
                tools = await list_all_tools(client)
            except Exception as error:  # noqa: BLE001
                failed("tools_list", error)
                return
            listing = [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools]
            report["tool_names"] = sorted(t.name for t in tools)
            report["tools_list_sha256"] = tools_list_digest(listing)
            passed("tools_list")
            try:
                problems = validate_pack(pack, tools)
            except Exception as error:  # noqa: BLE001
                failed("validate", error)
            else:
                report["validation_problems"] = problems
                if problems:
                    failed("validate", RuntimeError(f"{len(problems)} pack validation problem(s)"))
                else:
                    passed("validate")
            try:
                fixture = {**pack.read_fixtures, "repository": pack.repositories["read"]}
                recorded = await reader.snapshot(pack.standard_read_only_fields, fixture)
                report["snapshot_fields"] = sorted(recorded.snapshot)
            except Exception as error:  # noqa: BLE001
                failed("snapshot", error)
            else:
                passed("snapshot")
    except Exception as error:  # noqa: BLE001 - the server failed to start, or to stop
        failed("start" if not started else "shutdown", error)


async def _shakedown_github(args: argparse.Namespace, token: str) -> bool:
    pack = load_pack(args.pack)
    rest = GitHubRest(token)
    toolsets, features = _split(args.toolsets), _split(args.features)
    try:
        context = {
            "image": args.image,
            "image_digest": image_digest(args.image),
            "toolsets": toolsets,
            "features": features,
        }
        params = server_params(args.image, toolsets, features)
        return await shakedown(
            lambda: Client(params),
            rest,
            GitHubReader(rest, pack.repositories),
            pack,
            token,
            args.login,
            context,
            args.out,
        )
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
    sd = sub.add_parser(
        "shakedown",
        help="preflight, tools/list, pack validation and one snapshot; no tool calls, no writes",
    )
    sd.add_argument("--pack", type=Path, required=True)
    sd.add_argument("--image", required=True)
    sd.add_argument("--toolsets", required=True, help="comma-separated")
    sd.add_argument("--features", default="", help="comma-separated")
    sd.add_argument("--login", required=True, help="expected test-account login")
    sd.add_argument("--out", type=Path, required=True)
    lt = sub.add_parser("list-tools", help="write the server's tools/list to JSON")
    lt.add_argument("--image", required=True)
    lt.add_argument("--toolsets", required=True, help="comma-separated")
    lt.add_argument("--features", default="", help="comma-separated")
    lt.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "shakedown":
        token = None
        try:
            token = _token()
            ok = asyncio.run(_shakedown_github(args, token))
        except KeyboardInterrupt:
            print("interrupted", file=sys.stderr)
            return 130
        except BaseException as error:  # noqa: BLE001
            return _fail(error, token)
        print(args.out / "shakedown.json")
        print("shakedown passed" if ok else "shakedown FAILED (see shakedown.json)")
        return 0 if ok else 1

    if args.command in ("run", "list-tools"):
        token = None
        try:
            token = _token()
            if args.command == "list-tools":
                count = asyncio.run(_list_tools(args))
                print(f"{count} tools written to {args.out}")
                return 0
            header, results = asyncio.run(_run_github(args, token))
        except KeyboardInterrupt:
            print("interrupted", file=sys.stderr)
            return 130
        except BaseException as error:  # noqa: BLE001 - everything is redacted, never a traceback
            return _fail(error, token)
        for line in _validation(header):
            print(redact(line, [token] if token else []), file=sys.stderr)
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
            header, results = asyncio.run(_self_test(args.out))
        finally:
            server_logger.disabled = previous
        for line in _validation(header):
            print(line, file=sys.stderr)
        for name in ("report.md", "report.json", "private-findings.md"):
            print(args.out / name)
        print("outcomes:")
        print("\n".join(_summary(results)))
    return 0
