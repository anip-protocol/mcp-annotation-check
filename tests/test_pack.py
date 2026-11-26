from dataclasses import replace
from pathlib import Path

import pytest
from mcp.types import Tool

from mcp_annotation_check.pack import (
    ROLES,
    PackError,
    ToolEntry,
    load_pack,
    pack_warnings,
    render_arguments,
    supplied_values,
    validate_pack,
)
from mcp_annotation_check.snapshot import FieldKind, FieldSpec

HEADER = """
server: fake
version: "1"
allowlist: [fake]
repositories:
  write: octo/write-repo
  read: octo/read-repo
standard_read_only_fields:
  - {path: title, kind: scalar}
"""


def write_pack(tmp_path: Path, tools: str, extra: str = "") -> Path:
    p = tmp_path / "pack.yaml"
    p.write_text(HEADER + extra + "tools:\n" + tools)
    return p


def test_loads_entry_with_fields_and_supplies(tmp_path):
    p = write_pack(
        tmp_path,
        """
  add_labels:
    fixture: issue
    arguments: {labels: [a, b], issue_number: "{fixture.issue_number}"}
    argument_roles: {labels: content, issue_number: id}
    fields:
      - {path: labels, kind: collection}
    supplies: {labels: labels}
""",
    )
    pack = load_pack(p)
    e = pack.entries["add_labels"]
    assert pack.server == "fake"
    assert pack.repositories["write"] == "octo/write-repo"
    assert pack.standard_read_only_fields == [FieldSpec("title", FieldKind.SCALAR)]
    assert e.status == "enabled"
    assert e.repository == "write"
    assert e.fields == [FieldSpec("labels", FieldKind.COLLECTION)]
    assert e.supplies == {"labels": "labels"}
    assert e.argument_roles == {"labels": "content", "issue_number": "id"}


def test_skipped_without_reason_rejected(tmp_path):
    p = write_pack(tmp_path, "  t1:\n    status: skipped\n")
    with pytest.raises(PackError, match="t1"):
        load_pack(p)


def test_custom_verdict_without_reason_rejected(tmp_path):
    p = write_pack(tmp_path, "  t1:\n    custom_verdict: finding\n")
    with pytest.raises(PackError, match="t1"):
        load_pack(p)


@pytest.mark.parametrize(
    "body",
    ["cc @someone", "see octo/repo#12", "https://github.com/octo/repo", "github.com/x"],
)
def test_bad_content_rejected(tmp_path, body):
    p = write_pack(tmp_path, f'  t1:\n    arguments: {{body: "{body}"}}\n')
    with pytest.raises(PackError, match="t1"):
        load_pack(p)


def test_mention_in_arguments_rejected(tmp_path):
    p = write_pack(tmp_path, '  t1:\n    arguments: {body: ["x", {y: "cc @someone"}]}\n')
    with pytest.raises(PackError, match="t1"):
        load_pack(p)


def test_cross_repo_reference_rejected(tmp_path):
    p = write_pack(tmp_path, '  t1:\n    arguments: {body: "see octo/repo#12"}\n')
    with pytest.raises(PackError):
        load_pack(p)


def test_github_url_rejected(tmp_path):
    p = write_pack(tmp_path, '  t1:\n    arguments: {body: "https://github.com/a/b"}\n')
    with pytest.raises(PackError):
        load_pack(p)


def test_email_address_is_not_a_mention(tmp_path):
    p = write_pack(
        tmp_path, '  t1:\n    arguments: {body: "a@b.com"}\n    argument_roles: {body: content}\n'
    )
    assert load_pack(p).entries["t1"].arguments == {"body": "a@b.com"}


def test_supplies_must_reference_field_and_argument(tmp_path):
    p = write_pack(
        tmp_path,
        "  t1:\n    arguments: {labels: [a]}\n    argument_roles: {labels: content}\n"
        "    fields: [{path: labels, kind: collection}]\n    supplies: {other: labels}\n",
    )
    with pytest.raises(PackError, match="t1"):
        load_pack(p)
    p = write_pack(
        tmp_path,
        "  t1:\n    arguments: {labels: [a]}\n    argument_roles: {labels: content}\n"
        "    fields: [{path: labels, kind: collection}]\n    supplies: {labels: nope}\n",
    )
    with pytest.raises(PackError, match="t1"):
        load_pack(p)


