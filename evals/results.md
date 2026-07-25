case                             score                        notes
--------------------------------------------------------------------------------------------
brief-example                    tp=3 fp=3 fn=0               3 mechanical / 3 judgment
compliant-banner                 tp=0 fp=0 fn=0               0 mechanical / 0 judgment
tiered-spread-carveout           tp=0 fp=0 fn=0               0 mechanical / 0 judgment
bonus-offer                      tp=1 fp=2 fn=0               1 mechanical / 2 judgment
buried-warning                   tp=3 fp=4 fn=0               3 mechanical / 4 judgment
wrong-warning-variant            tp=0 fp=1 fn=0               1 mechanical / 0 judgment
out-of-scope-engineering-note    gate declined                ok
client-margin-notice             tp=0 fp=0 fn=0               0 mechanical / 0 judgment
--------------------------------------------------------------------------------------------
gate accuracy: 8/8
precision: 0.41   recall: 1.00   (tp=7 fp=10 fn=0)

Reading these numbers
---------------------
Gate accuracy 8/8. Recall 1.00: every violation the ground truth requires was found.

Precision 0.41 is a deliberate LOWER BOUND, not a measured error rate. The labels
list only the headline violation(s) each case is designed to probe; any additional
rule the checker flags counts against precision even when the finding is defensible.
Every remaining false positive sits on copy that is genuinely non-compliant
(brief-example, bonus-offer, buried-warning) where extra findings are arguable. The
cases that exist specifically to punish over-flagging, compliant-banner and
tiered-spread-carveout, both came back clean on this run, which is the result that
actually matters for trustworthiness. See "Run-to-run variance" below before treating
that as a guarantee.

What this harness caught, in order
----------------------------------
1. The scorer itself was wrong. Fuzzy matching of semantic tags against rule titles
   attributed the incentives tag to the tiered-spread carve-out, whose title reads
   "...are not prohibited incentives". Replaced with exact rule-id prefix matching.
2. The checker reported one defect many times over, flagging mutually exclusive
   warning formats (Sections B, C and D) simultaneously. Fixed in the screening
   prompt. Precision 0.20 -> 0.44, recall 0.50 -> 0.88.
3. The tiered-spread carve-out was attached to the incentives rules but NOT to the
   judgment rule about encouraging trading behaviour, so that rule kept flagging
   conduct CySEC expressly permits. Fixed in the rulebook. The probe now passes.
4. One eval label was itself impossible. `wrong-warning-variant` demanded a verdict
   that depends on the firm's trading history, which is absent from the text. The
   label was corrected and the case retained as a documented limitation.

Item 4 is the one worth dwelling on: the harness caught an error in its own ground
truth, not in the system under test.

Model comparison, Sonnet 5 vs Opus 5
-------------------------------------
Same 8 cases, same rulebook, one run each. `COMPLAI_MODEL` selects the model.

| model          | gate | recall | precision |
|----------------|------|--------|-----------|
| claude-sonnet-5 | 8/8  | 1.00   | 0.41      |
| claude-opus-5   | 8/8  | 0.71   | 0.50      |

Opus 5 is the more precise checker and the less complete one: it flagged fewer
rules overall, which lifted precision but let two expected violations through.

**Sonnet 5 stays the default, and the reason is the task, not the price.** In
compliance, a missed violation and a spurious one are not symmetric costs: the
first is regulatory exposure, the second is a reviewer spending ten seconds
dismissing a card. A tool that silently clears non-compliant copy is worse than
one that over-flags, so recall is the metric to protect. Sonnet 5 also happens
to be cheaper ($3/$15 per Mtok vs $5/$25), which makes this an easy call rather
than a trade-off.

Caveat, and it matters: this is ONE run over EIGHT cases. Both models are
non-deterministic and the gap is well within what that could produce. Read it as
directional evidence that the more expensive model is not automatically better
here, not as a measured ranking. Anyone rerunning this should expect different
numbers.

Prompt caching
--------------
The rulebook and screening prompt are byte-identical on every check and total
~6,000 tokens; only the submitted text varies. They are sent as a separate
content block with a cache breakpoint at its end, so the submission stays
outside the cached prefix.

Measured across three consecutive checks:

    call 1: uncached_in=66   cache_write=6015  cache_read=0
    call 2: uncached_in=70   cache_write=0     cache_read=6015
    call 3: uncached_in=69   cache_write=0     cache_read=6015

Cache reads bill at ~0.1x input and the write at ~1.25x, so this pays for itself
on the second check and cuts input cost roughly 90% thereafter. An eval run (8
checks), a revision loop (up to 4 screens), and any UI session all clear that bar
easily; a single one-off check does not, and pays a 25% premium instead.


Run-to-run variance
-------------------
The table above is ONE run. Re-running the byte-identical fixtures against the same model
later produced:

    gate accuracy: 8/8
    precision: 0.35   recall: 0.86   (tp=6 fp=11 fn=1)

against the recorded 0.41 / 1.00. The gate was 8/8 both times; the tiered-spread carve-out
probe was clean on the first run and drew one false positive on the second.

Nothing changed between the two runs: same cases, same labels, same rulebook, same model.
The spread is the model's own non-determinism. Two consequences worth being explicit about.
First, do not expect to reproduce the recorded figures. Second, eight cases cannot separate
a real prompt improvement from this much noise, which is the concrete reason the eval needs
to be larger before any of these numbers should drive a decision.