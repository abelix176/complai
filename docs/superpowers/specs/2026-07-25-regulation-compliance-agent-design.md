# Design — Regulation Compliance Agent (`complai`)

**Date:** 2026-07-25
**Author:** Felix Abrecht
**Status:** Approved for implementation
**Time box:** 2–3 hours of author time, AI-accelerated

---

## 1. What we are building

An LLM-powered tool that acts as a compliance officer for **marketing communications** in
the CFD/retail-trading space. It ingests a real regulatory source, decomposes it into
discrete checkable rules, and evaluates a supplied piece of marketing copy rule by rule,
producing an explicit verdict and reasoning for each rule.

Beyond the base requirement it also: refuses input that is not a marketing communication,
verifies each alleged violation against the original regulatory passage, and can propose a
compliant rewrite by looping its own checker until the copy passes.

### Why this framing

The brief contains a quiet constraint: *"It is the marketing materials compliance check,
not just random text from nowhere."* A submission that pipes any string into a checker has
missed it. Input classification is therefore a first-class stage, not a nicety.

---

## 2. Regulatory corpus

### Primary source — CySEC PS-04-2019

*Policy Statement on the imposition of national measures in relation to the marketing,
distribution and sale of CFDs*, issued 27 September 2019.
`https://www.cysec.gov.cy/CMSPages/GetFile.aspx?guid=2489c262-ffc6-4f64-ab57-90667c953d45`

Verified reachable and machine-readable (1.1 MB PDF, 30 pages). Chosen because:

- It is unambiguously real, public, and CySEC-issued — one of the two regulators the brief names.
- It is **directly about marketing communications**, so nearly every rule is checkable
  against a marketing blurb rather than against a firm's internal systems.
- It contains **verbatim mandated text** (the standardised risk warnings, Sections B–G),
  which yields genuinely mechanical, near-deterministic rules — a strong contrast class
  against the judgment rules and a good test of extraction quality.
- It is domain-adjacent to eToro's actual business, which makes the demo land.

Representative rules the extractor should find:

| Ref | Requirement | Type |
|---|---|---|
| §3.5.12 | No communication relating to marketing/distribution/sale of a CFD may be published to retail clients unless it includes the appropriate risk warning | mechanical |
| Section A(1) | Risk warning must be prominent, in a font size at least equal to the predominant font size, and in the same language as the communication | mechanical |
| Sections B/C/D | Correct warning template per medium: durable medium/webpage, abbreviated, or reduced-character (the last also requires a direct link to the Section B webpage) | mechanical |
| Section A(6) | Warning must carry an up-to-date provider-specific loss percentage, recalculated quarterly over a 12-month window | mechanical |
| Sections E–G | Firms without 12 months of retail data use the standard warning: *"The vast majority of retail investor accounts lose money when trading CFDs."* | mechanical |
| §3.4.3 | No direct or indirect payment, monetary or excluded non-monetary benefit, other than realised profits — i.e. no bonuses or trading incentives | mechanical |
| §3.4.10 | **Carve-out:** tiered fee/spread discounts are *not* within the prohibition | mechanical (negative) |
| §2.3 | Aggressive marketing techniques and inadequate risk disclosure are the mischief the measures address | judgment |

§3.4.10 is deliberately included: it is a rule that a naive checker **over-flags**. It earns
its place in the eval set as a false-positive probe.

### Secondary source — the "fair, clear and not misleading" layer

PS-04-2019 governs risk warnings and incentives but does not itself state the general
standard that marketing must be fair, clear and not misleading. Without that layer, the
brief's own example — *"Install our app and get rich tomorrow 🚀🚀🚀"* — would trip only the
missing-risk-warning rule, and the misleading-return-promise and urgency dimensions would go
undetected. So a second, deliberately small source is ingested through the same pipeline:

- **MiFID II Article 24(3)** — all information including marketing communications must be
  fair, clear and not misleading, and marketing communications must be clearly identifiable
  as such.
- **Commission Delegated Regulation (EU) 2017/565, Article 44** — the operative detail:
  benefits may not be emphasised without a fair and prominent indication of relevant risks;
  important items, statements or warnings may not be disguised, diminished or obscured.

Both are public EUR-Lex texts. They are fetched once, trimmed to the relevant articles, and
committed to `data/sources/` so the reviewer never depends on network access.

**Scoping decision:** two sources, one pipeline. Not a broad corpus sweep. The README states
this plainly — the goal is a defensible vertical slice, not rule coverage theatre.