def test_loads_id_only_write_tools_and_read_fixtures(tmp_path):
    p = write_pack(
        tmp_path,
        "  t1:\n    status: enabled\n",
        extra="id_only_write_tools: [create_thing]\nread_fixtures: {issue_number: 3}\n",
    )
    pack = load_pack(p)
    assert pack.id_only_write_tools == ["create_thing"]
    assert pack.read_fixtures == {"issue_number": 3}
    assert pack.no_target_tools == []


def test_loads_no_target_tools(tmp_path):
    p = write_pack(tmp_path, "  t1:\n    status: enabled\n", extra="no_target_tools: [get_me]\n")
    assert load_pack(p).no_target_tools == ["get_me"]


def test_render_arguments_substitutes_fixture_values(tmp_path):
    p = write_pack(
        tmp_path,
        '  t1:\n    arguments:\n      issue_number: "{fixture.issue_number}"\n'
        '      owner: "{repo.owner}"\n      title: "x {fixture.issue_number} in {repo.name}"\n'
        '      nested: [{n: "{repo.name}"}]\n'
        "    argument_roles: {issue_number: id, owner: owner, title: content, nested: content}\n",
    )
    e = load_pack(p).entries["t1"]
    out = render_arguments(e, {"issue_number": 7}, {"write": "octo/write-repo"})
    assert out == {
        "issue_number": 7,
        "owner": "octo",
        "title": "x 7 in write-repo",
        "nested": [{"n": "write-repo"}],
    }


def test_supplied_values_makes_frozenset_for_collections(tmp_path):
    p = write_pack(
        tmp_path,
        "  t1:\n    arguments: {labels: [a, b], title: T}\n"
        "    argument_roles: {labels: content, title: content}\n"
        "    fields: [{path: labels, kind: collection}, {path: title, kind: scalar}]\n"
        "    supplies: {labels: labels, title: title}\n",
    )
    e = load_pack(p).entries["t1"]
    out = supplied_values(e, dict(e.arguments), e.fields)
    assert out == {"labels": frozenset({"a", "b"}), "title": "T"}


def test_fake_pack_loads():
    assert load_pack(Path(__file__).parent.parent / "packs" / "fake.yaml").server == "fake"


def test_read_fixtures_content_rejected(tmp_path):
    p = write_pack(tmp_path, "  t1:\n    status: enabled\n", extra='read_fixtures: {body: "cc @someone"}\n')
    with pytest.raises(PackError, match="read_fixtures"):
        load_pack(p)


def test_mention_in_dict_key_rejected(tmp_path):
    p = write_pack(tmp_path, '  t1:\n    arguments: {"cc @someone": 1}\n')
    with pytest.raises(PackError, match="t1"):
        load_pack(p)


def test_nested_bad_content_rejected(tmp_path):
    for body in ('{a: [{b: "https://github.com/x/y"}]}', '{a: {b: ["see octo/repo#12"]}}'):
        p = write_pack(tmp_path, f"  t1:\n    arguments: {body}\n")
        with pytest.raises(PackError, match="t1"):
            load_pack(p)


def test_set_content_checked(tmp_path):
    p = write_pack(tmp_path, '  t1:\n    arguments:\n      a: !!set {"cc @someone": null}\n')
    with pytest.raises(PackError, match="t1"):
        load_pack(p)


def test_github_url_any_case_rejected(tmp_path):
    p = write_pack(tmp_path, '  t1:\n    arguments: {body: "GitHub.com/owner/repo"}\n')
    with pytest.raises(PackError, match="t1"):
        load_pack(p)


def _pack_text(allowlist: str, repositories: str) -> str:
    return (
        f"server: fake\nversion: '1'\nallowlist: {allowlist}\n"
        f"repositories: {repositories}\ntools: {{}}\n"
    )


@pytest.mark.parametrize(
    "allowlist",
    ["test-org", "[1, 2]", "[[test-org]]", "{test-org: 1}", "['teſt-org']", "['a b']"],
)
def test_allowlist_must_be_a_list_of_owner_names(tmp_path, allowlist):
    p = tmp_path / "pack.yaml"
    p.write_text(_pack_text(allowlist, "{write: o/w}"))
    with pytest.raises(PackError, match="allowlist"):
        load_pack(p)


