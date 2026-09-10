---
type: Computation
title: Transaction Booking Amount With Tax by fiscal period
description: Sanctioned computation for single-currency, tax-inclusive transaction booking amounts over an FY/PD window.
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
[Transaction Booking Amount With Tax](/metrics/transaction-booking-amount-with-tax.md).
For explicitly tax-inclusive requests only; the PA feed carries no
tax-inclusive amounts, so coverage is Oracle-source only and answers must
say so.

```sql
SELECT SUM("Book Amt WithTax") AS value
FROM bookings
WHERE "FY" = $fiscal_year
  AND "PD" BETWEEN $pd_start AND $pd_end
  AND "Currency" = $currency
```
