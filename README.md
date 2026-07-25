# complai — Regulation Compliance Agent

An LLM-powered compliance officer for marketing copy. It ingests a real regulatory
source, decomposes it into discrete checkable rules, and evaluates a piece of text
rule by rule — with every verdict traceable to the passage of regulation it came from.

Built as a take-home for eToro's BizOps (Agentic AI) role, in a 2–3 hour box.

```
$ complai check "Install our app and get rich tomorrow 🚀🚀🚀"

Input type: marketing_communication — promotional call to action with a
hyperbolic financial promise

Result: 6 violation(s)

✗ [VIOLATION] Marketing must not be aggressive or omit adequate risk information
    (PS-04-2019 2.3)
    'get rich tomorrow' with rocket emojis emphasises extreme, unrealistic gains
    with urgency-style excitement and provides zero risk information.
    evidence: "Install our app and get rich tomorrow 🚀🚀🚀"
    verified against source: ...squarely matches the regulation's concern about
    aggressive marketing lacking adequate risk information.
    confidence: 95%
```

---

## Quickstart

```bash
git clone https://github.com/abelix176/complai && cd complai
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
cp .env.example .env        # then add your ANTHROPIC_API_KEY

.venv/bin/python -m complai check "Install our app and get rich tomorrow 🚀🚀🚀"
.venv/bin/streamlit run app.py
```

**The rulebook is committed** (`data/rules/rules.json`), so nothing needs regenerating
and the first check costs one API call, not twenty. Default model is
`claude-sonnet-5`; override with `COMPLAI_MODEL`.

```bash
complai ingest    # re-fetch and normalise the regulation sources
complai extract   # regenerate the rulebook from those sources
complai check "<text>" [--file f] [--json] [--no-verify]
complai revise "<text>" [--max-iterations 3]
python -m evals.run_eval
```

Exit codes carry meaning: `check` returns 1 when violations were found, 0 when clean,
2 when the gate declined the input.

---

## How it works

```
regulation PDF ─▶ 1. INGEST    fetch → normalise → data/sources/*.txt   (committed)
                       ▼
                  2. EXTRACT   LLM → data/rules/rules.json              (committed)
                       ▼
marketing text ─▶ 3. GATE      is this even a client communication?
                       ▼
                  4. CHECK     pass 1: screen ALL rules in one call
                               pass 2: verify each violation vs its source passage
                       ▼
                  5. REVISE    rewrite → re-check → repeat, max 3
```

**Ingest** pulls CySEC PS-04-2019 (*Policy Statement on national measures for the
marketing, distribution and sale of CFDs*, 27 Sept 2019) and normalises it. A second,
deliberately small source carries the MiFID II Article 24(3) and Delegated Regulation
2017/565 Article 44 "fair, clear and not misleading" standard.

**Extract** decomposes both into 20 rules — 13 mechanical, 7 judgment — each carrying
a verbatim `source_quote`, a character span into the source, a severity, and where the
regulator stated one, a `counter_example` recording what is *not* caught.

**Gate** classifies the input as marketing communication, client communication, product
description, or out of scope, and declines the last outright.

**Check** screens every rule in a single call, then re-examines each alleged violation
against the regulation's own words, prompted to *overturn* the finding.

**Revise** proposes a compliant rewrite and re-checks it, up to three attempts.

---

## Key decisions

**Rules are extracted once and committed, not extracted at runtime.** The
decomposition is a reviewable, diffable, hand-correctable artifact — which is how this
would work in production, where a compliance officer corrects the machine's reading of
the rulebook. It also means a reviewer can judge extraction quality without spending a
cent. `complai extract` regenerates it, so the pass is reproducible rather than
hand-written.

**No RAG, deliberately.** Compliance is a *recall* problem, not a relevance problem.
Copy that never mentions risk warnings is precisely the copy that violates the
risk-warning rule — semantic search would never retrieve that rule for that text. A
human compliance officer reads copy against the entire checklist. Twenty rules fit in
one context window comfortably. Retrieval here would be engineering for a scale problem
this doesn't have. Provenance is instead a deterministic rule-id → source-span lookup.

**Two-pass checking: one cheap screen, verification only on hits.** Screening all rules
in a single call lets the model reason about interactions and costs far less than one
call per rule. The cost is a rushed verdict now and then, which is what pass 2 catches:
each alleged violation is re-examined against the verbatim regulation by a prompt told
to refute it. Findings that survive are marked verified; findings that don't become
`needs_review`, never `compliant` — a skeptic failing to confirm is not an all-clear.

**An input gate, because the brief hides a requirement in an aside:** *"It is the
marketing materials compliance check, not just random text from nowhere."* Piping any
string into the checker fails that quietly. The gate declines a sprint retrospective
instead of inventing verdicts about it, and its classification is load-bearing — it
selects which rules apply. If filtering leaves fewer than three rules the checker
reverts to the full rulebook and says so, because a gate misfire should degrade into
over-checking, never a silent all-clear.

