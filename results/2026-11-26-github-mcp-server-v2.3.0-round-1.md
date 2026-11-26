<!-- Published copy of the harness report for sweep round 1. One commit author email returned by get_commit and list_commits was replaced with [redacted]; nothing else was edited. -->

# MCP annotation check report

Findings apply to this image and configuration only.

## Run

| Field | Value |
|---|---|
| Server | github-mcp-server v2.3.0 |
| Image | ghcr.io/github/github-mcp-server:v2.3.0 |
| Image digest | ghcr.io/github/github-mcp-server@sha256:f8ee4dedc7d5c8cb32854ab91cc92a31c55a8a5510708cf8742e9f9427588ca6 |
| Deployment | local |
| Toolsets | default |
| Features | issues_granular |
| Date | 2026-11-26T08:12:23+00:00 |
| Protocol version | 2026-07-28 |
| MCP SDK | 2.3.0 |
| Harness | 0.1.0 |
| Pack version | 0.1 |
| tools/list | 62 tools, sha256 `e33f1e5e73a4b31f4dc192acb28e1092365da7cb6e892a79b061c267f3dba065` |
| Read-only comparison set | repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers |
| No-target tools | get_me, search_code, search_commits, search_repositories, search_users |

## Coverage

| Outcome | Tools |
|---|---|
| pass | 26 |
| finding | 2 |
| observation | 3 |
| skipped | 31 |
| unjudged | 0 |
| error | 0 |

Tools with at least one verdict of each kind (a tool can appear in several rows):

| Verdict | Tools |
|---|---|
| finding | 2 |
| observation | 3 |
| unjudged | 0 |
| pass | 26 |

Skipped:

- `add_comment_to_pending_review`: no explicit claim
- `add_issue_comment`: no explicit claim
- `add_issue_comment_reaction`: round 2: needs a new compared field
- `add_reply_to_pull_request_comment`: no explicit claim
- `add_sub_issue`: round 2: needs a new compared field
- `assign_copilot_to_issue`: starts outside work
- `create_branch`: no explicit claim
- `create_issue`: round 2: needs a new compared field
- `create_or_update_file`: no explicit claim
- `create_pull_request`: no explicit claim
- `create_repository`: no explicit claim
- `delete_file`: no explicit claim
- `fork_repository`: no explicit claim
- `get_team_members`: needs organization permissions the token does not have
- `get_teams`: needs organization permissions the token does not have
- `hide_issue_comment`: round 2: needs a new compared field
- `merge_pull_request`: no explicit claim
- `pull_request_review_write`: no explicit claim
- `push_files`: no explicit claim
- `remove_issue_comment_reaction`: no explicit claim
- `remove_issue_reaction`: no explicit claim
- `remove_sub_issue`: no explicit claim
- `reprioritize_sub_issue`: round 2: needs a new compared field
- `request_copilot_review`: no explicit claim
- `set_issue_fields`: round 2: needs a new compared field
- `unhide_issue_comment`: round 2: needs a new compared field
- `update_issue_comment`: no explicit claim
- `update_issue_milestone`: round 2: needs a new compared field
- `update_issue_type`: round 2: needs a new compared field
- `update_pull_request`: no explicit claim
- `update_pull_request_branch`: no explicit claim

## Tools

### add_comment_to_pending_review: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Add review comment to the requester's latest pending pull request review. A pending review needs to already exist to call this (check with the user if not sure).

### add_issue_comment: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Add a comment and/or reaction to a specific issue or issue comment in a GitHub repository. Use this tool with pull requests as well (in this case pass pull request number as issue_number), but only if user is not asking specifically to add or react to review comments. At least one of body or reaction is required.

### add_issue_comment_reaction: SKIPPED

- Claim: readOnlyHint: false, destructiveHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: round 2: needs a new compared field

Tool description:

> Add a reaction to an issue or pull request comment.

### add_issue_reaction: PASS

- Claim: readOnlyHint: false, destructiveHint: false, idempotentHint: false
- Review: unreviewed
- Settled: waited 4.46s

Tool description:

> Add a reaction to an issue or pull request.

#### non_destructive: PASS

> If true, the tool may perform destructive updates to its environment. If false, the tool performs only additive updates.

Result: nothing removed or overwritten in issue.labels, issue.assignees, issue.title, issue.body, issue.state, issue.reaction_set; additions in issue.reaction_set

Changes outside the compared fields are not observed.

Diff before and after the call:

```diff
@@ issue.reaction_set @@ additive
+ ["mcp-annotation-check-bot", "+1"]
```

Calls:

```json
[
  {
    "tool": "add_issue_reaction",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "write-fixture",
      "issue_number": 8,
      "content": "+1"
    },
    "is_error": false,
    "content": "{\"id\":\"690566361\",\"url\":\"https://api.github.com/repos/mcp-annotation-check-lab/write-fixture/issues/8/reactions/690566361\"}"
  }
]
```

### add_reply_to_pull_request_comment: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Add a reply and/or reaction to an existing pull request comment. This can create a new comment linked as a reply to the specified comment, add an emoji reaction to the specified comment, or do both. At least one of body or reaction is required.

### add_sub_issue: SKIPPED

