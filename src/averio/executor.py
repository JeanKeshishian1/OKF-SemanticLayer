"""Executor side of the attested-computation contract.

Implements, in code, exactly what ``bundle/references/executors/run-duckdb.md``
promises in prose: resolve the sanctioned SQL verbatim, derive the PD
window from semantic parameters, bind through the driver, execute
read-only, and emit a receipt the attester can verify. The agent never
calls DuckDB - it calls this, with semantic parameters only.

Two deliberate design points:

  * **Refusal, not repair.** An illegal ask (PD 13, a transaction metric
    without a currency, a parameter the SQL does not declare) raises
    ``ExecutionRefused``. Guessing what the caller meant is exactly the
    ungoverned behavior the layer exists to prevent.
  * **Independent hashing.** The receipt hash is computed here AND
    re-derived independently by the attester from the contract's wording.
    They are separate implementations on purpose - like the fiscal
    calendar, shared code would let one bug validate itself.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

import duckdb

from averio import fiscal
from averio.bundle_loader import Concept


class ExecutionRefused(ValueError):
    """The semantic parameters violate the executor contract."""


def derive_window(fiscal_period, ytd) -> tuple[int, int]:
    """Semantic period -> inclusive (pd_start, pd_end), per the contract:
    (pd, pd) for one period, (1, 12) for the full FY, (1, pd) for YTD.
    Anything else is rejected, not repaired."""
    if fiscal_period is None:
        if ytd:
            raise ExecutionRefused("ytd requires fiscal_period")
        return 1, 12
    pd = int(fiscal_period)
    if not 1 <= pd <= 12:
        raise ExecutionRefused(f"fiscal_period must be 1..12, got {fiscal_period}")
    return (1, pd) if ytd else (pd, pd)


def _normalize(sql: str) -> str:
    """Whitespace-normalized SQL, per the contract's hash definition."""
    return " ".join(sql.split())


def query_hash(executed_sql: str, bound_params: dict) -> str:
    """sha256(normalize(sql) + '|' + sorted-key no-space JSON params) -
    binds this SQL text to these bindings so neither can be swapped."""
    canonical = json.dumps(bound_params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((_normalize(executed_sql) + "|" + canonical).encode("utf-8")).hexdigest()


def execute(computation: Concept, db_path: str, *, fiscal_year,
            fiscal_period=None, ytd: bool = False,
            currency: str | None = None, trade_scope: str | None = None) -> dict:
    """Run one sanctioned computation and return its receipt.

    ``computation`` must be a Computation concept (its single sql fence is
    what runs - verbatim). The keyword-only signature mirrors the agent's
    entire permitted surface; there is deliberately no parameter through
    which SQL text, table names, or extra filters could arrive.
    """
    if computation.type != "Computation" or not computation.sql:
        raise ExecutionRefused(f"{computation.concept_id} is not an executable computation")
    sql = computation.sql

    if fiscal_year is None:
        raise ExecutionRefused("fiscal_year is required")
    pd_start, pd_end = derive_window(fiscal_period, ytd)
    # Sanity-tie to the fiscal module: the window must be constructible on
    # the executor-side calendar (raises on cross-year or bad PDs). The
    # attester will re-derive the same window on ITS calendar.
    fiscal.period_range_bounds(int(fiscal_year), pd_start, pd_end)

    bound: dict = {"fiscal_year": int(fiscal_year),
                   "pd_start": pd_start, "pd_end": pd_end}

    # Metric-specific parameters exist only where the sanctioned SQL
    # declares them. Binding extras is as much a contract violation as
    # omitting required ones - both directions are checked.
    if "$currency" in sql:
        if not currency:
            raise ExecutionRefused(
                f"{computation.concept_id} requires a currency - transaction "
                "amounts are never summed across currencies")
        bound["currency"] = str(currency)
    elif currency is not None:
        raise ExecutionRefused(f"{computation.concept_id} takes no currency parameter")
    if "$trade_scope" in sql:
        scope = trade_scope or "operational"  # contract default
        if scope not in ("operational", "trade"):
            raise ExecutionRefused(f"illegal trade_scope {scope!r}")
        bound["trade_scope"] = scope
    elif trade_scope is not None:
        raise ExecutionRefused(f"{computation.concept_id} takes no trade_scope parameter")

    # Read-only is part of the contract: the executor can never mutate the
    # snapshot, so a receipt can always be re-verified against it.
    con = duckdb.connect(db_path, read_only=True)
    try:
        result = con.execute(sql, bound).fetchone()[0]
    finally:
        con.close()
    if isinstance(result, Decimal):  # JSON-friendly receipts
        result = float(result)

    return {
        "executed_sql": sql,          # verbatim fence text, never reformatted
        "bound_params": bound,
        "query_hash": query_hash(sql, bound),
        "result": result,
    }
