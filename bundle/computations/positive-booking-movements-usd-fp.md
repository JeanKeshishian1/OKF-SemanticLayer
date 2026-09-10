---
type: Computation
title: Positive Booking Movements USD by fiscal period
description: Sanctioned computation for the positive-movements diagnostic over an FY/PD window.
tags: [bookings, computation]
status: stable
confidence: confirmed-internally
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified: { by: human:JeanKeshishian, at: 2026-08-24T14:00:00Z }
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

Implements
[Positive Booking Movements USD](/metrics/positive-booking-movements-usd.md).
Serve only with the mandatory caveat: positive movements include CHANGE
corrections and KOB positive legs — this is **not** Gross New Bookings.

```sql
SELECT SUM("USD Fixed Amount") AS value
FROM bookings
WHERE "FY" = $fiscal_year
  AND "PD" BETWEEN $pd_start AND $pd_end
  AND "USD Fixed Amount" > 0
```