- Claim: readOnlyHint: false, destructiveHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: round 2: needs a new compared field

Tool description:

> Add a sub-issue to a parent issue.

### assign_copilot_to_issue: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: true
- Review: unreviewed
- Skip reason: starts outside work

Tool description:

> Assign Copilot to a specific issue in a GitHub repository.
>
> This tool can help with the following outcomes:
> - a Pull Request created with source code changes to resolve the issue
>
>
> More information can be found at:
> - https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent

### create_branch: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Create a new branch in a GitHub repository

### create_issue: SKIPPED

- Claim: readOnlyHint: false, destructiveHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: round 2: needs a new compared field

Tool description:

> Create a new issue in a GitHub repository with a title and optional body.

### create_or_update_file: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Create or update a single file in a GitHub repository.
> If updating, you should provide the SHA of the file you want to update. Use this tool to create or update a file in a GitHub repository remotely; do not use it for local file operations.
>
> To obtain the current blob SHA before updating, call the get_file_contents tool with the same owner, repo, and path, and set its ref parameter to this tool's branch value. The first text result reports the blob SHA for the requested path.
>
> SHA MUST be provided for existing file updates.

### create_pull_request: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Create a new pull request in a GitHub repository.

### create_repository: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Create a new GitHub repository in your account or specified organization

### delete_file: SKIPPED

- Claim: readOnlyHint: false, destructiveHint: true, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Delete a file from a GitHub repository

### fork_repository: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Fork a GitHub repository to your account or specified organization

### get_commit: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.38s

Tool description:

> Get details for a commit from a GitHub repository

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "get_commit",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures",
      "sha": "v0.0.1"
    },
    "is_error": false,
    "content": "{\"author\":{\"avatar_url\":\"https://avatars.githubusercontent.com/u/361391923?v=4\",\"id\":361391923,\"login\":\"mcp-annotation-check-bot\",\"profile_url\":\"https://github.com/mcp-annotation-check-bot\"},\"commit\":{\"author\":{\"date\":\"2026-11-26T05:08:06Z\",\"email\":\"[redacted]\",\"name\":\"mcp-annotation-check-bot\"},\"committer\":{\"date\":\"2026-11-26T05:08:06Z\",\"email\":\"noreply@github.com\",\"name\":\"GitHub\"},\"message\":\"Add initial README.md with project title\"},\"committer\":{\"avatar_url\":\"https://avatars.githubusercontent.com/u/19864447?v=4\",\"id\":19864447,\"login\":\"web-flow\",\"profile_url\":\"https://github.com/web-flow\"},\"files\":[{\"additions\":1,\"changes\":1,\"filename\":\"README.md\",\"status\":\"added\"}],\"html_url\":\"https://github.com/mcp-annotation-check-lab/read-fixtures/commit/cf85a69271a02a1d94332bb1d67828f89dc71a31\",\"sha\":\"cf85a69271a02a1d94332bb1d67828f89dc71a31\",\"stats\":{\"additions\":1,\"total\":1}}"
  }
]
```

### get_file_contents: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.34s

Tool description:

> Get the contents of a file or directory from a GitHub repository

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "get_file_contents",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures",
      "path": "README.md"
    },
    "is_error": false,
    "content": "successfully downloaded text file (SHA: edbf9f9917286494672d1f0e9e4e4142db171da8)\n{\"type\":\"resource\",\"resource\":{\"uri\":\"repo://mcp-annotation-check-lab/read-fixtures/sha/cf85a69271a02a1d94332bb1d67828f89dc71a31/contents/README.md\",\"mime_type\":\"text/plain; charset=utf-8\",\"text\":\"# read-fixtures\\n\"}}"
  }
]
```

### get_label: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.60s

Tool description:

> Get a specific label from a repository.

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "get_label",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures",
      "name": "fixture-label"
    },
    "is_error": false,
    "content": "{\"color\":\"098d90\",\"description\":\"\",\"name\":\"fixture-label\"}"
  }
]
```

### get_latest_release: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.46s

Tool description:

> Get the latest release in a GitHub repository

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "get_latest_release",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures"
    },
    "is_error": false,
    "content": "{\"author\":{\"avatar_url\":\"https://avatars.githubusercontent.com/u/361391923?v=4\",\"id\":361391923,\"login\":\"mcp-annotation-check-bot\",\"profile_url\":\"https://github.com/mcp-annotation-check-bot\"},\"draft\":false,\"html_url\":\"https://github.com/mcp-annotation-check-lab/read-fixtures/releases/tag/v0.0.1\",\"id\":459091884,\"name\":\"fixture release\",\"prerelease\":false,\"published_at\":\"2026-11-26T07:41:45Z\",\"tag_name\":\"v0.0.1\"}"
  }
]
```

### get_me: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.28s

Tool description:

