---
type: Entity
title: End User
description: The customer ultimately using the products or services - a parallel transaction role to Sold-To, represented by Enduser ID; the name label is restricted.
aliases: [enduser, ultimate user]
tags: [parties]
status: stable
confidence: confirmed-internally
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified: { by: human:JeanKeshishian, at: 2026-08-24T14:00:00Z }
stale_after: 2027-09-30
---

# Definition

The customer ultimately using the products or services. Represented by the
`Enduser` ID column; the `Enduser Name` label is **restricted — blocked
output** under the [security policy](/policies/security-and-disclosure.md).

# Not the default "customer"

Sold-To and End User are **parallel transaction roles** — a distributor
Sold-To may serve many End Users, and one End User may buy through many
Sold-To parties (M:M over transactions). The End-User population is
substantially larger than the Sold-To population, so swapping the roles
does not produce "roughly the same" numbers; it produces wrong ones.

Use this role only when the question explicitly asks about ultimate
users/consumption, or after clarifying per the
[ambiguity rules](/policies/ambiguity-and-abstention.md). The ID ranges of
`Customer` and `Enduser` are disjoint; a join through the wrong column
matches nothing.
