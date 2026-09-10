---
type: Computation
title: Net Bookings USD by fiscal period
description: Sanctioned computation for Net Bookings USD over an FY/PD window, with optional Trade-only scope.
tags: [bookings, computation]
status: stable
confidence: confirmed-plus-dataset-supported
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified:
  - { by: human:JeanKeshishian, at: 2026-08-24T14:00:00Z }
  - { by: process:extract-profiler, at: 2026-08-24T09:00:00Z }
stale_after: 2027-09-30
runtime: duckdb
parameters:
  - name: fiscal_year
    required: true
    description: FY named for its ending calendar year
  - name: fiscal_period
    required: false
    description: PD 1-12; omit for the full fiscal year
  - name: ytd
    required: false
    description: with fiscal_period, widens the window to PD1..fiscal_period
  - name: trade_scope
    required: false
    description: "'operational' (default, all recorded activity) or 'trade' (external market)"
executor:
  resource: /references/executors/run-duckdb.md
  receipt: [executed_sql, bound_params, query_hash, result]
attester:
  resource: /references/attesters/sql_equality.py
---

# Computation

Implements [Net Bookings USD](/metrics/net-bookings-usd.md) under the
[booking recognition policy](/policies/booking-recognition.md) and the
[currency standard](/policies/currency-standard.md). The executor derives
`$pd_start`/`$pd_end` from the semantic parameters and binds
`$trade_scope` (defaulting to `operational`); no consolidated/eliminated
view exists.

```sql
SELECT SUM("USD Fixed Amount") AS value
FROM bookings
WHERE "FY" = $fiscal_year
  AND "PD" BETWEEN $pd_start AND $pd_end
  AND ($trade_scope = 'operational' OR "Interco & Trade" = 'Trade')
```
