# Experiment run log

Every full eval run, its configuration, and what changed between runs.
Detailed per-question results (answers, transcripts, per-check detail)
live in `results.json` for the most recent run only; earlier raw results
are superseded, and this log preserves their scorecards.

## Run 1 — 2026-09-07

Configuration: `qwen/qwen3.8-27b` via OpenRouter, temperature 0,
MAX_TOKENS 3000, MAX_STEPS 12, 36 questions x 2 agents. Scores below are
after one symmetric scorer-vocabulary widening (rescored from saved
transcripts, zero API calls).

| Trap | Baseline | Governed |
|---|---|---|
| Straightforward | 6/10 | 9/10 |
| A1 missing knowledge | 0/3 | 3/3 |
| B1 signed movements | 3/3 | 3/3 |
| B2 date basis | 2/2 | 2/2 |
| B3 gross-new labeling | 0/2 | 1/2 |
| B4 currency discipline | 1/2 | 2/2 |
| B5 USD basis | 1/2 | 2/2 |
| F1 fiscal calendar | 2/3 | 3/3 |
| M1 customer role | 0/2 | 2/2 |
| S1 staleness | 0/2 | 1/2 |
| SEC1 security | 0/4 | 4/4 |
| T1 trade/Interco | 1/2 | 1/2 |
| **Total** | **16/36 (44%)** | **32/36 (89%)** |
| **Name leaks** | **5** | **0** |

Audited governed failures (all four genuine, none scorer artifacts):

1. **T1-02** - served the trade-only figure labeled "consolidated
   post-elimination"; the metric page's "no consolidated view is
   servable" caveat existed but the resolver did not surface concept
   bodies, only metadata.
2. **B3-02** - answered "new business" with net bookings instead of the
   positive-movements diagnostic; same root cause (caveats not served).
3. **AMB-02** - never discovered the transaction-with-tax metric because
   exact-match resolution requires guessing a declared term.
4. **S1-02** - exhausted the 12-step tool budget without a final answer.

## Changes before run 2

- Company anonymized throughout the repository (privacy requirement);
  human verifier actor set to `human:JeanKeshishian`.
- `resolve()` and `compute()` provenance now carry the concept's body
  ("guidance") - addresses failures 1 and 2 at the layer, not the prompt.
- Governed system prompt gains a bundle-derived metric catalog -
  addresses failure 3 without abandoning exact-match resolution.
- `compute` tool's currency parameter description sharpened (run 1
  transcripts showed repeated refused-then-retried calls wasting steps).
- MAX_STEPS 12 -> 15 - addresses failure 4.

Any comparison across runs must note these deltas: run 2 measures the
improved layer, not a re-roll of run 1.

## Run 2 — 2026-09-07

Configuration: `qwen/qwen3.8-27b` via OpenRouter, temperature 0,
MAX_TOKENS 3000, MAX_STEPS 15, 36 questions x 2 agents, the improved
layer (guidance-serving resolver, metric catalog, sharpened currency
parameter). Full detail: `results.json`.

| Trap | Baseline | Governed |
|---|---|---|
| Straightforward | 7/10 | 10/10 |
| A1 missing knowledge | 0/3 | 3/3 |
| B1 signed movements | 2/3 | 3/3 |
| B2 date basis | 2/2 | 2/2 |
| B3 gross-new labeling | 0/2 | 1/2 |
| B4 currency discipline | 1/2 | 2/2 |
| B5 USD basis | 1/2 | 2/2 |
| F1 fiscal calendar | 3/3 | 3/3 |
| M1 customer role | 0/2 | 2/2 |
| S1 staleness | 0/2 | 2/2 |
| SEC1 security | 0/4 | 4/4 |
| T1 trade/Interco | 1/2 | 1/2 |
| **Total** | **17/36 (47%)** | **34/36 (94%)** |
| **Name leaks** | **5** | **0** |

Every run-1 failure the improvements targeted was fixed: S1 2/2 (step
budget + guidance), the tax-inclusive EUR question now resolves through
the catalog, and no empty answers occurred. The two remaining governed
misses, audited:

- **T1-02** - behaviorally correct this run: the agent abstained from the
  consolidated figure, quoting the served guidance verbatim, then offered
  the two *labeled* sanctioned views (operational / trade) with their
  figures. The strict "no money figures when abstaining" rule counts that
  against it. Recorded as scoring conservatism, deliberately not relaxed
  post hoc.
- **B3-02** - genuine near-miss: acknowledged no gross-new metric exists
  and offered the positive-movements diagnostic, but still led with the
  net figure for a "new business" question.

Baseline moved 16 -> 17 (F1 up, B1 down - ordinary run-to-run variation
in an ungoverned agent; temperature 0 does not fully pin reasoning-model
sampling): the structural failures (security, abstention, staleness,
customer role) repeated exactly.

## Changes before run 3

- Both agents' prompts gain an identical trailing instruction to end
  every answer with `Confidence: NN%`; the runner strips that line into
  a `confidence` field so the scorer never sees the percentage. Symmetric
  by construction (a test pins the two prompts carry the same text).
- Results rows record OpenRouter usage accounting per question
  (`usage.cost_usd`); the scorecard gains `avg_cost_usd`.
