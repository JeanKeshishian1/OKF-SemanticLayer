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
