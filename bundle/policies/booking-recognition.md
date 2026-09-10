---
type: Policy
title: Booking Recognition & Movement Model
description: Defines what a Booking is, how the extract records it as signed order-line movements, and which fields may classify movement activity.
tags: [bookings, policy]
status: stable
confidence: confirmed-internally
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified:
  - { by: human:JeanKeshishian, at: 2026-08-24T14:00:00Z }
  - { by: process:extract-profiler, at: 2026-08-24T09:00:00Z }
stale_after: 2027-09-30
sources:
  - id: handoff-v2
    resource: repo:docs/Averio_Semantic_Layer_AI_Handoff_v2.docx
    title: Governed AI Handoff Specification v2
    author: human:JeanKeshishian
    last_modified: 2026-08-24
---

# What a Booking is

A Booking occurs when Averio receives a customer Purchase Order, formally
accepts it, and enters the accepted order into the system, recognizing the
accepted order value. [^handoff-v2] The dataset operationalizes Bookings as
**signed order-line movements** — one row per
[booking movement](/entities/booking-movement.md), not one immutable record
per [sales order](/entities/sales-order.md).

# Movement rules

1. **Movements are signed, and the sign stays.** Negative movements
   (de-bookings, negative changes, the minus leg of a KOB
   reclassification) are legitimate booking activity. Filtering them out
   overstates every net figure. Net figures come from the signed sum —
   never from "positive rows only".
2. **Movement classification uses `Booking Type` plus the signed amount —
   nothing else.**
   - `BOOKED_FLAG` marks a *booked movement*; CANCEL movements still carry
     `BOOKED_FLAG = 'Y'`. It is never an active/cancel filter.
   - `Line Status` / `Order Status` describe *current* operational
     lifecycle state, stamped onto all of a line's movements — a cancelled
     line's original NEW row also shows `CANCELLED`. They must not replace
     Booking Type or sign for movement classification, and a fulfillment
     hold does not erase a historical Booking movement.
3. **Movement types** (dataset-supported pattern):

   | Type | Class | Rule |
   |---|---|---|
   | `NEW` | Positive booking/addition | Signed amount; classify separately only when requested |
   | `CANCEL` | De-booking | Signed negative; never filtered by `BOOKED_FLAG` |
   | `CHANGE` | Signed adjustment | May be + or −, often `Qty = 0`; include in net; do not describe the *reason* without an approved code mapping |
   | `KOB CHANGE - OLD` / `- NEW` | KOB reclassification pair | Value is redistributed and nets to zero; never count the positive leg alone as growth |
   | `ORIGINAL` / `ADDITIONAL` | PA-source movements | Keep source-specific; included in net (already signed USD); do not relabel without an owner rule |

4. **Date basis.** Booking timing is the movement's
   `Averio Booking Date`, reported through the
   [fiscal calendar](/policies/fiscal-calendar.md). `ACTUAL_SHIPMENT_DATE`
   serves shipment questions only — unshipped lines have no shipment date
   at all, and shipment-date changes never alter the fixed Booking date.
5. **Sanctioned computations only.** Booking figures MUST come from the
   attested computations in `computations/` — starting with
   [net bookings](/computations/net-bookings-usd-fp.md). Composing ad-hoc
   aggregations over [bookings](/tables/bookings.md) is a policy violation
   even when the result happens to agree.

# Counting and grain

- One row = one movement. Value questions sum signed amounts at movement
  grain; never collapse to one row per order or line before summing.
- Order counts use `COUNT(DISTINCT "SO")` — see
  [distinct sales orders](/metrics/distinct-sales-orders.md).
- The candidate movement key is `Source + OU + SO + LINE_NUMBER +
  Averio Booking Date + Booking Type`; an immutable source record ID is
  an open governance item, so deterministic row-level deduplication is not
  yet approved.

[^handoff-v2]: Governed AI Handoff Specification v2, §4 (Booking event and
    movement model).
