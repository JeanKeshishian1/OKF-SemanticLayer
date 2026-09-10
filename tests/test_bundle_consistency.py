"""Drift guards and conformance checks for the Averio MEA Bookings bundle.

Governed knowledge is deliberately duplicated in two places, and this file
is the only thing keeping the copies honest:

  * Sanctioned SQL lives in ``src/averio/sanctioned_sql.py`` (what
    produced the eval answer key) AND in the ```sql fences of
    ``bundle/computations/*.md`` (what the agent resolves and the attester
    compares receipts against). If the copies drift, an agent can pass
    attestation while disagreeing with ground truth, and every eval number
    becomes meaningless.
  * The fiscal calendar lives in ``src/averio/fiscal.py`` (executor side)
    AND is re-implemented independently in the attester. They must never
    share code (a shared bug would self-validate) - so this file makes
    them AGREE instead, across FY2023-FY2030.

Also enforced here: the OKF conventions the bundle promises (frontmatter
with a non-empty ``type`` on every non-reserved .md, root ``okf_version``,
resolvable bundle-absolute links) and the attester's behavior on
compliant, tampered, and misbound receipts.
"""

from __future__ import annotations

import importlib.util
import re
from datetime import date
from pathlib import Path

import yaml

from averio import fiscal
from averio.sanctioned_sql import SANCTIONED

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "bundle"

# Computation concept file -> sanctioned metric key. Every computation
# concept MUST appear here: an uncovered one would silently escape the
# drift check (test_fence_map_is_complete enforces both directions).
FENCE_TO_METRIC = {
    "net-bookings-usd-fp.md": "net_bookings_usd",
    "positive-booking-movements-usd-fp.md": "positive_booking_movements_usd",
    "debookings-usd-fp.md": "debookings_usd",
    "cancellation-debookings-usd-fp.md": "cancel_debookings_usd",
    "transaction-booking-amount-fp.md": "transaction_bookings",
    "transaction-booking-amount-with-tax-fp.md": "transaction_bookings_tax",
    "distinct-sales-orders-fp.md": "sales_order_count",
}

_SQL_FENCE = re.compile(r"```sql\n(.*?)```", re.DOTALL)


def _load_attester():
    """Import the attester from its bundle path (it is not a package -
    and must never become an importable sibling of ``averio``, or someone
    will 'helpfully' share the fiscal code)."""
    path = BUNDLE / "references" / "attesters" / "sql_equality.py"
    spec = importlib.util.spec_from_file_location("sql_equality", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize(sql: str) -> str:
    return " ".join(sql.split())


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} lacks YAML frontmatter"
    end = text.index("\n---", 4)
    return yaml.safe_load(text[4:end])


# --- Drift guard: bundle SQL fences == sanctioned_sql ------------------------

def test_sql_fences_match_sanctioned():
    """Every computation concept's single fence must equal its sanctioned
    SQL, whitespace-normalized: re-indenting is free, any token change is
    drift. Edit one copy, edit the other in the same change."""
    for filename, metric in FENCE_TO_METRIC.items():
        text = (BUNDLE / "computations" / filename).read_text(encoding="utf-8")
        fences = _SQL_FENCE.findall(text)
        assert len(fences) == 1, f"{filename}: expected exactly 1 sql fence, got {len(fences)}"
        assert _normalize(fences[0]) == _normalize(SANCTIONED[metric]), \
            f"{filename} drifted from sanctioned_sql.SANCTIONED[{metric!r}]"


def test_fence_map_is_complete():
    """Both directions: every computation concept is drift-checked, and
    every sanctioned metric has a computation concept."""
    concept_files = {p.name for p in (BUNDLE / "computations").glob("*.md")
                     if p.name != "index.md"}
    assert concept_files == set(FENCE_TO_METRIC), \
        f"FENCE_TO_METRIC out of sync with computations/: {concept_files ^ set(FENCE_TO_METRIC)}"
    assert set(FENCE_TO_METRIC.values()) == set(SANCTIONED), \
        "FENCE_TO_METRIC values out of sync with sanctioned_sql.SANCTIONED"


# --- Cross-check: attester fiscal calendar == harness fiscal calendar --------

