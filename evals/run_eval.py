"""Regression harness for the compliance checker.

Eight cases is not a statistically meaningful evaluation and this file does not
pretend otherwise. It exists so that a change to a prompt has to justify itself
against labelled examples instead of against an impression, and so that the
tiered-spread carve-out keeps being a case the checker gets right rather than
one it got right once.

Precision is reported separately from recall on purpose. Recall is the easy
half: a checker that flags everything scores perfectly on it and is worthless.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from complai.check import check
from complai.config import load_settings
from complai.extract import load_rules
from complai.gate import classify
from complai.llm import AnthropicClient
from complai.models import CheckResult

CASES_PATH = Path("evals/cases.yaml")


def _tag_matches(expected_id: str, rule_id: str) -> bool:
    """Exact prefix match of an expected rule id against a violated rule id.

    This replaced fuzzy matching of semantic tags against rule titles, which
    silently attributed a match to the WRONG rule: "prohibited_incentive_bonus"
    matched the tiered-spread carve-out, whose title reads "...are not prohibited
    incentives". A harness that mis-attributes matches produces confident numbers
    about nothing, which is worse than no harness.
    """
    return rule_id.startswith(expected_id)


def score(expected: dict, actual: CheckResult, rule_ids: list[str] | None = None) -> dict:
    violated = list(rule_ids) if rule_ids is not None else [v.rule_id for v in actual.violations]
    expected_ids = list(expected.get("expect_violations", []))

    matched, unmatched = [], list(violated)
    for expected_id in expected_ids:
        for rule_id in list(unmatched):
            if _tag_matches(expected_id, rule_id):
                matched.append(expected_id)
                unmatched.remove(rule_id)
                break

    return {
        "true_positives": len(matched),
        "false_negatives": len(expected_ids) - len(matched),
        "false_positives": len(unmatched),
    }


def main() -> int:
    cases = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
    rules = load_rules()
    families = {r.id: r.category for r in rules}
    llm = AnthropicClient(load_settings())

    totals = {"true_positives": 0, "false_positives": 0, "false_negatives": 0}
    rows: list[tuple[str, str, str]] = []
    gate_correct = 0

    for case in cases:
        gate = classify(case["text"], llm)
        gate_ok = gate.input_type == case["expect_input_type"]
        gate_correct += gate_ok

        if not gate.proceed:
            rows.append((
                case["id"],
                "gate declined",
                "ok" if gate_ok else f"GATE WRONG (got {gate.input_type})",
            ))
            continue

        result = check(case["text"], rules, llm, gate.input_type)
        s = score(case, result)
        for key in totals:
            totals[key] += s[key]
        mechanical = sum(1 for v in result.violations if families.get(v.rule_id) == "mechanical")
        judgment = len(result.violations) - mechanical
        rows.append((
            case["id"],
            f"tp={s['true_positives']} fp={s['false_positives']} fn={s['false_negatives']}",
            f"{mechanical} mechanical / {judgment} judgment"
            + ("" if gate_ok else f"  GATE WRONG (got {gate.input_type})"),
        ))

    tp, fp, fn = totals["true_positives"], totals["false_positives"], totals["false_negatives"]
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0

    print(f"{'case':<32} {'score':<28} notes")
    print("-" * 92)
    for row in rows:
        print(f"{row[0]:<32} {row[1]:<28} {row[2]}")
    print("-" * 92)
    print(f"gate accuracy: {gate_correct}/{len(cases)}")
    print(f"precision: {precision:.2f}   recall: {recall:.2f}   (tp={tp} fp={fp} fn={fn})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
