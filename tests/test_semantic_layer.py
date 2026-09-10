"""Behavioral tests for the semantic-layer facade (resolver + attested path).

These tests exercise the layer exactly the way the governed agent will:
resolve a term, read the ambiguity/security guidance, run a sanctioned
computation, and check the attested result against the generated answer
key (the ``workspace``/``layer`` fixtures in conftest.py). A passing suite
means the resolver, the executor, the attester, and the answer key all
agree end to end.
"""

from __future__ import annotations

import pytest

from averio.executor import ExecutionRefused

# --- Term resolution ----------------------------------------------------------

def test_resolve_alias_carries_confidence_and_trust(layer):
    """'Bookings' must land on the headline metric WITH its governance
    context - the confidence label and trust tier are what the governed
    agent quotes in provenance."""
    record = layer.resolve("Bookings")
    assert record["concept_id"] == "metrics/net-bookings-usd"
    assert record["type"] == "Metric"
    assert record["confidence"] == "confirmed-plus-dataset-supported"
    assert record["trust_tier"] == "human-reviewed"  # human:JeanKeshishian verified
    assert record["computation"] == "computations/net-bookings-usd-fp"
    # The resolution record must carry the concept's own caveats, not just
    # metadata - run 1 failures traced back to guidance the bundle had but
    # the resolver did not serve.
    assert "Never exclude negative movements" in record["guidance"]


def test_resolve_customer_roles_are_distinct(layer):
    """Trap M1: 'customer' and 'enduser' resolve to different entities."""
    assert layer.resolve("customer")["concept_id"] == "entities/sold-to-customer"
    assert layer.resolve("enduser")["concept_id"] == "entities/end-user"


def test_resolve_absent_concept_returns_none(layer):
    """Trap A1: what the bundle does not govern resolves to None - the
    abstention signal. None of these may ever quietly resolve."""
    for term in ("gross margin", "churn", "AUP", "lead time", "gross new bookings"):
        assert layer.resolve(term) is None, f"{term!r} should not resolve"


# --- Policy tables as data ----------------------------------------------------

def test_ambiguity_rule_country_has_no_default(layer):
    """The country rule is the always-clarify case: four role-specific
    country columns exist, so a default would be a silent guess."""
    rule = layer.ambiguity_rule("country")
    assert rule is not None
    assert "No default" in rule["default"]


def test_ambiguity_rule_interco_requires_abstention(layer):
    rule = layer.ambiguity_rule("Interco total")
    assert rule is not None
    assert "elimination" in rule["abstain_when"].lower()


def test_security_rules_block_name_columns(layer):
    """Trap SEC1: both name columns blocked outright; commercially
    sensitive amounts aggregate-only. Read from the table concept, so a
    schema/policy drift would fail here too."""
    rules = layer.security_rules()
    assert "Customer Name" in rules["blocked_columns"]
    assert "Enduser Name" in rules["blocked_columns"]
    for column in ("GP", "COGS Amt", "USD Fixed Amount"):
        assert column in rules["aggregate_only_columns"]


# --- Attested computation against the answer key ------------------------------

def test_compute_full_year_matches_ground_truth(layer, workspace):
    _, truth = workspace
    answer = layer.compute("metrics/net-bookings-usd", fiscal_year=2025)
    assert answer["attested"] and all(answer["attestation"]["checks"].values())
    assert answer["value"] == pytest.approx(truth["periods"]["FY2025"]["net_bookings_usd"])
    prov = answer["provenance"]
    assert prov["window"] == "FY2025"
    assert prov["confidence"] == "confirmed-plus-dataset-supported"
    assert prov["grain"] == "signed booking movement"
    # Caveats ride along at serving time too.
    assert "Never exclude negative movements" in prov["guidance"]


def test_compute_via_term_and_single_period(layer, workspace):
    """The agent can hand compute() a raw user term; resolution happens
    inside the governed path, not in agent-authored glue."""
    _, truth = workspace
    answer = layer.compute("bookings", fiscal_year=2026, fiscal_period=5)
    assert answer["value"] == pytest.approx(
        truth["periods"]["FY2026-PD05"]["net_bookings_usd"])


def test_compute_ytd_with_trade_scope(layer, workspace):
    """Trap T1's servable half: the external-market view is the same
    sanctioned SQL bound with trade_scope='trade' - and the attester must
    accept that binding against the same semantic claim."""
    _, truth = workspace
    answer = layer.compute("metrics/net-bookings-usd", fiscal_year=2026,
                           fiscal_period=10, ytd=True, trade_scope="trade")
    assert answer["value"] == pytest.approx(
        truth["periods"]["FY2026-YTD10"]["net_bookings_usd_trade"])
    assert answer["provenance"]["trade_scope"] == "trade"


def test_compute_transaction_metric_requires_currency(layer, workspace):
    """Trap B4 at the interface: no currency, no execution - and with a
    currency, the figure matches the per-currency answer key."""
    _, truth = workspace
    with pytest.raises(ExecutionRefused):
        layer.compute("metrics/transaction-booking-amount", fiscal_year=2025)
    answer = layer.compute("metrics/transaction-booking-amount",
                           fiscal_year=2025, currency="AED")
    assert answer["value"] == pytest.approx(
        truth["periods"]["FY2025"]["transaction_bookings"]["AED"])


def test_compute_refuses_undeclared_parameters(layer):
    """Binding extras is as illegal as omitting required params - the
    executor enforces the declared surface in both directions."""
    with pytest.raises(ExecutionRefused):
        layer.compute("metrics/distinct-sales-orders", fiscal_year=2025,
                      trade_scope="trade")
    with pytest.raises(ExecutionRefused):
        layer.compute("metrics/net-bookings-usd", fiscal_year=2025,
                      currency="USD")


def test_compute_stale_computation_is_flagged_not_hidden(layer, workspace):
    """Trap S1: the cancellation computation is past its stale_after. The
    layer still computes (the figure is real) but flags staleness with the
    reason - suppressing either the value or the flag would be wrong."""
    _, truth = workspace
    answer = layer.compute("metrics/cancellation-debookings-usd", fiscal_year=2025)
    assert answer["stale"] is True
    assert "stale_after" in answer["stale_reason"]
    assert answer["value"] == pytest.approx(
        truth["periods"]["FY2025"]["cancel_debookings_usd"])


def test_compute_unknown_metric_raises(layer):
    with pytest.raises(LookupError):
        layer.compute("gross margin", fiscal_year=2025)
