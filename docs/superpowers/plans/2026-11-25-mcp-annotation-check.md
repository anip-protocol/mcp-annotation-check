# mcp-annotation-check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a harness that calls an MCP server's tools against known fixtures and reports whether each tool behaves as its `readOnlyHint`, `destructiveHint` and `idempotentHint` claim. The first target is GitHub's MCP server.

**Architecture:** The rules are pure functions over before-and-after snapshots. A pack (YAML) describes one server's tools. A runner drives each tool serially through an MCP `Client`: fixture, snapshot, call, settle, snapshot, judge, cleanup. A state reader produces snapshots through a channel other than the server under test: GitHub's REST API, or an in-memory store for the fake server used in self-tests. Reports come out as JSON and Markdown, plus a separate private-findings file.

**Tech Stack:** Python ≥ 3.12; `mcp` 2.x (2.3.0 at time of writing: `mcp.Client`, `mcp.StdioServerParameters`, `mcp.server.mcpserver.MCPServer`, `mcp.types.ToolAnnotations`); `httpx`; `pyyaml`; `pytest` and `pytest-asyncio`; hatchling; Apache-2.0.

**Spec:** `docs/superpowers/specs/2026-11-25-mcp-annotation-check-design.md`

## Global Constraints

- Python 3.12 or later. `mcp>=2.3,<3`.
- Repository is neutral: no ANIP branding in names, CLI or report text. Licence is Apache-2.0.
- The GitHub token is read from the environment variable `MCP_ANNOTATION_CHECK_GITHUB_TOKEN`. It is never logged, never printed and never written to any report.
- Only explicit claims are tested; a hint that is `None` claims nothing. `destructiveHint` and `idempotentHint` are tested only when `readOnlyHint` is not `True`.
- Every judged result quotes the schema text for its hint verbatim:
  - read-only: "If true, the tool does not modify its environment."
  - destructive: "If true, the tool may perform destructive updates to its environment. If false, the tool performs only additive updates."
  - idempotent: "If true, calling the tool repeatedly with the same arguments will have no additional effect on its environment."
- Checks run one at a time. There is no concurrency inside a run.
- Snapshots never compare `updated_at` or ETags. They do compare reaction counts. `updated_at` is recorded.
- Closed fixtures get the label `mcp-annotation-check:done`. Cleanup never deletes that label.
- The harness never posts, comments or publishes anywhere. Every finding starts as `unreviewed`.
- Live GitHub tests are marked `@pytest.mark.live` and excluded from the default `pytest` run.
- Work on branches and merge through pull requests. If anything listens on a port, avoid 8000 to 8999.

**Plan's own calls** (not in the spec; flag in review):

- In a collection, removing an element **the caller listed** (for example `remove_label("c")` on a tool claiming `destructiveHint: false`) is a FINDING. Removal is never additive. The spec's OBSERVATION tier covers only a single value overwritten by a value the caller supplied.
- The pack format is YAML.
- The CLI name is `mcp-annotation-check`.

## Review Focus

These are the five failure modes most likely to bite. Each has its test in the owning task.

1. **A tool call that errors or returns `isError` but still changed state.** It must still get an after-snapshot and be judged; a change is a FINDING. Test in Task 5.
2. **A tool the server lists that the pack doesn't mention.** It appears as SKIPPED with "no pack entry yet" and is never dropped silently. A pack entry naming a tool the server doesn't list is reported as an ERROR, not ignored. Test in Task 5.
3. **State that never settles** (polling keeps seeing changes). The result is an ERROR "did not settle within Ns" with no verdict, and the run continues. Test in Task 5.
4. **Fixture creation or a REST call failing mid-run** (for example a rate limit). That tool gets an ERROR with the HTTP status, cleanup is still attempted, and the run continues with the next tool. Test in Task 6.
5. **The token leaking through an exception.** `httpx` errors and tracebacks can include request headers. Every error text that reaches a report or the console passes through `redact()`. Test in Task 7.

---

## File Structure

```
pyproject.toml                 package, deps, console script, pytest markers
LICENSE                        Apache-2.0
README.md                      what it is, safety model, how to run (Task 11)
src/mcp_annotation_check/
  claims.py                    explicit-claim extraction, which checks apply
  snapshot.py                  FieldSpec, Snapshot, field diffs
  rules.py                     the three rules and two tiers -> Verdict
  pack.py                      YAML pack loading, validation, argument templating
  reader.py                    StateReader protocol (narrow internal seam)
  settle.py                    poll until stable
  runner.py                    per-tool orchestration -> ToolResult
  report.py                    RunHeader, ToolResult, writers (json, md, private)
  redact.py                    secret redaction for all error text
  cli.py                       `mcp-annotation-check run|self-test|list-tools`
  fake/server.py               deliberately mislabelled MCPServer + in-memory store
  fake/reader.py               StateReader over the in-memory store
  github/rest.py               httpx client for GitHub REST
  github/reader.py             GitHub StateReader (snapshots, fixtures, cleanup)
  github/safety.py             preflight, per-call checks, ID resolution
  github/launcher.py           docker stdio params, image digest, flags
packs/fake.yaml                pack for the fake server
packs/github.yaml              pack for GitHub's MCP server
docs/verification.md           recorded results of live verification steps
tests/                         mirrors src/; live tests marked `live`
```

