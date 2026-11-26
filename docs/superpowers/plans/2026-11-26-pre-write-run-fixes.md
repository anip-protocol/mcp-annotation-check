# Pre-write-run fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close what an external read of the safety layer found and what the first live shakedown found, before the first run that writes to GitHub.

**Architecture:** Changes in `pack.py` (ID placeholders), `github/rest.py` (write guard), `github/safety.py` (nested pairs), `github/reader.py` (reaction set, empty repository), `cli.py` (image pull, annotations in shakedown.json), `packs/github.yaml`, `docs/verification.md`.

**Tech Stack:** unchanged.

**Spec:** `docs/superpowers/specs/2026-11-25-mcp-annotation-check-design.md` (Amendment 1 wins).

## Global Constraints

- Never use a real GitHub token in tests. Never run docker or `live` tests (the image-pull logic is tested with a fake `subprocess` runner).
- The token never appears in argv, logs or reports.
- Any pack problem stops the run before any fixture or call (exit 2).
- The whole suite and the self-test pass; self-test outcomes unchanged.

## Review Focus

1. A pack `id` argument with a literal value (`comment_id: 12345`) must fail at load. Test in Task 1.
2. A harness REST write (POST/PUT/PATCH/DELETE) to any path outside `/repos/<pack repository>/...` must be refused before the request is sent. Test in Task 1.
3. The reaction control must PASS when a reaction is added and FINDING when one is removed. Test in Task 2.

---

### Task 1: Safety — ID placeholders, REST write guard, nested pairs

**Files:**
- Modify: `src/mcp_annotation_check/pack.py`, `src/mcp_annotation_check/github/rest.py`, `src/mcp_annotation_check/github/safety.py` (and its docstring), the CLI/runner wiring that constructs `GitHubRest` for `run`, `README.md`
- Test: `tests/test_pack.py`, `tests/github/test_rest.py` (new or existing), `tests/github/test_safety.py`

**Interfaces:**
- Pack load: an enabled entry's argument with role `id` must have a value that is exactly one `{fixture.<key>}` placeholder (the whole string); anything else is a PackError. Arguments with role `id` that are not present in `arguments` are fine (only declared values are checked). `repository_id` values follow the same rule.
- `GitHubRest(token, ..., write_repositories: Collection[str] | None = None)`: when given, any non-GET request whose path does not start with `/repos/<owner>/<name>/` for one of those repositories (compared case-insensitively, ASCII) raises `GitHubError`-like refusal (a new `RestRefused(Exception)` is fine — say which) before sending. `run` constructs its client with the pack's repositories; the shakedown client gets an empty collection (refuses every write).
- Nested pairs: inside `content` values, an owner/repository pair found by the nested walk must be one of the pack's repositories, exactly as top-level pairs are; a nested owner alone still only needs the allowlist.

- [ ] **Step 1: Failing tests:** `test_literal_id_value_refused_at_load`, `test_fixture_placeholder_id_accepted`; `test_rest_refuses_write_outside_pack_repositories` (mock transport records zero requests), `test_rest_allows_write_inside`, `test_rest_get_unrestricted`, `test_shakedown_client_refuses_all_writes`; `test_nested_pair_outside_pack_repositories_refused`.
- [ ] **Step 2: Run; expected FAIL.**
- [ ] **Step 3: Implement.** Update `packs/fake.yaml` / test packs if any use literal IDs.
- [ ] **Step 4: Full suite + self-test; expected PASS, outcomes unchanged.**
- [ ] **Step 5: Commit** `fix(safety): pack IDs must be fixture placeholders; REST writes limited to the pack's repositories; nested pairs checked like top-level ones`.

### Task 2: Reader, CLI and pack — from the live shakedown

**Files:**
- Modify: `src/mcp_annotation_check/github/reader.py`, `src/mcp_annotation_check/github/launcher.py` and/or `cli.py`, `packs/github.yaml`, `docs/verification.md`, `README.md`
- Test: `tests/github/test_reader.py`, `tests/github/test_label_case.py`, `tests/test_shakedown.py`, `tests/github/test_launcher.py`

**Interfaces:**
- New reader field `issue.reaction_set` (collection): frozenset of `(login, content)` from `GET /repos/{repo}/issues/{n}/reactions`. `issue.reactions` (the count) stays for read-only snapshots.
- Empty repository: `repo.refs` returns an empty frozenset when GitHub answers 409 for the refs request (GitHub's "Git Repository is empty"); any other error still raises.
- Image: before `image_digest`, if `docker image inspect` fails, run `docker pull <image>` once (DOCKER_* env passed through as today, never the token), then inspect again; a failed pull raises with its stderr, redacted.
- `shakedown.json` gains `"tool_annotations": {name: {readOnlyHint, destructiveHint, idempotentHint, openWorldHint}}` (only keys the server sent) and `"claim_counts"`: number of tools with readOnlyHint true, destructiveHint false (not read-only), idempotentHint true (not read-only).
- `packs/github.yaml`: the `add_issue_reaction` entry compares `issue.reaction_set` in addition to the issue fields (do not add `issue.reactions`, the count: 0→1 is a scalar change and would read as a loss).
- `docs/verification.md`: record the live shakedown results (four runs on 2026-11-26: image not pulled; stale ghcr login, fixed by `docker logout ghcr.io`; pack repository name; empty repository; then passed with both tokens; 62 tools; protocol 2026-07-28; digest sha256:f8ee4dedc7d5c8cb32854ab91cc92a31c55a8a5510708cf8742e9f9427588ca6; `/user/orgs` returned `[]` although the account owns the organization, so preflight step 4 is token-filtered and proves nothing beyond step 3).

- [ ] **Step 1: Failing tests:** `test_reaction_set_snapshot` (real REST shape: list of objects with `user.login`, `content`); in test_label_case, a reaction tool that adds → PASS on `issue.reaction_set`, one that removes an existing reaction → FINDING; `test_refs_empty_repository_409_is_empty`; `test_refs_other_error_raises`; `test_image_pulled_when_missing` and `test_failed_pull_raises_redacted` (fake runner); `test_shakedown_json_records_annotations_and_claim_counts`.
- [ ] **Step 2: Run; expected FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Full suite + self-test; expected PASS.** Also re-validate `packs/github.yaml` loads.
- [ ] **Step 5: Commit** `fix: reaction set field, empty repositories, image pull, annotations in shakedown.json`.
