---
type: Policy
title: Security & Disclosure
description: Mandatory output restrictions - no person or organization names, row-level blocks, aggregate-only financial detail - applied before query generation and again before response generation.
tags: [security, policy]
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

# Mandatory restriction

**No person or organization names may appear in AI responses, examples,
prompt echoes, logs, or row-level outputs.** [^handoff-v2] Where a party
must be identified, use its ID (`Customer`, `Enduser`) or an authorized
masked label. Apply these restrictions twice: before query generation
(never select a restricted column) and again before response generation
(never echo a restricted value that leaked into context).

This rule has no exceptions for seniority, urgency, or "just one name".
A question that can only be answered with a name ("who is our top
customer?") is answered with the ID and the offer to route a name request
through governance.

# Security classes

| Class | Scope | Enforcement | Example columns |
|---|---|---|---|
| Restricted — names | Any field/value containing a person or organization name | Block generation, examples, prompt replay, row-level display; use ID/masked label where authorized | `Customer Name`, `Enduser Name` |
| Restricted by conservative policy | Addresses, addressees, project names, user IDs, detailed location text | Block row-level output; aggregate only | address fields, created-by/booked-by fields |
| Pending classification | Customer/End-User IDs, SO/PO/reference numbers, item/model strings | No row-level exposure until governance approval; MAY be used internally for joins and deduplication | `Customer`, `Enduser`, `SO` |
| Commercially sensitive | Amounts, price, cost, COGS, GP, discount, penalties | Approved aggregates only; no row-level detail | `COGS Amt`, `GP`, all amount columns |
| Safe metadata | Field names, definitions, formulas, non-row-level structures | May be supplied to AI freely | this bundle |

Column-level assignments live in the
[bookings table concept](/tables/bookings.md).

# Interaction with metrics

Aggregates produced by the sanctioned computations are approved
disclosures. Grouping an approved aggregate by a *pending-classification*
identifier (e.g. bookings by `Customer` ID) is permitted for internal
analytical use; attaching a restricted name label to it is not.

[^handoff-v2]: Governed AI Handoff Specification v2, §11 (Security and AI
    access).
