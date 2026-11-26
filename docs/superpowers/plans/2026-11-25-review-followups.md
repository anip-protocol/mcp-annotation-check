# Review follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Act on the post-build review: prove the label case is judged on GitHub's real shape, add the UNJUDGED outcome with findings ranked first, replace name-based owner detection with declared argument roles validated before the first call, and add a no-write `shakedown` command.

**Architecture:** Changes stay inside the existing modules: `snapshot.py` (outcome), `runner.py` (ranking, partial judging, pre-run validation), `report.py` (counts), `pack.py` (roles, validation), `github/safety.py` (per-call checks by role), `cli.py` (shakedown).

**Tech Stack:** unchanged (Python ≥ 3.12, `mcp` 2.x, httpx, pyyaml, pytest).

**Spec:** `docs/superpowers/specs/2026-11-25-mcp-annotation-check-design.md`, especially **Amendment 1** at its end, which wins over earlier sections.

## Global Constraints

- Never use a real GitHub token in tests. Never run docker or `live` tests.
- The token comes only from `MCP_ANNOTATION_CHECK_GITHUB_TOKEN` and never appears in argv, logs or reports.
- Outcome order, most severe first: FINDING, ERROR, UNJUDGED, OBSERVATION, PASS, SKIPPED.
- `Outcome.UNJUDGED` has the value `"unjudged"`.
- Roles: `owner`, `repository`, `full_name`, `repository_id`, `id`, `content`, `other`.
- Owner/repository values in a pack may only be `{repo.owner}`, `{repo.name}`, `{repo.owner}/{repo.name}` (full_name).
- Any pre-run validation problem stops the run before any fixture is created or tool called.
- The whole suite (`uv run pytest`) must pass; `mcp-annotation-check self-test` must still give the expected outcome for every fake tool.

## Review Focus

1. A tool with a real FINDING on one check and an UNJUDGED or ERROR on another must report FINDING and appear in the finding count. Test in Task 2.
2. A server whose `tools/list` gains an argument the pack didn't declare must be stopped before any write. Test in Task 3 (validation) and Task 3 (per-call refusal for an undeclared key).
3. A pack that hard-codes an owner (`owner: someone-else`) instead of the placeholder must fail validation. Test in Task 3.
4. `shakedown` must never call `tools/call` and never create a fixture, even when validation passes. Test in Task 4.
5. The label reproduction must produce FINDING through the real GitHub reader, not only the fake. Test in Task 1.

---

### Task 1: Prove the label case on GitHub's real shape

**Files:**
- Test: `tests/github/test_label_case.py` (new)

**Interfaces:**
- Consumes: `GitHubReader(rest, repositories)`, `GitHubRest(token, transport=httpx.MockTransport(...))`, `run(...)`, `Pack`, `ToolEntry`, `MCPServer` with `ToolAnnotations` (see `tests/github/test_reader.py` for the existing pattern).

- [ ] **Step 1: Write the tests.** An in-memory "GitHub" (a dict) behind `httpx.MockTransport` serves issues and labels in GitHub's real REST shape: each label object has `id`, `node_id`, `url`, `name`, `color`, `default`, `description`; the issue has `number`, `title`, `body`, `state`, `labels`, `assignees` (objects with `login`), `user`, `updated_at`. It must support what `GitHubReader.create_fixture("issue_with_labels")`, `snapshot` and `cleanup` call. An in-process `MCPServer` exposes `update_issue_labels(owner, repo, issue_number, labels)` with `ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)` that **replaces** the issue's labels in that same dict, and `add_issue_labels` with the same annotations that **adds**. The pack mirrors the spec's first entry: fixture `issue_with_labels`, arguments `owner: "{repo.owner}"`, `repo: "{repo.name}"`, `issue_number: "{fixture.issue_number}"` (use the key the reader's fixture actually returns), `labels: ["a"]`; fields `issue.labels` (collection), `issue.assignees` (collection), `issue.title`, `issue.body`, `issue.state` (scalar); `supplies: {issue.labels: labels}`.
  - `test_update_issue_labels_replacing_is_a_finding`: outcome FINDING for the non-destructive check; `changed["issue.labels"] == (frozenset({"c","d"}), frozenset({"a"}))`.
  - `test_add_issue_labels_is_a_pass`: non-destructive PASS.
  - `test_issue_labels_is_not_composite`: `"issue.labels" not in COMPOSITE_FIELDS`.