@pytest.mark.parametrize(
    "repositories",
    ["o/w", "[o/w]", "{write: 5}", "{write: o}", "{write: o/w/x}", "{write: /w}", "{1: o/w}"],
)
def test_repositories_must_map_names_to_owner_slash_name(tmp_path, repositories):
    p = tmp_path / "pack.yaml"
    p.write_text(_pack_text("[o]", repositories))
    with pytest.raises(PackError, match="repositories"):
        load_pack(p)


def test_valid_allowlist_and_repositories_load(tmp_path):
    p = tmp_path / "pack.yaml"
    p.write_text(_pack_text("[test-org, Test.Account_2]", "{write: test-org/w, read: test-org/r}"))
    pack = load_pack(p)
    assert pack.allowlist == ["test-org", "Test.Account_2"]
    assert pack.repositories == {"write": "test-org/w", "read": "test-org/r"}


# --- argument roles (spec Amendment 1) ----------------------------------------


def test_roles_are_the_declared_set():
    assert ROLES == frozenset(
        {"owner", "repository", "full_name", "repository_id", "id", "content", "other"}
    )


def test_unknown_role_rejected(tmp_path):
    p = write_pack(tmp_path, "  t1:\n    arguments: {body: x}\n    argument_roles: {body: text}\n")
    with pytest.raises(PackError, match="t1: argument 'body' has unknown role 'text'"):
        load_pack(p)


def test_argument_without_role_rejected(tmp_path):
    p = write_pack(
        tmp_path,
        "  t1:\n    arguments: {body: x, title: y}\n    argument_roles: {body: content}\n",
    )
    with pytest.raises(PackError, match="t1: argument 'title' has no declared role"):
        load_pack(p)


def test_argument_roles_must_map_names_to_roles(tmp_path):
    for roles in ("[body]", "content", "{body: [content]}"):
        p = write_pack(
            tmp_path, f"  t1:\n    arguments: {{body: x}}\n    argument_roles: {roles}\n"
        )
        with pytest.raises(PackError, match="t1"):
            load_pack(p)


def test_skipped_entry_needs_no_roles(tmp_path):
    p = write_pack(
        tmp_path, "  t1:\n    status: skipped\n    skip_reason: later\n    arguments: {body: x}\n"
    )
    assert load_pack(p).entries["t1"].argument_roles == {}


@pytest.mark.parametrize(
    ("role", "value"),
    [
        ("owner", "octo"),
        ("owner", "{repo.name}"),
        ("owner", "x{repo.owner}"),
        ("owner", "{fixture.owner}"),
        ("owner", 5),
        ("repository", "write-repo"),
        ("repository", "{repo.owner}/{repo.name}"),
        ("repository", "{fixture.repository}"),
        ("full_name", "octo/write-repo"),
        ("full_name", "{repo.owner}/write-repo"),
        ("full_name", "{fixture.repository}"),
    ],
)
def test_hard_coded_owner_refused(tmp_path, role, value):
    v = value if isinstance(value, int) else f'"{value}"'
    p = write_pack(
        tmp_path,
        f'  t1:\n    arguments: {{owner: "{{repo.owner}}", x: {v}}}\n'
        f"    argument_roles: {{owner: owner, x: {role}}}\n",
    )
    with pytest.raises(PackError, match=f"t1: {role} argument 'x' must be exactly"):
        load_pack(p)


def test_placeholder_owner_and_repository_load(tmp_path):
    p = write_pack(
        tmp_path,
        '  t1:\n    arguments: {owner: "{repo.owner}", repo: "{repo.name}"}\n'
        "    argument_roles: {owner: owner, repo: repository}\n"
        '  t2:\n    arguments: {full: "{repo.owner}/{repo.name}"}\n'
        "    argument_roles: {full: full_name}\n",
    )
    pack = load_pack(p)
    out = render_arguments(pack.entries["t1"], {}, pack.repositories)
    assert out == {"owner": "octo", "repo": "write-repo"}
    assert render_arguments(pack.entries["t2"], {}, pack.repositories) == {
        "full": "octo/write-repo"
    }


