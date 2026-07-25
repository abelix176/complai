from complai.check import check, screen, select_rules, verify
from complai.llm import FakeLLM
from complai.models import Rule, Verdict

def _rule(rid, applies_to=None, **over):
    return Rule.from_dict({
        "id": rid, "source_doc": "PS-04-2019", "source_ref": "§3.5.12",
        "source_quote": "verbatim passage", "title": "t", "requirement": "r",
        "category": "mechanical",
        "applies_to": applies_to or ["marketing_communication"],
        "check_guidance": "g", "severity": "high", **over,
    })

MARKETING = ["marketing_communication"]
BOTH = ["marketing_communication", "client_communication"]

def test_select_rules_filters_by_input_type():
    rules = [_rule(f"R{i}", MARKETING) for i in range(4)] + [_rule("C1", ["client_communication"])]
    selected, fallback = select_rules(rules, "marketing_communication")
    assert [r.id for r in selected] == ["R0", "R1", "R2", "R3"]
    assert fallback is False

def test_select_rules_falls_back_to_full_book_when_filter_is_too_narrow():
    rules = [_rule("R0", MARKETING), _rule("C1", ["client_communication"])]
    selected, fallback = select_rules(rules, "client_communication")
    assert len(selected) == 2
    assert fallback is True

def test_screen_makes_one_call_for_all_rules():
    rules = [_rule("R1"), _rule("R2")]
    fake = FakeLLM([{"verdicts": [
        {"rule_id": "R1", "verdict": "violation", "confidence": 0.9,
         "reasoning": "no warning", "evidence_span": "get rich"},
        {"rule_id": "R2", "verdict": "compliant", "confidence": 0.8, "reasoning": "fine"},
    ]}])
    verdicts = screen("get rich tomorrow", rules, fake)
    assert len(fake.calls) == 1
    assert [v.verdict for v in verdicts] == ["violation", "compliant"]

def test_screen_prompt_includes_counter_examples():
    rules = [_rule("R1", counter_example="tiered fee discounts are not caught")]
    fake = FakeLLM([{"verdicts": []}])
    screen("text", rules, fake)
    assert "tiered fee discounts are not caught" in fake.calls[0]["user"]

def test_verify_confirms_a_violation():
    rule = _rule("R1")
    v = Verdict(rule_id="R1", verdict="violation", confidence=0.9, reasoning="no warning")
    fake = FakeLLM([{"confirmed": True, "note": "no warning text present"}])
    out = verify("text", v, rule, fake)
    assert out.verdict == "violation"
    assert out.verified is True
    assert out.verification_note == "no warning text present"

def test_verify_overturns_and_downgrades_to_needs_review():
    rule = _rule("R1")
    v = Verdict(rule_id="R1", verdict="violation", confidence=0.9, reasoning="looks like a bonus")
    fake = FakeLLM([{"confirmed": False, "note": "this is a tiered spread, expressly carved out"}])
    out = verify("text", v, rule, fake)
    assert out.verdict == "needs_review"
    assert out.verified is True
    assert "carved out" in out.verification_note

def test_verify_prompt_carries_the_verbatim_source_quote():
    rule = _rule("R1")
    v = Verdict(rule_id="R1", verdict="violation", confidence=0.9, reasoning="r")
    fake = FakeLLM([{"confirmed": True, "note": "n"}])
    verify("text", v, rule, fake)
    assert "verbatim passage" in fake.calls[0]["user"]

def test_check_verifies_only_violations():
    rules = [_rule("R1"), _rule("R2"), _rule("R3")]
    fake = FakeLLM([
        {"verdicts": [
            {"rule_id": "R1", "verdict": "violation", "confidence": 0.9, "reasoning": "a"},
            {"rule_id": "R2", "verdict": "compliant", "confidence": 0.9, "reasoning": "b"},
            {"rule_id": "R3", "verdict": "not_applicable", "confidence": 0.9, "reasoning": "c"},
        ]},
        {"confirmed": True, "note": "confirmed"},
    ])
    result = check("text", rules, fake, "marketing_communication")
    assert len(fake.calls) == 2  # one screen + one verification
    assert result.has_violations
    assert result.violations[0].verified is True

def test_check_can_skip_verification():
    rules = [_rule("R1"), _rule("R2"), _rule("R3")]
    fake = FakeLLM([{"verdicts": [
        {"rule_id": "R1", "verdict": "violation", "confidence": 0.9, "reasoning": "a"},
    ]}])
    result = check("text", rules, fake, "marketing_communication", verify_violations=False)
    assert len(fake.calls) == 1
    assert result.violations[0].verified is False
