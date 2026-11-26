from mcp.types import Tool

from mcp_annotation_check.claims import SCHEMA_TEXT, Check, Claims, applicable_checks, claims_of


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
    assert SCHEMA_TEXT[Check.READ_ONLY] == "If true, the tool does not modify its environment."
    assert SCHEMA_TEXT[Check.IDEMPOTENT] == "If true, calling the tool repeatedly with the same arguments will have no additional effect on its environment."


def test_claims_of_reads_annotations():
    from mcp.types import ToolAnnotations
    t = Tool(name="t", inputSchema={"type": "object"}, annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    assert claims_of(t) == Claims(read_only=True, destructive=False, idempotent=None)
