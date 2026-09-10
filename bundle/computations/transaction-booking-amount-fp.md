---
type: Computation
title: Transaction Booking Amount by fiscal period
description: Sanctioned computation for single-currency transaction booking amounts over an FY/PD window. The currency parameter is required.
tags: [bookings, currency, computation]
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
  - name: currency
    required: true
    description: exactly one transaction currency code - never a cross-currency sum
executor:
  resource: /references/executors/run-duckdb.md
  receipt: [executed_sql, bound_params, query_hash, result]
attester:
  resource: /references/attesters/sql_equality.py
---

# Computation

Implements
[Transaction Booking Amount](/metrics/transaction-booking-amount.md) under
the [currency standard](/policies/currency-standard.md). The required
`currency` parameter is the enforcement of trap-free currency discipline:
a multi-currency answer is several executions of this computation, one
per currency, never one summed figure.

```sql
SELECT SUM("Book Amt") AS value
FROM bookings
WHERE "FY" = $fiscal_year
  AND "PD" BETWEEN $pd_start AND $pd_end
  AND "Currency" = $currency
```