---

## 3. Architecture

Four separable stages, matching the rubric's *ingestion → decomposition → eval* line, with a
revision loop wrapped around the evaluator.

```
                    ┌──────────────────────────────────────────┐
  regulation PDF ──▶│ 1. INGEST                                │
  EUR-Lex HTML  ──▶ │    fetch → text → data/sources/*.txt     │  committed
                    └──────────────┬───────────────────────────┘
                                   ▼
                    ┌──────────────────────────────────────────┐
                    │ 2. EXTRACT  (one-time, LLM)              │
                    │    text → data/rules/*.json              │  committed
                    └──────────────┬───────────────────────────┘
                                   ▼
  marketing text ─▶ ┌──────────────────────────────────────────┐
                    │ 3. GATE     classify input type          │
                    │    out-of-scope → decline + explain      │
                    └──────────────┬───────────────────────────┘
                                   ▼
                    ┌──────────────────────────────────────────┐
                    │ 4. CHECK                                 │
                    │    pass 1: screen ALL rules (1 call)     │
                    │    pass 2: verify each violation against │
                    │            its source passage            │
                    └──────────────┬───────────────────────────┘
                                   ▼
                    ┌──────────────────────────────────────────┐
                    │ 5. REVISE   (optional)                   │
                    │    rewrite → re-check → repeat, max 3    │
                    └──────────────┬───────────────────────────┘
                                   ▼
                         report.py → CLI / Streamlit
```

### Module layout

```
src/complai/
  config.py      env loading, model selection, client construction
  models.py      typed dataclasses: Rule, Verdict, CheckResult, GateResult, Revision
  ingest.py      PDF + HTML → normalised text
  extract.py     text → rules (LLM, structured output)
  gate.py        input classification
  check.py       two-pass compliance evaluation
  revise.py      rewrite-and-recheck loop
  report.py      rendering: terminal, markdown, JSON
  cli.py         `python -m complai <command>`
app.py           Streamlit UI
evals/
  cases.yaml     labelled fixtures
  run_eval.py    scorer
```

Each module has one job and a typed boundary. `check.py` never touches the filesystem;
`report.py` never calls the API. This is what makes the stages "clean and separable" in the
sense the rubric asks about, and it is what makes the eval harness possible at all.

### Why rules are a committed artifact

Extraction runs as a **one-time preprocessing pass** whose output (`data/rules/*.json`) is
committed to the repo. Three reasons:

1. The reviewer can read the decomposition quality directly, in a diffable file, without
   spending a cent or waiting on an API call.
2. The demo starts instantly and deterministically.
3. Rules become a reviewable artifact that a compliance officer could correct by hand — which
   is how this would actually work in production.

`complai extract` re-runs it and overwrites the file, so the pass is reproducible, not
hand-written. The brief explicitly asks that this choice be made visible; the README says it.

### Why not retrieval / RAG

Compliance is a **recall** problem, not a relevance problem. A blurb that never mentions risk
warnings is precisely the one violating the risk-warning rule — semantic search would never
retrieve that rule for that text. A human compliance officer reads copy against the entire
checklist. With a corpus of roughly 20–30 rules, the whole rulebook fits in one context
window comfortably. Embedding infrastructure here would be engineering for a scale problem we
do not have. This is a deliberate rejection, recorded in the README.

Rules do carry provenance (`source_ref`, `source_quote`, and a character span into the
ingested text), so pass 2 performs a **deterministic lookup by rule ID** rather than a
similarity search. Grounded, and reproducible.

---

## 4. Data structures

### Rule

```python
@dataclass(frozen=True)
class Rule:
    id: str                 # "CYSEC-PS0419-RW-001"
    source_doc: str         # "PS-04-2019"
    source_ref: str         # "§3.5.12 / Section A(1)"
    source_quote: str       # verbatim passage, for grounding pass 2
    source_span: tuple[int, int] | None   # char offsets into data/sources/<doc>.txt
    title: str              # "Risk warning must be present"
    requirement: str        # normative statement, imperative voice
    category: Literal["mechanical", "judgment"]
    applies_to: list[str]   # ["marketing_communication", ...]
    check_guidance: str     # how to decide; what counts as evidence
    severity: Literal["high", "medium", "low"]
    counter_example: str | None   # what does NOT violate it (e.g. tiered spreads)
```

`counter_example` exists because of §3.4.10. Encoding the carve-out in the rule itself is the
cheapest available defence against over-flagging.