def test_attester_calendar_agrees_with_harness():
    """The two independent calendar implementations must agree everywhere.

    Walks every calendar month FY2023-FY2030 and checks the attester's
    month->(FY, PD) lookup against the harness's arithmetic, plus the
    window derivation against the harness's period bounds. Also asserts
    the attester really is independent (no ``averio`` import)."""
    attester = _load_attester()
    src = (BUNDLE / "references" / "attesters" / "sql_equality.py").read_text(encoding="utf-8")
    assert "import averio" not in src and "from averio" not in src, \
        "attester must never import the harness fiscal module"

    for year in range(2022, 2031):
        for month in range(1, 13):
            expected = fiscal.fiscal_of(date(year, month, 1))
            assert attester._fy_pd_of_month(year, month) == expected, \
                f"calendar disagreement at {year}-{month:02d}"

    for fy in range(2023, 2031):
        # Full year, single period, and YTD windows must all reconstruct
        # the same calendar spans the harness derives.
        assert attester._expected_window(None, False) == (1, 12)
        start, end = fiscal.period_range_bounds(fy, 1, 12)
        assert (start, end) == fiscal.fiscal_year_bounds(fy)
        for pd in range(1, 13):
            assert attester._expected_window(pd, False) == (pd, pd)
            assert attester._expected_window(pd, True) == (1, pd)
            # The harness period's starting month must map back to the
            # same (fy, pd) through the attester's lookup table.
            p_start, _ = fiscal.fiscal_period_bounds(fy, pd)
            assert attester._fy_pd_of_month(p_start.year, p_start.month) == (fy, pd)


# --- Attester behavior on receipts -------------------------------------------

def _compliant_receipt(attester, metric="net_bookings_usd", result=123.45):
    """A receipt the executor contract would legitimately produce for
    'net bookings FY2026 YTD through PD10, operational scope'."""
    sql = SANCTIONED[metric]
    params = {"fiscal_year": 2026, "pd_start": 1, "pd_end": 10,
              "trade_scope": "operational"}
    return {
        "executed_sql": sql,
        "bound_params": params,
        "query_hash": attester._expected_hash(sql, params),
        "result": result,
    }, {"fiscal_year": 2026, "fiscal_period": 10, "ytd": True}


def test_attester_accepts_compliant_receipt():
    attester = _load_attester()
    receipt, claim = _compliant_receipt(attester)
    verdict = attester.attest(receipt, SANCTIONED["net_bookings_usd"], claim)
    assert verdict["ok"], verdict["reasons"]
    # A calendar-month claim resolving to the same period must also pass -
    # this is the independent month->FY/PD conversion doing real work.
    sql = SANCTIONED["net_bookings_usd"]
    params = {"fiscal_year": 2026, "pd_start": 10, "pd_end": 10,
              "trade_scope": "operational"}
    receipt2 = {"executed_sql": sql, "bound_params": params,
                "query_hash": attester._expected_hash(sql, params), "result": 1.0}
    verdict2 = attester.attest(receipt2, sql, {"calendar_month": "2026-07"})
    assert verdict2["ok"], verdict2["reasons"]


def test_attester_rejects_agent_authored_sql():
    """An agent quietly 'improving' the SQL - here, dropping negative
    movements exactly like naive variant B1 - must fail SQL equality even
    with an honestly computed hash."""
    attester = _load_attester()
    receipt, claim = _compliant_receipt(attester)
    authored = receipt["executed_sql"] + "\n  AND \"USD Fixed Amount\" > 0"
    receipt["executed_sql"] = authored
    receipt["query_hash"] = attester._expected_hash(authored, receipt["bound_params"])
    verdict = attester.attest(receipt, SANCTIONED["net_bookings_usd"], claim)
    assert not verdict["ok"]
    assert not verdict["checks"]["sql_matches_sanctioned"]


