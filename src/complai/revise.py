"""Stage 5 — propose a compliant rewrite, then re-check it. Cheap inner loop,
verified outer verdict.

Known weakness: the same model writes and judges. The trajectory is recorded so a
reviewer can see the work rather than trust a suspiciously clean result.
"""
from __future__ import annotations

from complai.check import check
from complai.llm import LLMClient
from complai.models import Attempt, Rule, RevisionResult, Verdict
from complai.prompts import REVISE_SYSTEM

MAX_ITERATIONS = 3

REVISE_SCHEMA = {
    "type": "object",
    "properties": {"revised_text": {"type": "string"}},
    "required": ["revised_text"],
}


def propose(text: str, violations: list[Verdict], rules: list[Rule], llm: LLMClient) -> str:
    by_id = {r.id: r for r in rules}
    findings = []
    for v in violations:
        rule = by_id.get(v.rule_id)
        findings.append(
            f"- {rule.title if rule else v.rule_id}: {v.reasoning}\n"
            f"  Requirement: {rule.requirement if rule else '(unknown)'}\n"
            f"  Mandated source text: {rule.source_quote if rule else '(unknown)'}"
        )
    payload = llm.structured(
        system=REVISE_SYSTEM,
        user=(
            f"# ORIGINAL COPY\n---\n{text}\n---\n\n"
            f"# VIOLATIONS TO FIX\n" + "\n".join(findings)
        ),
        schema=REVISE_SCHEMA,
        tool_name="revision",
        max_tokens=2048,
    )
    return payload["revised_text"]


def revise(
    text: str,
    rules: list[Rule],
    llm: LLMClient,
    input_type: str,
    max_iterations: int = MAX_ITERATIONS,
) -> RevisionResult:
    current = text
    attempts: list[Attempt] = []
    converged = False

    for iteration in range(1, max_iterations + 1):
        fast = check(current, rules, llm, input_type, verify_violations=False)
        attempts.append(Attempt(iteration, current, len(fast.violations)))
        if not fast.has_violations:
            converged = True
            break
        current = propose(current, fast.violations, rules, llm)

    final = check(current, rules, llm, input_type, verify_violations=True)
    return RevisionResult(
        original=text,
        final_text=current,
        attempts=attempts,
        final_check=final,
        converged=converged and not final.has_violations,
    )