---

### Task 1: Project scaffold and explicit claims

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `src/mcp_annotation_check/__init__.py`, `src/mcp_annotation_check/claims.py`
- Test: `tests/test_claims.py`

**Interfaces:**
- Produces:
  - `class Check(StrEnum): READ_ONLY = "read_only"; NON_DESTRUCTIVE = "non_destructive"; IDEMPOTENT = "idempotent"`
  - `@dataclass(frozen=True) class Claims: read_only: bool | None; destructive: bool | None; idempotent: bool | None`
  - `def claims_of(tool: mcp.types.Tool) -> Claims` (reads `tool.annotations`; a missing annotations object gives all `None`)
  - `def applicable_checks(claims: Claims) -> list[Check]`
  - `SCHEMA_TEXT: dict[Check, str]`, holding the three quotes from Global Constraints

- [ ] **Step 1: Write the failing tests**

```python
def test_missing_annotations_claim_nothing():
    assert applicable_checks(claims_of(Tool(name="t", inputSchema={"type": "object"}))) == []

def test_read_only_true_gives_only_read_only_check():
    c = Claims(read_only=True, destructive=False, idempotent=True)
    assert applicable_checks(c) == [Check.READ_ONLY]

def test_explicit_false_destructive_is_checked_when_not_read_only():
    assert applicable_checks(Claims(read_only=None, destructive=False, idempotent=None)) == [Check.NON_DESTRUCTIVE]

def test_destructive_true_or_none_is_not_checked():
    assert applicable_checks(Claims(read_only=False, destructive=True, idempotent=None)) == []
    assert applicable_checks(Claims(read_only=False, destructive=None, idempotent=None)) == []

def test_idempotent_true_checked_alongside_non_destructive():
    assert applicable_checks(Claims(read_only=False, destructive=False, idempotent=True)) == [Check.NON_DESTRUCTIVE, Check.IDEMPOTENT]

def test_schema_text_is_verbatim():
    assert SCHEMA_TEXT[Check.NON_DESTRUCTIVE].endswith("If false, the tool performs only additive updates.")
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `pytest tests/test_claims.py -v`. Expected: an import error.

- [ ] **Step 3: Write `pyproject.toml` and `claims.py`**

- `pyproject.toml`: dependencies `mcp>=2.3,<3`, `httpx>=0.27`, `pyyaml>=6`. Dev extra: `pytest`, `pytest-asyncio`. Console script `mcp-annotation-check = mcp_annotation_check.cli:main`. Pytest markers: `live` (excluded by default with `addopts = "-m 'not live'"`). `asyncio_mode = "auto"`.
- `LICENSE`: the full Apache-2.0 text.

- [ ] **Step 4: Run them and confirm they pass**

Run: `pip install -e '.[dev]' && pytest tests/test_claims.py -v`. Expected: 6 passed.

- [ ] **Step 5: Commit**

`git commit -m "feat: explicit-claim extraction and which checks apply"`

---

### Task 2: Snapshots and rules

**Files:**
- Create: `src/mcp_annotation_check/snapshot.py`, `src/mcp_annotation_check/rules.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: `Check`, `SCHEMA_TEXT` (Task 1)
- Produces:
  - `class FieldKind(StrEnum): COLLECTION = "collection"; SCALAR = "scalar"`
  - `@dataclass(frozen=True) class FieldSpec: path: str; kind: FieldKind`. Example paths: `"issue.labels"`, `"issue.title"`, `"repo.refs"`.
  - `Snapshot = dict[str, Any]`, keyed by `FieldSpec.path`. A collection value is a `frozenset` of hashables (for comments, a frozenset of `(id, body, reactions_total)` tuples); a scalar value is a hashable or `None`.
  - `@dataclass(frozen=True) class Recorded: snapshot: Snapshot; timestamps: dict[str, str]`, where `timestamps` holds `updated_at` values, recorded but never compared
  - `class Outcome(StrEnum): PASS, FINDING, OBSERVATION, SKIPPED, ERROR`
  - `@dataclass(frozen=True) class Verdict: check: Check; outcome: Outcome; detail: str; changed: dict[str, tuple[Any, Any]]; warnings: list[str]; schema_text: str`
  - `def judge_read_only(before: Recorded, after: Recorded, fields: list[FieldSpec]) -> Verdict`
  - `def judge_non_destructive(before: Recorded, after: Recorded, fields: list[FieldSpec], supplied: dict[str, Any]) -> Verdict`. `supplied` maps a field path to the value the caller's arguments give that field: a collection or a scalar. Fields absent from `supplied` were not named by the caller.
  - `def judge_idempotent(after_first: Recorded, after_second: Recorded, fields: list[FieldSpec]) -> Verdict`

