---
type: Metric
title: Net Bookings USD
description: Net signed booking value in USD, including positive and negative movements. The headline metric and the default meaning of "bookings".
aliases: [bookings, net bookings, booking value, sales orders value]
tags: [bookings, headline-metric]
status: stable
confidence: confirmed-plus-dataset-supported
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified:
  - { by: human:JeanKeshishian, at: 2026-08-24T14:00:00Z }
  - { by: process:extract-profiler, at: 2026-08-24T09:00:00Z }
stale_after: 2027-09-30
sources:
  - id: booking-policy
    resource: policies/booking-recognition.md
    title: Booking Recognition & Movement Model
    author: human:JeanKeshishian
    last_modified: 2026-08-24
---

# Definition

The net signed booking value in USD for a fiscal window: the sum of
**every** [booking movement](/entities/booking-movement.md)'s
`"USD Fixed Amount"` — positive and negative movements alike.
[^booking-policy] Approved for MEA operational reporting.

The sanctioned computation is
[computations/net-bookings-usd-fp.md](/computations/net-bookings-usd-fp.md).
It accepts a `trade_scope` parameter: `operational` (default — all
recorded activity, Interco included as recorded) or `trade` (the
external-market view). A consolidated, elimination-adjusted total is
**not** servable — see the
[ambiguity rules](/policies/ambiguity-and-abstention.md).

**Allowed reporting dimensions.** This metric may be broken down or
ranked by `BU`, `HFM PG Name`, `Booking Type`, `KOB Line`,
`Interco & Trade`, role-specific country fields, and **masked party IDs**
(`Customer`, `Enduser`) — applying the same signed-sum formula over the
same FY/PD window, with the total attested through the sanctioned
computation. Name labels never accompany a breakdown — see the
[security policy](/policies/security-and-disclosure.md).

# Controls

- Never exclude negative movements — de-bookings are real (a net figure
  below a naive "positive-only" figure is correct, not broken).
- Never time by shipment date; the window is FY/PD on
  `Averio Booking Date`.
- Never rebuild from `Book Amt`, GAAP, or functional columns — see the
  [currency standard](/policies/currency-standard.md).
- Exact technical duplicates are the only permitted exclusion, and
  deterministic dedup awaits an immutable movement key (open item).

# What this is not

- Not revenue, shipments, or billings.
- Not "gross new bookings" — no such approved metric exists.

[^booking-policy]: Booking Recognition & Movement Model.
