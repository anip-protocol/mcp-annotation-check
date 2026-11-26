"""packs/github.yaml against the committed v2.3.0 tools/list (tests/data/tools-v2.3.0.json).

Offline: no token, no Docker, no network.
"""

import json
from pathlib import Path

import pytest
from mcp.types import Tool

from mcp_annotation_check.claims import applicable_checks, claims_of
from mcp_annotation_check.github.safety import make_before_call
from mcp_annotation_check.pack import load_pack, render_arguments, validate_pack

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "packs" / "github.yaml"
TOOLS = Path(__file__).resolve().parent / "data" / "tools-v2.3.0.json"

# Read-only tools that cannot be checked with this token.
EXCLUDED_READ_ONLY = {"get_teams", "get_team_members"}
# Tools that act outside the two test repositories, whatever they claim.
EXCLUDED_OUTSIDE = {
    "assign_copilot_to_issue",
    "request_copilot_review",
    "create_repository",
    "fork_repository",
}
# The only destructiveHint: false tools enabled in round 1.
ENABLED_NON_DESTRUCTIVE = {
    "update_issue_labels",
    "add_issue_reaction",
    "update_issue_title",
    "update_issue_assignees",
    "update_issue_body",
    "update_issue_state",
}


@pytest.fixture(scope="module")
def pack():
    return load_pack(PACK)


@pytest.fixture(scope="module")
def tools() -> list[Tool]:
    raw = json.loads(TOOLS.read_text())
    return [Tool.model_validate(t) for t in raw["tools"]]


def test_data_file_has_the_62_shakedown_tools(tools):
    assert len(tools) == 62
    assert len({t.name for t in tools}) == 62


def test_every_listed_tool_has_entry_or_reason(pack, tools):
    listed = {t.name for t in tools}
    for tool in tools:
        if applicable_checks(claims_of(tool)):
            assert tool.name in pack.entries, f"{tool.name}: testable claim but no pack entry"
    for name, entry in pack.entries.items():
        assert name in listed, f"{name}: pack entry for a tool v2.3.0 does not list"
        if entry.status == "skipped":
            assert entry.skip_reason, f"{name}: skipped without a reason"


def test_pack_validates_against_v2_3_0(pack, tools):
    assert validate_pack(pack, tools) == []


def test_no_enabled_entry_in_excluded_categories(pack, tools):
    enabled = {n for n, e in pack.entries.items() if e.status == "enabled"}
    assert not enabled & (EXCLUDED_READ_ONLY | EXCLUDED_OUTSIDE)
    non_destructive = {
        t.name
        for t in tools
        if claims_of(t).read_only is not True and claims_of(t).destructive is False
    }
    assert enabled & non_destructive == ENABLED_NON_DESTRUCTIVE


def test_every_read_only_tool_is_enabled_on_the_read_repository(pack, tools):
    read_only = {t.name for t in tools if claims_of(t).read_only is True}
    assert len(read_only) == 27
    for name in read_only - EXCLUDED_READ_ONLY:
        entry = pack.entries.get(name)
        assert entry is not None and entry.status == "enabled", name
        assert entry.repository == "read", name
        assert entry.fixture is None, name


def test_read_entries_render_from_read_fixtures(pack):
    # Every {fixture.<key>} of a read entry, and every issue/pr field of the standard
    # read-only fields, must find its value in read_fixtures.
    fields = {f.path.split(".")[0] for f in pack.standard_read_only_fields}
    if "issue" in fields:
        assert "issue_number" in pack.read_fixtures
    if "pr" in fields:
        assert "pr_number" in pack.read_fixtures
    for entry in pack.entries.values():
        if entry.status == "enabled" and entry.repository == "read":
            render_arguments(entry, pack.read_fixtures, pack.repositories)


class _NoRest:
    """Any REST use fails the test: no enabled entry needs a lookup before its call."""

    def __getattr__(self, name):
        raise AssertionError(f"before_call used REST ({name})")


async def test_rendered_arguments_pass_the_call_safety_checks(pack):
    # The checks the live run makes before each call, on what this pack renders. A
    # write fixture's issue number is only known at run time; 1 stands in for it.
    before_call = make_before_call(_NoRest(), pack)
    for name, entry in pack.entries.items():
        if entry.status != "enabled":
            continue
        values = pack.read_fixtures if entry.repository == "read" else {"issue_number": 1}
        await before_call(name, render_arguments(entry, values, pack.repositories))