The non-destructive algorithm is not determined by the signature, so it is fixed here. For each field, with `b = before[path]`, `a = after[path]` and `s = supplied.get(path)`:
- **COLLECTION:** `lost = b - a`. If `lost` is non-empty, the outcome is FINDING. That covers both an element the caller didn't list and one the caller listed for removal. Additions are never findings.
- **SCALAR:** if `b is None` or `b == a`, nothing is lost. Otherwise, if the path is in `supplied` and `a == s`, the outcome is OBSERVATION. Otherwise it is FINDING.
- **Overall:** FINDING if any field is a FINDING, else OBSERVATION if any is an OBSERVATION, else PASS.

- [ ] **Step 1: Write the failing tests**

```python
LABELS = FieldSpec("issue.labels", FieldKind.COLLECTION)
TITLE = FieldSpec("issue.title", FieldKind.SCALAR)
def rec(**kv): return Recorded(snapshot={k.replace("__", "."): v for k, v in kv.items()}, timestamps={})

def test_label_replace_is_finding():   # github/github-mcp-server#3760
    v = judge_non_destructive(rec(issue__labels=frozenset({"c", "d"})), rec(issue__labels=frozenset({"a"})),
                              [LABELS], supplied={"issue.labels": frozenset({"a"})})
    assert v.outcome is Outcome.FINDING and v.changed["issue.labels"] == (frozenset({"c", "d"}), frozenset({"a"}))

def test_label_add_passes():
    v = judge_non_destructive(rec(issue__labels=frozenset({"c"})), rec(issue__labels=frozenset({"c", "a"})), [LABELS], {"issue.labels": frozenset({"a"})})
    assert v.outcome is Outcome.PASS

def test_listed_removal_is_finding():
    v = judge_non_destructive(rec(issue__labels=frozenset({"c", "d"})), rec(issue__labels=frozenset({"d"})), [LABELS], {"issue.labels": frozenset({"c"})})
    assert v.outcome is Outcome.FINDING

def test_supplied_title_overwrite_is_observation():
    v = judge_non_destructive(rec(issue__title="old"), rec(issue__title="new"), [TITLE], {"issue.title": "new"})
    assert v.outcome is Outcome.OBSERVATION

def test_unnamed_title_change_is_finding():
    assert judge_non_destructive(rec(issue__title="old"), rec(issue__title="x"), [TITLE], {}).outcome is Outcome.FINDING

def test_empty_to_set_is_additive():
    assert judge_non_destructive(rec(issue__title=None), rec(issue__title="x"), [TITLE], {}).outcome is Outcome.PASS

def test_read_only_change_is_finding_and_quotes_schema():
    v = judge_read_only(rec(issue__title="a"), rec(issue__title="b"), [TITLE])
    assert v.outcome is Outcome.FINDING and v.schema_text == SCHEMA_TEXT[Check.READ_ONLY]

def test_read_only_timestamp_only_change_warns_but_passes():
    b = Recorded({"issue.title": "a"}, {"issue": "2026-01-01T00:00:00Z"})
    a = Recorded({"issue.title": "a"}, {"issue": "2026-01-02T00:00:00Z"})
    v = judge_read_only(b, a, [TITLE])
    assert v.outcome is Outcome.PASS and any("updated_at" in w for w in v.warnings)

def test_idempotent_second_call_change_is_finding():
    assert judge_idempotent(rec(issue__labels=frozenset({"a"})), rec(issue__labels=frozenset({"a", "a2"})), [LABELS]).outcome is Outcome.FINDING
```

- [ ] **Step 2: Run them and confirm they fail.** Run: `pytest tests/test_rules.py -v`. Expected: an import error.
- [ ] **Step 3: Implement `snapshot.py` and `rules.py`** as specified above. `detail` names the fields compared, for example "no change observed in issue.labels, issue.title".
- [ ] **Step 4: Run them and confirm they pass.** Run: `pytest tests/test_rules.py -v`. Expected: 9 passed.
- [ ] **Step 5: Commit:** `git commit -m "feat: snapshot diffs and the three annotation rules"`

---

### Task 3: Pack format, validation and argument templating

**Files:**
- Create: `src/mcp_annotation_check/pack.py`, `packs/fake.yaml` (filled in Task 4)
- Test: `tests/test_pack.py`

**Interfaces:**
- Consumes: `FieldSpec`, `FieldKind` (Task 2)
- Produces:
  - `@dataclass(frozen=True) class ToolEntry: tool: str; status: Literal["enabled", "skipped"]; skip_reason: str | None; fixture: str | None; arguments: dict[str, Any]; fields: list[FieldSpec]; supplies: dict[str, str]; custom_setup: str | None; custom_verdict: str | None; custom_reason: str | None; repository: Literal["read", "write"]`. `supplies` maps a field path to the argument name whose value is supplied to that field.
  - `@dataclass(frozen=True) class Pack: server: str; version: str; allowlist: list[str]; repositories: dict[str, str]; standard_read_only_fields: list[FieldSpec]; entries: dict[str, ToolEntry]`
  - `def load_pack(path: Path) -> Pack`, which raises `PackError` on any validation failure
  - `def render_arguments(entry: ToolEntry, fixture_values: dict[str, Any], repositories: dict[str, str]) -> dict[str, Any]`, which replaces `"{fixture.X}"` and `"{repo.owner}"` / `"{repo.name}"` strings
  - `def supplied_values(entry: ToolEntry, rendered: dict[str, Any], fields: list[FieldSpec]) -> dict[str, Any]`. It converts list arguments to `frozenset` for COLLECTION fields.

