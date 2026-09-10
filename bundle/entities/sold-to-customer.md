---
type: Entity
title: Sold-To Customer
description: The company issuing the customer PO - the default "customer" role, represented by Customer ID; the name label is restricted.
aliases: [customer, sold-to]
tags: [parties]
status: stable
confidence: confirmed-internally
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified: { by: human:JeanKeshishian, at: 2026-08-24T14:00:00Z }
stale_after: 2027-09-30
---

# Definition

The company issuing the customer Purchase Order. Represented in the data
by the `Customer` ID column; the `Customer Name` label is
**restricted — blocked output** under the
[security policy](/policies/security-and-disclosure.md).

"By customer" questions default to this role per the
[ambiguity rules](/policies/ambiguity-and-abstention.md); clarify when the
question plausibly means the ultimate user
([End User](/entities/end-user.md)).

# Relationships

- Sold-To Customer 1:M [sales orders](/entities/sales-order.md).
- Sold-To Customer M:M [End User](/entities/end-user.md) **over
  transactions** — parallel roles on each movement, implemented through
  the fact table, never as a fixed parent-child hierarchy.

# Rules

- Use the ID for joins, grouping, and display; never the name.
- `Customer Country` is this role's country — one of four role-specific
  country columns, which is why "bookings in X" always needs a role
  clarification.