@pytest.mark.parametrize(
    ("arguments", "roles"),
    [
        ('{repo: "{repo.name}"}', "{repo: repository}"),
        (
            '{owner: "{repo.owner}", org: "{repo.owner}", repo: "{repo.name}"}',
            "{owner: owner, org: owner, repo: repository}",
        ),
    ],
)
def test_repository_needs_exactly_one_owner_argument(tmp_path, arguments, roles):
    p = write_pack(tmp_path, f"  t1:\n    arguments: {arguments}\n    argument_roles: {roles}\n")
    with pytest.raises(PackError, match="t1: .*exactly one owner argument"):
        load_pack(p)


@pytest.mark.parametrize("role", ["other", "id", "repository_id"])
def test_nested_value_only_for_content(tmp_path, role):
    p = write_pack(
        tmp_path, f"  t1:\n    arguments: {{x: {{a: 1}}}}\n    argument_roles: {{x: {role}}}\n"
    )
    with pytest.raises(PackError, match="t1: argument 'x' has a nested value"):
        load_pack(p)
    p = write_pack(
        tmp_path, "  t1:\n    arguments: {x: {a: [1]}}\n    argument_roles: {x: content}\n"
    )
    assert load_pack(p).entries["t1"].arguments == {"x": {"a": [1]}}


# --- validate_pack: the pack against tools/list -----------------------------------


def tool(name: str, *props: str) -> Tool:
    return Tool(
        name=name,
        input_schema={"type": "object", "properties": {p: {"type": "string"} for p in props}},
    )


ROLE_PACK = """
  t1:
    arguments: {owner: "{repo.owner}", repo: "{repo.name}", body: hi}
    argument_roles: {owner: owner, repo: repository, body: content, state: other}
  t2:
    status: skipped
    skip_reason: later
"""


def test_validate_pack_clean_returns_no_problems(tmp_path):
    pack = load_pack(write_pack(tmp_path, ROLE_PACK))
    tools = [tool("t1", "owner", "repo", "body", "state"), tool("t2", "anything")]
    assert validate_pack(pack, tools) == []
    assert pack_warnings(pack) == []


def test_missing_tool_is_a_problem(tmp_path):
    pack = load_pack(write_pack(tmp_path, ROLE_PACK))
    assert validate_pack(pack, [tool("t2")]) == ["t1: not in the server's tools/list"]


def test_undeclared_schema_property_is_a_problem(tmp_path):
    pack = load_pack(write_pack(tmp_path, ROLE_PACK))
    tools = [tool("t1", "owner", "repo", "body", "state", "new_owner")]
    assert validate_pack(pack, tools) == [
        "t1: input-schema property 'new_owner' has no declared role"
    ]


def test_role_for_a_property_not_in_the_schema_is_a_problem(tmp_path):
    pack = load_pack(write_pack(tmp_path, ROLE_PACK))
    tools = [tool("t1", "owner", "repo", "body")]
    assert validate_pack(pack, tools) == [
        "t1: role declared for 'state', which is not an input-schema property"
    ]


def test_unreadable_input_schema_is_a_problem(tmp_path):
    pack = load_pack(write_pack(tmp_path, ROLE_PACK))
    bad = Tool(name="t1", input_schema={"type": "object", "properties": ["owner"]})
    assert validate_pack(pack, [bad]) == ["t1: the input schema's properties are not a mapping"]


def test_skipped_entries_are_not_validated(tmp_path):
    pack = load_pack(write_pack(tmp_path, ROLE_PACK))
    tools = [tool("t1", "owner", "repo", "body", "state")]  # t2 is not listed at all
    assert validate_pack(pack, tools) == []


def test_validate_pack_rechecks_entries_built_in_code(tmp_path):
    pack = load_pack(write_pack(tmp_path, ROLE_PACK))
    entry = replace(
        pack.entries["t1"], arguments={"owner": "outside-org", "repo": "{repo.name}", "x": 1}
    )
    pack = replace(pack, entries={"t1": entry})
    problems = validate_pack(pack, [tool("t1", "owner", "repo", "body", "state")])
    assert problems == [
        "t1: owner argument 'owner' must be exactly '{repo.owner}', not 'outside-org'",
        "t1: argument 'x' has no declared role",
    ]