**Validation rules** (each raises `PackError` with the tool name):
- `status: skipped` requires `skip_reason`.
- `custom_verdict` requires `custom_reason`.
- Every `supplies` key must be one of the entry's `fields`, and its value must be an argument name.
- **The content rule:** no string anywhere in `arguments` or in fixture text may contain an @mention (regex `(?<![\w.])@[A-Za-z0-9-]+`), a cross-repository reference (`[\w.-]+/[\w.-]+#\d+`), or a `github.com/` URL.

- [ ] **Step 1: Write the failing tests:**
  - `test_loads_entry_with_fields_and_supplies`
  - `test_skipped_without_reason_rejected`
  - `test_custom_verdict_without_reason_rejected`
  - `test_mention_in_arguments_rejected`, with an argument body of `"cc @someone"`
  - `test_cross_repo_reference_rejected`, with `"see octo/repo#12"`
  - `test_github_url_rejected`
  - `test_email_address_is_not_a_mention`, with `"a@b.com"`, which is accepted
  - `test_render_arguments_substitutes_fixture_values`: `{"issue_number": "{fixture.issue_number}"}` with `{"issue_number": 7}` gives `{"issue_number": 7}`, keeping the int type
  - `test_supplied_values_makes_frozenset_for_collections`

  Each test writes a small YAML pack to `tmp_path`.
- [ ] **Step 2: Run them and confirm they fail.** Run: `pytest tests/test_pack.py -v`.
- [ ] **Step 3: Implement `pack.py`.** Use `yaml.safe_load` only.
- [ ] **Step 4: Run them and confirm they pass.** Expected: 9 passed.
- [ ] **Step 5: Commit:** `git commit -m "feat: pack format with validation and the content safety rule"`

---

### Task 4: Fake server and its reader

**Files:**
- Create: `src/mcp_annotation_check/reader.py`, `src/mcp_annotation_check/fake/server.py`, `src/mcp_annotation_check/fake/reader.py`; fill in `packs/fake.yaml`
- Test: `tests/test_fake.py`

**Interfaces:**
- Consumes: `Recorded`, `FieldSpec` (Task 2); `Pack`, `ToolEntry` (Task 3)
- Produces:
  - `class StateReader(Protocol)`, with:
    - `async def create_fixture(self, entry: ToolEntry, run_id: str) -> dict[str, Any]`, which returns the fixture values;
    - `async def snapshot(self, fields: list[FieldSpec], fixture: dict[str, Any]) -> Recorded`;
    - `async def cleanup(self, entry: ToolEntry, fixture: dict[str, Any]) -> None`.
  - `class FakeStore` (in-memory issues: `labels: set[str]`, `title: str | None`, `notes: list[str]`, `updated_at: str`)
  - `def build_fake_server(store: FakeStore) -> MCPServer`
  - `class FakeReader(StateReader)`

**The fake server's tools** (annotations via `mcp.types.ToolAnnotations`). The comment after each one is the outcome the harness must report:
- `get_issue`: `read_only_hint=True`, pure. PASS.
- `peek_and_touch`: `read_only_hint=True`, but appends a note. FINDING (read-only).
- `set_labels`: `destructive_hint=False`, replaces labels. FINDING (tier 1).
- `add_labels`: `destructive_hint=False`, adds labels. PASS (the false-positive guard).
- `rename_issue`: `destructive_hint=False`, sets the title from arguments. OBSERVATION.
- `append_note`: `destructive_hint=False, idempotent_hint=True`, appends every call. Idempotent FINDING; non-destructive PASS.
- `bump_hidden_counter`: `read_only_hint=True`, but changes a counter that the pack doesn't compare. PASS with "no change observed in …". It shows the "not observed" limit.
- `explode`: `destructive_hint=False`. It removes a label and then raises. FINDING despite the error (Review Focus 1).

- [ ] **Step 1: Write the failing tests:**
  - `test_fake_server_lists_all_tools_with_annotations`: use `async with Client(build_fake_server(store)) as c` and assert that the 8 tool names and their hints appear in `(await c.list_tools()).tools`.
  - `test_fake_reader_snapshot_reflects_store`.
  - `test_fake_pack_loads`: `load_pack(Path("packs/fake.yaml"))` succeeds, and `bump_hidden_counter` doesn't compare the counter.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** the protocol, the store, the server, the reader and `packs/fake.yaml`.
- [ ] **Step 4: Run them and confirm they pass.** Expected: 3 passed.
- [ ] **Step 5: Commit:** `git commit -m "test: deliberately mislabelled fake MCP server and reader"`

