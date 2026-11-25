# mcp-annotation-check: design

Date: 2026-11-25. Status: approved 2026-11-25.

## Intent

A harness that checks whether an MCP server's tools behave the way their annotations claim, by calling them against known test fixtures and observing what changed.

**Why.** MCP tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`) are claims, and clients use them to decide when to ask a human for confirmation. An audit of GitHub's MCP server (modelcontextprotocol/experimental-ext-tool-annotations#10) found claims that are wrong. The best-known case is `update_issue_labels`: it claims `destructiveHint: false` but replaces the whole label set (github/github-mcp-server#3760). The Tool Annotations group's trust model says annotations matter only if they can be verified, and no shared way to verify them exists. The maintainer offered to build one in a public reply on #10. This harness is that offer.

It also carries over ANIP's contract-testing method (per-service packs, before-and-after state probes, results with a confidence level) into MCP. That fits ANIP's move to put its ideas into MCP instead of growing as a separate protocol.

**Who it is for.**
1. **First:** the maintainer, acting as an outsider who audits well-known public MCP servers, starting with GitHub's. Findings spread the idea: a concrete, reproducible "this tool claims X and does Y", filed as a helpful bug report.
2. **Second, later:** server authors who run it on their own server, using a throwaway instance and a snapshot function they supply.

## Goals (version 1)

1. **Reproduce the label finding on its own.** Starting from a fresh fixture, the harness detects the #3760 behaviour with the general non-destructive rule, not a test written for that one tool.
2. **Sweep GitHub's MCP server.** Every read-only tool and the issue and pull-request write tools are judged. Every other tool is listed as skipped with a stated reason.
3. **Write a report.** The maintainer can review it and post it as a follow-up on #10.

## Non-goals (version 1)

- GitHub's hosted MCP server. Version 1 covers one pinned local image only, because hosted annotations may differ.
- Any server other than GitHub's. The second domain comes later and will shape a general state-reader interface.
- `openWorldHint`, and the `action-metadata` fields (`outcome`, `requiresReview`, `undo`, `cost`). These come later; undo waits for PR #11 to settle.
- Generating arguments from input schemas, or fuzzing.
- Tooling for server authors in CI. The design must not block it (see "Server authors, later").

## Anti-goals

These would make the project a failure even if the code works.

- **A wrong public finding.** One mistaken finding against GitHub's server costs more credibility than ten correct ones earn. Nothing is published without the maintainer reviewing each finding by hand.
- **Touching anything outside the test organization.**
- **Claiming proof.** The harness observes; it cannot prove a tool is read-only. Results always name what was observed.
- **ANIP branding.** The project must be able to stand alone or move into the group's repository.
- **Abstracting too early.** The reader interface stays specific to GitHub until a second domain exists.

## Constraints

- **Language and libraries:** Python 3.12 or later, the official MCP Python SDK (`mcp` 2.x) as the client, and `httpx` for GitHub's REST API. When server authors become an audience, revisit the Python floor against their CI.
- **Repository:** a new repository under the `anip-protocol` GitHub organization, with a neutral name. Working name: `mcp-annotation-check`. Apache-2.0 licence, the same as the MCP interceptors repository, so a later move is easy. If #10 says the group wants it in their repository, it moves.
- **Credentials:** a GitHub token from an environment variable, never logged and never written to reports. It belongs to a separate account and test organization that the maintainer creates. Its token reaches only that organization.
- **Server under test:** GitHub's MCP server from its official Docker image, run locally over stdio. Pin it by tag and record the image digest.
- **Maintainer rules:** work on branches and merge through pull requests; never push to main. If anything listens on a port, avoid 8000 to 8999.

## Approaches considered

- **A. General rules plus a pack per server.** One rule per hint, plus a pack giving each tool's arguments, fixture and compared state. It gives a real sweep and consistent judgments, but some tools fit a general rule badly.
- **B. A scripted test per tool.** It is quickest to the first finding, but there is no general rule, it doesn't sweep, and it is hard to present as conformance.
- **C. A with a per-tool escape hatch (chosen).** It has A's rules and packs, and a tool's pack entry may supply its own setup and, rarely, its own verdict.
- **Rejected:** generating arguments automatically from input schemas. Real calls need IDs of resources that exist, and random calls against a live system are unsafe.

The maintainer chose C, with these guardrails:

- **Custom setup is allowed freely.** Multi-step fixtures are the usual reason for the escape hatch.
- **Custom verdicts are rare.** Each needs a written reason in the pack, and its findings are flagged as custom in the report. The general rule stays the judge wherever possible.

**Build order inside C:** first the label reproduction end to end, as one pack entry judged by the general rule; then the sweep.

## How it works

### The run

1. **Preflight safety checks** (see Safety). The run refuses to start if any fails.
2. **Start the server.** Launch the pinned image over stdio with the chosen toolsets and the test token. Record the image tag and digest, `serverInfo` from `initialize`, the enabled toolsets, the date, and the full `tools/list` result with annotations.
3. **Plan.** For each tool in `tools/list`, decide whether it is judged or skipped, using the rules below and the pack. Every tool appears in the report.
4. **Run each judged tool in isolation:**
   1. Create a fresh fixture through GitHub's REST API.
   2. Take the before-snapshot through the REST API.
   3. Call the tool through MCP.
   4. Wait for effects to settle.
   5. Take the after-snapshot.
   6. Apply the rule. For idempotency, call the tool a second time with the same arguments and snapshot again.
   7. Clean up the fixture as far as the token allows (see Fixtures and cleanup).

   Tests must not depend on each other or on run order.
5. **Write the report.**

### Which claims are tested

Only explicit claims count. The schema defaults are `readOnlyHint` false, `destructiveHint` true and `idempotentHint` false, so a missing hint claims nothing and is not tested.

- **Read-only check:** applies when `readOnlyHint` is explicitly true.
- **Non-destructive check:** applies when `readOnlyHint` is not true and `destructiveHint` is explicitly false.
- **Idempotent check:** applies when `readOnlyHint` is not true and `idempotentHint` is explicitly true.

`destructiveHint` and `idempotentHint` are meaningful only when the tool is not read-only, as the schema says.

### Rules

Every finding quotes the schema text for the hint it tests.

- **Read-only:** nothing in the compared state changes.
  - A violation is the most serious kind of finding: clients may skip asking for confirmation because of this hint. The report marks it **"report privately to the server's maintainers first"**.
- **Non-destructive** (schema: "If false, the tool performs only additive updates"). The pack says which compared fields each argument names, and whether each field is a collection or a single value. Two tiers:
  1. **Finding: a prior value was lost.** For a collection, an element the caller did not list disappeared. This is the label case: the call names the labels field, but losing `c` and `d` is still a finding, because the caller did not list them. Any field, named or not, also counts if a prior value disappeared without the caller supplying a replacement for it. Setting a previously empty value is additive, never a finding.
  2. **Observation.** A single value the caller explicitly supplied overwrote the previous value, for example a new title given in the arguments. These are reported together, as a question for the group about what "additive" means, and are not filed as bugs against the server.
- **Idempotent** (schema: "calling the tool repeatedly with the same arguments will have no additional effect"). The state after the second call equals the state after the first, on the compared fields.
- **Custom verdicts** (escape hatch) carry the pack's written reason and are flagged in the report.

### State and the reader

- **Observe through a different channel.** Fixtures are created and snapshots taken through GitHub's REST API directly, never through the MCP server under test, so the server is not also the witness.
- **A declared comparison set.** Each pack entry names the state it compares, such as an issue's labels, assignees, title, body, state and comments, or a repository's branches. Timestamps (`updated_at`) and ETags are not compared, so a second call's timestamp change is not mistaken for a finding. Reaction counts **are** compared: in a private test organization, a changed count means a tool wrote something.
- **Timestamps are recorded anyway.** On a read-only check, a changed `updated_at` with no compared change is reported as a warning.
- **A failed call still gets an after-snapshot.** An error that changed state is a finding.
- **Checks run one at a time.** The repository-wide snapshot assumes nothing else is writing.
- **Wait for effects to settle.** Poll the after-snapshot until it is stable or a timeout passes. Record the wait in the report.
- **Confidence.** A result says what was observed, for example "no change observed in labels, assignees, title, body or comments of issue #12". A tool judged on a narrow comparison set gets lower confidence. This follows ANIP's contract tests.
- **Keep the reader GitHub-specific in version 1.**

### Fixtures and cleanup

- **Issues cannot be deleted with ordinary repository permissions.** Fixtures are therefore closed, labelled `mcp-annotation-check:done`, and left behind, never reused. Every fixture's name carries the run ID.
- **Resetting.** When fixture clutter slows things down, the owner archives or deletes the test repository and creates a fresh one; the harness never needs repository-delete permission. Labels the harness created for a fixture are removed after the run, except `mcp-annotation-check:done`, which the owner creates once during repository setup and which cleanup never touches. Deleting it would strip it from every closed fixture.
- **Read-only checks get their own small repository.** It holds a fixed set of issues, labels, comments, a pull request and a few refs, so the repository-wide snapshot stays fast and stable. Write tools run in a separate repository.

### Coverage in version 1

Version 1 covers a curated set:

- every read-only tool;
- the issue and pull-request write tools.

Every other tool appears in the report as skipped, with "no pack entry yet" as an allowed reason, so coverage is visible. Covering every tool that makes an explicit claim waits until the group has responded to the #10 follow-up.

**One standard snapshot for read-only checks.** Every read-only tool is judged against the same repository-wide comparison set: issues, labels, comments, reactions, pull-request state and refs. The report names that set.

### Packs

A pack is a data file describing one server, starting with `packs/github.*`. For each tool it gives:

- **arguments,** which may refer to fixture values (for example the new issue's number);
- **fixture:** what to create first, as a named fixture or REST steps, with its cleanup;
- **compared state:** which compared fields each argument names, and whether each field is a collection or a single value. The non-destructive rule needs both;
- **status:** enabled, or skipped with a reason;
- **optional custom setup;**
- **optional custom verdict,** which requires a reason.

The first entry is `update_issue_labels`. Its fixture is an issue labelled `c` and `d`, its arguments set the labels to `["a"]`, its compared state is the issue's labels, assignees, title, body and state, and the `labels` argument names the labels field.

### Safety

The harness performs real actions on GitHub. Safety checks come first, and failing any of them stops the run.

- **The token is the boundary; the harness's own checks are a convenience.** The harness never treats a call as safe because of the tool's annotations, since those are what is being tested. A tool is allowed to run because the token cannot write anywhere outside the boundary, not because the tool claims to be read-only.
- **What the boundary covers.** It covers writes. Reading public data is unavoidable and allowed. Inside the boundary are the test organization and the dedicated test account. The test organization's repositories are private, to keep test churn out of public search and activity feeds.
- **The token.** It is a fine-grained token whose resource owner is the test organization. It has repository permissions only, and only those the curated set needs; it has no account-level permissions. Account-level write tools therefore fail on permission and are listed as skipped.
- **Preflight checks:**
  - refuse classic tokens (`ghp_…`);
  - confirm the token belongs to the dedicated test account;
  - list every repository the token can access, and refuse to run unless all are owned by the test organization.
- **Per-call checks:**
  - every repository or owner named in the arguments must be on the allowlist;
  - a write tool that takes only an ID has the ID resolved to its owner through the REST API first, and is refused if the owner cannot be confirmed;
  - search queries are never rewritten, since that would change what is being tested.
- **Content must not reach outside.** A write inside the boundary can still reach a real person or repository through its content: an @mention sends a notification, and a reference to another repository's issue or pull request (as text or a URL) creates a visible backlink. Fixture text and sample arguments must contain neither, and the harness refuses pack entries that do.
- **Default skips.** These tools are skipped unless explicitly enabled:
  - tools that act on the account rather than a repository (starring, forking, creating repositories, following, gists);
  - tools that reach outside GitHub's data (notifications, workflow dispatch, anything with external effects);
  - tools that start outside work, such as assigning an issue to Copilot or requesting a Copilot review.

  GitHub Actions is turned off for the test organization.

  Tools that need features unavailable on private repositories in a free organization are skipped too, each with the reason.
- **No secrets in output.** Reports and logs never contain the token.

### Report

Write JSON for machines and Markdown for people, from the same data.

**Header:**
- the image tag and digest, and `serverInfo`;
- "hosted versus local": always local in version 1, stated explicitly;
- the enabled toolsets, the feature flags and the date;
- a hash of the `tools/list` result, plus the result itself;
- the harness version, the pack version, the MCP SDK version and the negotiated protocol version. `serverInfo` is read from whichever handshake the pinned image uses; the 2026-07-28 specification changed the handshake;
- the statement that findings apply to this image at this version only.

**Per tool:**
- **Outcome:** PASS, FINDING, OBSERVATION, SKIPPED (with the reason), or ERROR (with the reason).
- **The claim tested, and the quoted schema definition.**
- **Evidence:** the before and after values of the compared fields, as a diff, plus the tool's own description. If it says "replaces all labels", the report already shows that.
- **The exact MCP calls made,** so a reader can reproduce the result.
- **Confidence and the observed scope.**
- **Flags:** "custom verdict" with its reason, and "report privately" for read-only violations.

**Coverage summary:** counts of tools judged, passed, found, observed and skipped, each with reasons.

**Private findings go to a separate file.** Read-only violations go to a separate private-first file, never into the publishable report, so they can't be pasted publicly by mistake.

**Review gate:** every finding starts as "unreviewed". Publishing is always a manual step. The harness never posts anywhere.

### Testing the harness itself

- **Unit tests for each rule,** on synthetic before-and-after snapshots, including both non-destructive tiers and volatile-field exclusion.
- **A small fake MCP server** built with the Python SDK, with in-memory state and a reader for that state. It tests the harness end to end without GitHub, and later doubles as the example for server authors. Its tools are:
  - deliberately mislabelled tools, one per rule;
  - a correctly labelled tool, to catch false positives;
  - a tool that changes state outside the compared set, to show the "not observed" limit in the report.
- **Live runs against GitHub** use the test organization only and are not part of the default test command.

### Server authors, later

Not built in version 1, but the design must leave room for it:

- Server authors supply a snapshot function for their own server's state, and run the harness against a throwaway instance.
- Keeping the GitHub reader behind a narrow internal seam (snapshot a declared comparison set; create and clean up fixtures) is enough for now.

## Images and tool sets (designer's call)

GitHub has open fixes for #3760 (#3791 and #3800, which set `DestructiveHint: true`), and `update_issue_labels` exists only with `--features=issues_granular`. So:

- **The label reproduction runs on an image where the bug exists:** v2.1.0, or the latest image without the fix at build time, with `issues_granular` enabled. It shows that the harness catches a real, known case. Re-running the same entry on a fixed image should give PASS, which shows the fix works.
- **The sweep runs on the latest release with default feature flags:** the tools users actually get.
- **A report covers exactly one image and one configuration.** The header records the toolsets **and** the feature flags.
- **What the report says about the label case:** the finding needs the non-default `issues_granular` flag, and fixes are open as pull requests (#3791, #3800) but not yet released.

## Milestones

1. **Label reproduction:** the `update_issue_labels` entry is judged FINDING by the general non-destructive rule, on an image where the bug exists with `issues_granular` enabled, in the test organization.
2. **Sweep:** the curated set is judged on the latest release with default flags. Every other tool is listed as skipped with its reason, and the report is written.
3. **Follow-up on #10:** the maintainer reviews every finding and posts the sweep report **even if it finds nothing**. A clean result is still useful data for the group. Any read-only violation is reported privately first.
4. **Fix check:** once a fixed image is released, run the label entry on it and expect PASS.

## Left to the builder

- **For the plan to verify:** whether the repository-listing preflight reflects what the token can reach or the account's wider access. If it reflects the account, the check is weaker than it reads, and the plan must say so and add a compensating check.

- Package layout, CLI commands and flags.
- The pack file format (YAML or JSON) and its exact schema.
- Settle polling intervals and timeouts.
- Which state selectors to implement, beyond those the GitHub tools need.
- How fixtures are named so that runs don't collide, for example with a run ID in names.
- Which toolsets to enable in the first sweep, within the safety defaults.

## Owner prerequisites

The maintainer does these:

- Create the separate GitHub account and test organization, after checking GitHub's terms on secondary accounts.
- Create two private repositories in it: one for read-only checks, one for write tools. Turn off GitHub Actions for the organization. In the write repository, create the label `mcp-annotation-check:done`.
- Create a fine-grained token with the test organization as its resource owner, access to those two repositories only, and these repository permissions: Metadata read; Contents read and write; Issues read and write; Pull requests read and write. No account permissions, and no Actions, Administration or Workflows permissions. The plan may narrow this further once each tool's needs are known.
- Create the new repository under `anip-protocol` once the name is agreed.