### Verdict

```python
@dataclass
class Verdict:
    rule_id: str
    verdict: Literal["compliant", "violation", "not_applicable", "needs_review"]
    confidence: float                # 0.0–1.0
    reasoning: str
    evidence_span: str | None        # quoted from the INPUT text
    verified: bool = False           # pass 2 ran
    verification_note: str | None = None   # or the reason it was overturned
```

`not_applicable` is a distinct outcome from `compliant`, and the distinction matters: a rule
about reduced-character third-party formats simply does not apply to a webpage banner.
Collapsing the two would inflate the apparent compliance rate.

`needs_review` is where low-confidence judgment calls land. It is deliberately *not* wired to
a triage workflow in this build — see the cut list.

---

## 5. Prompt design

The rubric says prompt design matters more than framework choice, so this is the section that
carries the most weight.

### Extraction prompt

- **Role:** a regulatory analyst decomposing a policy statement into an auditable checklist.
- **Hard constraint:** every rule must be *checkable against a single piece of marketing copy
  by reading it*. Rules that require access to the firm's systems (leverage caps actually
  applied, margin close-out implementation, quarterly recalculation of the loss percentage)
  are to be classified as out-of-scope-for-text-checking and excluded, with the reason
  recorded. This is the single highest-leverage instruction in the build: it is exactly the
  difference between "extracts checkable rules" and "restates paragraphs", which is a named
  rubric line.
- **Grounding:** every rule must carry a verbatim `source_quote`. No quote, no rule.
- **Split instruction:** classify each rule `mechanical` (decidable by inspection — presence,
  wording, format) versus `judgment` (requires interpretation — is this misleading, is this
  urgency pressure). The two families are prompted differently downstream.
- **Output:** forced structured output via an Anthropic tool schema, not free-text JSON.

### Gate prompt

Classifies input into `marketing_communication`, `client_communication`, `product_description`,
or `out_of_scope`, with reasoning. On `out_of_scope` the pipeline stops and explains what it
expected, rather than fabricating verdicts about a shopping list. Cheap, small, and directly
responsive to the brief's aside.

The classification is **load-bearing, not decorative**: it selects the rulebook. `check.py`
filters rules to those whose `applies_to` contains the gate's verdict, so a factual margin-call
notice is not judged against rules that only bind promotional material. Rules whose
`applies_to` covers every in-scope type (the risk-warning requirement of §3.5.12, which binds
any communication "relating to the marketing, distribution or sale of a CFD") always apply.
If filtering leaves fewer than three rules, the check falls back to the full rulebook and says
so in the report — a narrow gate misfire should degrade to over-checking, never to a silent
all-clear.

### Check prompt — pass 1 (screen)

All rules plus the input text in a single call. One call rather than one-call-per-rule
because: the model sees the whole rulebook at once and can reason about interactions
(a missing risk warning and an emphasised benefit are related findings), it is roughly 20×
cheaper, and latency stays demo-friendly. The cost is a slightly higher chance of a rushed
verdict on any individual rule — which is what pass 2 exists to catch.

