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
  `GET /user/repos?affiliation=owner` and prints whether each answers, and with how many
  entries.

Both make only GET requests and never print the token.

### What each result means

- **Only the token's two repositories.** Step 3 checks the token's real reach: with a
  fine-grained token it can never list anything outside the test organization. The
  compensating check (step 4) still runs as a second line of defence.
- **The account's wider set.** Step 3 alone is weaker than it reads: it checks the
  account, not the token. A fine-grained token is bound to a single resource owner, so
  the token still cannot write outside the test organization, but that guarantee then
  rests on GitHub's token model, not on what step 3 observed. The compensating check
  (step 4) is what guarantees isolation: `/user/orgs` listing only allowlisted
  organizations and `/user/repos?affiliation=owner` being empty or allowlisted mean the
  account itself reaches nothing else. Repositories where the account is only a
  collaborator also appear in the default `/user/repos` listing in this case, so step 3
  refuses them.
- **A test repository is missing.** The token is not set up as intended; preflight
  step 3 refuses to run, which is correct. Fix the token's repository access and repeat.
- **`/user/orgs` or `/user/repos?affiliation=owner` fails (for example 403).**
  Preflight step 4 treats any failure as a refusal, so the harness can never run with
  this token. The design of step 4 would have to be revisited (for example by granting
  the smallest account permission that lets these endpoints answer); the check must not
  simply be dropped.

### Observed

_Pending. Record here: the date, which result above was seen, and the printed lines._
