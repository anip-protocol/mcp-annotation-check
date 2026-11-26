# mcp-annotation-check

A harness that checks whether MCP server tools behave as their annotations claim. It calls each tool against known fixtures and observes the resulting state through a separate channel (for GitHub, the REST API), then compares what changed with what the tool's hints promised.

It exists because tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`) are only useful if they are true. See the discussion in [modelcontextprotocol/experimental-ext-tool-annotations#10](https://github.com/modelcontextprotocol/experimental-ext-tool-annotations/issues/10) and the report that motivated it, [github/github-mcp-server#3760](https://github.com/github/github-mcp-server/issues/3760).

Licence: Apache-2.0.

## Status

Built and tested: the harness core, the safety checks, the report writer, the CLI, and a self-test against a built-in, deliberately mislabelled fake server.

**Not done yet:** the GitHub pack (`packs/github.yaml`), the live label reproduction and the live sweep. They wait for the owner's test account, organization and token (see below), and for the live checks recorded as Pending in [docs/verification.md](docs/verification.md). There are no results against GitHub's server yet, and none should be assumed.

## Only explicit claims are tested

A hint that is unset claims nothing and is not tested. `destructiveHint` and `idempotentHint` are tested only when `readOnlyHint` is not `true`. Each judged result quotes the schema text for its hint.

## Safety model

The harness calls tools that can write. The token is the boundary: a fine-grained token whose resource owner is a dedicated test organization, limited to two private test repositories, can only ever touch those repositories. The harness's own checks make sure it is pointed at that boundary and refuse loudly when it is not.

- The token is read from the environment variable `MCP_ANNOTATION_CHECK_GITHUB_TOKEN`. The harness never logs, prints or writes it to a report; error text passes through a redactor before it reaches a report or the console, so that protection is only as strong as the redactor.
- Preflight, before any tool runs, using GET requests only: the token must be fine-grained; `GET /user` must be the expected test account (`--login`); every repository the token lists must belong to the pack's allowlist and every pack repository must be listed; and the account must belong to no organization outside the allowlist and own no repository outside it. The last check may pass vacuously if GitHub filters those endpoints by token; see [docs/verification.md](docs/verification.md).
- Before the first call, the pack is validated against the server's `tools/list` (see [Pack format](#pack-format)). Any problem stops the run before a fixture is created or a tool is called.
- Per-call checks, before every tool call: the rendered arguments are re-checked against the pack's content rule; every argument must have a role declared in the pack, and one without is refused; each value is checked by its role (owners must be allowlisted, repositories must be the pack's own, repository IDs are resolved to their owner through REST). Inside free-form `content` values, keys that look like owners or repositories are still checked, as defence in depth. Tools that take only IDs have the IDs resolved to an owner first.
- A safety refusal stops the whole run. Arguments are never rewritten.
- Checks run one at a time. The harness never posts, comments or publishes anywhere.

### Owner prerequisites

The maintainer does these:

- Create the separate GitHub account and test organization, after checking GitHub's terms on secondary accounts.
- Create two private repositories in it: one for read-only checks, one for write tools. Turn off GitHub Actions for the organization. In the write repository, create the label `mcp-annotation-check:done`.
- Create a fine-grained token with the test organization as its resource owner, access to those two repositories only, and these repository permissions: Metadata read; Contents read and write; Issues read and write; Pull requests read and write. No account permissions, and no Actions, Administration or Workflows permissions. The plan may narrow this further once each tool's needs are known.
- Create the new repository under `anip-protocol` once the name is agreed.

## Install

Python 3.12 or later.

```
uv venv --python 3.13 .venv && uv pip install -e '.[dev]'
.venv/bin/pytest
```

Live GitHub tests are marked `live` and are excluded from the default run.

## Commands

### `self-test`

Runs the harness against the built-in fake server, whose annotations are wrong on purpose. No network, no token.

```
mcp-annotation-check self-test --out out/self-test
```

### `list-tools`

Starts GitHub's MCP server in Docker and writes its `tools/list` to JSON. Needs the token.

```
export MCP_ANNOTATION_CHECK_GITHUB_TOKEN=<fine-grained token>
mcp-annotation-check list-tools --image ghcr.io/github/github-mcp-server:<tag> \
  --toolsets default [--features <a,b>] --out out/tools.json
```

`--toolsets` and `--features` are comma-separated.

### `run`

Runs a pack against GitHub's MCP server in Docker and writes the reports to `--out`. Needs the token and a pack, which does not exist yet for GitHub.

```
mcp-annotation-check run --pack packs/github.yaml \
  --image ghcr.io/github/github-mcp-server:<tag> --toolsets default \
  [--features <a,b>] --login <test-account-login> --out out/run-1 \
  [--settle-interval SECONDS] [--settle-timeout SECONDS]
