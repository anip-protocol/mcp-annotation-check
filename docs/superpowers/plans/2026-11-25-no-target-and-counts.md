# No-target tools and independent counts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let tools with no repository argument by design (`get_me`, query-only search) be enabled through an explicit pack declaration, catch ID-only tools without an ID at validation time, and count each kind of verdict independently in the coverage summary.

**Architecture:** `pack.py` gains a `no_target_tools` list and two validation rules; `github/safety.py` re-checks the declaration per call; `report.py` gains per-kind verdict counts.

**Tech Stack:** unchanged.

**Spec:** `docs/superpowers/specs/2026-11-25-mcp-annotation-check-design.md` ("Amendment 1" wins; Goals: version 1 covers every read-only tool).

## Global Constraints

- The declaration never depends on a tool's annotations: a tool is "no target" because the pack says so, never because it claims `readOnlyHint`.
- Any validation problem stops the run before any fixture is created or tool called (exit code 2, as today).
- Never use a real GitHub token in tests. Never run docker or `live` tests. The token never appears in argv, logs or reports.
- The whole suite must pass; the self-test outcomes must not change.

## Review Focus

1. A tool on `no_target_tools` whose schema has an owner/repository/ID argument must fail validation, not run. Test in Task 1.
2. A tool on `id_only_write_tools` with no `id`/`repository_id` role must fail validation before the first call (today it validates, then the first call is refused and the run stops). Test in Task 1.
3. A FINDING or OBSERVATION hidden under a more severe headline outcome must still be counted. Test in Task 2.

---

### Task 1: `no_target_tools`

**Files:**
- Modify: `src/mcp_annotation_check/pack.py` (Pack, loading, `validate_pack`, module docstring), `src/mcp_annotation_check/github/safety.py` (per-call check, docstring), `src/mcp_annotation_check/report.py` + `runner.py` (header lists no-target tools), `README.md`, `docs/verification.md` (replace the "Before writing `packs/github.yaml`" section with one line saying it is done)
- Test: `tests/test_pack.py`, `tests/github/test_safety.py`, `tests/test_report.py`

**Interfaces:**
- Produces: `Pack.no_target_tools: list[str]` (YAML key `no_target_tools`, default empty); `RunHeader.no_target_tools: list[str]`.

- [ ] **Step 1: Failing tests.**
  - `validate_pack`: a tool on `no_target_tools` with only `content`/`other` roles is valid and satisfies the "names a repository" rule; one with any `owner`, `repository`, `full_name`, `repository_id` or `id` role is a problem (`test_no_target_tool_with_repository_role_is_a_problem`); a tool on both `no_target_tools` and `id_only_write_tools` is a problem; a tool on `id_only_write_tools` with no `id` or `repository_id` role is a problem (`test_id_only_tool_without_id_fails_validation`); a name on `no_target_tools` with no enabled entry is a problem.
  - safety per call: a no-target tool whose rendered arguments include a key whose role is not `content`/`other` is refused; a no-target tool with only content/other arguments passes without any REST request.
  - report: header shows the no-target tools in report.json and report.md.
- [ ] **Step 2: Run; expected FAIL.**
- [ ] **Step 3: Implement.** Also add pack load errors for unknown names only if consistent with how `id_only_write_tools` is handled; say which in the report. Leave `packs/fake.yaml` valid (add a no-target tool to the fake server only if a test needs a real MCP round trip).
- [ ] **Step 4: Run the full suite and the self-test; expected PASS, outcomes unchanged.**
- [ ] **Step 5: Commit** `feat(pack): no_target_tools — tools with no repository by declaration; ID-only tools without an ID fail validation`.

### Task 2: Count each kind of verdict independently

**Files:**
- Modify: `src/mcp_annotation_check/report.py`, `src/mcp_annotation_check/cli.py` (`_summary`, only if it prints counts), `README.md`
- Test: `tests/test_report.py`

**Interfaces:**
- Produces: `verdict_counts(results: list[ToolResult]) -> dict[str, int]` — for each of `finding`, `observation`, `unjudged`, `pass`, the number of public tools with at least one verdict of that kind. report.json gains `"verdict_counts"`; report.md gains a table "Tools with at least one verdict of each kind" right after the coverage table, with one sentence saying a tool can appear in several rows.

- [ ] **Step 1: Failing test** `test_observation_under_unjudged_is_counted`: a tool with verdicts [UNJUDGED, OBSERVATION] counts 1 under `unjudged` in `coverage` and 1 under `observation` in `verdict_counts`; a tool with [FINDING, PASS] counts in both `finding` and `pass`; withheld (private) tools are not counted in the public file.
- [ ] **Step 2: Run; expected FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite; expected PASS.**
- [ ] **Step 5: Commit** `feat(report): count each kind of verdict independently of the headline outcome`.