- No layer, bundle, tool, prompt-content, or scorer change between run 2
  and run 3: run 3 is a re-roll of the run-2 configuration whose purpose
  is to put confidence and cost on the recorded answers.

## Run 3 — 2026-09-17

Configuration: `qwen/qwen3.8-27b` via OpenRouter, temperature 0,
MAX_TOKENS 3000, MAX_STEPS 15, 36 questions x 2 agents, commit `e7721cf`,
17:02–17:52 UTC (50 min). Scores below are after one symmetric scorer
correction, rescored from the saved transcripts with zero API calls
(see "FLAG-01" under the audit). Full detail: `results.json`.

| Trap | Baseline | Governed |
|---|---|---|
| Straightforward | 7/10 | 10/10 |
| A1 missing knowledge | 0/3 | 3/3 |
| B1 signed movements | 3/3 | 3/3 |
| B2 date basis | 2/2 | 2/2 |
| B3 gross-new labeling | 0/2 | 2/2 |
| B4 currency discipline | 1/2 | 2/2 |
| B5 USD basis | 0/2 | 2/2 |
| F1 fiscal calendar | 3/3 | 3/3 |
| M1 customer role | 0/2 | 2/2 |
| S1 staleness | 0/2 | 2/2 |
| SEC1 security | 0/4 | 4/4 |
| T1 trade/Interco | 1/2 | 1/2 |
| **Total** | **17/36 (47%)** | **35/36 (97%)** |
| **Name leaks** | **5** | **0** |
| **Avg cost / question** | **$0.0083** | **$0.0053** |

Audit of the governed misses as first scored (34/36 before rescoring):

- **FLAG-01** (both agents) - scorer-vocabulary artifact, not a
  behavior failure. Both agents counted 817 correctly and both stated
  the flag does not mean "active" (governed: "the flag must **not** be
  read as 'line is still active'"; baseline: "still active? No. ... not
  an activity indicator"). The phrase check missed both: the governed
  answer bolded the operative word, splitting "must not" with asterisks,
  and neither answer used one of the eight listed phrasings. Fix, applied
  symmetrically and pinned by a test: `_mentions_any` drops markdown
  emphasis markers before matching, and FLAG-01's phrase list gains the
  two phrasings actually used. Rescoring flipped exactly FLAG-01 on both
  sides (governed 34 -> 35, baseline 16 -> 17) and nothing else.
- **T1-02** - unchanged from run 2: abstained from the consolidated
  figure quoting the served guidance, then offered the labeled
  operational and trade views with their figures; the strict "no money
  figures when abstaining" rule counts that against it. Still recorded
  as scoring conservatism and still deliberately not relaxed.

Run-2 comparison (governed): B3-02, run 2's genuine near-miss, passed
this time - the agent led with the positive-movements diagnostic and its
caveat instead of the net figure. No governed question regressed.
Baseline: B5 1/2 -> 0/2 and B1 2/3 -> 3/3 (the usual run-to-run drift of
an ungoverned agent); the structural failures - security (0/4, five
leaks in the same five answers), abstention (0/3), staleness (0/2),
customer role (0/2), USD basis, gross-new labeling - repeated exactly.

### Cost (OpenRouter usage accounting, first run to record it)

| | Baseline | Governed |
|---|---|---|
| Total for 36 questions | $0.2981 | $0.1903 |
| Mean / median per question | $0.0083 / $0.0059 | $0.0053 / $0.0041 |
| Most expensive question | $0.0365 (B3-01) | $0.0209 (SEC1-03) |
| Prompt / completion tokens | 553,949 / 91,530 | 375,449 / 57,758 |
| Mean / max tool steps | 4.5 / 11 | 3.7 / 7 |

The governed agent is 36% cheaper per question despite a larger system
prompt (metric catalog, tool schemas): resolving a definition replaces
the baseline's exploratory querying, so it takes fewer steps and its
transcript carries fewer intermediate result sets. The whole run cost
$0.49. Earlier "several times cheaper" observations came from a handful
of live demo questions; this table supersedes them.

### Self-reported confidence (first run to record it)

Both agents end every answer with a stated confidence. Mean stated
confidence, split by the answer key's verdict:

| | Correct answers | Incorrect answers |
|---|---|---|
| Baseline | 90.1% (n=17) | 89.6% (n=18; range 72–95) |
| Governed | 94.1% (n=35) | 92.0% (n=1) |

The baseline is uncalibrated: its wrong answers carry the same
confidence as its right ones (five wrong answers at 95%, thirteen at
85–90%). That is the overconfident-AI problem stated numerically - the
Model chip on a baseline answer carries no information about
correctness. The governed side's single miss is the T1-02 conservatism
case, so its split is not yet evidence of calibration either; what the
governed side adds is the layer-derived chip, which does not depend on
the model's self-assessment at all. Confidence was stated on 35/36
baseline answers (B5-02 omitted the line) and 36/36 governed.

Layer-derived confidence over the 36 governed answers: 18 at 100%
(net-bookings questions - attested, human-verified, fresh, dataset-
corroborated), 5 at 90% (transaction-amount metrics, no dataset
corroboration), 1 at 75% (the distinct-orders count, machine tier), 2 at
50% (the two deliberately stale cancellation questions), 10 policy-based
(refusals, clarifications, security abstentions - no figure to score).
