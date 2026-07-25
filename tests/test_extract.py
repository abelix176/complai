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


def test_rule_dicts_accepts_the_plain_shape():
    from complai.extract import rule_dicts
    assert rule_dicts({"rules": [{"id": "R1"}]}) == [{"id": "R1"}]


def test_rule_dicts_unwraps_double_nesting():
    """Regression: forced tool-use intermittently returns {"rules": {"rules": [...]}}."""
    from complai.extract import rule_dicts
    assert rule_dicts({"rules": {"rules": [{"id": "R1"}]}}) == [{"id": "R1"}]


def test_rule_dicts_refuses_a_shape_it_cannot_understand():
    import pytest as _pytest
    from complai.extract import rule_dicts
    with _pytest.raises(ValueError):
        rule_dicts({"unexpected": 42})


def test_locate_tolerates_reflowed_whitespace():
    """The model reflows quotes — table padding and wrapped lines are lost —
    so exact matching misses passages that are genuinely present."""
    from complai.extract import locate
    text = "Major Currency  Pairs  3,33%\n  30:1 applies"
    span = locate("Major Currency Pairs 3,33% 30:1", text)
    assert span is not None
    assert text[span[0]:span[1]].split() == "Major Currency Pairs 3,33% 30:1".split()


def test_locate_returns_none_for_absent_text():
    from complai.extract import locate
    assert locate("this phrase is not present", "some other document") is None


def test_ground_snaps_the_quote_to_the_sources_own_wording():
    from complai.extract import ground
    from complai.models import Rule
    text = "The risk warning shall be in a layout\n   ensuring its prominence."
    rule = Rule.from_dict({
        "id": "R1", "source_doc": "PS", "source_ref": "A(1)",
        "source_quote": "risk warning shall be in a layout ensuring its prominence",
        "title": "t", "requirement": "r", "category": "mechanical",
        "applies_to": ["marketing_communication"], "check_guidance": "g", "severity": "high",
    })
    grounded = ground(rule, text)
    assert grounded.source_quote in text
    assert grounded.source_span is not None
