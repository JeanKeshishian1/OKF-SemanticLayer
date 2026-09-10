---
type: Metric
title: Positive Booking Movements USD
description: Sum of positive signed movements. An analytical diagnostic - explicitly NOT Gross New Bookings.
aliases: [positive movements, positive bookings]
tags: [bookings, diagnostic]
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

The sum of movements with `"USD Fixed Amount" > 0` in the fiscal window —
an **analytical diagnostic** for movement analysis. [^booking-policy]

The sanctioned computation is
[computations/positive-booking-movements-usd-fp.md](/computations/positive-booking-movements-usd-fp.md).

# The mandatory caveat

**Do not label this metric "Gross New Bookings".** Positive movements
include positive CHANGE corrections and the positive leg of KOB
reclassification pairs — neither is new demand. No approved gross/new
metric exists (the Booking Type dictionary is an open governance item);
a question about "gross new bookings" is answered by *offering* this
diagnostic with this caveat, never by renaming it.

# What this is not

- Not new-order demand, not growth, not a headline figure.
- Not [Net Bookings](/metrics/net-bookings-usd.md) — it ignores
  de-bookings entirely.

[^booking-policy]: Booking Recognition & Movement Model.