---

### Task 5: Runner, settling, reports and self-test

**Files:**
- Create: `src/mcp_annotation_check/settle.py`, `src/mcp_annotation_check/runner.py`, `src/mcp_annotation_check/report.py`, `src/mcp_annotation_check/redact.py` (a stub that returns its input; finished in Task 7), `src/mcp_annotation_check/cli.py` (the `self-test` command)
- Test: `tests/test_runner.py`, `tests/test_report.py`

**Interfaces:**
- Consumes: Tasks 1 to 4
- Produces:
  - `async def settle(read: Callable[[], Awaitable[Recorded]], interval_s: float = 1.0, timeout_s: float = 20.0, stable_reads: int = 2) -> tuple[Recorded, float]`. It returns the snapshot and the seconds waited, and raises `SettleTimeout` if the state is still changing at the timeout.
  - `@dataclass class ToolResult: tool: str; description: str; claims: Claims; outcome: Outcome; verdicts: list[Verdict]; skip_reason: str | None; error: str | None; calls: list[dict]; waited_s: float; custom: str | None; private: bool; review: Literal["unreviewed"] = "unreviewed"`. `private` is `True` when any read-only verdict is a FINDING.
  - `@dataclass class RunHeader: server_info: dict; protocol_version: str | None; sdk_version: str; harness_version: str; pack_version: str; image: str | None; image_digest: str | None; deployment: Literal["local", "in-memory"]; toolsets: list[str]; features: list[str]; date: str; tools_list: list[dict]; tools_list_sha256: str; standard_read_only_fields: list[str]`
  - `async def run(client: mcp.Client, reader: StateReader, pack: Pack, header_context: dict[str, Any], before_call: Callable[[str, dict], Awaitable[None]] | None = None) -> tuple[RunHeader, list[ToolResult]]`.
  - `header_context` supplies `image`, `image_digest`, `deployment`, `toolsets` and `features`. The runner fills the rest of `RunHeader` from the client (`server_info`, `protocol_version`) and the pack.
  - `before_call` is the per-call safety hook from Task 7; it raises `SafetyRefusal` to refuse.
- `CUSTOM_SETUPS: dict[str, Callable[[StateReader, ToolEntry, str], Awaitable[dict[str, Any]]]]` and `CUSTOM_VERDICTS: dict[str, Callable[[Recorded, Recorded, ToolEntry, dict[str, Any]], Verdict]]`, two registries in `runner.py`.
  - A pack's `custom_setup` / `custom_verdict` names a key in them, and an unknown name is an ERROR for that tool.
  - A custom setup replaces `create_fixture`.
  - A custom verdict replaces the general rule only for that entry. `ToolResult.custom` then carries the pack's `custom_reason`, and the report flags it.
  - `def write_reports(header: RunHeader, results: list[ToolResult], out_dir: Path) -> None`. It writes `report.json`, `report.md` and `private-findings.md`. The last is always written, saying "none" when empty.

**Per-tool flow** in `run`:
1. List the tools. Each listed tool without a pack entry is SKIPPED with "no pack entry yet". An entry whose tool isn't listed is an ERROR "pack entry for unlisted tool".
2. Skip tools with no applicable checks ("no explicit claim") and pack-skipped tools, with their reasons.
3. For each enabled tool:
   1. create the fixture;
   2. render the arguments;
   3. take the before-snapshot (judged tools get their fields; read-only tools get `pack.standard_read_only_fields`);
   4. call `before_call`, then `client.call_tool`, recording the call in `calls`;
   5. settle the after-snapshot, which happens **even when the call raised or returned `isError`**;
   6. apply the rules;
   7. for the idempotent check, call again with the same arguments and settle;
   8. clean up in a `finally` block.

   An exception at any step is an ERROR for that tool, passed through `redact()`, and the run continues.

**The Markdown report:**
- the header table;
- the coverage summary (counts per outcome);
- one section per tool, giving: the claim, the schema text as a blockquote, the tool description, the before/after diff, the exact calls as JSON, the confidence line ("no change observed in …") and any custom-verdict flag;
- the statement that findings apply to this image and configuration only.

Private results appear in the public report only as "withheld: see private-findings.md".

- [ ] **Step 1: Write the failing tests** (in-memory, against the fake server):
  - `test_self_test_outcomes`: run against the fake server and its pack, and assert the outcome per tool exactly as listed in Task 4.
  - `test_error_with_state_change_is_finding`: `explode` gives FINDING, and `error` is recorded.
  - `test_unlisted_tool_is_skipped_with_reason`: add a tool to the server that isn't in the pack. It's SKIPPED with "no pack entry yet".
  - `test_pack_entry_for_missing_tool_is_error`.
  - `test_settle_timeout_is_error_and_run_continues`: a reader that changes on every read gives ERROR "did not settle", and later tools are still judged.
  - `test_private_finding_withheld_from_public_report`: `peek_and_touch` appears in `private-findings.md` and not in `report.md`'s details.
  - `test_report_json_has_header_fields`: `tools_list_sha256`, `sdk_version`, `features` and `deployment == "in-memory"`.
  - `test_custom_verdict_is_flagged_with_reason`: a fake-pack entry with `custom_verdict: always_pass` and `custom_reason: "demo"` registered in `CUSTOM_VERDICTS` has `custom == "demo"` in its result, and the report shows the flag.
  - `test_unknown_custom_name_is_error`.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** `settle.py`, `runner.py`, `report.py`, the `redact.py` stub, and `cli.py self-test`. `self-test` runs the fake server in memory and writes the reports to `--out`, defaulting to `./out/self-test`.
