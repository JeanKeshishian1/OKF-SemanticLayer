"""Deterministic attester for Averio MEA Bookings computation receipts.

Given a receipt produced by the executor contract
(/references/executors/run-duckdb.md), the sanctioned SQL text from the
computation concept, and the *semantic claim* the answer makes ("this is
net bookings for FY2026 YTD through PD10"), this module decides - with no
LLM involvement and no database access - whether the receipt proves the
claim. Four independent checks:

  1. receipt_complete        every receipt field is present
  2. sql_matches_sanctioned  the executed SQL is the sanctioned text
                             (whitespace-normalized: re-indenting is free,
                             any token change is drift)
  3. binding_matches_claim   the bound parameters equal an INDEPENDENT
                             re-derivation from the claim, including this
                             module's own calendar-month -> FY/PD mapping
  4. hash_integrity          the receipt hash binds this SQL to these
                             bindings (neither can be swapped afterwards)

DELIBERATE NON-SHARING: this file re-implements the Averio fiscal
calendar (October-start, FY named for its ending year) instead of
importing ``averio.fiscal``. If the attester shared date code with the
executor side, one bug would corrupt the parameter binding and the check
of that binding identically, and attestation would pass vacuously.
``tests/test_bundle_consistency.py`` cross-checks the two implementations
over FY2023-FY2030; keep them independent and let the test do the
agreeing. Never add an ``averio`` import here.
"""

from __future__ import annotations

import hashlib
import json

# --- Independent fiscal calendar --------------------------------------------
# Expressed as a lookup table rather than arithmetic on purpose: it is a
# *different implementation* of the same governed fact (PD1 = October), so a
# copy-paste error in one implementation cannot hide in the other.
_PD_OF_MONTH = {10: 1, 11: 2, 12: 3, 1: 4, 2: 5, 3: 6,
                4: 7, 5: 8, 6: 9, 7: 10, 8: 11, 9: 12}
# Months that belong to the fiscal year ENDING in the following calendar
# year (the October-December stub that opens each FY).
_NEXT_YEAR_MONTHS = (10, 11, 12)


def _fy_pd_of_month(year: int, month: int) -> tuple[int, int]:
    """Independently map a calendar (year, month) to (fiscal_year, PD)."""
    if month not in _PD_OF_MONTH:
        raise ValueError(f"month must be 1..12, got {month}")
    fy = year + 1 if month in _NEXT_YEAR_MONTHS else year
    return fy, _PD_OF_MONTH[month]


def _expected_window(fiscal_period, ytd) -> tuple[int, int]:
    """Re-derive the (pd_start, pd_end) window the executor should have
    bound. Mirrors the executor CONTRACT (the prose in run-duckdb.md), not
    the executor's code."""
    if fiscal_period is None:
        if ytd:
            raise ValueError("ytd requires fiscal_period")
        return 1, 12  # full fiscal year
    pd = int(fiscal_period)
    if not 1 <= pd <= 12:
        raise ValueError(f"fiscal_period must be 1..12, got {pd}")
    return (1, pd) if ytd else (pd, pd)


# --- Receipt verification ----------------------------------------------------

_RECEIPT_FIELDS = ("executed_sql", "bound_params", "query_hash", "result")


def _normalize(sql: str) -> str:
    """Whitespace-normalize SQL: collapse every run of whitespace to one
    space and trim. Formatting is free; every token is load-bearing."""
    return " ".join(sql.split())


