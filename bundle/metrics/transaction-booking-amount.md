---
type: Metric
title: Transaction Booking Amount
description: Signed booking amount in ONE transaction currency. Requires a currency parameter - never summed across currencies.
aliases: [book amt, transaction amount, transaction bookings]
tags: [bookings, currency]
status: stable
confidence: confirmed-internally
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified: { by: human:JeanKeshishian, at: 2026-08-24T14:00:00Z }
stale_after: 2027-09-30
sources:
  - id: currency-policy
    resource: policies/currency-standard.md
    title: Currency Standard
    author: human:JeanKeshishian
    last_modified: 2026-08-24
---

# Definition

The signed sum of `"Book Amt"` — the movement amount in its transaction
`"Currency"` — for a fiscal window and **exactly one currency**.
[^currency-policy]

The sanctioned computation is
[computations/transaction-booking-amount-fp.md](/computations/transaction-booking-amount-fp.md);
its `currency` parameter is required precisely so this metric cannot be
asked to add dirhams to dollars. A multi-currency view is a set of
single-currency figures, one per currency — never one number.

# Controls

- Never mix with `"Book Amt WithTax"` or any USD column in one figure.
- Cross-currency totals belong to
  [Net Bookings USD](/metrics/net-bookings-usd.md).

[^currency-policy]: Currency Standard.
