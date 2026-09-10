---
type: Metric
title: De-bookings USD
description: Sum of negative signed movements in the fiscal window. Returns a negative value by design.
aliases: [debookings, de-bookings, negative movements]
tags: [bookings]
status: stable
confidence: confirmed-internally
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified: { by: human:JeanKeshishian, at: 2026-08-24T14:00:00Z }
stale_after: 2027-09-30
sources:
  - id: booking-policy
    resource: policies/booking-recognition.md
    title: Booking Recognition & Movement Model
    author: human:JeanKeshishian
    last_modified: 2026-08-24
---

# Definition

The sum of movements with `"USD Fixed Amount" < 0` — cancellations,
negative changes, and the negative legs of KOB pairs. Approved as an
analytical movement metric. [^booking-policy]

The sanctioned computation is
[computations/debookings-usd-fp.md](/computations/debookings-usd-fp.md).

# Controls

- **The value is negative.** Displaying it as a positive magnitude is an
  explicit presentation transformation the answer must declare.
- Includes negative CHANGE adjustments, not only cancellations — for the
  CANCEL-only view use
  [cancellation de-bookings](/metrics/cancellation-debookings-usd.md).
- KOB negative legs appear here with their positive twins in
  [positive movements](/metrics/positive-booking-movements-usd.md);
  interpreting either side alone as demand change is wrong.

[^booking-policy]: Booking Recognition & Movement Model.
