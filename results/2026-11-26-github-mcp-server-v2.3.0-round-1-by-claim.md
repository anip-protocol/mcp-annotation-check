# Round 1: results by claim

github-mcp-server v2.3.0 (`--toolsets default --features issues_granular`), run on 2026-11-26. One row per explicit claim the harness can test. Each tool links to its section in the [full report](2026-11-26-github-mcp-server-v2.3.0-round-1.md), which has every call and the before/after diff.

A pass means no counterexample on these fixtures, not proof. The read-only comparison covers the fields listed in the full report under "Read-only comparison set".

## `readOnlyHint: true` (25 of 27 tested)

| Tool | Result | Observed |
|---|---|---|
| [`get_commit`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#get_commit-pass) | pass | no change in the compared fields |
| [`get_file_contents`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#get_file_contents-pass) | pass | no change in the compared fields |
| [`get_label`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#get_label-pass) | pass | no change in the compared fields |
| [`get_latest_release`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#get_latest_release-pass) | pass | no change in the compared fields |
| [`get_me`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#get_me-pass) | pass | no change in the compared fields |
| [`get_release_by_tag`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#get_release_by_tag-pass) | pass | no change in the compared fields |
| [`get_tag`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#get_tag-pass) | pass | no change in the compared fields |
| [`get_team_members`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#get_team_members-skipped) | skipped | not tested: needs organization permissions the test token lacks |
| [`get_teams`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#get_teams-skipped) | skipped | not tested: needs organization permissions the test token lacks |
| [`issue_read`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#issue_read-pass) | pass | no change in the compared fields |
| [`list_branches`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#list_branches-pass) | pass | no change in the compared fields |
| [`list_commits`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#list_commits-pass) | pass | no change in the compared fields |
| [`list_issue_fields`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#list_issue_fields-pass) | pass | no change in the compared fields |
| [`list_issue_types`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#list_issue_types-pass) | pass | no change in the compared fields |
| [`list_issues`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#list_issues-pass) | pass | no change in the compared fields |
| [`list_pull_requests`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#list_pull_requests-pass) | pass | no change in the compared fields |
| [`list_releases`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#list_releases-pass) | pass | no change in the compared fields |
| [`list_repository_collaborators`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#list_repository_collaborators-pass) | pass | no change in the compared fields |
| [`list_tags`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#list_tags-pass) | pass | no change in the compared fields |
| [`pull_request_read`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#pull_request_read-pass) | pass | no change in the compared fields |
| [`search_code`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#search_code-pass) | pass | no change in the compared fields |
| [`search_commits`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#search_commits-pass) | pass | no change in the compared fields |
| [`search_issues`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#search_issues-pass) | pass | no change in the compared fields |
| [`search_pull_requests`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#search_pull_requests-pass) | pass | no change in the compared fields |
| [`search_repositories`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#search_repositories-pass) | pass | no change in the compared fields |
| [`search_users`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#search_users-pass) | pass | no change in the compared fields |
| [`ui_get`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#ui_get-pass) | pass | no change in the compared fields |

## `destructiveHint: false` (6 of 15 tested)

| Tool | Result | Observed |
|---|---|---|
| [`add_issue_comment_reaction`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#add_issue_comment_reaction-skipped) | skipped | not tested: needs state the harness does not compare yet |
| [`add_issue_reaction`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#add_issue_reaction-pass) | pass | added a reaction; nothing removed or overwritten |
| [`add_sub_issue`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#add_sub_issue-skipped) | skipped | not tested: needs state the harness does not compare yet |
| [`create_issue`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#create_issue-skipped) | skipped | not tested: needs state the harness does not compare yet |
| [`hide_issue_comment`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#hide_issue_comment-skipped) | skipped | not tested: needs state the harness does not compare yet |
| [`reprioritize_sub_issue`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#reprioritize_sub_issue-skipped) | skipped | not tested: needs state the harness does not compare yet |
| [`set_issue_fields`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#set_issue_fields-skipped) | skipped | not tested: needs state the harness does not compare yet |
| [`unhide_issue_comment`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#unhide_issue_comment-skipped) | skipped | not tested: needs state the harness does not compare yet |
| [`update_issue_assignees`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#update_issue_assignees-finding) | finding | `assignees: []` removed the existing assignee |
| [`update_issue_body`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#update_issue_body-observation) | observation | overwrote the body with the supplied value |
| [`update_issue_labels`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#update_issue_labels-finding) | finding | replaced the label set: `c`, `d` became `a` |
| [`update_issue_milestone`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#update_issue_milestone-skipped) | skipped | not tested: needs state the harness does not compare yet |
| [`update_issue_state`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#update_issue_state-observation) | observation | overwrote the state with the supplied value |
| [`update_issue_title`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#update_issue_title-observation) | observation | overwrote the title with the supplied value |
| [`update_issue_type`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#update_issue_type-skipped) | skipped | not tested: needs state the harness does not compare yet |

## `idempotentHint: true` (0 of 1 tested)

| Tool | Result | Observed |
|---|---|---|
| [`assign_copilot_to_issue`](2026-11-26-github-mcp-server-v2.3.0-round-1.md#assign_copilot_to_issue-skipped) | skipped | not tested: starts Copilot work |

## No testable claim (19 tools)

These tools make none of the three claims above, so the harness does not call them. Their other hint values (`readOnlyHint: false`, `destructiveHint: true`, `idempotentHint: false`, stated or by default) are the conservative ones, which no observed behaviour can contradict.

`add_comment_to_pending_review`, `add_issue_comment`, `add_reply_to_pull_request_comment`, `create_branch`, `create_or_update_file`, `create_pull_request`, `create_repository`, `delete_file`, `fork_repository`, `merge_pull_request`, `pull_request_review_write`, `push_files`, `remove_issue_comment_reaction`, `remove_issue_reaction`, `remove_sub_issue`, `request_copilot_review`, `update_issue_comment`, `update_pull_request`, `update_pull_request_branch`
