---
type: Metric
title: Distinct Sales Orders
description: COUNT(DISTINCT SO) over the fiscal window - order-header distinctness, not row counts.
aliases: [order count, number of orders, SO count]
tags: [orders]
status: stable
confidence: strongly-supported
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified: { by: process:extract-profiler, at: 2026-08-24T09:00:00Z }
stale_after: 2027-09-30
sources:
  - id: booking-policy
    resource: policies/booking-recognition.md
    title: Booking Recognition & Movement Model
    author: human:JeanKeshishian
    last_modified: 2026-08-24
---

# Definition

The number of distinct [sales orders](/entities/sales-order.md) with any
booking movement in the fiscal window: `COUNT(DISTINCT "SO")`.
[^booking-policy]

This metric is **strongly supported** (machine-verified pattern): global
SO uniqueness across `Source`/`OU` is not technically proven, so where
collision risk matters the count may require Source/OU scoping — answers
should carry that caveat.

The sanctioned computation is
[computations/distinct-sales-orders-fp.md](/computations/distinct-sales-orders-fp.md).

# What this is not

- Not a movement count (row count) and not a line count
  (`OU + SO + LINE_NUMBER` distinctness) — three different questions.
- Not "active orders": an order counts here if it had movement activity in
  the window, regardless of its current status.

[^booking-policy]: Booking Recognition & Movement Model.