- [ ] **Step 4: Run them and confirm they pass.** Run: `pytest -v`, then `mcp-annotation-check self-test --out /tmp/mac-self-test` and open `report.md`. Expected: all tests pass, and the report shows 8 tools with the expected outcomes.
- [ ] **Step 5: Commit:** `git commit -m "feat: serial runner, settling, reports and self-test against the fake server"`

---

### Task 6: GitHub REST client and reader

**Files:**
- Create: `src/mcp_annotation_check/github/rest.py`, `src/mcp_annotation_check/github/reader.py`
- Test: `tests/github/test_reader.py` (using `httpx.MockTransport`)

**Interfaces:**
- Consumes: `StateReader`, `Recorded`, `FieldSpec`, `ToolEntry`
- Produces:
  - `class GitHubRest`, with `__init__(self, token: str, base_url: str = "https://api.github.com", transport: httpx.AsyncBaseTransport | None = None)`; `async get(path, params=None) -> Any`, which follows `Link` pagination for lists; `async post(path, json) -> Any`; `async patch(path, json) -> Any`; `async delete(path) -> None`. Any status ≥ 400 raises `GitHubError(status, path)`, whose message never contains headers.
  - `class GitHubReader(StateReader)`, with `__init__(self, rest: GitHubRest, repositories: dict[str, str])`. `repositories` maps `"read"`/`"write"` to `"owner/name"`.

**Fields supported in version 1** (paths and REST source):
- `issue.labels` (collection of names)
- `issue.assignees` (collection of logins)
- `issue.title`, `issue.body`, `issue.state` (scalars)
- `issue.comments`: a collection of `(id, body, reactions.total_count)`
- `issue.reactions`: a scalar `reactions.total_count`
- `pr.state`, `pr.title`, `pr.body` (scalars)
- `pr.requested_reviewers` (collection)
- `repo.refs`: a collection of `(ref, sha)` from `/git/matching-refs/`
- `repo.labels`: a collection of `(name, color, description)`
- `repo.issues`: a collection of `(number, title, state, labels-tuple, reactions_total)` covering all issues, including pull requests

`issue.*` timestamps are recorded from `updated_at`.

**Named fixtures:**
- `issue_with_labels`: create labels `c` and `d` if missing, then an issue titled `mac-{run_id}-{tool}` with labels `[c, d]` and body `"fixture"`. Values: `issue_number`.
- `plain_issue`.
- `issue_with_comment`.
- `open_pr`: create a branch `mac-{run_id}-{tool}` from the default branch, commit one file under `fixtures/`, and open a pull request.
- `none`.

**Cleanup:** close the issue or pull request, add the `mcp-annotation-check:done` label, delete fixture branches, and delete labels the fixture created except `c`, `d` and `mcp-annotation-check:done`.

- [ ] **Step 1: Write the failing tests:**
  - `test_snapshot_issue_fields`
  - `test_pagination_follows_link_header`
  - `test_issue_with_labels_fixture_calls`, which asserts the exact POST bodies
  - `test_cleanup_closes_and_labels_done_never_deletes_done_label`
  - `test_rest_error_mid_fixture_is_reported_and_cleanup_attempted` (Review Focus 4): a 403 with `x-ratelimit-remaining: 0` on create raises `GitHubError(403, …)`, the runner records an ERROR, and cleanup is called
  - `test_github_error_message_has_no_headers`
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** `rest.py` and `reader.py`.
- [ ] **Step 4: Run them and confirm they pass.** Expected: 6 passed.
- [ ] **Step 5: Commit:** `git commit -m "feat: GitHub REST reader with fixtures and cleanup"`

---

### Task 7: Safety (preflight, per-call checks, redaction)

**Files:**
- Create: `src/mcp_annotation_check/github/safety.py`; finish `src/mcp_annotation_check/redact.py`
- Create: `docs/verification.md`
- Test: `tests/github/test_safety.py`, `tests/test_redact.py`

**Interfaces:**
- Consumes: `GitHubRest`, `Pack`
- Produces:
  - `class SafetyRefusal(Exception)`
  - `async def preflight(rest: GitHubRest, token: str, pack: Pack, expected_login: str) -> dict`. It returns facts for the report header (login, the repositories seen) and raises `SafetyRefusal` on any failure.
  - `def make_before_call(rest: GitHubRest, pack: Pack) -> Callable[[str, dict], Awaitable[None]]`
  - `def redact(text: str, secrets: Iterable[str]) -> str`. It replaces each secret and any `Authorization: …` / `token …` / `Bearer …` value with `[REDACTED]`.