> Get details of the authenticated GitHub user. Use this when a request is about the user's own profile for GitHub. Or when information is missing to build other tool calls.

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "get_me",
    "arguments": {},
    "is_error": false,
    "content": "{\"avatar_url\":\"https://avatars.githubusercontent.com/u/361391923?v=4\",\"details\":{\"created_at\":\"2026-11-26T03:50:10Z\",\"followers\":0,\"following\":0,\"public_gists\":0,\"public_repos\":0,\"updated_at\":\"2026-11-26T03:50:51Z\"},\"id\":361391923,\"login\":\"mcp-annotation-check-bot\",\"profile_url\":\"https://github.com/mcp-annotation-check-bot\"}"
  }
]
```

### get_release_by_tag: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.69s

Tool description:

> Get a specific release by its tag name in a GitHub repository

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "get_release_by_tag",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures",
      "tag": "v0.0.1"
    },
    "is_error": false,
    "content": "{\"author\":{\"avatar_url\":\"https://avatars.githubusercontent.com/u/361391923?v=4\",\"id\":361391923,\"login\":\"mcp-annotation-check-bot\",\"profile_url\":\"https://github.com/mcp-annotation-check-bot\"},\"draft\":false,\"html_url\":\"https://github.com/mcp-annotation-check-lab/read-fixtures/releases/tag/v0.0.1\",\"id\":459091884,\"name\":\"fixture release\",\"prerelease\":false,\"published_at\":\"2026-11-26T07:41:45Z\",\"tag_name\":\"v0.0.1\"}"
  }
]
```

### get_tag: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.72s

Tool description:

> Get details about a specific git tag in a GitHub repository

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "get_tag",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures",
      "tag": "v0.0.1"
    },
    "is_error": false,
    "content": "{\"object\":{\"sha\":\"cf85a69271a02a1d94332bb1d67828f89dc71a31\",\"type\":\"commit\"},\"ref\":\"refs/tags/v0.0.1\"}"
  }
]
```

### get_team_members: SKIPPED

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Skip reason: needs organization permissions the token does not have

Tool description:

> Get member usernames of a specific team in an organization. Limited to organizations accessible with current credentials

### get_teams: SKIPPED

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Skip reason: needs organization permissions the token does not have

Tool description:

> Get details of the teams the user is a member of. Limited to organizations accessible with current credentials

### hide_issue_comment: SKIPPED

- Claim: readOnlyHint: false, destructiveHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: round 2: needs a new compared field

Tool description:

> Hide (minimize) a comment on an issue, or a conversation comment on a pull request. Requires triage or write access to the repository, or being its author.

### issue_read: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.50s

Tool description:

> Get information about a specific issue in a GitHub repository.

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "issue_read",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures",
      "issue_number": 1,
      "method": "get"
    },
    "is_error": false,
    "content": "{\"issue\":{\"assignees\":[],\"author_association\":\"MEMBER\",\"body\":\"fixture\",\"closed_by_pull_requests\":{\"references\":[],\"total_count\":0},\"comments\":1,\"created_at\":\"2026-11-26T07:37:04Z\",\"has_children\":false,\"has_parent\":false,\"html_url\":\"https://github.com/mcp-annotation-check-lab/read-fixtures/issues/1\",\"labels\":[\"fixture-label\"],\"number\":1,\"reactions\":{\"+1\":0,\"-1\":0,\"confused\":0,\"eyes\":0,\"heart\":0,\"hooray\":0,\"laugh\":0,\"rocket\":0,\"total_count\":0},\"state\":\"open\",\"title\":\"read fixture issue\",\"updated_at\":\"2026-11-26T07:39:09Z\",\"user\":{\"id\":361391923,\"login\":\"mcp-annotation-check-bot\"}},\"method\":\"get\"}"
  }
]
```

### list_branches: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.47s

Tool description:

> List branches in a GitHub repository

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "list_branches",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures"
    },
    "is_error": false,
    "content": "[{\"name\":\"fixture-branch\",\"sha\":\"6398c8fcbbbb2015b84f8fafd48eb1940c340542\",\"protected\":false},{\"name\":\"main\",\"sha\":\"cf85a69271a02a1d94332bb1d67828f89dc71a31\",\"protected\":false}]"
  }
]
```

### list_commits: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.70s

Tool description:

> Get list of commits of a branch in a GitHub repository. Returns at least 30 results per page by default, but can return more if specified using the perPage parameter (up to 100).

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "list_commits",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures"
    },
    "is_error": false,
    "content": "[{\"sha\":\"cf85a69271a02a1d94332bb1d67828f89dc71a31\",\"html_url\":\"https://github.com/mcp-annotation-check-lab/read-fixtures/commit/cf85a69271a02a1d94332bb1d67828f89dc71a31\",\"commit\":{\"message\":\"Add initial README.md with project title\",\"author\":{\"name\":\"mcp-annotation-check-bot\",\"email\":\"[redacted]\",\"date\":\"2026-11-26T05:08:06Z\"},\"committer\":{\"name\":\"GitHub\",\"email\":\"noreply@github.com\",\"date\":\"2026-11-26T05:08:06Z\"}},\"author\":{\"login\":\"mcp-annotation-check-bot\",\"id\":361391923,\"profile_url\":\"https://github.com/mcp-annotation-check-bot\",\"avatar_url\":\"https://avatars.githubusercontent.com/u/361391923?v=4\"},\"committer\":{\"login\":\"web-flow\",\"id\":19864447,\"profile_url\":\"https://github.com/web-flow\",\"avatar_url\":\"https://avatars.githubusercontent.com/u/19864447?v=4\"}}]"
  }
]
```