def test_entry_without_roles_is_a_problem():
    pack = load_pack(Path(__file__).parent.parent / "packs" / "fake.yaml")
    pack = replace(pack, entries={"t1": ToolEntry(tool="t1")}, id_only_write_tools=["t1"])
    assert validate_pack(pack, [tool("t1", "issue_id")]) == [
        "t1: input-schema property 'issue_id' has no declared role",
        "t1: on id_only_write_tools, but no argument has the id or repository_id role",
    ]


def test_id_only_tool_with_an_id_declared_otherwise_is_a_problem(tmp_path):
    pack = load_pack(
        write_pack(
            tmp_path,
            "  t1:\n    argument_roles: {issue_number: other, gist_id: id}\n",
            extra="id_only_write_tools: [t1]\n",
        )
    )
    assert validate_pack(pack, [tool("t1", "issue_number", "gist_id")]) == [
        "t1: 'issue_number' looks like an ID of an ID-only write tool but is declared 'other'"
    ]


@pytest.mark.parametrize("role", ["content", "other", "id"])
@pytest.mark.parametrize("prop", ["target_owner", "newowner", "org", "repoName", "ownér", "nwo"])
def test_owner_like_property_declared_harmless_is_a_warning(tmp_path, role, prop):
    body = f'  t1:\n    argument_roles: {{"{prop}": {role}, gist_id: id}}\n'
    pack = load_pack(write_pack(tmp_path, body, extra="id_only_write_tools: [t1]\n"))
    tools = [tool("t1", prop, "gist_id")]
    assert validate_pack(pack, tools) == []  # a warning is not a problem
    assert pack_warnings(pack) == [
        f"warning: t1: property {prop!r} may name an owner or repository but is declared "
        f"{role!r}; check it by hand"
    ]


@pytest.mark.parametrize("prop", ["report", "body", "title"])
def test_harmless_property_names_give_no_warning(tmp_path, prop):
    pack = load_pack(write_pack(tmp_path, f"  t1:\n    argument_roles: {{{prop}: content}}\n"))
    assert pack_warnings(pack) == []


def test_enabled_entry_naming_no_repository_must_be_id_only(tmp_path):
    body = "  t1:\n    argument_roles: {issue_number: id, text: content}\n"
    tools = [tool("t1", "issue_number", "text")]
    flagged = validate_pack(load_pack(write_pack(tmp_path, body)), tools)
    assert flagged == [
        "t1: no argument names a repository (owner, repository, full_name or repository_id "
        "role), so the tool must be on id_only_write_tools or no_target_tools"
    ]
    listed = write_pack(tmp_path, body, extra="id_only_write_tools: [t1]\n")
    assert validate_pack(load_pack(listed), tools) == []


@pytest.mark.parametrize("role", ["owner", "repository", "full_name", "repository_id"])
def test_a_repository_role_satisfies_the_rule(tmp_path, role):
    pack = load_pack(write_pack(tmp_path, f"  t1:\n    argument_roles: {{x: {role}}}\n"))
    problems = validate_pack(pack, [tool("t1", "x")])
    assert not any("names a repository" in p or "no argument names" in p for p in problems)


# --- no_target_tools: tools with no repository by declaration ----------------------


NO_TARGET = "  t1:\n    argument_roles: {query: other, body: content}\n"


def test_no_target_tool_with_content_and_other_roles_is_valid(tmp_path):
    pack = load_pack(write_pack(tmp_path, NO_TARGET, extra="no_target_tools: [t1]\n"))
    assert validate_pack(pack, [tool("t1", "query", "body")]) == []
    # an entry with no arguments at all (get_me) is valid too
    pack = load_pack(
        write_pack(tmp_path, "  t1:\n    status: enabled\n", extra="no_target_tools: [t1]\n")
    )
    assert validate_pack(pack, [tool("t1")]) == []


@pytest.mark.parametrize("role", ["owner", "repository", "full_name", "repository_id", "id"])
def test_no_target_tool_with_repository_role_is_a_problem(tmp_path, role):
    body = f"  t1:\n    argument_roles: {{query: other, x: {role}}}\n"
    pack = load_pack(write_pack(tmp_path, body, extra="no_target_tools: [t1]\n"))
    problems = validate_pack(pack, [tool("t1", "query", "x")])
    assert (
        f"t1: on no_target_tools, so argument 'x' must be content or other, not {role!r}"
        in problems
    )


