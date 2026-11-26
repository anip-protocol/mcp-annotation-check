"""Run results and the three report files: report.json, report.md, private-findings.md.

Read-only violations are private: they go only to private-findings.md. The public
reports (JSON and Markdown) neither name the tool nor show its evidence; they say
only how many results were withheld. Because the header still carries the full
tools/list, the withheld tool can be inferred by elimination, so whenever anything
is withheld both public files also carry a "do not publish" banner (ruling R18).
"""

import dataclasses
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from mcp_annotation_check.claims import Check, Claims
from mcp_annotation_check.snapshot import COMPOSITE_FIELDS, Outcome, Verdict

STATEMENT = "Findings apply to this image and configuration only."
WITHHELD = "withheld: see private-findings.md"
PRIVATE_FLAG = "Report privately to the server's maintainers first."
NOT_OBSERVED = "Changes outside the compared fields are not observed."
PUBLISH_BLOCKED = (
    "Do not publish this report until every withheld finding is fixed by the server's "
    "maintainers or 90 days have passed since it was reported to them privately, "
    "whichever comes first. A reader can infer the withheld tool from this report (the "
    "full tools/list is in the header). Findings that are already public may be posted "
    "separately."
)

_HINT_NAMES = {
    "read_only": "readOnlyHint",
    "destructive": "destructiveHint",
    "idempotent": "idempotentHint",
}
_COVERAGE_ORDER = [
    Outcome.PASS,
    Outcome.FINDING,
    Outcome.OBSERVATION,
    Outcome.SKIPPED,
    Outcome.UNJUDGED,
    Outcome.ERROR,
]


@dataclass
class ToolResult:
    tool: str
    description: str
    claims: Claims
    outcome: Outcome
    verdicts: list[Verdict]
    skip_reason: str | None
    error: str | None
    calls: list[dict]
    waited_s: float
    custom: str | None
    private: bool
    review: Literal["unreviewed"] = "unreviewed"


@dataclass
class RunHeader:
    server_info: dict
    protocol_version: str | None
    sdk_version: str
    harness_version: str
    pack_version: str
    image: str | None
    image_digest: str | None
    deployment: Literal["local", "in-memory"]
    toolsets: list[str]
    features: list[str]
    date: str
    tools_list: list[dict]
    tools_list_sha256: str
    standard_read_only_fields: list[str]
    # From pack.validate_pack and pack.pack_warnings, run against tools/list before
    # the first call. Any problem means no tool was called and no fixture created.
    pack_problems: list[str] = field(default_factory=list)
    pack_warnings: list[str] = field(default_factory=list)


def jsonable(value: Any) -> Any:
    """Convert dataclasses, enums, sets and tuples into JSON-ready values.

    Sets become sorted lists so the output is stable.
    """
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((jsonable(v) for v in value), key=_sort_key)
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def _sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def claim_text(claims: Claims) -> str:
    parts = [
        f"{hint}: {str(getattr(claims, attr)).lower()}"
        for attr, hint in _HINT_NAMES.items()
        if getattr(claims, attr) is not None
    ]
    return ", ".join(parts) or "none"


def coverage(results: list[ToolResult]) -> dict[str, int]:
    return {o.value: sum(r.outcome is o for r in results) for o in _COVERAGE_ORDER}