### list_issue_fields: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.53s

Tool description:

> List issue fields for a repository or organization. Returns field definitions including name, type (text, number, date, single_select), and for single_select fields the list of valid option names. When repo is omitted, returns org-level fields directly.

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "list_issue_fields",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures"
    },
    "is_error": false,
    "content": "[{\"id\":\"IFSS_kgDOAwHHPQ\",\"full_database_id\":50448189,\"name\":\"Priority\",\"description\":\"Current importance level assigned to this issue\",\"data_type\":\"SINGLE_SELECT\",\"visibility\":\"ORG_ONLY\",\"options\":[{\"id\":\"IFSSO_kgDOBUPf5g\",\"name\":\"Urgent\",\"color\":\"PINK\",\"priority\":1},{\"id\":\"IFSSO_kgDOBUPf5w\",\"name\":\"High\",\"color\":\"RED\",\"priority\":2},{\"id\":\"IFSSO_kgDOBUPf6A\",\"name\":\"Medium\",\"color\":\"YELLOW\",\"priority\":3},{\"id\":\"IFSSO_kgDOBUPf6Q\",\"name\":\"Low\",\"color\":\"GREEN\",\"priority\":4}]},{\"id\":\"IFD_kgDOAwHHPg\",\"full_database_id\":50448190,\"name\":\"Start date\",\"description\":\"Date when work on issue will begin\",\"data_type\":\"DATE\",\"visibility\":\"ORG_ONLY\"},{\"id\":\"IFD_kgDOAwHHPw\",\"full_database_id\":50448191,\"name\":\"Target date\",\"description\":\"Expected completion date for this issue\",\"data_type\":\"DATE\",\"visibility\":\"ORG_ONLY\"},{\"id\":\"IFSS_kgDOAwHHQA\",\"full_database_id\":50448192,\"name\":\"Effort\",\"description\":\"Relative level of effort for completing this issue\",\"data_type\":\"SINGLE_SELECT\",\"visibility\":\"ORG_ONLY\",\"options\":[{\"id\":\"IFSSO_kgDOBUPf6g\",\"name\":\"High\",\"color\":\"RED\",\"priority\":1},{\"id\":\"IFSSO_kgDOBUPf6w\",\"name\":\"Medium\",\"color\":\"YELLOW\",\"priority\":2},{\"id\":\"IFSSO_kgDOBUPf7A\",\"name\":\"Low\",\"color\":\"GREEN\",\"priority\":3}]}]"
  }
]
```

### list_issue_types: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.68s

Tool description:

> List supported issue types for a repository or its owner organization. When repo is omitted, returns org-level issue types directly.

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "list_issue_types",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures"
    },
    "is_error": false,
    "content": "[{\"id\":951269208,\"name\":\"Task\",\"description\":\"A specific piece of work\",\"color\":\"yellow\",\"is_enabled\":true},{\"id\":951269209,\"name\":\"Bug\",\"description\":\"An unexpected problem or behavior\",\"color\":\"red\",\"is_enabled\":true},{\"id\":951269210,\"name\":\"Feature\",\"description\":\"A request, idea, or new functionality\",\"color\":\"blue\",\"is_enabled\":true}]"
  }
]
```

### list_issues: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.33s

Tool description:

> List issues in a GitHub repository. For pagination, use the 'endCursor' from the previous response's 'pageInfo' in the 'after' parameter.

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "list_issues",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures"
    },
    "is_error": false,
    "content": "{\"issues\":[{\"assignees\":[],\"body\":\"fixture\",\"comments\":1,\"created_at\":\"2026-11-26T07:37:04Z\",\"labels\":[\"fixture-label\"],\"number\":1,\"state\":\"OPEN\",\"title\":\"read fixture issue\",\"updated_at\":\"2026-11-26T07:39:09Z\",\"user\":{\"login\":\"mcp-annotation-check-bot\"}}],\"pageInfo\":{\"endCursor\":\"Y3Vyc29yOnYyOpK0MjAyNi0xMS0yNlQwNzozNzowNFrPAAAAAYqxN7I=\",\"hasNextPage\":false,\"hasPreviousPage\":false,\"startCursor\":\"Y3Vyc29yOnYyOpK0MjAyNi0xMS0yNlQwNzozNzowNFrPAAAAAYqxN7I=\"},\"totalCount\":1}"
  }
]
```

### list_pull_requests: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.52s

Tool description:

> List pull requests in a GitHub repository. If the user specifies an author, then DO NOT use this tool and use the search_pull_requests tool instead.

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "list_pull_requests",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures"
    },
    "is_error": false,
    "content": "[{\"number\":2,\"title\":\"read fixture pull request\",\"state\":\"open\",\"draft\":false,\"merged\":false,\"html_url\":\"https://github.com/mcp-annotation-check-lab/read-fixtures/pull/2\",\"user\":{\"login\":\"mcp-annotation-check-bot\",\"id\":361391923,\"profile_url\":\"https://github.com/mcp-annotation-check-bot\",\"avatar_url\":\"https://avatars.githubusercontent.com/u/361391923?v=4\"},\"head\":{\"ref\":\"fixture-branch\",\"sha\":\"6398c8fcbbbb2015b84f8fafd48eb1940c340542\",\"repo\":{\"full_name\":\"mcp-annotation-check-lab/read-fixtures\"}},\"base\":{\"ref\":\"main\",\"sha\":\"cf85a69271a02a1d94332bb1d67828f89dc71a31\",\"repo\":{\"full_name\":\"mcp-annotation-check-lab/read-fixtures\"}},\"created_at\":\"2026-11-26T07:39:50Z\",\"updated_at\":\"2026-11-26T07:39:50Z\"}]"
  }
]
```