Mechanical rules are instructed toward literal inspection ("quote the exact text that
constitutes the risk warning, or state that none is present"). Judgment rules are instructed
toward explicit reasoning against the `check_guidance` and, where present, the
`counter_example`. Every verdict must cite an `evidence_span` quoted from the input, or
explain why no span exists.

### Check prompt — pass 2 (verify)

Runs **only on rules returned as `violation`**. Each verification call sees the alleged
violation, the input text, and the rule's verbatim `source_quote` pulled from the ingested
document by rule ID. It is prompted adversarially: *try to overturn this finding*. It returns
confirm/overturn plus a note. Violations that survive are marked `verified: true` and are the
ones the report leads with.

This is the knowledge base being consulted at *check* time rather than only at extraction
time — the ingested regulation stays in the loop, without embeddings.

### Revision prompt

Given the input and the confirmed violations, produce a compliant rewrite that preserves
marketing intent and tone as far as the rules allow. It is explicitly instructed that
inserting the mandated risk warning verbatim is required and that removing the entire offending
claim is preferable to hedging it into meaninglessness.

---

## 6. The revision loop, and its honest weakness

```
attempt = original
for i in range(MAX_ITERATIONS):        # MAX_ITERATIONS = 3
    result = check(attempt, fast=True)  # pass 1 only — cheap inner loop
    if no violations:
        break
    attempt = revise(attempt, result.violations)
final = check(attempt, fast=False)      # full two-pass verification on the accepted result
```

**Cheap inner loop, rigorous outer verdict.** Inner iterations use single-pass screening;
only the final accepted text gets source-grounded verification. This caps a worst-case run at
roughly 3 rewrite calls + 4 screens + a handful of verifications, instead of multiplying the
two-pass cost by every iteration.

### The weakness, stated plainly

The same model both writes the rewrite and judges it. A loop like this can converge on
"compliant" by satisfying its own grader rather than by genuinely fixing the copy — a small
instance of reward hacking. Three mitigations, none of which fully solve it:

1. The final verdict is re-derived with source-grounded verification, not the inner fast check.
2. The UI and report show the **full trajectory** (attempt 1: 3 violations → attempt 2: 1 →
   attempt 3: clean), so a reviewer sees the work rather than a suspiciously perfect result.
3. The eval set includes a case where a superficial rewrite would false-pass.

A genuine fix needs an independent judge — a different model, or a human. That is named in the
README as a known limitation, not hidden.

---

## 7. Eval harness

The differentiator, and the thing that never gets cut. Prompt design without measurement is
vibes; the harness turns it into engineering.

`evals/cases.yaml` holds roughly 8–10 hand-labelled cases, each with input text, expected
input-type from the gate, and expected verdicts for the rules that matter:

1. **The brief's own example** — *"Install our app and get rich tomorrow 🚀🚀🚀"*. Expect:
   missing risk warning (high), misleading return promise, urgency/excitement signalling.
2. **Fully compliant webpage banner** — correct Section B warning with a loss percentage,
   sober claims. Expect zero violations. Guards against a checker that flags everything.
3. **Bonus offer** — "Deposit €500, trade with €1000". Expect the §3.4.3 incentives violation.
4. **Tiered spread discount** — the §3.4.10 carve-out. Expect **no** violation. A
   false-positive probe.
5. **Risk warning present but buried** — warning in tiny print at the end after heavy benefit
   emphasis. Expect a prominence violation and an Article 44 obscuring violation. Tests
   whether the checker reads for substance rather than keyword presence.
6. **Wrong warning variant** — abbreviated (Section C) warning used where Section B is
   required, or a stale/absent loss percentage.
7. **Out-of-scope input** — an internal engineering status update. Expect the gate to decline.
8. **Client communication, not marketing** — a factual margin-call notice. Expect the gate to
   classify it as `client_communication` and a narrower rule set to apply.

`evals/run_eval.py` scores per-rule precision and recall, reports separately for the
`mechanical` and `judgment` families (they should not be judged by the same standard), and
prints a confusion table of disagreements so failures are legible rather than a single number.
A committed `evals/results.md` from a real run means the reviewer sees measured behaviour
even if they never run it themselves.

**Honest framing for the README:** 8–10 cases is not a statistically meaningful eval. It is a
regression harness and a statement of intent about how prompts should be developed. Claiming
more would be the exact overreach this project is supposed to catch in others.

---

## 8. Interfaces

### CLI (primary)

```
complai ingest                       # fetch + normalise sources
complai extract                      # regenerate data/rules/*.json
complai check "<text>"  [--json] [--no-verify]
complai revise "<text>" [--max-iterations 3]
complai eval                         # run the harness
```

Text may also come from `--file`. Default human output is a coloured terminal report; `--json`
emits the raw structures for piping.

### Streamlit UI (secondary)

Chosen over a hand-built FastAPI page deliberately, and the README says why: **the point is
how fast a working thing reaches a discussion.** A morning brief should produce something
demoable by lunch. Streamlit costs ~20 minutes for a functional interface; a bespoke frontend
costs an hour or more of the same 2–3 hour budget and would come out of the pipeline, prompts,
and evals — which is what is actually being graded. The UI layer is thin and swappable; the
decision is reversible and the reasoning is the deliverable.

Screens: a text area with the eval cases loadable as one-click examples, the gate result, then
verdict cards grouped violation-first. Each card shows verdict, severity, confidence, the
quoted evidence from the input, and an expander revealing the verbatim regulatory passage with
its citation — the provenance view. A "propose compliant rewrite" button runs the revision
loop and renders the trajectory with a diff against the original.

---

## 9. Configuration and BYOK

`ANTHROPIC_API_KEY` via `.env`, loaded with `python-dotenv`; `.env.example` documents it.
Default model `claude-sonnet-5`, overridable with `COMPLAI_MODEL` — Sonnet because the
reviewer is paying, and because a task that runs well on the mid-tier model is a better
engineering result than one that needs the largest.

Structured output uses the Anthropic SDK's tool-use with a forced `tool_choice` and an
explicit `input_schema`, rather than asking for JSON in prose and parsing it. Reliability
comes from the schema, not from prompt pleading.

Missing key fails fast with a clear message naming `.env.example`, at startup rather than
mid-pipeline.

---

## 10. Testing

Unit tests, no API calls, using recorded fixtures:

- `ingest`: PDF text extraction produces expected anchors; HTML trimming keeps Article 44.
- `models`: rule/verdict (de)serialisation round-trips; malformed rule JSON is rejected loudly.
- `check`: given a canned model response, verdicts parse, group, and sort correctly;
  `not_applicable` never counts as a violation.
- `revise`: the loop terminates at `MAX_ITERATIONS`; a clean first check performs zero
  rewrites; the trajectory is recorded in order.
- `report`: violations sort before compliant, high severity before low.

The LLM-dependent behaviour is covered by the eval harness rather than by mocked assertions —
mocking a model's judgement and then asserting on the mock tests nothing.

---

## 11. Deployment (bonus, only if time remains)

Streamlit Community Cloud: point it at the public repo, set `ANTHROPIC_API_KEY` as a secret,
done — no Dockerfile, no Procfile, and the committed `rules.json` means the deployed app needs
no build-time API calls. A `Procfile` for Heroku is a three-line addition if wanted. This is
explicitly the last thing built and the first thing cut.

---

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Extraction produces restated paragraphs rather than checkable rules | The checkability constraint is the core extraction instruction; eval case 2 and 4 catch a checker that flags everything; committed rules are human-reviewable and hand-correctable |
| Over-flagging (compliance theatre) | `counter_example` on rules, the §3.4.10 carve-out as an explicit false-positive probe, precision reported separately from recall |
| Revision loop games its own judge | Full trajectory shown, final verdict source-verified, limitation stated in README |
| Cost/latency on the reviewer's machine | One screening call not N; verification only on violations; Sonnet default; committed rules and committed eval results mean the repo reads well with zero spend |
| PDF extraction mangles the layout-dependent risk-warning boxes | Ingested text is committed and eyeballed once; if a Section B/C/D box is mangled, the affected rule's `source_quote` is corrected by hand and that correction is disclosed in the README |
| Scope creep eats the README | README is a scheduled deliverable with reserved time, not an afterthought; the rubric weights it equally with the code |

---

## 13. Explicitly cut

Named in the README with reasons, because the brief asks for scoping decisions to be visible:

- **Human-in-the-loop triage queue.** `needs_review` is emitted but not routed. Correct next
  step for production; not demonstrable value in a 3-hour build.
- **Embedding-based retrieval.** Rejected on recall grounds (§3).
- **Multi-jurisdiction support.** PS-04-2019's territorial scope rules (§4) mean the real
  rulebook varies by client residence. Genuinely interesting, out of budget, and it would
  double the extraction surface.
- **Layout-aware PDF ingestion.** Font size and prominence are literally regulated
  (Section A(1)), so a text-only pipeline can only assess prominence from textual cues. This
  limitation is stated rather than papered over — it is the most intellectually honest thing
  in the submission.
- **Rule versioning / regulatory change diffing.** Obvious production need, no demo value here.
- **Independent judge model for the revision loop.** The right fix for §6; out of budget.

---

## 14. Time budget

| Slot | Work |
|---|---|
| 0:00–0:20 | ingest, sources committed |
| 0:20–0:50 | extraction prompt, `rules.json` reviewed by hand |
| 0:50–1:30 | gate + two-pass check |
| 1:30–1:50 | eval harness + fixtures |
| 1:50–2:15 | revision loop |
| 2:15–2:40 | Streamlit UI |
| 2:40–3:00 | README |

Cut order under time pressure: provenance expanders, then the revision loop, then the gate.
The eval harness is never cut — it is the evidence.

---

## 15. Definition of done

- `complai check` runs end to end from a clean clone with only an API key added.
- `data/rules/*.json` committed and hand-reviewed.
- Eval harness runs and `evals/results.md` is committed.
- Streamlit app launches with `streamlit run app.py`.
- README covers: what was built, what was cut and why, key prompt-design decisions, what I'd
  do differently with more time, and one thing that surprised me — the four questions the
  brief asks for by name.
- No API key, and no confidential material, anywhere in git history.