**Preflight checks, in order:**
1. A token starting `ghp_`, `gho_`, `ghu_` or `ghs_` is refused ("classic or app token; use a fine-grained token"). The token must start with `github_pat_`.
2. `GET /user` must have `login == expected_login`.
3. `GET /user/repos?per_page=100` (all pages): every `owner.login` must be on `pack.allowlist`, and both pack repositories must be present.
4. **The compensating check** (always run, whatever Step 1 of the verification below shows): `GET /user/orgs` must list only allowlisted organizations, and `GET /user/repos?affiliation=owner` must be empty or allowlisted. Together these mean the account itself reaches nothing else.

**Per-call checks** (`before_call(tool, arguments)`):
- every `owner`, `repo`, `repository` or `full_name` argument must resolve to `owner/name` with an allowlisted owner;
- a tool from the pack's `id_only_write_tools` list has its ID resolved through REST to an owner first, and is refused if that fails;
- the content rule from Task 3 is re-applied to the rendered arguments;
- search query arguments are never rewritten.

- [ ] **Step 1: Write the failing tests:**
  - `test_classic_token_refused`
  - `test_wrong_login_refused`
  - `test_repo_outside_allowlist_refused`
  - `test_extra_org_membership_refused`
  - `test_call_to_non_allowlisted_owner_refused`
  - `test_id_only_write_unresolvable_refused`
  - `test_search_query_not_modified`
  - `test_redact_removes_token_and_authorization_header` (Review Focus 5): `redact("Authorization: Bearer github_pat_abc", ["github_pat_abc"])` has no `github_pat_abc` and no `Bearer github`.
  - `test_runner_error_text_is_redacted`: a fake reader raises an exception whose text includes the token, and the report contains only `[REDACTED]`.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** `safety.py` and `redact.py`, and wire `redact` into `runner.py`'s error path. Pass secrets from the CLI.
