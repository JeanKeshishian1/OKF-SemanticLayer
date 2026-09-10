---
type: Computation
title: Distinct Sales Orders by fiscal period
description: Sanctioned computation for order-header distinct counts over an FY/PD window.
tags: [orders, computation]
status: stable
confidence: strongly-supported
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified: { by: process:extract-profiler, at: 2026-08-24T09:00:00Z }
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
executor:
  resource: /references/executors/run-duckdb.md
  receipt: [executed_sql, bound_params, query_hash, result]
attester:
  resource: /references/attesters/sql_equality.py
---

# Computation

Implements [Distinct Sales Orders](/metrics/distinct-sales-orders.md):
order-header distinctness over movements in the window. Carry the standing
caveat that global SO uniqueness across Source/OU is not technically
proven.

```sql
SELECT COUNT(DISTINCT "SO") AS value
FROM bookings
WHERE "FY" = $fiscal_year
  AND "PD" BETWEEN $pd_start AND $pd_end
```
