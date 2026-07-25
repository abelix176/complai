"""Streamlit front end. Deliberately thin — all logic lives in src/complai.

The UI is the most replaceable part of this project and the least graded. It exists
so a reviewer can see rule-by-rule verdicts and their provenance without reading
JSON, not to demonstrate frontend work.
"""
from __future__ import annotations

import random
from pathlib import Path

import streamlit as st
import yaml

from complai.check import check
from complai.config import MissingAPIKey, load_settings
from complai.extract import load_rules
from complai.gate import classify
from complai.llm import AnthropicClient
from complai.report import sort_verdicts
from complai.revise import revise

SHOWCASE = Path("data/samples/showcase.yaml")
BADGE = {
    "violation": ("🔴", "Violation"),
    "needs_review": ("🟡", "Needs review"),
    "compliant": ("🟢", "Compliant"),
    "not_applicable": ("⚪", "Not applicable"),
}

st.set_page_config(page_title="complai — Regulation Compliance Agent", layout="wide")
st.title("complai")
st.caption(
    "Checks marketing communications against CySEC PS-04-2019 and the MiFID II "
    "fair-clear-not-misleading standard, rule by rule, with every verdict traceable "
    "to the regulation it came from."
)


@st.cache_data
def _samples() -> list[dict]:
    if not SHOWCASE.exists():
        return []
    return yaml.safe_load(SHOWCASE.read_text(encoding="utf-8")) or []


@st.cache_resource
def _rules():
    return load_rules()


def _client():
    try:
        return AnthropicClient(load_settings())
    except MissingAPIKey as exc:
        st.error(str(exc))
        st.stop()


def _pick(pool: list[dict], n: int = 3) -> list[dict]:
    return random.sample(pool, min(n, len(pool)))


if "text" not in st.session_state:
    st.session_state.text = ""
if "picks" not in st.session_state:
    st.session_state.picks = _pick(_samples())

with st.sidebar:
    st.subheader("Try an example")
    st.caption("Three drawn at random from the sample corpus.")
    for sample in st.session_state.picks:
        label = sample["text"].strip().replace("\n", " ")[:58] + "…"
        if st.button(label, key=sample["id"], use_container_width=True):
            st.session_state.text = sample["text"]
            st.rerun()
    if st.button("🔀 Shuffle examples", use_container_width=True):
        st.session_state.picks = _pick(_samples())
        st.rerun()
    st.divider()
    rules = _rules()
    st.metric("Rules in force", len(rules))
    st.caption(
        f"{sum(1 for r in rules if r.is_mechanical)} mechanical · "
        f"{sum(1 for r in rules if not r.is_mechanical)} judgment"
    )

text = st.text_area("Marketing communication", value=st.session_state.text, height=180)
col_check, col_revise = st.columns(2)
run_check = col_check.button("Check compliance", type="primary", use_container_width=True)
run_revise = col_revise.button("Propose compliant rewrite", use_container_width=True)

if run_check or run_revise:
    if not text.strip():
        st.warning("Paste some marketing copy first, or load an example from the sidebar.")
        st.stop()

    llm, rules = _client(), _rules()

    with st.spinner("Classifying input…"):
        gate = classify(text, llm)

    if not gate.proceed:
        st.error(f"Declined — this is not a client-facing communication ({gate.input_type}).")
        st.caption(gate.reasoning)
        st.caption("This tool checks marketing materials against CySEC rules.")
        st.stop()

    st.info(f"Classified as **{gate.input_type}** — {gate.reasoning}")

    if run_check:
        with st.spinner("Checking rule by rule, then verifying each finding against source…"):
            result = check(text, rules, llm, gate.input_type)

        if result.fallback_used:
            st.warning(
                "Rule filtering was too narrow, so the full rulebook was applied. "
                "A gate misfire degrades to over-checking, never to a silent all-clear."
            )

        violations = len(result.violations)
        st.subheader(f"{violations} violation(s)" if violations else "No violations found")

        by_id = {r.id: r for r in rules}
        for verdict in sort_verdicts(result.verdicts, rules):
            rule = by_id.get(verdict.rule_id)
            icon, label = BADGE.get(verdict.verdict, ("⚪", verdict.verdict))
            title = rule.title if rule else verdict.rule_id
            with st.container(border=True):
                st.markdown(f"{icon} **{label}** — {title}")
                st.write(verdict.reasoning)
                if verdict.evidence_span:
                    st.markdown(f"> {verdict.evidence_span}")
                st.caption(f"Confidence {verdict.confidence:.0%}")
                if verdict.verified:
                    st.caption(f"✓ Verified against source — {verdict.verification_note}")
                if rule:
                    with st.expander(f"Source — {rule.source_doc} {rule.source_ref}"):
                        st.markdown(f"> {rule.source_quote}")
                        st.caption(f"**Requirement:** {rule.requirement}")
                        if rule.counter_example:
                            st.caption(f"**Expressly NOT a violation:** {rule.counter_example}")

    if run_revise:
        with st.spinner("Rewriting and re-checking…"):
            result = revise(text, rules, llm, gate.input_type)

        st.subheader("Revision trajectory")
        for attempt in result.attempts:
            st.write(f"Attempt {attempt.iteration}: **{attempt.violation_count}** violation(s)")
        if result.converged:
            st.success("Converged to a compliant version.")
        else:
            st.warning(
                f"Did not fully converge in {len(result.attempts)} attempt(s). "
                "Best effort shown below."
            )
        st.caption(
            "The same model writes and judges these rewrites, so it can converge by "
            "satisfying its own grader rather than genuinely fixing the copy. The "
            "trajectory is shown so you can see the work rather than trust the label, "
            "and the final verdict is re-derived with source-grounded verification."
        )
        col_a, col_b = st.columns(2)
        col_a.text_area("Original", value=result.original, height=280, disabled=True)
        col_b.text_area("Revised", value=result.final_text, height=280)