- [ ] **Step 2: Run** `uv run pytest tests/github/test_label_case.py -v`. Expected: PASS (this task documents current behaviour; if it fails, stop and report — it means milestone 1 is broken).
- [ ] **Step 3: Commit** `test(github): the label reproduction gives a finding on GitHub's real response shape`.

---

### Task 2: UNJUDGED outcome and findings ranked first

**Files:**
- Modify: `src/mcp_annotation_check/snapshot.py` (Outcome), `src/mcp_annotation_check/runner.py` (`_SEVERITY`, `_judge`, R19 logic), `src/mcp_annotation_check/report.py` (coverage, Markdown wording), `src/mcp_annotation_check/cli.py` (summary, self-test expectations if they list outcomes), `README.md` (outcome list)
- Test: `tests/test_runner.py`, `tests/test_report.py`

**Interfaces:**
- Produces: `Outcome.UNJUDGED = "unjudged"`; `_SEVERITY` = SKIPPED 0, PASS 1, OBSERVATION 2, UNJUDGED 3, ERROR 4, FINDING 5.

- [ ] **Step 1: Write failing tests** in `tests/test_runner.py` using the fake server/reader (add fake tools or reader fields if needed; keep the self-test's eight tools and their expected outcomes unchanged, or update the expectations consciously and say so in the report):
  - `test_composite_field_alone_is_unjudged_not_error`: a non-destructive entry whose fields include a composite field and nothing is lost → tool outcome UNJUDGED; verdict detail names the composite field; the run's errors list does not contain it.
  - `test_finding_on_plain_field_wins_over_composite`: same entry but a plain collection field loses an element → non-destructive verdict FINDING, detail also says which composite fields were not judged.
  - `test_finding_outranks_error`: one check FINDING, the call returned `isError` → tool outcome FINDING (the error text is still recorded).
  - `test_unjudged_counts_in_coverage` (test_report.py): `coverage()` includes an `unjudged` count; a tool with FINDING + UNJUDGED is counted under findings.
- [ ] **Step 2: Run** them; expected FAIL.
- [ ] **Step 3: Implement.** In `_judge` for NON_DESTRUCTIVE: split fields into composite and plain; judge plain with `judge_non_destructive`; if that is FINDING, return it with the composite names appended to `detail` ("; not judged yet (composite elements): …") and `diff` over all fields; otherwise return `Verdict(check, Outcome.UNJUDGED, detail, changed=<plain verdict's changed>, warnings=<plain verdict's warnings>, schema_text=…, diff=<all fields>)` where detail names the composite fields and includes the plain verdict's detail. Do not append to `self.errors`. If there are no composite fields, behaviour is unchanged. R19 ("call failed and no FINDING/OBSERVATION verdict → ERROR") stays as is.
- [ ] **Step 4: Run** `uv run pytest` and `uv run mcp-annotation-check self-test --out <tmp>`; expected all pass, self-test outcomes as before.
- [ ] **Step 5: Commit** `feat: UNJUDGED outcome for composite fields; a finding outranks every other outcome`.

---

### Task 3: Declared argument roles, validated before the first call

**Files:**
- Modify: `src/mcp_annotation_check/pack.py` (ToolEntry, loading, new `validate_pack`), `src/mcp_annotation_check/runner.py` (call `validate_pack` after `tools/list`, before any fixture), `src/mcp_annotation_check/github/safety.py` (per-call checks by role; module docstring), `packs/fake.yaml`, `README.md` (pack format)
- Test: `tests/test_pack.py`, `tests/test_runner.py`, `tests/github/test_safety.py`

**Interfaces:**
- Produces:
  - `ToolEntry.argument_roles: dict[str, str]` (YAML key `argument_roles`).
  - `ROLES = frozenset({"owner","repository","full_name","repository_id","id","content","other"})` in `pack.py`.
  - `validate_pack(pack: Pack, tools: list[mcp.types.Tool]) -> list[str]` — returns problems; empty means valid.
  - Runner: when `validate_pack` returns problems, no tool is called and no fixture is created; every enabled tool's result is SKIPPED with reason `"pack validation failed: <n> problem(s)"`, the problems are recorded in the run's errors and the report header, and reports are still written.
- Consumes: existing `check_content`, `_ascii_name`, `_on_allowlist`, the ID resolver tables and `_walk` in `safety.py`.

- [ ] **Step 1: Write failing tests.**
  - test_pack.py — load-time: unknown role → PackError; an enabled entry with an `arguments` key that has no role → PackError; a role on an owner/repository/full_name argument whose `arguments` value is not exactly its placeholder (`{repo.owner}`, `{repo.name}`, `{repo.owner}/{repo.name}`) → PackError (`test_hard_coded_owner_refused`).
  - test_pack.py — `validate_pack`: missing tool; an input-schema property with no role (`test_undeclared_schema_property_is_a_problem`); a role naming a property not in the schema; a clean pack returns `[]`. Skipped entries are not validated.
  - test_runner.py — `test_validation_problem_stops_before_any_fixture`: the reader records zero `create_fixture` calls and the client zero `call_tool` calls; results all SKIPPED with the reason above; reports written.
  - test_safety.py — per call: an argument key not in the entry's roles is refused (`SafetyRefusal`); `owner` role value not allowlisted → refused; non-ASCII owner value → refused; `repository` role pairs with the single `owner`-role argument and the pair must equal one of `pack.repositories` values; `full_name` must be "owner/name" and match; `repository_id` resolved through `/repositories/{id}` and owner allowlisted; `content` and string `other` values pass `check_content`; nested dict/list values are allowed only for `content` and go through the existing nested key walk; `id`-role arguments of `id_only_write_tools` are resolved as today. Keep the existing tests that still apply; delete or rewrite those that tested top-level name-based detection, and list them in the report.
- [ ] **Step 2: Run**; expected FAIL.
- [ ] **Step 3: Implement.** `before_call(tool, arguments)` looks up `pack.entries[tool].argument_roles`. Top-level name-based detection (`_OWNER_KEYS`, `_OWNER_STEMS`, …) no longer decides anything at the top level; keep it for nested levels inside `content` values. `validate_pack` also returns a *warning* (prefix `"warning: "`, not counted as a problem — return warnings in a second list or a small dataclass, your call, document it) when a property whose name matches the old owner/repo stems is declared `content` or `other`, so a human reviewer sees it. Update `packs/fake.yaml` with roles for every fake tool's input schema. Update the `safety.py` docstring to describe the role-based checks.
- [ ] **Step 4: Run** `uv run pytest` and the self-test; expected all pass.
- [ ] **Step 5: Commit** `feat(safety): pack entries declare every argument's role; the pack is validated against tools/list before the first call`.

---

### Task 4: `shakedown` command

**Files:**
- Modify: `src/mcp_annotation_check/cli.py`, `docs/verification.md` (make shakedown the first live step, read-only token first), `README.md`
- Test: `tests/test_cli.py` (new or existing CLI test file)

**Interfaces:**
- Consumes: `preflight`, `server_params`, `image_digest`, `list_all_tools`, `validate_pack` (Task 3), `GitHubReader.snapshot`.
- Produces: `mcp-annotation-check shakedown --pack P --login L --image I --toolsets T [--features F] --out DIR` (same option names as `run`). Steps: preflight → start server → `tools/list` → `validate_pack` → one `reader.snapshot(pack.standard_read_only_fields, <read fixture of kind none for the read repository>)`. Writes `DIR/shakedown.json` with: image, digest, serverInfo, protocol version, tools/list hash and tool names, validation problems and warnings, the snapshot's field names (not values), and pass/fail per step. Exit 0 only when every step passed and there are no validation problems.

- [ ] **Step 1: Write failing tests** with an in-memory MCP server and a mock-transport `GitHubRest` (factor the CLI so the shakedown core takes a client, rest and reader; the argparse layer wires docker): `test_shakedown_never_calls_tools_or_creates_fixtures` (spy client/reader: zero `call_tool`, zero `create_fixture`, zero non-GET REST requests), `test_shakedown_reports_validation_problems_and_exits_nonzero`, `test_shakedown_json_has_no_token` (token string absent from the file).
- [ ] **Step 2: Run**; expected FAIL.
- [ ] **Step 3: Implement**, reusing `run`'s redaction and failure handling.
- [ ] **Step 4: Run** `uv run pytest`; expected PASS.
- [ ] **Step 5: Commit** `feat(cli): shakedown — preflight, tools/list, pack validation and one snapshot, with no tool calls`.
