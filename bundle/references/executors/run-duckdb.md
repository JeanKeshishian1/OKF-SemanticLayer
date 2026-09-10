---
type: Executor
title: DuckDB Executor Contract
description: How a sanctioned computation is executed - parameter derivation, binding, read-only execution, and the receipt the attester verifies.
tags: [executor, trust]
status: stable
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified: { by: human:JeanKeshishian, at: 2026-08-24T14:00:00Z }
stale_after: 2027-09-30
---

# Contract

The executor is the only component that touches SQL and the database. The
agent supplies **semantic parameters only** — it never authors, edits, or
re-indents SQL, and it never sees the database connection.

1. **Resolve.** Load the computation concept and extract the contents of
   its single ```sql fence, verbatim. That text is `executed_sql` — no
   reformatting, no substitution.
2. **Derive the period window.** From the semantic parameters, derive the
   inclusive PD range:
   - `fiscal_period` given, `ytd` absent/false → `(pd, pd)`
   - `fiscal_period` absent → `(1, 12)` (full fiscal year)
   - `fiscal_period` given, `ytd: true` → `(1, pd)`
   Anything else (PD outside 1–12, a range spanning fiscal years) is
   rejected, not repaired.
3. **Bind.** Bind exactly the named parameters the SQL declares:
   `$fiscal_year`, `$pd_start`, `$pd_end`, plus `$currency` where declared
   (required — refuse to run a transaction metric without one) and
   `$trade_scope` where declared (default `'operational'`; only
   `'operational'` or `'trade'` are legal). Binding happens through the
   database driver's parameter mechanism — never string interpolation.
4. **Execute read-only.** Open the DuckDB snapshot file in read-only mode
   and execute. The snapshot's `REFRESH_DATE` is the session's freshness
   context; the executor takes no date override, because "as of when" is a
   property of the snapshot, not a query knob.
5. **Emit the receipt**:

   ```
   {
     "executed_sql":  <the verbatim fence text>,
     "bound_params":  {name: value, ...},
     "query_hash":    sha256(normalize(executed_sql) + "|" + canonical_params),
     "result":        <the scalar value>
   }
   ```

   where `normalize` collapses all whitespace runs to single spaces and
   trims, and `canonical_params` is the bound-params object serialized as
   JSON with sorted keys and no spaces. The hash binds *this SQL* to
   *these bindings*, so neither can be swapped after the fact.

Receipts are **runtime artifacts**: they travel with the answer as
provenance and are verified by the attester
(`/references/attesters/sql_equality.py`), but they are never written into
the bundle.