def _expected_hash(executed_sql: str, bound_params: dict) -> str:
    """Recompute the receipt hash exactly as the executor contract states:
    sha256 over the normalized SQL and the canonical (sorted-key, no-space
    JSON) parameter serialization, joined by '|'."""
    canonical = json.dumps(bound_params, sort_keys=True, separators=(",", ":"))
    payload = _normalize(executed_sql) + "|" + canonical
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _expected_binding(claim: dict, sanctioned_sql: str) -> dict:
    """Independently re-derive the full parameter binding from the claim.

    The claim may name the period semantically (fiscal_year [+
    fiscal_period] [+ ytd]) or as a calendar month ("calendar_month":
    "YYYY-MM", e.g. resolved from a question like "July 2026"). When both
    forms appear they must agree - a resolver that says "July 2026" and
    binds PD4 is exactly the bug this check exists to catch.
    """
    fiscal_year = claim.get("fiscal_year")
    fiscal_period = claim.get("fiscal_period")
    if claim.get("calendar_month"):
        y, m = (int(part) for part in str(claim["calendar_month"]).split("-"))
        month_fy, month_pd = _fy_pd_of_month(y, m)
        if fiscal_year is not None and int(fiscal_year) != month_fy:
            raise ValueError(
                f"claim incoherent: calendar_month {claim['calendar_month']} "
                f"is FY{month_fy}, claim says FY{fiscal_year}")
        if fiscal_period is not None and int(fiscal_period) != month_pd:
            raise ValueError(
                f"claim incoherent: calendar_month {claim['calendar_month']} "
                f"is PD{month_pd}, claim says PD{fiscal_period}")
        fiscal_year, fiscal_period = month_fy, month_pd
    if fiscal_year is None:
        raise ValueError("claim must carry fiscal_year or calendar_month")

    pd_start, pd_end = _expected_window(fiscal_period, claim.get("ytd"))
    expected = {"fiscal_year": int(fiscal_year),
                "pd_start": pd_start, "pd_end": pd_end}

    # Metric-specific parameters exist only where the sanctioned SQL
    # declares them - binding extras is as much a violation as omitting
    # required ones.
    if "$currency" in sanctioned_sql:
        if not claim.get("currency"):
            raise ValueError("this computation requires a currency claim")
        expected["currency"] = str(claim["currency"])
    if "$trade_scope" in sanctioned_sql:
        scope = claim.get("trade_scope") or "operational"
        if scope not in ("operational", "trade"):
            raise ValueError(f"illegal trade_scope {scope!r}")
        expected["trade_scope"] = scope
    return expected


def attest(receipt: dict, sanctioned_sql: str, claim: dict) -> dict:
    """Verify a receipt against the sanctioned SQL and the semantic claim.

    Returns {"ok": bool, "checks": {name: bool}, "reasons": [str]} - the
    caller surfaces reasons verbatim so a failed attestation is
    explainable, not just red.
    """
    checks = {"receipt_complete": False, "sql_matches_sanctioned": False,
              "binding_matches_claim": False, "hash_integrity": False}
    reasons: list[str] = []

    # 1. Completeness first: the other checks dereference these fields.
    missing = [f for f in _RECEIPT_FIELDS if f not in (receipt or {})]
    checks["receipt_complete"] = not missing
    if missing:
        reasons.append(f"receipt missing fields: {missing}")
        return {"ok": False, "checks": checks, "reasons": reasons}

    # 2. SQL equality. Normalized comparison: the agent may not author,
    # edit, or re-indent SQL, but the *executor* fence extraction is
    # allowed to differ in whitespace only.
    if _normalize(receipt["executed_sql"]) == _normalize(sanctioned_sql):
        checks["sql_matches_sanctioned"] = True
    else:
        reasons.append("executed SQL differs from the sanctioned computation")

    # 3. Binding vs independent re-derivation from the claim.
    try:
        expected = _expected_binding(claim, sanctioned_sql)
        if receipt["bound_params"] == expected:
            checks["binding_matches_claim"] = True
        else:
            reasons.append(
                f"bound params {receipt['bound_params']} != expected {expected}")
    except ValueError as exc:
        reasons.append(f"claim rejected: {exc}")

    # 4. Hash integrity: binds the SQL text to the bindings so a receipt
    # cannot be assembled from a compliant query and someone else's params.
    if receipt["query_hash"] == _expected_hash(
            receipt["executed_sql"], receipt["bound_params"]):
        checks["hash_integrity"] = True
    else:
        reasons.append("query_hash does not match executed_sql + bound_params")

    return {"ok": all(checks.values()), "checks": checks, "reasons": reasons}