### list_releases: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.21s

Tool description:

> List releases in a GitHub repository

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "list_releases",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures"
    },
    "is_error": false,
    "content": "[{\"id\":459091884,\"tag_name\":\"v0.0.1\",\"name\":\"fixture release\",\"html_url\":\"https://github.com/mcp-annotation-check-lab/read-fixtures/releases/tag/v0.0.1\",\"published_at\":\"2026-11-26T07:41:45Z\",\"prerelease\":false,\"draft\":false,\"author\":{\"login\":\"mcp-annotation-check-bot\",\"id\":361391923,\"profile_url\":\"https://github.com/mcp-annotation-check-bot\",\"avatar_url\":\"https://avatars.githubusercontent.com/u/361391923?v=4\"}}]"
  }
]
```

### list_repository_collaborators: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.98s

Tool description:

> List collaborators of a GitHub repository. Results are paginated; the response includes `nextPage`, `prevPage`, `firstPage`, and `lastPage` fields. To get the next page, use the `nextPage` value as the `page` parameter.

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "list_repository_collaborators",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures"
    },
    "is_error": false,
    "content": "{\"firstPage\":0,\"items\":[{\"id\":361391923,\"login\":\"mcp-annotation-check-bot\",\"role_name\":\"admin\"}],\"lastPage\":0,\"nextPage\":0,\"prevPage\":0}"
  }
]
```

### list_tags: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.69s

Tool description:

> List git tags in a GitHub repository

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "list_tags",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures"
    },
    "is_error": false,
    "content": "[{\"name\":\"v0.0.1\",\"sha\":\"cf85a69271a02a1d94332bb1d67828f89dc71a31\"}]"
  }
]
```

### merge_pull_request: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Merge a pull request in a GitHub repository.

### pull_request_read: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.58s

Tool description:

> Get information on a specific pull request in GitHub repository.

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "pull_request_read",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures",
      "pullNumber": 2,
      "method": "get"
    },
    "is_error": false,
    "content": "{\"additions\":1,\"base\":{\"ref\":\"main\",\"repo\":{\"full_name\":\"mcp-annotation-check-lab/read-fixtures\"},\"sha\":\"cf85a69271a02a1d94332bb1d67828f89dc71a31\"},\"changed_files\":1,\"commits\":1,\"created_at\":\"2026-11-26T07:39:50Z\",\"draft\":false,\"head\":{\"ref\":\"fixture-branch\",\"repo\":{\"full_name\":\"mcp-annotation-check-lab/read-fixtures\"},\"sha\":\"6398c8fcbbbb2015b84f8fafd48eb1940c340542\"},\"html_url\":\"https://github.com/mcp-annotation-check-lab/read-fixtures/pull/2\",\"mergeable_state\":\"clean\",\"merged\":false,\"number\":2,\"state\":\"open\",\"title\":\"read fixture pull request\",\"updated_at\":\"2026-11-26T07:39:50Z\",\"user\":{\"avatar_url\":\"https://avatars.githubusercontent.com/u/361391923?v=4\",\"id\":361391923,\"login\":\"mcp-annotation-check-bot\",\"profile_url\":\"https://github.com/mcp-annotation-check-bot\"}}"
  }
]
```

### pull_request_review_write: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Create and/or submit, delete review of a pull request.
>
> Available methods:
> - create: Create a new review of a pull request. If "event" parameter is provided, the review is submitted. If "event" is omitted, a pending review is created.
> - submit_pending: Submit an existing pending review of a pull request. This requires that a pending review exists for the current user on the specified pull request. The "body" and "event" parameters are used when submitting the review.
> - delete_pending: Delete an existing pending review of a pull request. This requires that a pending review exists for the current user on the specified pull request.
> - resolve_thread: Resolve a review thread. Requires only "threadId" parameter with the thread's node ID (e.g., PRRT_kwDOxxx). The owner, repo, and pullNumber parameters are not used for this method. Resolving an already-resolved thread is a no-op.
> - unresolve_thread: Unresolve a previously resolved review thread. Requires only "threadId" parameter. The owner, repo, and pullNumber parameters are not used for this method. Unresolving an already-unresolved thread is a no-op.

### push_files: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Push multiple files to a GitHub repository in a single commit

### remove_issue_comment_reaction: SKIPPED

- Claim: readOnlyHint: false, destructiveHint: true, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Remove a reaction from an issue or pull request comment.

### remove_issue_reaction: SKIPPED

- Claim: readOnlyHint: false, destructiveHint: true, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Remove a reaction from an issue or pull request.

### remove_sub_issue: SKIPPED