**The rulebook is sent as a cached prefix.** The screening prompt and rulebook are
byte-identical on every check and total ~6,000 tokens; only the submitted copy varies. They
go in their own content block with the cache breakpoint at its end, so the submission stays
*outside* the cached prefix — putting them in one block would make every submission write a
fresh entry and never hit. Measured across three consecutive checks: 6,015 tokens written
once, then read on both subsequent calls with ~70 uncached each. It pays for itself on the
second check and cuts input cost roughly 90% after that. An eval run (8 checks), a revision
loop (up to 4 screens), and any UI session all clear that bar; a single cold one-off check
does not, and pays a ~25% write premium instead.

**Sonnet 5 over Opus 5 — measured, not assumed.** `COMPLAI_MODEL` switches the model, so the
eval harness can answer this empirically. Over the same 8 cases, Opus 5 scored precision 0.50
/ recall 0.71 against Sonnet 5's 0.41 / 1.00: it flagged less, which bought precision at the
cost of letting two expected violations through. **That is the wrong trade for compliance.**
A missed violation is regulatory exposure; a spurious one costs a reviewer ten seconds
dismissing a card. Recall is the metric to protect, and Sonnet 5 is also cheaper ($3/$15 per
Mtok vs $5/$25). Caveat stated plainly: one run, eight cases, two non-deterministic models —
the gap is within what noise alone could produce. It is directional evidence that the pricier
model is not automatically better here, not a measured ranking. Rerun it yourself with
`COMPLAI_MODEL=claude-opus-5 python -m evals.run_eval`.

**Streamlit over a bespoke frontend.** The brief says UI isn't graded. More to the
point, the realistic version of this task is: brief in the morning, something to argue
about by lunch. Streamlit costs ~20 minutes; a hand-built frontend costs an hour or more
out of the same budget, taken from the pipeline, prompts and evals that *are* graded.
The UI is thin and swappable — every piece of logic lives in `src/complai` behind typed
functions, so replacing it is a rewrite of one file.

---

## Prompt design

Four prompts, in `src/complai/prompts.py`. The single most important instruction in the
project is the checkability constraint in the extraction prompt:

> **CHECKABILITY IS MANDATORY.** Only produce a rule if a reviewer could decide it by
> reading the marketing text alone. Requirements that depend on the firm's internal
> systems — actual leverage applied, margin close-out implementation, negative balance
> protection, the quarterly recalculation of a loss percentage — are NOT checkable from
> text. Omit them. Do not restate paragraphs as rules; a rule that cannot be violated by
> a piece of copy is not a rule here.

That is the whole difference between extracting *checkable rules* and restating
paragraphs. PS-04-2019 is largely about things a firm must *do* — hold margin, cap
leverage, protect against negative balances. Almost none of that is decidable from a
marketing blurb. Without this constraint the extractor happily produces twenty
authoritative-sounding rules that no piece of copy could ever violate.

The other three each turn on one idea. The **gate** is told that if text isn't a
communication to actual or prospective clients it should say so rather than strain to
find a category. The **screening** prompt demands a quoted `evidence_span` from the
input for every verdict, respects `counter_example` before flagging, and — added after
the eval caught it — treats alternative formats as mutually exclusive. The
**verification** prompt is adversarial: *try to overturn this finding*, confirm only if
the verbatim regulation actually prohibits what the text actually does.

---

## Evaluation

`evals/cases.yaml` holds 8 hand-labelled cases; `python -m evals.run_eval` scores them.
Current results are in `evals/results.md`:

| metric | value |
|---|---|
| gate accuracy | 8/8 |
| recall | 1.00 |
| precision | 0.41 (deliberate lower bound — see below) |

**Eight cases is not a statistically meaningful evaluation**, and this doesn't pretend
otherwise. It's a regression harness: it makes a prompt change justify itself against
labelled examples instead of against an impression.

Precision is a lower bound because the labels list only each case's *headline*
violations; any additional rule the checker flags counts against it even when
defensible. Every remaining false positive sits on copy that is genuinely
non-compliant. The two cases built specifically to punish over-flagging —
`compliant-banner` and `tiered-spread-carveout` — both return completely clean, which
is the result that matters. **A compliance agent that never says "clean" is worthless,
because reviewers learn to ignore it.**

**The labels are hand-authored on purpose.** The showcase corpus in `data/samples/` was
model-generated, because it's only demo input. But if a model also wrote the expected
answers, the harness would measure agreement between two model outputs rather than
correctness — and it would agree with itself most confidently in exactly the cases where
it's confidently wrong.

### What the harness actually caught

1. **A bug in its own scorer.** Fuzzy-matching semantic tags against rule titles
   attributed the incentives expectation to the tiered-spread carve-out, whose title
   reads "…are not prohibited incentives". It was scoring against the wrong rule.
   Replaced with exact rule-id matching.
2. **The checker reporting one defect many times over** — flagging Sections B, C and D
   warning formats simultaneously though they're mutually exclusive by medium. Fixed in
   the screening prompt: precision 0.20 → 0.44, recall 0.50 → 0.88.
