import json

from complai.models import CheckResult, Rule, Verdict
from complai.report import render_markdown, render_terminal, sort_verdicts, to_json

def _rule(rid, severity="high"):
    return Rule.from_dict({
        "id": rid, "source_doc": "PS-04-2019", "source_ref": "§3.5.12",
        "source_quote": "verbatim passage", "title": f"Title {rid}", "requirement": "r",
        "category": "mechanical", "applies_to": ["marketing_communication"],
        "check_guidance": "g", "severity": severity,
    })

def test_violations_sort_first_then_by_severity():
    rules = [_rule("A", "low"), _rule("B", "high"), _rule("C", "high")]
    verdicts = [
        Verdict("A", "violation", 0.9, "low sev violation"),
        Verdict("C", "compliant", 0.9, "fine"),
        Verdict("B", "violation", 0.9, "high sev violation"),
    ]
    ordered = sort_verdicts(verdicts, rules)
    assert [v.rule_id for v in ordered] == ["B", "A", "C"]

def test_terminal_report_names_every_rule_and_shows_the_citation():
    rules = [_rule("A")]
    result = CheckResult("marketing_communication", [Verdict("A", "violation", 0.9, "no warning")], 1, False)
    out = render_terminal(result, rules)
    assert "Title A" in out
    assert "§3.5.12" in out
    assert "no warning" in out

def test_report_discloses_the_fallback():
    rules = [_rule("A")]
    result = CheckResult("client_communication", [Verdict("A", "compliant", 0.9, "ok")], 1, True)
    assert "full rulebook" in render_terminal(result, rules).lower()

def test_markdown_report_has_a_verdict_table():
    rules = [_rule("A")]
    result = CheckResult("marketing_communication", [Verdict("A", "violation", 0.9, "x")], 1, False)
    md = render_markdown(result, rules)
    assert "| Rule |" in md
    assert "VIOLATION" in md.upper()

def test_json_output_round_trips():
    rules = [_rule("A")]
    result = CheckResult("marketing_communication", [Verdict("A", "violation", 0.9, "x")], 1, False)
    parsed = json.loads(to_json(result))
    assert parsed["input_type"] == "marketing_communication"
    assert parsed["verdicts"][0]["rule_id"] == "A"