- Claim: readOnlyHint: false, destructiveHint: true, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Remove a sub-issue from a parent issue.

### reprioritize_sub_issue: SKIPPED

- Claim: readOnlyHint: false, destructiveHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: round 2: needs a new compared field

Tool description:

> Reprioritize (reorder) a sub-issue relative to other sub-issues.

### request_copilot_review: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Request a GitHub Copilot code review for a pull request. Use this for automated feedback on pull requests, usually before requesting a human reviewer.

### search_code: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.42s

Tool description:

> Fast and precise code search across ALL GitHub repositories using GitHub's native search engine. Best for finding exact symbols, functions, classes, or specific code patterns.

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "search_code",
    "arguments": {
      "query": "fixture repo:mcp-annotation-check-lab/read-fixtures"
    },
    "is_error": false,
    "content": "{\"incomplete_results\":true,\"items\":[],\"total_count\":0}"
  }
]
```

### search_commits: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.50s

Tool description:

> Search for commits across GitHub repositories using GitHub's commit search syntax. Useful for finding specific changes, authors, or messages across one or many repositories. Searches the default branch only.

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "search_commits",
    "arguments": {
      "query": "fixture repo:mcp-annotation-check-lab/read-fixtures"
    },
    "is_error": false,
    "content": "{\"incomplete_results\":false,\"items\":[],\"total_count\":0}"
  }
]
```

### search_issues: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.35s

Tool description:

> Search issues using natural-language semantic matching. Best for conceptual or paraphrased queries (e.g. "login fails after password reset"). Already scoped to is:issue.

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "search_issues",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures",
      "query": "read fixture issue"
    },
    "is_error": false,
    "content": "{\"incomplete_results\":false,\"items\":[{\"author_association\":\"MEMBER\",\"body\":\"fixture\",\"comments\":1,\"created_at\":\"2026-11-26T07:37:04Z\",\"field_values\":[],\"html_url\":\"https://github.com/mcp-annotation-check-lab/read-fixtures/issues/1\",\"labels\":[\"fixture-label\"],\"locked\":false,\"number\":1,\"reactions\":{\"+1\":0,\"-1\":0,\"confused\":0,\"eyes\":0,\"heart\":0,\"hooray\":0,\"laugh\":0,\"rocket\":0,\"total_count\":0},\"repository_url\":\"https://api.github.com/repos/mcp-annotation-check-lab/read-fixtures\",\"state\":\"open\",\"title\":\"read fixture issue\",\"updated_at\":\"2026-11-26T07:39:09Z\",\"user\":{\"avatar_url\":\"https://avatars.githubusercontent.com/u/361391923?v=4\",\"id\":361391923,\"login\":\"mcp-annotation-check-bot\",\"profile_url\":\"https://github.com/mcp-annotation-check-bot\"}}],\"total_count\":1}"
  }
]
```

### search_pull_requests: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.77s

Tool description:

> Search for pull requests in GitHub repositories using issues search syntax already scoped to is:pr

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "search_pull_requests",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures",
      "query": "head:fixture-branch"
    },
    "is_error": false,
    "content": "{\"incomplete_results\":false,\"items\":[{\"author_association\":\"MEMBER\",\"comments\":0,\"created_at\":\"2026-11-26T07:39:50Z\",\"draft\":false,\"html_url\":\"https://github.com/mcp-annotation-check-lab/read-fixtures/pull/2\",\"locked\":false,\"number\":2,\"pull_request\":{\"diff_url\":\"https://github.com/mcp-annotation-check-lab/read-fixtures/pull/2.diff\",\"html_url\":\"https://github.com/mcp-annotation-check-lab/read-fixtures/pull/2\",\"patch_url\":\"https://github.com/mcp-annotation-check-lab/read-fixtures/pull/2.patch\",\"url\":\"https://api.github.com/repos/mcp-annotation-check-lab/read-fixtures/pulls/2\"},\"reactions\":{\"+1\":0,\"-1\":0,\"confused\":0,\"eyes\":0,\"heart\":0,\"hooray\":0,\"laugh\":0,\"rocket\":0,\"total_count\":0},\"repository_url\":\"https://api.github.com/repos/mcp-annotation-check-lab/read-fixtures\",\"state\":\"open\",\"title\":\"read fixture pull request\",\"updated_at\":\"2026-11-26T07:39:50Z\",\"user\":{\"avatar_url\":\"https://avatars.githubusercontent.com/u/361391923?v=4\",\"id\":361391923,\"login\":\"mcp-annotation-check-bot\",\"profile_url\":\"https://github.com/mcp-annotation-check-bot\"}}],\"total_count\":1}"
  }
]
```

### search_repositories: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.51s

Tool description:

