# Verification

Live observations that the harness's safety design depends on. Each section says what
was run, when, and what was seen.

## What `GET /user/repos` lists for a fine-grained token

**Status: Pending: requires the owner's fine-grained token.** Nothing below has been
observed yet.

### Why it matters

Preflight step 3 lists every repository returned by `GET /user/repos` and refuses to run
unless every owner is on the pack's allowlist. That check is only as strong as the
listing. If GitHub answers with the repositories the *token* can reach, step 3 proves the
token reaches nothing else. If it answers with the repositories the *account* can reach,
step 3 proves something about the account instead, and says less about the token than it
appears to.

### What will be run

With the dedicated test account's fine-grained token (resource owner: the test
organization; repository permissions only; access limited to the two test repositories):

```
MCP_ANNOTATION_CHECK_GITHUB_TOKEN=… \
MCP_ANNOTATION_CHECK_TEST_REPOSITORIES=<org>/<read-repo>,<org>/<write-repo> \
pytest -m live tests/github/test_live_preflight.py -v -s
```

- `test_user_repos_reflects_token_scope` calls `GET /user/repos` (every page), checks
  that both test repositories are listed, and prints whether the listing is exactly those
  two or something wider.
- `test_compensating_check_endpoints_answer` calls `GET /user/orgs` and
  `GET /user/repos?affiliation=owner`, prints whether each answers and what it lists, and,
  when a known extra membership is named (below), whether that membership is visible.

Both make only GET requests and never print the token.

An empty or allowlisted answer from the step-4 endpoints cannot, on its own, tell
"the account has no other memberships" from "the token hides them". To tell them apart,
for the duration of this check only:

1. Create a throwaway organization and add the test account to it, and create a throwaway
   repository owned by the test account. Do not grant the token access to either. Confirm
   both appear in the account's web UI (Settings > Organizations; the account's
   repository list).
2. Run the tests with them named:

   ```
   MCP_ANNOTATION_CHECK_KNOWN_EXTRA_ORG=<throwaway-org> \
   MCP_ANNOTATION_CHECK_KNOWN_OWNED_REPO=<test-account>/<throwaway-repo> \
   MCP_ANNOTATION_CHECK_GITHUB_TOKEN=… \
   MCP_ANNOTATION_CHECK_TEST_REPOSITORIES=<org>/<read-repo>,<org>/<write-repo> \
   pytest -m live tests/github/test_live_preflight.py -v -s
   ```

   The test prints, for each endpoint, either "lists <name>: it reports the account" or
   "hides <name>: it is filtered by the token". Without the variables it prints what was
   listed, and the comparison against the web UI must be done by hand.
3. Remove the account from the throwaway organization and delete the throwaway
   repository. If the step-4 endpoints report the account, preflight step 4 refuses to
   run while they exist, which is expected; if the endpoints are filtered by the token,
   step 4 does not see them and passes (the vacuous case below).

### What each result means

For `/user/repos` (preflight step 3):

- **Only the token's two repositories.** Step 3 sees exactly what the token can reach,
  and that is inside the test organization.
- **The account's wider set.** Step 3 alone is weaker than it reads: it checks the
  account, not the token. A fine-grained token is bound to a single resource owner, so
  the token still cannot write outside the test organization, but that guarantee then
  rests on GitHub's token model, not on what step 3 observed. Repositories where the
  account is only a collaborator also appear in this listing, so step 3 refuses them.
- **A test repository is missing.** The token is not set up as intended; preflight
  step 3 refuses to run, which is correct. Fix the token's repository access and repeat.

For `/user/orgs` and `/user/repos?affiliation=owner` (preflight step 4):

- **They list the throwaway organization and repository (they report the account).**
  Step 4 is meaningful: when it passes, the account itself belongs to no organization
  and owns no repository outside the allowlist. This is the case in which step 4 is what
  guarantees isolation, whatever `/user/repos` reflects.
- **They hide the throwaway organization and repository (they are filtered by the
  token).** Step 4 passes vacuously: it proves nothing beyond step 3. Isolation then
  rests on the token alone (single resource owner, repository permissions only, limited
  to the two repositories) and on keeping the test account free of other memberships,
  which must be checked by hand in the web UI before each run. Record this plainly; do
  not describe step 4 as a guarantee.
- **Either endpoint fails (for example 403).** Preflight step 4 treats any failure as a
  refusal, so the harness can never run with this token. The design of step 4 would have
  to be revisited (for example by granting the smallest account permission that lets
  these endpoints answer); the check must not simply be dropped.

### Observed

_Pending. Record here: the date, which result above was seen for each endpoint, and the
printed lines._

## Pending: GitHub server launch flags

Not yet run: it needs the owner's token and test organization, which do not exist yet.
No Docker image was pulled or run while writing the launcher.

What will be run, once they exist:

```
export MCP_ANNOTATION_CHECK_GITHUB_TOKEN=<fine-grained token>
mcp-annotation-check list-tools --image ghcr.io/github/github-mcp-server:<latest> \
  --toolsets default --out out/tools-latest.json
mcp-annotation-check list-tools --image ghcr.io/github/github-mcp-server:<unfixed tag> \
  --toolsets default --features issues_granular --out out/tools-unfixed.json
```

Expected: the second list contains `update_issue_labels` with `destructiveHint: false`,
and the first is the default tool set. Also compare `docker run ... --help` with the
flags `server_params` renders (`stdio --toolsets=<a,b> [--features=<x,y>]`); if the
syntax differs, fix `server_params`.

To record here: both image tags, their digests (`image_digest`), the tool count of each
list, the date, and whether the flag syntax matched `--help`.