3. **A misplaced carve-out.** The tiered-spread exclusion was attached to the incentives
   rules but not to the judgment rule about encouraging trading behaviour, so that rule
   kept flagging conduct §3.4.10 expressly permits.
4. **An impossible label of my own.** `wrong-warning-variant` demanded a verdict that
   depends on the firm's trading history — absent from the text. The checker was right
   to return clean. I corrected the label, not the system, and kept the case as a
   documented limitation.

Item 4 is the one worth dwelling on: the harness caught an error in its own ground
truth, not in the system under test.

---

## What I cut, and why

- **Human-in-the-loop triage.** `needs_review` is emitted but not routed anywhere.
  It's the correct next step for production and demonstrates nothing in a 3-hour build.
- **Embedding-based retrieval.** Rejected on recall grounds (above).
- **Multi-jurisdiction support.** PS-04-2019 §4 makes the applicable rulebook vary by
  client residence — genuinely interesting, and it would double the extraction surface.
- **Layout-aware PDF ingestion.** See limitations.
- **Rule versioning / regulatory change diffing.** Obvious production need, no demo value.
- **An independent judge for the revision loop.** The right fix for the weakness below.

## Known limitations

- **Prominence is regulated but not text-checkable.** Section A(1) requires the warning
  be "in a font size at least equal to the predominant font size" and in a prominent
  layout. Those are visual properties. A text pipeline can infer prominence only from
  position and surrounding emphasis. The rule is extracted and checked *as far as text
  allows*, and this is the honest boundary of the approach rather than something the
  demo papers over.
- **The revision loop judges its own work.** The same model writes and grades the
  rewrite, so it can converge by satisfying its own grader rather than genuinely fixing
  the copy. Mitigations: the final verdict is re-derived with source-grounded
  verification rather than the cheap inner check; `converged` is true only if *both*
  agree; and the UI shows the full trajectory so a reviewer sees the work instead of
  trusting a suspiciously clean result. A real fix needs an independent judge.
- **Four rules were hand-corrected.** The leverage limits live in a PDF table whose
  column wrapping scatters the words ("gold and major **5% 20:1** indices"), so no
  contiguous verbatim quote exists. I repointed those four to §3.1.29, CySEC's operative
  statement adopting the ESMA limits, which *is* contiguous. Everything else is
  machine-extracted and unmodified; all 20 quotes are verbatim-present in the sources.
- **Rule ids are referenced by the eval.** Re-running `complai extract` can renumber
  rules and require updating `evals/cases.yaml`.

## What I'd do differently with more time

Give the revision loop an independent judge — a different model, or a human — since
self-grading is its central weakness. Route `needs_review` into an actual triage queue
with reviewer assignment, which is what would make this usable by a real compliance
team. Add layout-aware ingestion so prominence becomes checkable rather than inferred.
Expand the eval from 8 cases to something with statistical weight, ideally labelled by
someone who isn't me. And chunk extraction per document section rather than sending 52KB
in one call, which would improve rule granularity and source references.

## One thing that surprised me

PS-04-2019 §3.4.10 expressly carves tiered fee/spread discounts *out* of the incentives
prohibition — even though they look exactly like the bonuses that are banned. CySEC
reasons that because the discount is embedded in the cost structure rather than paid
retrospectively, it doesn't incentivise higher volumes.

That reframed the whole build. An over-flagging compliance agent isn't "safely
cautious" — it's wrong in a way that erodes trust and trains people to ignore it. So
the carve-out became a `counter_example` field on every rule, a false-positive probe in
the eval set, and the reason precision is reported separately from recall. And the eval
promptly proved the point: the carve-out was attached to the incentives rules but not to
the judgment rule about encouraging trading, which kept flagging exactly the conduct the
regulator had gone out of its way to permit.

## AI-native workflow

Built with Claude Code, and the process is in the repo rather than described after the
fact: the design spec and implementation plan are committed under `docs/superpowers/`
before any code exists, and the git history follows them task by task.

Test-driven throughout — 65 tests, none of which make a network call. All LLM access
goes through one narrow `LLMClient` protocol, so every module is testable with a fake
and the model-dependent behaviour is covered by the eval harness instead of by mocked
assertions about model judgement, which test nothing.

Subagents did the mechanical implementation from the plan's specified code, and one
generated the 18-sample showcase corpus. The line I drew: **subagents wrote the demo
inputs, but the ground-truth eval labels are hand-authored**, because a generated label
isn't evidence.

Three things the model got wrong that are worth recording. Forced tool-use returned
three different shapes for the same schema across runs — a proper array, a JSON-encoded
string, and a double-nested object — so the client seam now coerces and the extractor
unwraps, both with regression tests. Default PDF extraction inserted stray spaces inside
words in the narrative text ("fon t size", "lose mo ney") in exactly the passages the
rules quote; `pypdf`'s layout mode eliminated all nine instances. And a regex I wrote to
restore paragraph boundaries matched *inside* `3.5.12.`, splitting it into `3.` and
`5.12.` and silently destroying every cross-reference in the document — the tests still
passed and the file still looked plausible.
