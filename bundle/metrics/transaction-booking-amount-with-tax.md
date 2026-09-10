---
type: Metric
title: Transaction Booking Amount With Tax
description: Signed tax-inclusive booking amount in ONE transaction currency, for explicitly tax-inclusive requests only.
aliases: [book amt withtax, tax-inclusive bookings]
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

The signed sum of `"Book Amt WithTax"` for a fiscal window and exactly one
currency — served only when the requester explicitly wants tax-inclusive
figures. [^currency-policy]

The sanctioned computation is
[computations/transaction-booking-amount-with-tax-fp.md](/computations/transaction-booking-amount-with-tax-fp.md).

# Controls

- Never mixed with `"Book Amt"` or any USD measure in one figure.
- The PA feed does not carry tax-inclusive amounts, so this metric is
  implicitly Oracle-source only; answers must state that coverage limit.
- Not a tax metric: the tax *component* alone is not governed.

[^currency-policy]: Currency Standard.
