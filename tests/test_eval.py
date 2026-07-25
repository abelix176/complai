from complai.models import CheckResult, Verdict
from evals.run_eval import score


def _result(*pairs):
    return CheckResult(
        "marketing_communication",
        [Verdict(rid, v, 0.9, "r") for rid, v in pairs],
        rules_considered=3,
        fallback_used=False,
    )


def test_expected_rule_that_fired_is_a_true_positive():
    expected = {"expect_violations": ["CYSEC-RW-001"]}
    s = score(expected, _result(("CYSEC-RW-001", "violation"), ("CYSEC-MIS-001", "compliant")))
    assert s == {"true_positives": 1, "false_positives": 0, "false_negatives": 0}


def test_prefix_matches_a_rule_family():
    expected = {"expect_violations": ["CYSEC-RW"]}
    s = score(expected, _result(("CYSEC-RW-003", "violation")))
    assert s["true_positives"] == 1


def test_false_positive_on_a_clean_case_is_counted():
    """The failure mode that matters: flagging copy that is actually compliant."""
    s = score({"expect_violations": []}, _result(("CYSEC-RW-001", "violation")))
    assert s["false_positives"] == 1


def test_missed_violation_is_counted():
    s = score({"expect_violations": ["CYSEC-MIS-001"]}, _result(("CYSEC-MIS-001", "compliant")))
    assert s["false_negatives"] == 1


def test_each_expected_rule_consumes_only_one_violation():
    expected = {"expect_violations": ["CYSEC-RW-001", "CYSEC-MIS-001"]}
    s = score(expected, _result(("CYSEC-RW-001", "violation")))
    assert s["true_positives"] == 1
    assert s["false_negatives"] == 1


def test_a_tag_never_matches_an_unrelated_rule():
    """Regression: fuzzy title matching scored the incentives tag against the
    tiered-spread carve-out, whose title contains 'not prohibited incentives'."""
    expected = {"expect_violations": ["CYSEC-PS0419-INCENTIVE"]}
    s = score(expected, _result(("CYSEC-PS0419-TIERED-001", "violation")))
    assert s["true_positives"] == 0
    assert s["false_positives"] == 1


def test_not_applicable_never_counts_as_a_violation():
    s = score({"expect_violations": []}, _result(("R1", "not_applicable"), ("R2", "needs_review")))
    assert s["false_positives"] == 0
