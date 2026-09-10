---
type: Entity
title: Sales Order
description: System order created from an accepted customer PO. SO means Sales Order; it identifies the order header, never the fact row.
aliases: [SO, order]
tags: [orders]
status: stable
confidence: confirmed-internally
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified: { by: human:JeanKeshishian, at: 2026-08-24T14:00:00Z }
stale_after: 2027-09-30
---

# Definition

A Sales Order is the system order created from an accepted customer
Purchase Order. `SO` identifies the order **header**; each order has one
or more operational lines (`OU + SO + LINE_NUMBER` is the candidate line
key), and the [bookings table](/tables/bookings.md) records signed
[booking movements](/entities/booking-movement.md) against those lines —
so one SO usually spans many rows.

# Relationships

- Sales Order 1:M Sales Order Line 1:M Booking Movement.
- Sales Order M:1 [Sold-To Customer](/entities/sold-to-customer.md),
  M:1 [End User](/entities/end-user.md), M:1 Bill-To site, M:1 Ship-To
  site (the site roles are represented in this dataset only as
  role-specific country columns).

# Counting

Order counts are `COUNT(DISTINCT "SO")` — see
[distinct sales orders](/metrics/distinct-sales-orders.md). Row counts are
movement counts, not order counts. Global SO uniqueness across
`Source`/`OU` is not technically proven (open item), so order counts may
require Source/OU scoping where collision risk matters.

# What this is not

- Not the booking fact: summing "one row per SO" undercounts CHANGE,
  CANCEL, and KOB movements.
- `Entered Date` on the order is system entry, which precedes formal
  booking acceptance — it is not the booking date.