def test_tool_on_both_no_target_and_id_only_is_a_problem(tmp_path):
    extra = "no_target_tools: [t1]\nid_only_write_tools: [t1]\n"
    pack = load_pack(write_pack(tmp_path, NO_TARGET, extra=extra))
    problems = validate_pack(pack, [tool("t1", "query", "body")])
    assert "t1: on both no_target_tools and id_only_write_tools" in problems


def test_id_only_tool_without_id_fails_validation(tmp_path):
    body = "  t1:\n    argument_roles: {owner: owner, repo: repository, body: content}\n"
    pack = load_pack(write_pack(tmp_path, body, extra="id_only_write_tools: [t1]\n"))
    assert validate_pack(pack, [tool("t1", "owner", "repo", "body")]) == [
        "t1: on id_only_write_tools, but no argument has the id or repository_id role"
    ]
    for role in ("id", "repository_id"):
        body = f"  t1:\n    argument_roles: {{owner: owner, repo: repository, gist_id: {role}}}\n"
        pack = load_pack(write_pack(tmp_path, body, extra="id_only_write_tools: [t1]\n"))
        assert validate_pack(pack, [tool("t1", "owner", "repo", "gist_id")]) == []


def test_no_target_name_needs_a_pack_entry_enabled_or_skipped(tmp_path):
    tools = "  t1:\n    status: skipped\n    skip_reason: later\n  t2:\n    status: enabled\n"
    pack = load_pack(write_pack(tmp_path, tools, extra="no_target_tools: [t1, t2, t3]\n"))
    assert validate_pack(pack, [tool("t1"), tool("t2")]) == [
        "t3: on no_target_tools, but has no pack entry",
    ]


@pytest.mark.parametrize(
    "arg,role",
    [("owner", "other"), ("repo", "content"), ("issue_number", "other"), ("repositoryId", "other")],
)
def test_no_target_tool_argument_named_like_a_target_is_a_problem_whatever_its_role(
    tmp_path, arg, role
):
    body = f"  t1:\n    argument_roles: {{query: other, {arg}: {role}}}\n"
    pack = load_pack(write_pack(tmp_path, body, extra="no_target_tools: [t1]\n"))
    problems = validate_pack(pack, [tool("t1", "query", arg)])
    assert any(f"argument {arg!r}" in p and "no_target_tools" in p for p in problems), problems


def test_no_target_tool_ordinary_search_arguments_stay_valid(tmp_path):
    names = ["query", "q", "sort", "order", "page", "perPage", "type", "minimal_output"]
    roles = ", ".join(f"{n}: other" for n in names)
    body = f"  t1:\n    argument_roles: {{{roles}}}\n"
    pack = load_pack(write_pack(tmp_path, body, extra="no_target_tools: [t1]\n"))
    assert validate_pack(pack, [tool("t1", *names)]) == []


@pytest.mark.parametrize("key", ["no_target_tools", "id_only_write_tools"])
@pytest.mark.parametrize("value", ["5", "{get_issue: 1}", "[123]", "get_issue", "[[a]]"])
def test_tool_name_lists_must_be_lists_of_strings(tmp_path, key, value):
    p = write_pack(tmp_path, "  t1:\n    status: enabled\n", extra=f"{key}: {value}\n")
    with pytest.raises(PackError, match=key):
        load_pack(p)


def test_no_target_does_not_depend_on_annotations(tmp_path):
    # The declaration is the pack's alone: a tool claiming readOnlyHint is not exempt.
    from mcp.types import ToolAnnotations

    body = "  t1:\n    argument_roles: {query: other}\n"
    listed = Tool(
        name="t1",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        annotations=ToolAnnotations(read_only_hint=True),
    )
    assert validate_pack(load_pack(write_pack(tmp_path, body)), [listed]) == [
        (
            "t1: no argument names a repository (owner, repository, full_name or "
            "repository_id role), so the tool must be on id_only_write_tools or "
            "no_target_tools"
        )
    ]
