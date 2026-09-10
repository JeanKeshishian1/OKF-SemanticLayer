---
okf_version: "0.2"
title: Averio MEA Bookings Semantic Layer
description: Governed, agent-facing semantic layer for MEA operational Bookings, serialized from the v2 Governed Spec and AI Handoff.
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
---

# Averio MEA Bookings Semantic Layer

This bundle is the governed knowledge an agent must consult before touching
the MEA bookings data. It serializes the v2 governance artifacts (the AI
Handoff contract and the Governed Spec workbook) into Open Knowledge Format:
concepts an agent can resolve, policies it must obey, and attested
computations it may execute — with parameter binding only, never authored
SQL.

**Handoff contract (primary rule).** Use explicit internal business
guidance first, then documented guide definitions, then dataset-pattern
evidence. Never elevate a record pattern into corporate policy without
labeling it dataset-supported. If a required rule is unresolved, ask a
targeted clarification or abstain — do not substitute generic Oracle,
finance, or sales knowledge.

**Canonical defaults.**

- Net measure: signed `SUM("USD Fixed Amount")` — [net bookings](/metrics/net-bookings-usd.md)
- Date basis: `Averio Booking Date`, reported by FY/PD — [fiscal calendar](/policies/fiscal-calendar.md)
- Hierarchy: `BU` → `HFM PG Name` only
- Customer role: Sold-To [customer](/entities/sold-to-customer.md) **ID** — names are restricted
- Scope: MEA-exclusive FY2025–FY2026 snapshot; `WORLD_AREA` is scope metadata, not a hierarchy

**Mandatory restriction.** No person or organization names may appear in
any output, example, prompt echo, log, or row-level display. See the
[security policy](/policies/security-and-disclosure.md) before generating
any query or answer.

## Map

- `policies/` — the rules: [booking recognition](/policies/booking-recognition.md),
  [currency standard](/policies/currency-standard.md),
  [fiscal calendar](/policies/fiscal-calendar.md),
  [security & disclosure](/policies/security-and-disclosure.md),
  [ambiguity & abstention](/policies/ambiguity-and-abstention.md)
- `entities/` — [sales order](/entities/sales-order.md),
  [booking movement](/entities/booking-movement.md),
  [sold-to customer](/entities/sold-to-customer.md),
  [end user](/entities/end-user.md)
- `metrics/` — the seven governed metrics, each backed by an attested
  computation in `computations/`
- `tables/` — [bookings](/tables/bookings.md), the one governed fact table
- `references/` — the [executor contract](/references/executors/run-duckdb.md)
  and the deterministic attester

## Trust model

The handoff's five-level confidence model maps onto OKF trust frontmatter;
the resolver must carry the level into every answer's provenance:

| Confidence | Frontmatter signature |
|---|---|
| Confirmed internally | `verified` by `human:JeanKeshishian` |
| Confirmed + dataset-supported | `verified` by `human:JeanKeshishian` **and** `process:extract-profiler` |
| Strongly supported | `verified` by `process:extract-profiler` only (machine tier) |
| Context-dependent | `status: draft` + clarification rule in the body |
| Not defined | concept absent from this bundle → abstain |

Deliberately absent (open approval backlog — abstain, do not infer): Gross
New Bookings, GP/COGS/margin metrics, AUP, on-time delivery, lead time,
consolidated (elimination-adjusted) Averio totals, marketing/IMO/LCS
product hierarchies, Sub-BU reporting.
