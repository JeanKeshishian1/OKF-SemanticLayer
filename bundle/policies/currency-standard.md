---
type: Policy
title: Currency Standard
description: Defines the canonical USD basis for cross-currency figures and the discipline for transaction-currency amounts.
tags: [currency, policy]
status: stable
confidence: confirmed-internally
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified: { by: human:JeanKeshishian, at: 2026-08-24T14:00:00Z }
stale_after: 2027-09-30
sources:
  - id: handoff-v2
    resource: repo:docs/Averio_Semantic_Layer_AI_Handoff_v2.docx
    title: Governed AI Handoff Specification v2
    author: human:JeanKeshishian
    last_modified: 2026-08-24
---

# Canonical USD basis

The one sanctioned cross-currency measure is **`"USD Fixed Amount"`** —
each movement's transaction amount converted at the fiscal year's fixed
(plan) rate, precomputed on every row. [^handoff-v2]

- **Do not** use `"USD GAAP Amount"`, `"Functional Amt"`, or any other
  amount column as a substitute; their rate bases differ and none is
  approved for Bookings reporting (open item: Fixed/GAAP/functional rate
  semantics).
- **Do not** derive USD as `"Book Amt" × "Fixed Rate"`: the rate column is
  NULL on PA-source rows, so the derivation silently drops an entire
  source system. The precomputed column exists precisely so nobody
  re-derives it.

# Transaction-currency discipline

- `"Book Amt"` (and `"Book Amt WithTax"`) are signed amounts in the
  order's transaction `"Currency"`. Amounts in different currencies MUST
  NOT be summed without conversion — the
  [transaction amount computation](/computations/transaction-booking-amount-fp.md)
  therefore *requires* a single-currency parameter.
- Never mix `"Book Amt"`, `"Book Amt WithTax"`, and USD columns in one
  figure. Tax-inclusive amounts serve explicitly tax-inclusive requests
  only.
- `"Book Amt WithTax"` is not populated by the PA feed; the tax-inclusive
  metric is implicitly Oracle-source only, and answers must say so.

[^handoff-v2]: Governed AI Handoff Specification v2, §5 (Governed metrics,
    "Do not do this" controls).
