from complai.llm import FakeLLM
from complai.models import Rule
from complai.revise import MAX_ITERATIONS, revise

def _rule(rid):
    return Rule.from_dict({
        "id": rid, "source_doc": "PS-04-2019", "source_ref": "§3.5.12",
        "source_quote": "verbatim passage", "title": "t", "requirement": "r",
        "category": "mechanical", "applies_to": ["marketing_communication"],
        "check_guidance": "g", "severity": "high",
    })

RULES = [_rule("R1"), _rule("R2"), _rule("R3")]

def _screen(*verdicts):
    return {"verdicts": [
        {"rule_id": rid, "verdict": v, "confidence": 0.9, "reasoning": "r"}
        for rid, v in verdicts
    ]}

def test_clean_text_is_never_rewritten():
    fake = FakeLLM([
        _screen(("R1", "compliant")),          # inner fast check
        _screen(("R1", "compliant")),          # final verified check
    ])
    result = revise("already compliant copy", RULES, fake, "marketing_communication")
    assert result.final_text == "already compliant copy"
    assert result.converged is True
    assert len(result.attempts) == 1
    assert result.attempts[0].violation_count == 0

def test_loop_rewrites_until_clean_and_records_the_trajectory():
    fake = FakeLLM([
        _screen(("R1", "violation"), ("R2", "violation")),   # attempt 1: 2 violations
        {"revised_text": "better copy"},
        _screen(("R1", "violation")),                        # attempt 2: 1 violation
        {"revised_text": "compliant copy"},
        _screen(("R1", "compliant")),                        # attempt 3: clean
        _screen(("R1", "compliant")),                        # final verified check
    ])
    result = revise("get rich tomorrow", RULES, fake, "marketing_communication")
    assert result.final_text == "compliant copy"
    assert result.converged is True
    assert [a.violation_count for a in result.attempts] == [2, 1, 0]

def test_loop_stops_at_max_iterations_without_converging():
    responses = []
    for _ in range(MAX_ITERATIONS):
        responses.append(_screen(("R1", "violation")))   # inner fast check
        responses.append({"revised_text": "still bad"})  # rewrite
    responses.append(_screen(("R1", "violation")))       # final check, still failing
    responses.append({"confirmed": True, "note": "still no warning"})  # its verification
    fake = FakeLLM(responses)
    result = revise("hopeless", RULES, fake, "marketing_communication")
    assert result.converged is False
    assert len(result.attempts) == MAX_ITERATIONS
    assert result.final_check.violations[0].verified is True

def test_revision_prompt_demands_verbatim_warning_insertion():
    fake = FakeLLM([
        _screen(("R1", "violation")),
        {"revised_text": "fixed"},
        _screen(("R1", "compliant")),
        _screen(("R1", "compliant")),
    ])
    revise("bad copy", RULES, fake, "marketing_communication")
    revise_call = [c for c in fake.calls if c["tool_name"] == "revision"][0]
    assert "verbatim" in revise_call["system"].lower()
