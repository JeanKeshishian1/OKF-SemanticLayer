---
type: Policy
title: Fiscal Calendar
description: Averio fiscal year (Oct 1 - Sep 30, named for the ending year) and fiscal periods (PD1 = October), the only sanctioned reporting calendar.
tags: [calendar, policy]
status: stable
confidence: confirmed-plus-dataset-supported
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

# Fiscal year

The fiscal year runs **October 1 through September 30** and is named for
the calendar year in which it **ends**: FY2025 = 2024-10-01 through
2025-09-30; FY2026 = 2025-10-01 through 2026-09-30. [^handoff-v2] A
question that says "FY2026" or "fiscal 2026" means this window — never
calendar 2026.

# Fiscal periods

Monthly periods, renumbered from October:

| PD | Month | PD | Month |
|---|---|---|---|
| 1 | October | 7 | April |
| 2 | November | 8 | May |
| 3 | December | 9 | June |
| 4 | January | 10 | July |
| 5 | February | 11 | August |
| 6 | March | 12 | September |

# Resolution rules

- Booking timing uses `Averio Booking Date`; the `FY` and `PD` columns
  are the authoritative reporting fields derived from it.
- **YTD** means PD1 through the selected fiscal period.
- Relative expressions ("last period", "this year") resolve against this
  calendar, never the calendar year. "Last period" on a date means the
  most recent PD fully completed before that date.
- Figures for a period that has not fully closed are provisional and must
  be labeled as such.
- Shipment and fulfillment dates never substitute for Booking timing —
  see the [booking recognition policy](/policies/booking-recognition.md).

[^handoff-v2]: Governed AI Handoff Specification v2, §6 (Fiscal calendar).