> Find GitHub repositories by name, description, readme, topics, or other metadata. Perfect for discovering projects, finding examples, or locating specific repositories across GitHub.

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "search_repositories",
    "arguments": {
      "query": "repo:mcp-annotation-check-lab/read-fixtures"
    },
    "is_error": false,
    "content": "{\"incomplete_results\":false,\"items\":[{\"archived\":false,\"created_at\":\"2026-11-26T03:54:21Z\",\"default_branch\":\"main\",\"fork\":false,\"forks_count\":0,\"full_name\":\"mcp-annotation-check-lab/read-fixtures\",\"html_url\":\"https://github.com/mcp-annotation-check-lab/read-fixtures\",\"id\":1472638662,\"name\":\"read-fixtures\",\"open_issues_count\":2,\"private\":true,\"stargazers_count\":0,\"updated_at\":\"2026-11-26T03:54:22Z\"}],\"total_count\":1}"
  }
]
```

### search_users: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.60s

Tool description:

> Find GitHub users by username, real name, or other profile information. Useful for locating developers, contributors, or team members.

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "search_users",
    "arguments": {
      "query": "mcp-annotation-check-lab"
    },
    "is_error": false,
    "content": "{\"incomplete_results\":false,\"items\":[],\"total_count\":0}"
  }
]
```

### set_issue_fields: SKIPPED

- Claim: readOnlyHint: false, destructiveHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: round 2: needs a new compared field

Tool description:

> Set issue field values for an issue. Fields are organization-level custom fields (text, number, date, or single select). Use this to create or update field values on an issue.

### ui_get: PASS

- Claim: readOnlyHint: true, idempotentHint: false
- Review: unreviewed
- Settled: waited 9.18s

Tool description:

> Fetch UI data for MCP Apps (labels, assignees, milestones, issue types, branches, issue fields, reviewers).

#### read_only: PASS

> If true, the tool does not modify its environment.

Result: no change observed in repo.labels, repo.refs, repo.issues, issue.comments, issue.reactions, issue.body, issue.assignees, pr.state, pr.title, pr.body, pr.requested_reviewers

Changes outside the compared fields are not observed.

Calls:

```json
[
  {
    "tool": "ui_get",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "read-fixtures",
      "method": "labels"
    },
    "is_error": false,
    "content": "{\"labels\":{\"has_more\":false,\"labels\":[{\"color\":\"f143ab\",\"description\":\"Barrier affecting people with disabilities\",\"id\":\"LA_kwDOV8auxs8AAAADFJ1-xA\",\"name\":\"accessibility\"},{\"color\":\"d73a4a\",\"description\":\"Something isn't working\",\"id\":\"LA_kwDOV8auxs8AAAADFJ1-0Q\",\"name\":\"bug\"},{\"color\":\"0075ca\",\"description\":\"Improvements or additions to documentation\",\"id\":\"LA_kwDOV8auxs8AAAADFJ1-4Q\",\"name\":\"documentation\"},{\"color\":\"cfd3d7\",\"description\":\"This issue or pull request already exists\",\"id\":\"LA_kwDOV8auxs8AAAADFJ1-6g\",\"name\":\"duplicate\"},{\"color\":\"a2eeef\",\"description\":\"New feature or request\",\"id\":\"LA_kwDOV8auxs8AAAADFJ1-_A\",\"name\":\"enhancement\"},{\"color\":\"7057ff\",\"description\":\"Good for newcomers\",\"id\":\"LA_kwDOV8auxs8AAAADFJ1_DQ\",\"name\":\"good first issue\"},{\"color\":\"008672\",\"description\":\"Extra attention is needed\",\"id\":\"LA_kwDOV8auxs8AAAADFJ1_JA\",\"name\":\"help wanted\"},{\"color\":\"e4e669\",\"description\":\"This doesn't seem right\",\"id\":\"LA_kwDOV8auxs8AAAADFJ1_OA\",\"name\":\"invalid\"},{\"color\":\"d876e3\",\"description\":\"Further information is requested\",\"id\":\"LA_kwDOV8auxs8AAAADFJ1_UQ\",\"name\":\"question\"},{\"color\":\"ffffff\",\"description\":\"This will not be worked on\",\"id\":\"LA_kwDOV8auxs8AAAADFJ1_ag\",\"name\":\"wontfix\"},{\"color\":\"098d90\",\"description\":\"\",\"id\":\"LA_kwDOV8auxs8AAAADFLo2rg\",\"name\":\"fixture-label\"}],\"totalCount\":11},\"method\":\"labels\"}"
  }
]
```

### unhide_issue_comment: SKIPPED

- Claim: readOnlyHint: false, destructiveHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: round 2: needs a new compared field

Tool description:

> Unhide (unminimize) a previously hidden comment on an issue, or conversation comment on a pull request. Requires triage or write access to the repository, or being its author.

### update_issue_assignees: FINDING

- Claim: readOnlyHint: false, destructiveHint: false, idempotentHint: false
- Review: unreviewed
- Settled: waited 3.17s

Tool description:

> Update the assignees of an existing issue. This replaces the current assignees with the provided list. When setting values, include a confidence level (LOW, MEDIUM, or HIGH) reflecting how certain you are about the choice.

#### non_destructive: FINDING

> If true, the tool may perform destructive updates to its environment. If false, the tool performs only additive updates.

Result: lost or overwritten: issue.assignees

Changes outside the compared fields are not observed.

Diff before and after the call:

```diff
@@ issue.assignees @@ lost or overwritten
- mcp-annotation-check-bot
```

Calls:

```json
[
  {
    "tool": "update_issue_assignees",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "write-fixture",
      "issue_number": 9,
      "assignees": []
    },
    "is_error": false,
    "content": "{\"id\":\"6622408466\",\"url\":\"https://github.com/mcp-annotation-check-lab/write-fixture/issues/9\"}"
  }
]
```

