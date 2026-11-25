from mcp_annotation_check.claims import SCHEMA_TEXT, Check
from mcp_annotation_check.rules import (
    judge_idempotent,
    judge_non_destructive,
    judge_read_only,
)
from mcp_annotation_check.snapshot import FieldKind, FieldSpec, Outcome, Recorded

LABELS = FieldSpec("issue.labels", FieldKind.COLLECTION)
TITLE = FieldSpec("issue.title", FieldKind.SCALAR)


def rec(**kv):
    return Recorded(snapshot={k.replace("__", "."): v for k, v in kv.items()}, timestamps={})


def test_label_replace_is_finding():  # github/github-mcp-server#3760
    v = judge_non_destructive(
        rec(issue__labels=frozenset({"c", "d"})),
        rec(issue__labels=frozenset({"a"})),
        [LABELS],
        supplied={"issue.labels": frozenset({"a"})},
    )
    assert v.outcome is Outcome.FINDING
    assert v.changed["issue.labels"] == (frozenset({"c", "d"}), frozenset({"a"}))


def test_label_add_passes():
    v = judge_non_destructive(
        rec(issue__labels=frozenset({"c"})),
        rec(issue__labels=frozenset({"c", "a"})),
        [LABELS],
        {"issue.labels": frozenset({"a"})},
    )
    assert v.outcome is Outcome.PASS


def test_listed_removal_is_finding():
    v = judge_non_destructive(
        rec(issue__labels=frozenset({"c", "d"})),
        rec(issue__labels=frozenset({"d"})),
        [LABELS],
        {"issue.labels": frozenset({"c"})},
    )
    assert v.outcome is Outcome.FINDING


def test_supplied_title_overwrite_is_observation():
    v = judge_non_destructive(
        rec(issue__title="old"), rec(issue__title="new"), [TITLE], {"issue.title": "new"}
    )
    assert v.outcome is Outcome.OBSERVATION


def test_unnamed_title_change_is_finding():
    v = judge_non_destructive(rec(issue__title="old"), rec(issue__title="x"), [TITLE], {})
    assert v.outcome is Outcome.FINDING


def test_empty_to_set_is_additive():
    v = judge_non_destructive(rec(issue__title=None), rec(issue__title="x"), [TITLE], {})
    assert v.outcome is Outcome.PASS


def test_read_only_change_is_finding_and_quotes_schema():
    v = judge_read_only(rec(issue__title="a"), rec(issue__title="b"), [TITLE])
    assert v.outcome is Outcome.FINDING
    assert v.schema_text == SCHEMA_TEXT[Check.READ_ONLY]
    assert "issue.title" in v.detail


def test_read_only_timestamp_only_change_warns_but_passes():
    b = Recorded({"issue.title": "a"}, {"issue": "2026-01-01T00:00:00Z"})
    a = Recorded({"issue.title": "a"}, {"issue": "2026-01-02T00:00:00Z"})
    v = judge_read_only(b, a, [TITLE])
    assert v.outcome is Outcome.PASS
    assert any("updated_at" in w for w in v.warnings)


def test_idempotent_second_call_change_is_finding():
    v = judge_idempotent(
        rec(issue__labels=frozenset({"a"})),
        rec(issue__labels=frozenset({"a", "a2"})),
        [LABELS],
    )
    assert v.outcome is Outcome.FINDING


def test_pass_detail_names_fields():
    v = judge_read_only(
        rec(issue__labels=frozenset(), issue__title="a"),
        rec(issue__labels=frozenset(), issue__title="a"),
        [LABELS, TITLE],
    )
    assert v.detail == "no change observed in issue.labels, issue.title"
