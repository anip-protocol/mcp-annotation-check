"""Pack format: a YAML file describing one MCP server's tools.

Top-level keys:
  server, version      strings
  allowlist            list of GitHub owners (the test organization, and the test
                       account if needed) the harness may act on, as ASCII names;
                       compared case-insensitively by the safety checks
  repositories         map name -> "owner/name", ASCII (names used: "read", "write")
  standard_read_only_fields   list of {path, kind} compared for read-only tools
  id_only_write_tools  list of tool names (default empty)
  read_fixtures        map of fixture values for read-repository entries
                       that name no fixture (default empty)
  tools                map tool name -> entry:
      status           "enabled" (default) or "skipped" (needs skip_reason)
      skip_reason, fixture, repository ("write" default | "read")
      arguments        dict; strings may hold {fixture.X}, {repo.owner}, {repo.name}
      fields           list of {path, kind} (kind: collection | scalar)
      supplies         map field path -> argument name supplying that field
      custom_setup, custom_verdict, custom_reason (verdict needs reason)

Content rule: no string in arguments may contain an @mention, a
cross-repository reference or a github.com URL.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from mcp_annotation_check.snapshot import FieldKind, FieldSpec

_MENTION = re.compile(r"(?<![\w.])@[A-Za-z0-9-]+")
_XREF = re.compile(r"[\w.-]+/[\w.-]+#\d+")
_PLACEHOLDER = re.compile(r"\{(fixture\.[\w]+|repo\.owner|repo\.name)\}")
_OWNER = re.compile(r"[A-Za-z0-9_.-]+")  # ASCII only, as the safety checks require
_FULL_NAME = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class PackError(Exception):
    pass


@dataclass(frozen=True)
class ToolEntry:
    tool: str
    status: Literal["enabled", "skipped"] = "enabled"
    skip_reason: str | None = None
    fixture: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    fields: list[FieldSpec] = field(default_factory=list)
    supplies: dict[str, str] = field(default_factory=dict)
    custom_setup: str | None = None
    custom_verdict: str | None = None
    custom_reason: str | None = None
    repository: Literal["read", "write"] = "write"


@dataclass(frozen=True)
class Pack:
    server: str
    version: str
    allowlist: list[str]
    repositories: dict[str, str]
    standard_read_only_fields: list[FieldSpec]
    entries: dict[str, ToolEntry]
    id_only_write_tools: list[str] = field(default_factory=list)
    read_fixtures: dict[str, Any] = field(default_factory=dict)


def check_content(value: Any, tool: str) -> None:
    """Raise PackError if any string in value breaks the content rule."""
    if isinstance(value, str):
        if _MENTION.search(value):
            raise PackError(f"{tool}: argument text contains an @mention: {value!r}")
        if _XREF.search(value):
            raise PackError(f"{tool}: argument text contains a cross-repository reference: {value!r}")
        if "github.com/" in value.lower():
            raise PackError(f"{tool}: argument text contains a github.com URL: {value!r}")
    elif isinstance(value, dict):
        for k, v in value.items():
            check_content(k, tool)
            check_content(v, tool)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for v in value:
            check_content(v, tool)
    elif value is None or isinstance(value, (bool, int, float)):
        pass
    else:
        raise PackError(f"{tool}: unsupported value type {type(value).__name__}")


def _fields(raw: Any, where: str) -> list[FieldSpec]:
    out = []
    for f in raw or []:
        try:
            out.append(FieldSpec(str(f["path"]), FieldKind(f["kind"])))
        except (KeyError, TypeError, ValueError) as e:
            raise PackError(f"{where}: bad field spec {f!r}") from e
    return out


def _entry(tool: str, raw: dict[str, Any]) -> ToolEntry:
    raw = raw or {}
    status = raw.get("status", "enabled")
    if status not in ("enabled", "skipped"):
        raise PackError(f"{tool}: status must be enabled or skipped")
    repository = raw.get("repository", "write")
    if repository not in ("read", "write"):
        raise PackError(f"{tool}: repository must be read or write")
    arguments = raw.get("arguments") or {}
    fields = _fields(raw.get("fields"), tool)
    supplies = dict(raw.get("supplies") or {})
    if status == "skipped" and not raw.get("skip_reason"):
        raise PackError(f"{tool}: status skipped requires skip_reason")
    if raw.get("custom_verdict") and not raw.get("custom_reason"):
        raise PackError(f"{tool}: custom_verdict requires custom_reason")
    paths = {f.path for f in fields}
    for path, arg in supplies.items():
        if path not in paths:
            raise PackError(f"{tool}: supplies key {path!r} is not one of the entry's fields")
        if arg not in arguments:
            raise PackError(f"{tool}: supplies value {arg!r} is not an argument name")
    check_content(arguments, tool)
    return ToolEntry(
        tool=tool,
        status=status,
        skip_reason=raw.get("skip_reason"),
        fixture=raw.get("fixture"),
        arguments=arguments,
        fields=fields,
        supplies=supplies,
        custom_setup=raw.get("custom_setup"),
        custom_verdict=raw.get("custom_verdict"),
        custom_reason=raw.get("custom_reason"),
        repository=repository,
    )


def _allowlist(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PackError(f"allowlist must be a list of owner names, not {type(raw).__name__}")
    for owner in raw:
        if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
            raise PackError(f"allowlist entry {owner!r} is not an ASCII owner name")
    return list(raw)


def _repositories(raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PackError(f"repositories must be a mapping, not {type(raw).__name__}")
    for name, full_name in raw.items():
        if not isinstance(name, str):
            raise PackError(f"repositories key {name!r} is not a string")
        if not isinstance(full_name, str) or not _FULL_NAME.fullmatch(full_name):
            raise PackError(f"repositories[{name!r}] = {full_name!r} is not \"owner/name\"")
    return dict(raw)


def load_pack(path: Path) -> Pack:
    try:
        raw = yaml.safe_load(Path(path).read_text())
    except (OSError, yaml.YAMLError) as e:
        raise PackError(f"cannot read pack {path}: {e}") from e
    if not isinstance(raw, dict):
        raise PackError(f"pack {path} must be a mapping")
    try:
        server, version = str(raw["server"]), str(raw["version"])
    except KeyError as e:
        raise PackError(f"pack {path} is missing {e.args[0]}") from e
    tools = raw.get("tools") or {}
    read_fixtures = dict(raw.get("read_fixtures") or {})
    check_content(read_fixtures, "read_fixtures")
    return Pack(
        server=server,
        version=version,
        allowlist=_allowlist(raw.get("allowlist")),
        repositories=_repositories(raw.get("repositories")),
        standard_read_only_fields=_fields(raw.get("standard_read_only_fields"), "pack"),
        entries={name: _entry(name, body) for name, body in tools.items()},
        id_only_write_tools=list(raw.get("id_only_write_tools") or []),
        read_fixtures=read_fixtures,
    )


def render_arguments(
    entry: ToolEntry, fixture_values: dict[str, Any], repositories: dict[str, str]
) -> dict[str, Any]:
    owner, _, name = repositories[entry.repository].partition("/")

    def lookup(key: str) -> Any:
        if key == "repo.owner":
            return owner
        if key == "repo.name":
            return name
        return fixture_values[key.removeprefix("fixture.")]

    def render(v: Any) -> Any:
        if isinstance(v, str):
            m = _PLACEHOLDER.fullmatch(v)
            if m:
                return lookup(m.group(1))
            return _PLACEHOLDER.sub(lambda mm: str(lookup(mm.group(1))), v)
        if isinstance(v, list):
            return [render(x) for x in v]
        if isinstance(v, dict):
            return {k: render(x) for k, x in v.items()}
        return v

    return render(entry.arguments)


def supplied_values(
    entry: ToolEntry, rendered: dict[str, Any], fields: list[FieldSpec]
) -> dict[str, Any]:
    kinds = {f.path: f.kind for f in fields}
    out: dict[str, Any] = {}
    for path, arg in entry.supplies.items():
        v = rendered[arg]
        if kinds.get(path) == FieldKind.COLLECTION and isinstance(v, list):
            v = frozenset(v)
        out[path] = v
    return out
