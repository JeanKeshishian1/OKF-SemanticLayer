---
type: Computation
title: Cancellation De-bookings USD by fiscal period
description: Sanctioned computation for the CANCEL subset of de-bookings. Freshness is deliberately expired pending the Booking Type dictionary review.
tags: [bookings, computation]
status: stable
confidence: strongly-supported
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified: { by: process:extract-profiler, at: 2026-08-24T09:00:00Z }
stale_after: 2026-07-31
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
[Cancellation De-bookings USD](/metrics/cancellation-debookings-usd.md):
classification strictly by `Booking Type`, never `BOOKED_FLAG`.

**Freshness.** `stale_after` on this computation is intentionally in the
past: the Booking Type dictionary — including nonstandard cancellation
variants — is under open governance review, and until it closes this
computation's coverage (standard `CANCEL` only) cannot be re-certified.
An agent serving this figure MUST surface the stale state and its reason.
Do not advance the date to "fix" it.

```sql
SELECT SUM("USD Fixed Amount") AS value
FROM bookings
WHERE "FY" = $fiscal_year
  AND "PD" BETWEEN $pd_start AND $pd_end
  AND "Booking Type" = 'CANCEL'
```
