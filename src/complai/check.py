"""Stage 4 — screen every rule in one call, then verify each hit against source."""
from __future__ import annotations

from complai.llm import LLMClient
from complai.models import CheckResult, Rule, Verdict
from complai.prompts import SCREEN_SYSTEM, VERIFY_SYSTEM

SCREEN_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule_id": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["compliant", "violation", "not_applicable", "needs_review"],
                    },
                    "confidence": {"type": "number"},
                    "reasoning": {"type": "string"},
                    "evidence_span": {"type": "string"},
                },
                "required": ["rule_id", "verdict", "confidence", "reasoning"],
            },
        }
    },
    "required": ["verdicts"],
}

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "confirmed": {"type": "boolean"},
        "note": {"type": "string"},
    },
    "required": ["confirmed", "note"],
}


def _render_rule(rule: Rule) -> str:
    lines = [
        f"### {rule.id} [{rule.category}, severity={rule.severity}]",
        f"Title: {rule.title}",
        f"Requirement: {rule.requirement}",
        f"Source: {rule.source_doc} {rule.source_ref}",
        f"How to check: {rule.check_guidance}",
    ]
    if rule.counter_example:
        lines.append(f"NOT a violation: {rule.counter_example}")
    return "\n".join(lines)


def select_rules(
    rules: list[Rule], input_type: str, min_rules: int = 3
) -> tuple[list[Rule], bool]:
    """Narrow the rulebook to the input type.

    A gate misfire must degrade to over-checking, never to a silent all-clear,
    so too-narrow a selection falls back to the whole book.
    """
    filtered = [r for r in rules if input_type in r.applies_to]
    if len(filtered) < min_rules:
        return rules, True
    return filtered, False


def screen(text: str, rules: list[Rule], llm: LLMClient) -> list[Verdict]:
    rulebook = "\n\n".join(_render_rule(r) for r in rules)
    payload = llm.structured(
        system=SCREEN_SYSTEM,
        user=(
            f"# RULEBOOK ({len(rules)} rules)\n\n{rulebook}\n\n"
            f"# SUBMITTED COMMUNICATION\n\n---\n{text}\n---\n\n"
            f"Return one verdict per rule, {len(rules)} in total."
        ),
        schema=SCREEN_SCHEMA,
        tool_name="verdicts",
        max_tokens=8192,
    )
    return [Verdict.from_dict(d) for d in payload["verdicts"]]


def verify(text: str, verdict: Verdict, rule: Rule, llm: LLMClient) -> Verdict:
    payload = llm.structured(
        system=VERIFY_SYSTEM,
        user=(
            f"# REGULATION (verbatim, {rule.source_doc} {rule.source_ref})\n"
            f"{rule.source_quote}\n\n"
            f"# RULE AS RECORDED\n{rule.requirement}\n\n"
            f"# SUBMITTED COMMUNICATION\n---\n{text}\n---\n\n"
            f"# ALLEGED VIOLATION\n{verdict.reasoning}\n"
            f"Cited evidence: {verdict.evidence_span or '(none — alleged absence)'}"
        ),
        schema=VERIFY_SCHEMA,
        tool_name="verification",
        max_tokens=1024,
    )
    verdict.verified = True
    verdict.verification_note = payload["note"]
    if not payload["confirmed"]:
        verdict.verdict = "needs_review"
    return verdict


def check(
    text: str,
    rules: list[Rule],
    llm: LLMClient,
    input_type: str,
    verify_violations: bool = True,
) -> CheckResult:
    selected, fallback = select_rules(rules, input_type)
    verdicts = screen(text, selected, llm)
    if verify_violations:
        by_id = {r.id: r for r in selected}
        for verdict in verdicts:
            if verdict.verdict == "violation" and verdict.rule_id in by_id:
                verify(text, verdict, by_id[verdict.rule_id], llm)
    return CheckResult(
        input_type=input_type,
        verdicts=verdicts,
        rules_considered=len(selected),
        fallback_used=fallback,
    )