```

After each call the harness polls until the observed state stops changing. `--settle-interval` and `--settle-timeout` control that polling.

## Pack format

A pack is a YAML file describing one server's tools; the full key list is in the docstring of `src/mcp_annotation_check/pack.py`, and `packs/fake.yaml` is a small example. Each enabled tool entry declares the role of every argument in the tool's input schema under `argument_roles`:

| Role | Meaning | Value in the pack |
|---|---|---|
| `owner` | an owner login | exactly `{repo.owner}` |
| `repository` | a bare repository name, paired with the call's one `owner` argument | exactly `{repo.name}` |
| `full_name` | `owner/name` | exactly `{repo.owner}/{repo.name}` |
| `repository_id` | a numeric repository ID, resolved to its owner through REST | any plain ID |
| `id` | any other ID (issue number, comment ID, ...) | any plain ID |
| `content` | free text or structured data; the only role that may hold a mapping or list | anything the content rule allows |
| `other` | any other scalar (state, sort order, a search query, ...) | a scalar |

```yaml
tools:
  add_issue_labels:
    fixture: issue_with_labels
    arguments:
      owner: "{repo.owner}"
      repo: "{repo.name}"
      issue_number: "{fixture.issue_number}"
      labels: [a]
    argument_roles: {owner: owner, repo: repository, issue_number: id, labels: content}
```

If a tool's repository argument takes `owner/name`, declare it `full_name`. Skipped entries need no roles.

Before the first call, the harness checks the pack against the server's `tools/list`: every enabled tool exists, every input-schema property has a role, every role names a real property, and owner and repository values are the placeholders above. Problems are listed under "Pack validation" in the report header (`pack_problems` in `report.json`) and on stderr; every enabled tool is then SKIPPED with "pack validation failed: <n> problem(s)". Warnings do not stop the run: a property whose name looks like an owner or repository (such as `target_owner` or `org`) but is declared `content`, `other` or `id` is listed as a warning (`pack_warnings`) for a human to check.

## How to read a report

A run writes three files to `--out`: `report.md`, `report.json` and `private-findings.md`.

Each tool gets one outcome (the most severe of its checks, in this order: FINDING, ERROR, UNJUDGED, OBSERVATION, PASS, SKIPPED; a finding outranks everything, so it always reaches the coverage counts):

- **PASS**: every call succeeded and the observed state matched the claim.
- **FINDING**: the tool did something its annotation says it does not. This includes a non-destructive tool that lost a value that was already there, and a non-destructive tool that removed an element the caller listed. Removal is never additive.
- **OBSERVATION**: a weaker case, worth a human look. A non-destructive tool overwrote a single value with a value the caller supplied.
- **SKIPPED**: no check ran, with the reason (for example "no pack entry yet" for a tool the server lists that the pack does not mention).
- **ERROR**: the harness could not reach a verdict (a failed REST call with its HTTP status, state that did not settle within the timeout, a pack entry naming a tool the server does not list), or a call failed and no change counting against the claim was observed ("call failed; no change observed in ...", with the call's error; the checks are kept as evidence). A failed call that changed nothing has not shown the claim true. An ERROR is not a pass.
- **UNJUDGED**: the harness cannot judge this field yet, which is not a failed call. A non-destructive check over a field whose elements are whole objects (an issue's comments, a repository's refs, issues or labels) judges the other fields as usual. If those show a finding, the result is FINDING (the detail names the composite fields it did not judge). Otherwise it is UNJUDGED, naming them: editing one object in place would look like a loss. Read-only and idempotent checks still compare these fields. The coverage table counts UNJUDGED separately.

"No change observed in ..." describes the fields and scope the harness compared, not proof that nothing changed. Changes outside the compared fields are not observed.

Read-only violations are private. They appear only in `private-findings.md`; the public `report.md` and `report.json` do not name the tool or show its evidence, and say only how many results were withheld. The header still lists every tool the server offers, so the withheld tool can be inferred by elimination: whenever anything is withheld, both public files carry a "Do not publish until the withheld findings are disclosed" banner (`"publish_blocked": true` and `"publish_notice"` in `report.json`).

The report header records the server info, image and digest, toolsets and features, pack version and date. **Findings apply only to the image and configuration in the report header.**

## Review rule

Every finding starts as `unreviewed`. The harness never publishes. Nothing is published until every finding has been reviewed by hand. A read-only violation is reported privately to the server's maintainers first.

## Next steps (owner)

1. Complete the owner prerequisites and run the pending checks in [docs/verification.md](docs/verification.md).
2. Write `packs/github.yaml`, then run the label reproduction and the sweep.
3. Follow up on the discussion in #10, and run the fix check on a fixed image. The fix sets `destructiveHint: true` on the label tools, and a `true` destructive claim is not tested, so the live label test with the fixed image tag should give SKIPPED with "no explicit claim": the claim was corrected, not shown to hold. (If the fixed tool also claims `idempotentHint: true`, that check runs and its own outcome is reported instead.)
