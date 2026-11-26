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
      argument_roles   map argument name -> role, one of ROLES (see below)
      fields           list of {path, kind} (kind: collection | scalar)
      supplies         map field path -> argument name supplying that field
      custom_setup, custom_verdict, custom_reason (verdict needs reason)

Content rule: no string in arguments may contain an @mention, a
cross-repository reference or a github.com URL.

Argument roles (spec Amendment 1). An enabled entry declares the role of every
argument in the tool's input schema; skipped entries need none:
  owner          an owner login; its value must be exactly "{repo.owner}"
  repository     a bare repository name; exactly "{repo.name}", and the call must
                 have exactly one owner argument to pair it with
  full_name      "owner/name"; exactly "{repo.owner}/{repo.name}"
  repository_id  a numeric repository ID, resolved to its owner through REST
  id             any other ID (issue number, comment ID, ...)
  content        free text or structured data; the only role whose value may be
                 a mapping or a list
  other          any other scalar (state, sort order, a search query, ...)
At load time every argument of an enabled entry must have a role, and owner and
repository values must be those placeholders, so they render to the pack's own
repositories by construction. `validate_pack` then checks the pack against the
server's tools/list before the first call; `pack_warnings` lists properties whose
names look like owners or repositories but are declared content, other or id.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from mcp.types import Tool

from mcp_annotation_check.argnames import looks_like_id, may_name_owner_or_repository
from mcp_annotation_check.snapshot import FieldKind, FieldSpec

REPOSITORY_ROLES = frozenset({"owner", "repository", "full_name", "repository_id"})
ROLES = frozenset({"owner", "repository", "full_name", "repository_id", "id", "content", "other"})
# The only value each of these roles may have in a pack.
_PLACEHOLDER_ROLES = {
    "owner": "{repo.owner}",
    "repository": "{repo.name}",
    "full_name": "{repo.owner}/{repo.name}",
}
_NESTED = (dict, list, tuple, set, frozenset)

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
    argument_roles: dict[str, str] = field(default_factory=dict)


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
    entry = ToolEntry(
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
        argument_roles=_argument_roles(raw.get("argument_roles"), tool),
    )
    problems = _role_problems(entry)
    if problems:
        raise PackError("; ".join(problems))
    return entry


def _argument_roles(raw: Any, tool: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PackError(f"{tool}: argument_roles must map argument names to roles")
    for name, role in raw.items():
        if not isinstance(name, str) or not isinstance(role, str):
            raise PackError(f"{tool}: argument_roles entry {name!r}: {role!r} is not name: role")
    return dict(raw)


def _role_problems(entry: ToolEntry) -> list[str]:
    """What is wrong with an entry's roles, on their own (no tools/list needed)."""
    tool, roles = entry.tool, entry.argument_roles
    problems = [
        f"{tool}: argument {name!r} has unknown role {role!r} (roles: {', '.join(sorted(ROLES))})"
        for name, role in roles.items()
        if role not in ROLES
    ]
    if entry.status != "enabled":
        return problems
    owners = repositories = 0
    for name, value in entry.arguments.items():
        role = roles.get(name)
        if role is None:
            problems.append(f"{tool}: argument {name!r} has no declared role")
            continue
        owners += role == "owner"
        repositories += role == "repository"
        expected = _PLACEHOLDER_ROLES.get(role)
        if expected is not None and value != expected:
            problems.append(
                f"{tool}: {role} argument {name!r} must be exactly {expected!r}, not {value!r}"
            )
        elif role != "content" and isinstance(value, _NESTED):
            problems.append(
                f"{tool}: argument {name!r} has a nested value; only content arguments may"
            )
    if repositories and owners != 1:
        problems.append(
            f"{tool}: a repository argument needs exactly one owner argument to pair with, "
            f"and the entry has {owners}"
        )
    return problems


def _schema_properties(tool: Tool) -> dict[str, Any] | None:
    schema = tool.input_schema
    if not isinstance(schema, dict):
        return None
    properties = schema.get("properties", {})
    return properties if isinstance(properties, dict) else None


def validate_pack(pack: Pack, tools: list[Tool]) -> list[str]:
    """Problems with the pack against the server's tools/list; empty means valid.

    Checked for every enabled entry (skipped entries are not validated): its role
    rules (as at load time, so entries built in code are covered too), that the tool
    is listed, that every input-schema property has a declared role and every role
    names a property, that it names a repository unless it is on `id_only_write_tools`, and, for ID-only write tools, that nothing that looks like an
    ID is declared anything but `id` or `repository_id`. Warnings are separate: see
    `pack_warnings`.
    """
    listed = {t.name: t for t in tools}
    id_only = set(pack.id_only_write_tools)
    problems: list[str] = []
    for name, entry in pack.entries.items():
        if entry.status != "enabled":
            continue
        problems += _role_problems(entry)
        if name not in listed:
            problems.append(f"{name}: not in the server's tools/list")
            continue
        properties = _schema_properties(listed[name])
        if properties is None:
            problems.append(f"{name}: the input schema's properties are not a mapping")
            continue
        roles = entry.argument_roles
        problems += [
            f"{name}: input-schema property {p!r} has no declared role"
            for p in properties
            if p not in roles
        ]
        problems += [
            f"{name}: role declared for {r!r}, which is not an input-schema property"
            for r in roles
            if r not in properties
        ]
        if name not in id_only and not any(r in REPOSITORY_ROLES for r in roles.values()):
            problems.append(
                f"{name}: no argument names a repository (owner, repository, full_name or "
                "repository_id role), so the tool must be on id_only_write_tools"
            )
        if name in id_only:
            problems += [
                f"{name}: {p!r} looks like an ID of an ID-only write tool but is declared "
                f"{roles[p]!r}"
                for p in properties
                if p in roles and roles[p] not in ("id", "repository_id") and looks_like_id(p)
            ]
    return problems


def pack_warnings(pack: Pack) -> list[str]:
    """Warnings for a human reviewer, each starting "warning: "; never problems.

    A declared property whose name looks like it may name an owner or repository
    (the name stems the safety checks used before roles) but whose role is
    `content`, `other` or `id` is listed, so a mis-declared owner is seen. Once
    `validate_pack` passes, the declared roles cover every input-schema property.
    """
    warnings: list[str] = []
    for name, entry in pack.entries.items():
        if entry.status != "enabled":
            continue
        for prop, role in entry.argument_roles.items():
            if role in ("content", "other", "id") and may_name_owner_or_repository(prop):
                warnings.append(
                    f"warning: {name}: property {prop!r} may name an owner or repository "
                    f"but is declared {role!r}; check it by hand"
                )
    return warnings


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
