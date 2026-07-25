import pytest
from complai.extract import extract_rules, save_rules, load_rules
from complai.llm import FakeLLM
from complai.models import InvalidRule

def _rule(rid, **over):
    base = {
        "id": rid, "source_doc": "PS-04-2019", "source_ref": "§3.5.12",
        "source_quote": "quoted passage", "title": "t", "requirement": "r",
        "category": "mechanical", "applies_to": ["marketing_communication"],
        "check_guidance": "g", "severity": "high",
    }
    return {**base, **over}

def test_extract_returns_typed_rules():
    fake = FakeLLM([{"rules": [_rule("R1"), _rule("R2", category="judgment")]}])
    rules = extract_rules("source text", "PS-04-2019", fake)
    assert [r.id for r in rules] == ["R1", "R2"]
    assert rules[0].is_mechanical and not rules[1].is_mechanical

def test_extraction_prompt_demands_checkability_and_quotes():
    fake = FakeLLM([{"rules": [_rule("R1")]}])
    extract_rules("source text", "PS-04-2019", fake)
    system = fake.calls[0]["system"].lower()
    assert "checkable" in system
    assert "verbatim" in system
    assert "source text" in fake.calls[0]["user"]

def test_rule_without_quote_is_rejected_loudly():
    fake = FakeLLM([{"rules": [_rule("R1", source_quote="")]}])
    with pytest.raises(InvalidRule):
        extract_rules("source text", "PS-04-2019", fake)

def test_rules_round_trip_through_disk(tmp_path):
    fake = FakeLLM([{"rules": [_rule("R1")]}])
    rules = extract_rules("source text", "PS-04-2019", fake)
    path = tmp_path / "rules.json"
    save_rules(rules, path)
    assert [r.id for r in load_rules(path)] == ["R1"]

def test_source_span_is_located_when_quote_appears_in_text():
    quote = "the appropriate risk warning"
    text = f"prefix prefix {quote} suffix"
    fake = FakeLLM([{"rules": [_rule("R1", source_quote=quote)]}])
    rules = extract_rules(text, "PS-04-2019", fake)
    start, end = rules[0].source_span
    assert text[start:end] == quote
