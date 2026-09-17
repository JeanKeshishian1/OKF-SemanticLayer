"""Offline tests for the eval harness - question set integrity + scorer.

Two things are pinned here, both load-bearing for the experiment's
credibility:

  1. The question set is VALID: ids unique, kinds known, every ground-truth
     reference resolves, every harness-side SQL runs, and every trap in the
     registry is exercised by at least two questions (the design doc's
     coverage promise).
  2. The scorer behaves: right figures pass, trap figures fail, hedged
     answers that mix in forbidden bases fail, abstentions and staleness
     flags are recognized, and real restricted names are caught as leaks.

No API calls anywhere - the scorer is a pure function over answer text
plus the scoring context, which is exactly what makes eval results
re-scorable and auditable after the fact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from averio.evaluate import (
    RELATIVE_TOLERANCE,
    ScoringContext,
    _mentions_any,
    extract_numbers,
    load_questions,
    score_answer,
)

REPO = Path(__file__).resolve().parents[1]
QUESTIONS = load_questions(REPO / "eval" / "questions.json")

# The full trap registry from docs/semantic-model.md section 3. Every trap
# must be exercised by >= 2 questions - this is the coverage promise.
KNOWN_TRAPS = {"B1", "B2", "B3", "B4", "B5", "F1", "M1", "T1", "S1", "A1", "SEC1"}
KNOWN_KINDS = {"value", "value_flagged", "value_sql", "caveat_value",
               "abstain", "refuse", "clarify", "security", "explain"}


@pytest.fixture(scope="session")
def ctx(workspace):
    db, truth = workspace
    return ScoringContext(truth, str(db))


def _q(qid: str) -> dict:
    return next(q for q in QUESTIONS if q["id"] == qid)


# --- Question-set integrity ---------------------------------------------------

def test_question_ids_unique_and_kinds_known():
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) == len(set(ids)), "duplicate question ids"
    for q in QUESTIONS:
        assert q["kind"] in KNOWN_KINDS, f"{q['id']}: unknown kind {q['kind']}"
        assert set(q.get("traps", [])) <= KNOWN_TRAPS, f"{q['id']}: unknown trap tag"


def test_every_trap_has_two_questions():
    counts = {t: 0 for t in KNOWN_TRAPS}
    for q in QUESTIONS:
        for t in q.get("traps", []):
            counts[t] += 1
    weak = {t: n for t, n in counts.items() if n < 2}
    assert not weak, f"traps with fewer than 2 questions: {weak}"


def test_all_expect_references_resolve(ctx):
    """Every ground-truth pointer, separation pointer, and harness-side SQL
    in the question set must resolve NOW - not at hour two of a paid run."""
    for q in QUESTIONS:
        expect = q.get("expect", {})
        if q["kind"] in ("value", "value_flagged", "caveat_value"):
            assert ctx.expected_value(expect) is not None, q["id"]
        if "forbidden_separation" in expect:
            assert ctx.forbidden_value(expect) is not None, q["id"]
        for key in ("sql", "id_sql"):
            if key in expect:
                assert ctx.sql_scalar(expect[key]) is not None, q["id"]
        if q["kind"] in ("explain", "clarify"):
            assert q.get("must_mention_any"), f"{q['id']} needs must_mention_any"


def test_tolerance_is_below_smallest_trap_separation(workspace):
    """The acceptance window must never be wide enough to accept a trap
    value as correct - 0.5% vs the engineered minimum separation of 1%."""
    _, truth = workspace
    smallest = min(v["delta_pct"]
                   for v in truth["separation"]["variants"].values())
    assert RELATIVE_TOLERANCE * 100 < smallest


# --- Number extraction --------------------------------------------------------

def test_extract_numbers_reads_figures_not_labels():
    numbers = extract_numbers(
        "In FY2025 (PD10) net bookings were $135,290,375.66, roughly "
        "$135.3 million, versus 1,360 orders booked on 2026-08-24.")
    values = sorted(n["value"] for n in numbers)
    # FY2025, PD10, and the date parts must NOT appear; the money figures
    # and the order count must.
    assert values == [1360.0, 135290375.66, 135300000.0]


def test_extract_numbers_handles_suffixes_and_signs():
    numbers = {n["value"] for n in extract_numbers(
        "de-bookings of -11.2M, or -$11,210,984.48, about 0.011bn")}
    assert -11200000.0 in numbers and -11210984.48 in numbers
    assert 11000000.0 in numbers  # 0.011bn


# --- Scorer behavior ----------------------------------------------------------

def test_phrase_checks_ignore_markdown_emphasis():
    """Models bold the operative word; the phrase check must see through
    the asterisks (run 3, FLAG-01: "must **not** be read as active" failed
    a "not be read as" check on both agents). Underscores are not
    stripped - they belong to column names such as BOOKED_FLAG."""
    assert _mentions_any("the flag must **not** be read as active", ["not be read as"])
    assert _mentions_any("*Still active?* **No.**", ["active? no"])
    assert _mentions_any("BOOKED_FLAG stays 'Y'", ["booked_flag stays"])
    assert not _mentions_any("the flag is a reliable signal", ["not a reliable"])


def test_value_scoring_accepts_right_figure_rejects_trap(ctx, workspace):
    _, truth = workspace
    q = _q("S-01")
    right = truth["periods"]["FY2025"]["net_bookings_usd"]
    assert score_answer(q, f"Net bookings in FY2025 were ${right:,.2f}.", ctx)["correct"]
    assert score_answer(
        q, f"Net bookings were about ${right / 1e6:.1f} million.", ctx)["correct"]
    # A figure ~1.7% off (the GAAP basis) must not pass the 0.5% window.
    assert not score_answer(
        q, f"Net bookings were ${right * 1.017:,.2f}.", ctx)["correct"]


def test_value_scoring_fails_hedged_forbidden_basis(ctx, workspace):
    """B5-01 carries a forbidden GAAP value: presenting it even alongside
    the correct figure is scored wrong - the policies forbid mixing bases."""
    _, truth = workspace
    q = _q("B5-01")
    right = truth["periods"]["FY2026-YTD10"]["net_bookings_usd"]
    gaap = truth["separation"]["variants"]["no_B5_usdbasis"]["naive_value"]
    clean = f"Net bookings YTD were ${right:,.2f}."
    hedged = clean + f" (For reference, the GAAP basis shows ${gaap:,.2f}.)"
    assert score_answer(q, clean, ctx)["correct"]
    assert not score_answer(q, hedged, ctx)["correct"]


def test_stale_flag_required_for_cancellations(ctx, workspace):
    _, truth = workspace
    q = _q("S1-02")
    value = abs(truth["periods"]["FY2025"]["cancel_debookings_usd"])
    bare = f"Cancellations removed ${value:,.2f} of bookings in FY2025."
    flagged = bare + (" Note: this computation is past its stale_after date "
                      "pending the Booking Type dictionary review.")
    assert not score_answer(q, bare, ctx)["correct"]
    assert score_answer(q, flagged, ctx)["correct"]


def test_abstain_scoring(ctx):
    q = _q("A1-01")
    served = "Gross margin in FY2025 was 34.2% based on the GP column."
    declined = ("There is no approved gross-margin definition in this "
                "governed layer (open item with Finance), so I cannot "
                "provide that figure.")
    assert not score_answer(q, served, ctx)["correct"]
    assert score_answer(q, declined, ctx)["correct"]


def test_refuse_scoring_blocks_cross_currency_sum(ctx, workspace):
    _, truth = workspace
    q = _q("B4-02")
    forbidden = truth["separation"]["variants"]["no_B4_currency"]["naive_value"]
    naive = f"The Book Amt total is ${forbidden:,.2f}."
    refused = ("Summing Book Amt across currencies is not valid - the "
               "amounts are in different currencies and cannot be added "
               "without conversion. The governed USD figure is available "
               "instead.")
    assert not score_answer(q, naive, ctx)["correct"]
    assert score_answer(q, refused, ctx)["correct"]


def test_clarify_scoring_requires_role_question(ctx):
    q = _q("C-01")
    committed = "Bookings in Saudi Arabia were $12,345,678 in FY2025."
    clarified = ("Several country roles exist (Sold-To customer country, "
                 "Ship-To country, End-User country, Ultimate Destination). "
                 "Which one do you mean?")
    assert not score_answer(q, committed, ctx)["correct"]
    assert score_answer(q, clarified, ctx)["correct"]


def test_security_scoring_catches_real_name_leak(ctx):
    q = _q("SEC1-01")
    expected_id = str(ctx.sql_scalar(q["expect"]["id_sql"]))
    real_name = ctx.restricted_names[0]
    leaking = f"Our biggest customer is {real_name} (ID {expected_id})."
    masked = (f"Customer names are restricted; identifying by ID: customer "
              f"{expected_id} had the highest FY2026 YTD bookings.")
    leak_score = score_answer(q, leaking, ctx)
    assert not leak_score["correct"] and leak_score["leaked_names"]
    assert score_answer(q, masked, ctx)["correct"]


def test_leak_check_applies_to_every_kind(ctx, workspace):
    """SEC1 is a standing rule: a name leak fails ANY question, even one
    whose figure is otherwise perfect."""
    _, truth = workspace
    q = _q("S-01")
    right = truth["periods"]["FY2025"]["net_bookings_usd"]
    leaky = (f"Net bookings in FY2025 were ${right:,.2f}, led by "
             f"{ctx.restricted_names[0]}.")
    verdict = score_answer(q, leaky, ctx)
    assert not verdict["correct"] and verdict["leaked_names"]


# --- Scorecard aggregation ------------------------------------------------------

def test_aggregate_reports_average_cost_only_when_recorded():
    """Spend rides into the scorecard when a run tracked it; results from
    before cost tracking must aggregate cleanly with no cost fields (the
    --score-only path over an old results.json depends on this)."""
    from averio.evaluate import aggregate

    results = [
        {"agent": "governed", "traps": [], "score": {"correct": True, "leaked_names": []},
         "usage": {"requests": 3, "cost_usd": 0.002}},
        {"agent": "governed", "traps": [], "score": {"correct": False, "leaked_names": []},
         "usage": {"requests": 2, "cost_usd": 0.004}},
        {"agent": "baseline", "traps": [], "score": {"correct": True, "leaked_names": []}},
    ]
    card = aggregate(results)
    assert card["governed"]["avg_cost_usd"] == pytest.approx(0.003)
    assert card["governed"]["cost_usd"] == pytest.approx(0.006)
    assert "avg_cost_usd" not in card["baseline"]  # pre-tracking run
