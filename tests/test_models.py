import pytest
from complai.models import Rule, Verdict, CheckResult, InvalidRule

RULE_DICT = {
    "id": "CYSEC-PS0419-RW-001",
    "source_doc": "PS-04-2019",
    "source_ref": "§3.5.12",
    "source_quote": "the CFD provider should not send directly or indirectly a communication",
    "title": "Risk warning must be present",
    "requirement": "Any communication marketing a CFD to retail clients must include the risk warning.",
    "category": "mechanical",
    "applies_to": ["marketing_communication", "client_communication"],
    "check_guidance": "Look for the mandated warning text. Absence is a violation.",
    "severity": "high",
}

def test_rule_round_trips():
    rule = Rule.from_dict(RULE_DICT)
    assert rule.id == "CYSEC-PS0419-RW-001"
    assert rule.is_mechanical
    assert rule.to_dict() == {**RULE_DICT, "source_span": None, "counter_example": None}

def test_rule_without_source_quote_is_rejected():
    bad = {**RULE_DICT, "source_quote": "  "}
    with pytest.raises(InvalidRule) as exc:
        Rule.from_dict(bad)
    assert "source_quote" in str(exc.value)

def test_rule_with_unknown_category_is_rejected():
    with pytest.raises(InvalidRule):
        Rule.from_dict({**RULE_DICT, "category": "vibes"})

def test_not_applicable_is_not_a_violation():
    result = CheckResult(
        input_type="marketing_communication",
        verdicts=[
            Verdict(rule_id="a", verdict="not_applicable", confidence=0.9, reasoning="n/a"),
            Verdict(rule_id="b", verdict="compliant", confidence=0.9, reasoning="fine"),
        ],
        rules_considered=2,
        fallback_used=False,
    )
    assert result.violations == []
    assert result.has_violations is False

def test_violations_are_extracted():
    v = Verdict(rule_id="c", verdict="violation", confidence=0.8, reasoning="no warning")
    result = CheckResult("marketing_communication", [v], rules_considered=1, fallback_used=False)
    assert result.violations == [v]
    assert result.has_violations is True