- [ ] **Step 4: Run them and confirm they pass.** Expected: 9 passed.
- [ ] **Step 5: Live verification of the listing semantics** (requires the owner's token; marked `live`):
  - Test: `tests/github/test_live_preflight.py::test_user_repos_reflects_token_scope`.
  - With the fine-grained token limited to the two test repositories, call `GET /user/repos`. Record in `docs/verification.md` whether it returns only the token's repositories or the account's wider set.
  - If it is the account's set, write down that Step 3 above alone is weaker than it reads, and that the compensating check (Step 4) is what guarantees isolation.
  - Run: `MCP_ANNOTATION_CHECK_GITHUB_TOKEN=… pytest -m live tests/github/test_live_preflight.py -v`. Expected: the test passes, and `docs/verification.md` records the observed behaviour with the date.
- [ ] **Step 6: Commit:** `git commit -m "feat: safety preflight, per-call checks and secret redaction"`

---

### Task 8: GitHub server launcher

**Files:**
- Create: `src/mcp_annotation_check/github/launcher.py`; extend `cli.py` with `run` and `list-tools`
- Test: `tests/github/test_launcher.py`

**Interfaces:**
- Consumes: `run`, `write_reports`, `preflight`, `make_before_call`, `GitHubReader`, `load_pack`
- Produces:
  - `def server_params(image: str, toolsets: list[str], features: list[str], token_env: str = "MCP_ANNOTATION_CHECK_GITHUB_TOKEN") -> StdioServerParameters`. It runs `docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN <image> stdio --toolsets=<a,b> [--features=<x,y>]`. The token is passed via the `env` of the parameters, never on the command line.
  - `def image_digest(image: str) -> str`, using `docker image inspect --format '{{index .RepoDigests 0}}'`
  - CLI: `mcp-annotation-check run --pack packs/github.yaml --image <ref> --toolsets <list> [--features <list>] --login <test-account> --out <dir>`. It runs the preflight, starts the server, runs and writes reports. `list-tools` writes `tools/list` to JSON without calling any tool.

- [ ] **Step 1: Write the failing tests:**
  - `test_server_params_has_no_token_in_args`: assert the token value is absent from `params.args`, and `GITHUB_PERSONAL_ACCESS_TOKEN` is present in `params.env`.
  - `test_features_flag_rendered_only_when_given`.
  - `test_run_refuses_before_starting_server_when_preflight_fails`: a monkeypatched `preflight` raises, and `server_params` is never called.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** the launcher and the CLI commands.
- [ ] **Step 4: Run them and confirm they pass.** Expected: 3 passed.
- [ ] **Step 5: Live check of the server flags.** Run `mcp-annotation-check list-tools --image ghcr.io/github/github-mcp-server:<latest> --toolsets default --out out/tools-latest.json`, and the same with `--image <unfixed tag> --features issues_granular`. Expected: the second list contains `update_issue_labels` with `destructiveHint: false`, and the first is the default tool set. Record both tags, digests and tool counts in `docs/verification.md`. If the flag syntax differs from the server's `--help`, fix `server_params` to match it.
- [ ] **Step 6: Commit:** `git commit -m "feat: docker launcher and the run and list-tools commands"`

---

### Task 9: Milestone 1, the label reproduction

**Files:**
- Modify: `packs/github.yaml` (the first entry)
- Test: `tests/github/test_live_label.py` (`live`)

**Interfaces:**
- Consumes: everything above

**Pack entry** `update_issue_labels`:
- `fixture: issue_with_labels`
- `repository: write`
- `arguments: {owner: "{repo.owner}", repo: "{repo.name}", issue_number: "{fixture.issue_number}", labels: ["a"]}`
- `fields`: `issue.labels` (collection), `issue.assignees` (collection), `issue.title`, `issue.body`, `issue.state` (scalars)
- `supplies: {issue.labels: labels}`

The argument names must match the image's input schema from Task 8 Step 5; adjust them if that schema differs.

- [ ] **Step 1: Write the live test:** `test_label_replace_reproduced`. Run against the unfixed image with `--features issues_granular`, and assert that the result for `update_issue_labels` is FINDING, its `changed["issue.labels"]` is `({"c", "d"}, {"a"})`, and the report quotes the destructive schema text.
- [ ] **Step 2: Run it.** Run: `pytest -m live tests/github/test_live_label.py -v`. Expected: PASS. Then open the written `report.md` and confirm the header names the image digest, `issues_granular` and "local".
- [ ] **Step 3: Commit:** `git commit -m "feat: GitHub pack entry reproducing github/github-mcp-server#3760"`

---

### Task 10: The curated sweep

**Files:**
- Modify: `packs/github.yaml`
- Test: `tests/test_github_pack.py` (offline), `tests/github/test_live_sweep.py` (`live`)

**Interfaces:**
- Consumes: `out/tools-latest.json` from Task 8 Step 5

**The pack, built from the latest image's default tool list:**
- **Every read-only tool:**
  - `repository: read`, using the standard read-only fields: `repo.issues`, `repo.labels`, `repo.refs`, plus per-fixture `issue.comments` and `issue.reactions` on the read repository's fixed issue, and `pr.state` on its fixed pull request;
  - arguments point at the fixed issue, pull request and refs of the read repository, whose numbers are recorded in the pack under `repositories.read_fixtures`.
- **Every issue and pull-request write tool,** each with a fixture and fields chosen as in Task 9.
- **Everything else is skipped,** each with a reason:
  - `"no pack entry yet"`;
  - `"acts on the account"` (stars, forks, repository creation, follows, gists);
  - `"external effects"` (notifications, workflow dispatch);
  - `"starts outside work"` (Copilot assignment, Copilot review);
  - `"needs a feature unavailable on private repositories in a free organization"`.
- `id_only_write_tools`: list every write tool whose arguments carry no owner or repository.

Steps:
- [ ] **Step 1: Write the failing offline test:** `test_every_listed_tool_has_entry_or_reason`. Load the pack and `out/tools-latest.json` (committed as `tests/data/tools-latest.json`). Every tool name must have an entry; every skipped entry must have a reason; no enabled entry may be in an account, external or Copilot category.
- [ ] **Step 2: Run it and confirm it fails.**
- [ ] **Step 3: Write the pack entries.**
- [ ] **Step 4: Run it and confirm it passes.**
- [ ] **Step 5: Run the live sweep:** `mcp-annotation-check run --pack packs/github.yaml --image ghcr.io/github/github-mcp-server:<latest> --toolsets default --login <test-account> --out out/sweep-<date>`. Expected:
  - the run completes;
  - every tool in the list appears in `report.md` with an outcome;
  - `private-findings.md` exists;
  - no ERROR other than those explained in the report.
- [ ] **Step 6: Commit:** `git commit -m "feat: curated GitHub sweep pack"`. Commit the pack and the test data, not `out/`; add `out/` to `.gitignore`.

---

### Task 11: README and handover

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`** covering:
  - what the harness checks and why, linking modelcontextprotocol/experimental-ext-tool-annotations#10;
  - the safety model: the token is the boundary, and the owner prerequisites from the spec, verbatim;
  - `self-test`, `list-tools` and `run`;
  - how to read a report: the outcomes, the two non-destructive tiers, "no change observed", and the private file;
  - "findings apply only to the image and configuration in the report header";
  - the review rule: nothing is published until every finding is reviewed by hand, and read-only violations are reported privately first.
- [ ] **Step 2: Check it.** Run: `pytest -v && mcp-annotation-check self-test --out /tmp/mac-final`. Expected: all tests pass, and the self-test report matches Task 5's expected outcomes.
- [ ] **Step 3: Commit:** `git commit -m "docs: README with safety model and how to read a report"`

Milestones 3 and 4 from the spec (the follow-up on #10, and the fix check on a fixed image) are owner actions after this plan. To run the fix check, use Task 9's live test with the fixed image tag and expect PASS.
