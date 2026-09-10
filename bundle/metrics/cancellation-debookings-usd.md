---
type: Metric
title: Cancellation De-bookings USD
description: The CANCEL subset of de-bookings, classified by Booking Type - never by BOOKED_FLAG. Signed negative.
aliases: [cancellations, cancel debookings]
tags: [bookings]
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

The sum of movements with `"Booking Type" = 'CANCEL'` in the fiscal
window — the cancellation subset of
[de-bookings](/metrics/debookings-usd.md), retained signed (negative).
[^booking-policy]

This metric is **strongly supported** (machine-verified extract pattern,
not formal policy): treat it as an operational implementation rule and
label it accordingly in answers.

The sanctioned computation is
[computations/cancellation-debookings-usd-fp.md](/computations/cancellation-debookings-usd-fp.md)
— **check that computation's freshness state before serving**; its
`stale_after` is tied to the open Booking Type dictionary review.

# Controls

- Classification is by `Booking Type`, never `BOOKED_FLAG` — cancelled
  movements still carry `BOOKED_FLAG = 'Y'`.
- Nonstandard cancellation variants (PA-source and KOB-related types) are
  not yet mapped; this figure covers the standard `CANCEL` type only, and
  answers must say so.

[^booking-policy]: Booking Recognition & Movement Model.
