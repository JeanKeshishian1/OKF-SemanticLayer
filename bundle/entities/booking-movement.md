---
type: Entity
title: Booking Movement
description: One signed order-line movement - the grain of the bookings fact table and of every governed bookings metric.
aliases: [booking transaction, booking delta, movement]
tags: [bookings]
status: stable
confidence: strongly-supported
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified: { by: process:extract-profiler, at: 2026-08-24T09:00:00Z }
stale_after: 2027-09-30
---

# Definition

A signed order-line movement representing new booking, de-booking, change,
KOB reclassification, or source-specific booking activity. One row of the
[bookings table](/tables/bookings.md) is one movement; every governed
bookings metric aggregates at this grain.

This is a **dataset-supported** operational model (machine-verified
pattern, not formal policy): the extract demonstrably records bookings
this way, and the
[booking recognition policy](/policies/booking-recognition.md) governs how
the movements may be classified and summed.

# Identity

The candidate movement key is `Source + OU + SO + LINE_NUMBER +
Averio Booking Date + Booking Type`. It is *candidate* because an
immutable source record ID is an open governance item; until one exists,
deterministic row-level deduplication is not approved and exact technical
duplicates are the only permitted exclusion.

# What this is not

- Not an order: see [sales order](/entities/sales-order.md).
- Not a current-state snapshot: `Line Status` on a movement row describes
  the line's state *today*, not the movement's nature — a cancelled line's
  original NEW movement still happened.
