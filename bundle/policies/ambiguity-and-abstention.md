---
type: Policy
title: Ambiguity & Abstention Rules
description: The default / clarify / abstain table for ambiguous user terms, and the list of questions that must not be answered at all.
tags: [ambiguity, abstention, policy]
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

# How to read this table

For each ambiguous user term: apply the **default** silently when nothing
in the question contradicts it; **clarify** when the stated trigger
appears; **abstain** — with the reason — when the abstain condition holds.
Abstention is a correct answer, not a failure. [^handoff-v2]

| Term | Default | Clarify when | Abstain when |
|---|---|---|---|
| "bookings" | [Net Bookings USD](/metrics/net-bookings-usd.md) — signed sum | User asks gross/new-only (no approved gross-new metric exists) | Consolidated Interco elimination would be required |
| "customer" | [Sold-To Customer](/entities/sold-to-customer.md) ID | Context suggests the ultimate user → [End User](/entities/end-user.md) | Never disclose name labels |
| "country" / "bookings in X" | **No default country role** | Always — Sold-To, Ship-To, End-User, and Ultimate Destination countries differ | User will not specify a role |
| "business" | `BU` | User requests OU/Sub-BU/segment views | Cross-hierarchy equivalence claims |
| "product" / "product group" | `HFM PG Name` beneath `BU` | User wants item, marketing, IMO, or LCS views | Claiming authority for any alternative hierarchy |
| "amount" | `USD Fixed Amount` | Tax-inclusive or transaction-currency needs | GAAP/functional definitions (no approved rule) |
| "period" | FY/PD on `Averio Booking Date` | Shipment/fulfillment timing is meant | Date basis unclear **and** materially changes the answer |
| "active order" | Current `Order Status`/`Line Status` — never inferred from Booking value | Desired status definition is vague | Hold logic is required but unmapped |
| "Interco total" | Operational view may include Interco as recorded | Operational vs Trade-only vs consolidated | Consolidated total — no elimination rule exists |

# Trade and Interco scope

Interco and Trade activity use the same operational signed booking logic.
Three views exist, and only two are servable:

1. **Operational** (default): all recorded MEA activity, Interco included
   as recorded — no elimination applied or implied.
2. **External market**: filter `"Interco & Trade" = 'Trade'`.
3. **Consolidated Averio total**: requires an approved elimination rule
   that has not been supplied — **abstain**, citing the open item.

# Must-abstain list (missing knowledge)

No governed definition exists for: Gross New Bookings, GP / gross-profit
percent, COGS-based margin, AUP, on-time delivery, lead time, quoted
lead-time analysis, consolidated totals, marketing/IMO/LCS hierarchies,
Sub-BU reporting. Columns that *look* usable for these (`GP`, `COGS Amt`)
are unapproved and mostly unpopulated. Do not infer a formula — state that
the concept is not governed, cite the open approval item, and stop.

[^handoff-v2]: Governed AI Handoff Specification v2, §12 (Ambiguity and
    abstention rules) and §16 (Remaining approval backlog).