### update_issue_body: OBSERVATION

- Claim: readOnlyHint: false, destructiveHint: false, idempotentHint: false
- Review: unreviewed
- Settled: waited 3.28s

Tool description:

> Update the body content of an existing issue.

#### non_destructive: OBSERVATION

> If true, the tool may perform destructive updates to its environment. If false, the tool performs only additive updates.

Result: overwritten with the supplied value: issue.body

Changes outside the compared fields are not observed.

Diff before and after the call:

```diff
@@ issue.body @@ lost or overwritten
- fixture
+ mcp-annotation-check new body
```

Calls:

```json
[
  {
    "tool": "update_issue_body",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "write-fixture",
      "issue_number": 10,
      "body": "mcp-annotation-check new body"
    },
    "is_error": false,
    "content": "{\"id\":\"6622410810\",\"url\":\"https://github.com/mcp-annotation-check-lab/write-fixture/issues/10\"}"
  }
]
```

### update_issue_comment: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Update the body of an existing issue or pull request conversation comment. This tool cannot update pull request review comments.

### update_issue_labels: FINDING

- Claim: readOnlyHint: false, destructiveHint: false, idempotentHint: false
- Review: unreviewed
- Settled: waited 3.17s

Tool description:

> Update the labels of an existing issue. This replaces the current labels with the provided list. When setting values, include a confidence level (LOW, MEDIUM, or HIGH) reflecting how certain you are about the choice.

#### non_destructive: FINDING

> If true, the tool may perform destructive updates to its environment. If false, the tool performs only additive updates.

Result: lost or overwritten: issue.labels

Changes outside the compared fields are not observed.

Diff before and after the call:

```diff
@@ issue.labels @@ lost or overwritten
+ a
- c
- d
```

Calls:

```json
[
  {
    "tool": "update_issue_labels",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "write-fixture",
      "issue_number": 11,
      "labels": [
        "a"
      ]
    },
    "is_error": false,
    "content": "{\"id\":\"6622412784\",\"url\":\"https://github.com/mcp-annotation-check-lab/write-fixture/issues/11\"}"
  }
]
```

### update_issue_milestone: SKIPPED

- Claim: readOnlyHint: false, destructiveHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: round 2: needs a new compared field

Tool description:

> Update the milestone of an existing issue.

### update_issue_state: OBSERVATION

- Claim: readOnlyHint: false, destructiveHint: false, idempotentHint: false
- Review: unreviewed
- Settled: waited 3.28s

Tool description:

> Update the state of an existing issue (open or closed), with an optional state reason. When closing, include a confidence level (LOW, MEDIUM, or HIGH) reflecting how certain you are about the decision. Use is_suggestion to propose the change without applying it directly.

#### non_destructive: OBSERVATION

> If true, the tool may perform destructive updates to its environment. If false, the tool performs only additive updates.

Result: overwritten with the supplied value: issue.state

Changes outside the compared fields are not observed.

Diff before and after the call:

```diff
@@ issue.state @@ lost or overwritten
- open
+ closed
```

Calls:

```json
[
  {
    "tool": "update_issue_state",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "write-fixture",
      "issue_number": 12,
      "state": "closed"
    },
    "is_error": false,
    "content": "{\"id\":\"6622414953\",\"url\":\"https://github.com/mcp-annotation-check-lab/write-fixture/issues/12\"}"
  }
]
```

### update_issue_title: OBSERVATION

- Claim: readOnlyHint: false, destructiveHint: false, idempotentHint: false
- Review: unreviewed
- Settled: waited 3.22s

Tool description:

> Update the title of an existing issue.

#### non_destructive: OBSERVATION

> If true, the tool may perform destructive updates to its environment. If false, the tool performs only additive updates.

Result: overwritten with the supplied value: issue.title

Changes outside the compared fields are not observed.

Diff before and after the call:

```diff
@@ issue.title @@ lost or overwritten
- mac-4f6dcece-update_issue_title
+ mcp-annotation-check renamed
```

Calls:

```json
[
  {
    "tool": "update_issue_title",
    "arguments": {
      "owner": "mcp-annotation-check-lab",
      "repo": "write-fixture",
      "issue_number": 13,
      "title": "mcp-annotation-check renamed"
    },
    "is_error": false,
    "content": "{\"id\":\"6622416972\",\"url\":\"https://github.com/mcp-annotation-check-lab/write-fixture/issues/13\"}"
  }
]
```

### update_issue_type: SKIPPED

- Claim: readOnlyHint: false, destructiveHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: round 2: needs a new compared field

Tool description:

> Set or remove the type of an existing issue. Pass null to remove the current type. When setting a value, include a confidence level (LOW, MEDIUM, or HIGH) reflecting how certain you are about the choice.

### update_pull_request: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Update an existing pull request in a GitHub repository.

### update_pull_request_branch: SKIPPED

- Claim: readOnlyHint: false, idempotentHint: false
- Review: unreviewed
- Skip reason: no explicit claim

Tool description:

> Update the branch of a pull request with the latest changes from the base branch.
