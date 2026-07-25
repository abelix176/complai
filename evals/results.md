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
cases that exist specifically to punish over-flagging — compliant-banner and
tiered-spread-carveout — both come back completely clean, which is the result that
actually matters for trustworthiness.

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