def write_reports(header: RunHeader, results: list[ToolResult], out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    public = [r for r in results if not r.private]
    private = [r for r in results if r.private]
    (out_dir / "report.json").write_text(_json_report(header, public, len(private)))
    (out_dir / "report.md").write_text(_markdown_report(header, public, len(private)))
    (out_dir / "private-findings.md").write_text(_private_report(header, private))


# --- JSON -------------------------------------------------------------------


def _json_report(header: RunHeader, public: list[ToolResult], withheld: int) -> str:
    data = {
        "statement": STATEMENT,
        "publish_blocked": withheld > 0,
        "publish_notice": PUBLISH_BLOCKED if withheld else None,
        "header": jsonable(header),
        "coverage": coverage(public),
        "withheld": withheld,
        "results": [jsonable(r) for r in public],
    }
    return json.dumps(data, indent=2) + "\n"


# --- Markdown ---------------------------------------------------------------


def _markdown_report(header: RunHeader, public: list[ToolResult], withheld: int) -> str:
    lines = ["# MCP annotation check report", ""]
    if withheld:
        lines += [f"> **{PUBLISH_BLOCKED}**", ""]
    lines += [STATEMENT, "", "## Run", ""]
    lines += _header_table(header)
    lines += _validation_section(header)
    lines += ["", "## Coverage", "", "| Outcome | Tools |", "|---|---|"]
    lines += [f"| {name} | {count} |" for name, count in coverage(public).items()]
    if withheld:
        lines.append(f"| withheld | {withheld} |")
    for label, outcome, attr in (
        ("Skipped", Outcome.SKIPPED, "skip_reason"),
        ("Errors", Outcome.ERROR, "error"),
    ):
        listed = [r for r in public if r.outcome is outcome]
        if listed:
            lines += ["", f"{label}:", ""]
            lines += [f"- `{r.tool}`: {_inline(getattr(r, attr) or '')}" for r in listed]
    lines += ["", "## Tools", ""]
    if withheld:
        noun = "result" if withheld == 1 else "results"
        lines += [f"- {withheld} tool {noun} {WITHHELD}", ""]
    for r in public:
        lines += _tool_section(r)
    return "\n".join(lines).rstrip() + "\n"


def _private_report(header: RunHeader, private: list[ToolResult]) -> str:
    lines = ["# Private findings", ""]
    if not private:
        return "\n".join(lines + ["none", ""])
    lines += [
        "Read-only violations. Clients may skip asking for confirmation because of this hint.",
        f"{PRIVATE_FLAG} Do not paste this file anywhere public.",
        "",
        STATEMENT,
        "",
        "## Run",
        "",
    ]
    lines += _header_table(header)
    lines += ["", "## Tools", ""]
    for r in private:
        lines += _tool_section(r)
    return "\n".join(lines).rstrip() + "\n"


def _header_table(h: RunHeader) -> list[str]:
    server = " ".join(
        str(v) for v in (h.server_info.get("name"), h.server_info.get("version")) if v
    )
    rows = [
        ("Server", server or "unknown"),
        ("Image", h.image or "none"),
        ("Image digest", h.image_digest or "none"),
        ("Deployment", h.deployment),
        ("Toolsets", ", ".join(h.toolsets) or "none"),
        ("Features", ", ".join(h.features) or "none"),
        ("Date", h.date),
        ("Protocol version", h.protocol_version or "unknown"),
        ("MCP SDK", h.sdk_version),
        ("Harness", h.harness_version),
        ("Pack version", h.pack_version),
        ("tools/list", f"{len(h.tools_list)} tools, sha256 `{h.tools_list_sha256}`"),
        ("Read-only comparison set", ", ".join(h.standard_read_only_fields) or "none"),
    ]
    return ["| Field | Value |", "|---|---|"] + [
        f"| {name} | {_cell(value)} |" for name, value in rows
    ]


def _validation_section(h: RunHeader) -> list[str]:
    if not (h.pack_problems or h.pack_warnings):
        return []
    lines = ["", "## Pack validation", ""]
    if h.pack_problems:
        lines += ["Problems (the run stopped before any fixture or call):", ""]
        lines += [f"- {_inline(p)}" for p in h.pack_problems] + [""]
    if h.pack_warnings:
        lines += ["Warnings (for a human reviewer; they do not stop the run):", ""]
        lines += [f"- {_inline(w)}" for w in h.pack_warnings] + [""]
    return lines[:-1]


def _tool_section(r: ToolResult) -> list[str]:
    lines = [f"### {r.tool}: {r.outcome.value.upper()}", ""]
    if r.private:
        lines += [f"**{PRIVATE_FLAG}**", ""]
    lines += [
        f"- Claim: {claim_text(r.claims)}",
        f"- Review: {r.review}",
    ]
    if r.custom:
        lines.append(f"- **Custom verdict:** {_inline(r.custom)}")
    if r.skip_reason:
        lines.append(f"- Skip reason: {_inline(r.skip_reason)}")
    if r.error:
        lines.append(f"- Error: {_inline(r.error)}")
    if r.verdicts:
        lines.append(f"- Settled: waited {r.waited_s:.2f}s")
    lines += ["", "Tool description:", ""]
    lines += _quote(r.description or "(none)")
    lines.append("")
    for v in r.verdicts:
        lines += _verdict_section(v, custom=r.custom is not None)
    if r.calls:
        lines += ["Calls:", ""] + _fenced(json.dumps(r.calls, indent=2), "json") + [""]
    return lines


def _verdict_section(v: Verdict, custom: bool = False) -> list[str]:
    lines = [f"#### {v.check.value}: {v.outcome.value.upper()}", ""]
    if v.schema_text:
        lines += _quote(v.schema_text) + [""]
    lines += [f"Result: {_inline(v.detail)}", "", NOT_OBSERVED, ""]
    lines += [f"Warning: {_inline(w)}" for w in v.warnings]
    if v.warnings:
        lines.append("")
    if v.diff:
        between = (
            "after the first call and after the second call"
            if v.check is Check.IDEMPOTENT
            else "before and after the call"
        )
        lines += [f"Diff {between}:", ""] + _fenced(_diff_text(v, custom), "diff") + [""]
    return lines


def _diff_text(v: Verdict, custom: bool = False) -> str:
    """Render every differing field; mark which ones count against the claim.

    Under a custom verdict an uncounted field is not necessarily additive, so the
    mark says only that the custom verdict did not count it. A verdict that is an
    ERROR judged nothing, so its fields are marked "not judged"; so is a composite
    field in a non-destructive verdict, which that check does not judge.
    """
    counted = "lost or overwritten" if v.check is Check.NON_DESTRUCTIVE else "changed"
    if v.outcome is Outcome.ERROR:
        uncounted = "not judged"
    elif custom:
        uncounted = "not counted by the custom verdict"
    else:
        uncounted = "additive"
    out: list[str] = []
    for path, (before, after) in v.diff.items():
        label = counted if path in v.changed else uncounted
        if (
            not custom
            and v.check is Check.NON_DESTRUCTIVE
            and path in COMPOSITE_FIELDS
            and path not in v.changed
        ):
            label = "not judged"
        out.append(f"@@ {path} @@ {label}")
        if isinstance(before, frozenset) or isinstance(after, frozenset):
            b, a = before or frozenset(), after or frozenset()
            for item in sorted(b | a, key=lambda x: _sort_key(jsonable(x))):
                mark = " " if item in b and item in a else ("-" if item in b else "+")
                out.append(f"{mark} {_item(item)}")
        else:
            out.append(f"- {_item(before)}")
            out.append(f"+ {_item(after)}")
    return "\n".join(out)


def _item(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(jsonable(value))


def _quote(text: str) -> list[str]:
    return [f"> {line}".rstrip() for line in text.splitlines() or [""]]


def _fenced(text: str, lang: str) -> list[str]:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return [f"{fence}{lang}", text, fence]


def _inline(text: str) -> str:
    return " ".join(str(text).split())


def _cell(text: str) -> str:
    return _inline(text).replace("|", "\\|")
