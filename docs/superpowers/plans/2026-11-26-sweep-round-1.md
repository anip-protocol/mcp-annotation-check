# Sweep round 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the deferred hardening items, then extend `packs/github.yaml` to every testable read-only tool plus `update_issue_body` and `update_issue_state`, with every other listed tool skipped with a reason.

**Architecture:** Task 1 changes `pack.py`, `github/rest.py`, `github/launcher.py`. Task 2 adds pack entries, committed tool-list test data and an offline completeness test.

**Tech Stack:** unchanged.

**Spec:** `docs/superpowers/specs/2026-11-25-mcp-annotation-check-design.md` (Amendment 1 wins).

## Global Constraints

- Never use a real GitHub token in tests. Never run docker or `live` tests.
- The token never appears in argv, logs, reports, or (new) the environment of `docker image inspect` / `docker pull`.
- Any pack problem stops the run before any fixture or call (exit 2).
- Full suite and self-test pass; self-test outcomes unchanged; `packs/github.yaml` loads and validates against the committed v2.3.0 tool list with no problems.

## Review Focus

1. A read entry (`repository: read`) with a fixture other than `none`, or with `custom_setup`, must fail at load. Test in Task 1.
2. An argument whose name looks like an ID (`looks_like_id`) declared `other` or `content` must fail at load. Test in Task 1.
3. Every tool in the committed v2.3.0 tools/list must have a pack entry, and every skipped entry a reason. Test in Task 2.

---

### Task 1: Deferred hardening

**Files:** `src/mcp_annotation_check/pack.py`, `src/mcp_annotation_check/github/rest.py`, `src/mcp_annotation_check/github/launcher.py`, `README.md`; tests in `tests/test_pack.py`, `tests/github/test_rest.py`, `tests/github/test_launcher.py`.

- Load errors: (a) an enabled entry with `repository: read` and `fixture` not in (None, "none"), or with `custom_setup` → PackError; (b) an enabled entry argument whose name satisfies `looks_like_id` with role `other` or `content` → PackError.
- REST write guard: in addition to the repository check, a write's path after `/repos/<owner>/<name>/` must start with one of `issues`, `labels`, `git/refs`, `contents/`, `pulls`, `milestones`; anything else (e.g. `forks`, `transfer`, `generate`, `hooks`, `collaborators`, `keys`) → `RestRefused` before sending.
- Launcher: `docker image inspect` and `docker pull` run with an explicit env of `PATH`, `HOME` and `DOCKER_*` only (never `MCP_ANNOTATION_CHECK_GITHUB_TOKEN`); fix the docstring.
- Wording: `pack.py` comment near `_FIXTURE_ID` and the README sentence say IDs come from a fixture or the pack's `read_fixtures`, not "an object the harness created".
- Tests: `test_read_entry_with_fixture_refused`, `test_read_entry_with_custom_setup_refused`, `test_id_like_name_declared_other_refused` (parametrize other/content), `test_write_outside_allowed_prefixes_refused` (zero requests recorded), `test_docker_subprocesses_get_no_token` (fake runner asserts env lacks the token var).
- Commit: `fix: load-time checks for read fixtures and ID-like names; write-path prefixes; docker env without the token`.

### Task 2: Sweep pack, round 1

**Files:** `packs/github.yaml`, `tests/data/tools-v2.3.0.json` (new; from the live shakedown), `tests/test_github_pack.py` (new), `docs/verification.md`.

- `tests/data/tools-v2.3.0.json`: the 62 tools' `name`, `inputSchema` and `annotations` at v2.3.0, built from `out/shakedown-rw/shakedown.json` tool names and the `pkg/github/__toolsnaps__/<name>.snap` files at tag v2.3.0 (`gh api` GET, public repo). Record in the file header how it was built.
- `read_fixtures` (values given by the controller in the dispatch): `issue_number`, `pr_number`, `label_name: fixture-label`, `tag: v0.0.1`, `ref: v0.0.1`, `path: README.md`.
- `standard_read_only_fields`: `repo.labels`, `repo.refs`, `repo.issues` (collections), `issue.comments` (collection), `issue.reactions` (scalar), `pr.state` (scalar) — on the read repository's fixed issue and pull request.
- Enabled read-only entries (`repository: read`, no fixture): every tool claiming `readOnlyHint: true` except `get_teams` and `get_team_members`. Owner/repo args use placeholders; IDs use `{fixture.<key>}` from read_fixtures; `issue_read`, `pull_request_read` use `method: get`; `ui_get` uses `method: labels`; search queries are scoped with `repo:mcp-annotation-check-lab/read-fixtures` where the tool searches repositories' content, and `get_me`, `search_repositories`, `search_users`, `search_commits` go on `no_target_tools` unless their schema has owner/repo arguments. Optional arguments are declared but not passed unless needed.
- Enabled write entries: `update_issue_body` (fixture `plain_issue`, supplies `issue.body`, expected OBSERVATION) and `update_issue_state` (fixture `plain_issue`, `state: closed`, supplies `issue.state`, expected OBSERVATION).
- Skipped, each with a reason: `get_teams`, `get_team_members` ("needs organization permissions the token does not have"); `assign_copilot_to_issue`, `request_copilot_review` ("starts outside work"); `create_repository`, `fork_repository` ("acts on the account"); the remaining `destructiveHint: false` tools ("round 2: needs a new compared field"); tools with no testable claim may be left without entries (the runner skips them as "no explicit claim") — the test must treat those as covered.
- `tests/test_github_pack.py`: `test_every_listed_tool_has_entry_or_reason` (every tool in the data file either has a pack entry, or has no testable claim), `test_pack_validates_against_v2_3_0` (validate_pack problems == []), `test_no_enabled_entry_in_excluded_categories`.
- `docs/verification.md`: a short "Sweep round 1" section listing the read fixtures the owner created.
- Commit: `feat(packs): sweep round 1 — every testable read-only tool, update_issue_body and update_issue_state`.