def test_attester_rejects_wrong_period_binding():
    """Right SQL, wrong window: claim says YTD-through-PD10 but the
    executor bound a single period. The independent re-derivation must
    catch it even though the hash is internally consistent."""
    attester = _load_attester()
    receipt, claim = _compliant_receipt(attester)
    receipt["bound_params"] = {"fiscal_year": 2026, "pd_start": 10,
                               "pd_end": 10, "trade_scope": "operational"}
    receipt["query_hash"] = attester._expected_hash(
        receipt["executed_sql"], receipt["bound_params"])
    verdict = attester.attest(receipt, SANCTIONED["net_bookings_usd"], claim)
    assert not verdict["ok"]
    assert not verdict["checks"]["binding_matches_claim"]


def test_attester_rejects_incoherent_month_claim():
    """A claim carrying both a calendar month and a mismatched FY/PD is a
    resolver bug (the F1 trap in action) and must be rejected, not
    silently repaired."""
    attester = _load_attester()
    sql = SANCTIONED["sales_order_count"]
    params = {"fiscal_year": 2025, "pd_start": 3, "pd_end": 3}
    receipt = {"executed_sql": sql, "bound_params": params,
               "query_hash": attester._expected_hash(sql, params), "result": 7}
    # December 2024 is PD3 of FY2025; claiming FY2024 misreads the naming.
    verdict = attester.attest(receipt, sql, {
        "calendar_month": "2024-12", "fiscal_year": 2024})
    assert not verdict["ok"]
    assert not verdict["checks"]["binding_matches_claim"]


def test_attester_rejects_tampered_hash():
    attester = _load_attester()
    receipt, claim = _compliant_receipt(attester)
    receipt["query_hash"] = "0" * 64
    verdict = attester.attest(receipt, SANCTIONED["net_bookings_usd"], claim)
    assert not verdict["ok"]
    assert not verdict["checks"]["hash_integrity"]


# --- OKF conformance ---------------------------------------------------------

def _bundle_markdown():
    return sorted(BUNDLE.rglob("*.md"))


def test_frontmatter_type_on_every_concept():
    """Every .md except the reserved index.md / log.md needs YAML
    frontmatter with a non-empty ``type`` - that is what makes it a
    resolvable OKF concept rather than loose prose."""
    for path in _bundle_markdown():
        if path.name in ("index.md", "log.md"):
            continue
        fm = _frontmatter(path)
        assert fm.get("type"), f"{path} missing non-empty frontmatter 'type'"


def test_root_index_declares_okf_version():
    fm = _frontmatter(BUNDLE / "index.md")
    assert fm.get("okf_version") == "0.2"


_LINK = re.compile(r"\]\((/[^)\s#]+\.(?:md|py))\)")


def test_internal_links_resolve():
    """Links are bundle-absolute (/policies/x.md) and must resolve - a
    dangling link is knowledge the resolver can cite but never retrieve."""
    for path in _bundle_markdown():
        for target in _LINK.findall(path.read_text(encoding="utf-8")):
            assert (BUNDLE / target.lstrip("/")).exists(), \
                f"{path}: dangling link {target}"


def test_security_restrictions_declared():
    """The security dimension of the eval depends on the bundle actually
    declaring the name columns blocked - both in the policy and on the
    table concept - so their absence is a conformance failure, not a
    documentation nit."""
    policy = (BUNDLE / "policies" / "security-and-disclosure.md").read_text(encoding="utf-8")
    table = (BUNDLE / "tables" / "bookings.md").read_text(encoding="utf-8")
    for column in ("Customer Name", "Enduser Name"):
        assert column in policy, f"security policy silent on {column!r}"
        assert re.search(rf"`{column}`.*Restricted", table), \
            f"bookings table does not mark {column!r} restricted"


def test_stale_computation_is_stale():
    """Trap S1 is load-bearing frontmatter: the cancellation computation's
    stale_after must remain in the past relative to the pinned as-of date.
    'Fixing' the date would delete a scored eval behavior."""
    fm = _frontmatter(BUNDLE / "computations" / "cancellation-debookings-usd-fp.md")
    stale_after = fm["stale_after"]
    if not isinstance(stale_after, date):  # yaml may parse it either way
        stale_after = date.fromisoformat(str(stale_after))
    from averio.generate_data import DEFAULT_AS_OF
    assert stale_after < DEFAULT_AS_OF, \
        "cancellation computation must stay stale at the pinned as-of (trap S1)"
