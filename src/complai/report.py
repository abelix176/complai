"""Rendering only. Never calls the API, never touches the filesystem."""
from __future__ import annotations

import json
from dataclasses import asdict

from complai.models import CheckResult, Rule, Verdict

_VERDICT_ORDER = {"violation": 0, "needs_review": 1, "compliant": 2, "not_applicable": 3}
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_MARK = {
    "violation": "✗", "needs_review": "?", "compliant": "✓", "not_applicable": "–",
}


def sort_verdicts(verdicts: list[Verdict], rules: list[Rule]) -> list[Verdict]:
    severity = {r.id: r.severity for r in rules}
    return sorted(
        verdicts,
        key=lambda v: (
            _VERDICT_ORDER.get(v.verdict, 9),
            _SEVERITY_ORDER.get(severity.get(v.rule_id, "low"), 9),
            v.rule_id,
        ),
    )


def _header(result: CheckResult) -> list[str]:
    lines = [
        f"Input classified as: {result.input_type}",
        f"Rules considered: {result.rules_considered}",
    ]
    if result.fallback_used:
        lines.append(
            "Note: rule filtering was too narrow, so the full rulebook was applied."
        )
    violations = len(result.violations)
    lines.append(
        f"Result: {violations} violation(s)" if violations else "Result: no violations found"
    )
    return lines


def render_terminal(result: CheckResult, rules: list[Rule]) -> str:
    by_id = {r.id: r for r in rules}
    lines = _header(result) + [""]
    for verdict in sort_verdicts(result.verdicts, rules):
        rule = by_id.get(verdict.rule_id)
        title = rule.title if rule else verdict.rule_id
        ref = f"{rule.source_doc} {rule.source_ref}" if rule else "unknown source"
        mark = _MARK.get(verdict.verdict, "?")
        lines.append(f"{mark} [{verdict.verdict.upper()}] {title}  ({ref})")
        lines.append(f"    {verdict.reasoning}")
        if verdict.evidence_span:
            lines.append(f"    evidence: \"{verdict.evidence_span}\"")
        if verdict.verified:
            lines.append(f"    verified against source: {verdict.verification_note}")
        lines.append(f"    confidence: {verdict.confidence:.0%}")
        lines.append("")
    return "\n".join(lines)


def render_markdown(result: CheckResult, rules: list[Rule]) -> str:
    by_id = {r.id: r for r in rules}
    lines = ["# Compliance report", ""] + _header(result)
    lines += ["", "| Rule | Verdict | Severity | Source | Reasoning |", "|---|---|---|---|---|"]
    for verdict in sort_verdicts(result.verdicts, rules):
        rule = by_id.get(verdict.rule_id)
        title = rule.title if rule else verdict.rule_id
        severity = rule.severity if rule else "?"
        ref = f"{rule.source_doc} {rule.source_ref}" if rule else "?"
        reasoning = verdict.reasoning.replace("|", "\\|")
        lines.append(
            f"| {title} | **{verdict.verdict.upper()}** | {severity} | {ref} | {reasoning} |"
        )
    return "\n".join(lines) + "\n"


def to_json(result: CheckResult) -> str:
    return json.dumps(asdict(result), indent=2, ensure_ascii=False)
