from pathlib import Path

import pytest

from mcp_annotation_check.pack import (
    PackError,
    load_pack,
    render_arguments,
    supplied_values,
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
    p = write_pack(tmp_path, '  t1:\n    arguments: {body: "a@b.com"}\n')
    assert load_pack(p).entries["t1"].arguments == {"body": "a@b.com"}


def test_supplies_must_reference_field_and_argument(tmp_path):
    p = write_pack(
        tmp_path,
        "  t1:\n    arguments: {labels: [a]}\n    fields: [{path: labels, kind: collection}]\n"
        "    supplies: {other: labels}\n",
    )
    with pytest.raises(PackError, match="t1"):
        load_pack(p)
    p = write_pack(
        tmp_path,
        "  t1:\n    arguments: {labels: [a]}\n    fields: [{path: labels, kind: collection}]\n"
        "    supplies: {labels: nope}\n",
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


def test_render_arguments_substitutes_fixture_values(tmp_path):
    p = write_pack(
        tmp_path,
        '  t1:\n    arguments:\n      issue_number: "{fixture.issue_number}"\n'
        '      owner: "{repo.owner}"\n      title: "x {fixture.issue_number} in {repo.name}"\n'
        '      nested: [{n: "{repo.name}"}]\n',
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
