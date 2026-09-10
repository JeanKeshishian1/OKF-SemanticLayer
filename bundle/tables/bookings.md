---
type: Table
title: bookings
description: Movement-grain fact table of MEA booking activity - one row per signed order-line booking movement, FY2025-FY2026 snapshot.
tags: [bookings, fact-table]
status: stable
generated: { by: okf_capstone/claude-fable-5, at: 2026-08-24T12:00:00Z }
verified: { by: process:schema-sync, at: 2026-08-24T09:00:00Z }
stale_after: 2027-09-30
---

# Grain and scope

One row = one [booking movement](/entities/booking-movement.md). The table
is a **daily-refreshed snapshot**: `REFRESH_DATE` is the load stamp
(identical on every row), and no movement postdates the snapshot date.
Scope is MEA-exclusive (`WORLD_AREA = 'MEA'` is a constant, not a
hierarchy); the source extract was row-capped, so source-system
completeness must never be claimed.

The schema deliberately contains **decoy columns** — near-duplicate dates
and alternative amount bases — because the real extract does. The
"Governed use" column below is the difference between a right answer and a
plausible wrong one; when in doubt, only *Canonical* columns feed governed
figures.

# Columns

| Column | Type | Security class | Governed use |
|---|---|---|---|
| `Averio Booking Date` | DATE | Safe metadata | **Canonical** booking date basis for all timing |
| `Oracle Booked Date` | DATE | Pending | Decoy: frozen at the line's first booking; NULL on PA rows. Not a timing basis |
| `Entered Date` | TIMESTAMP | Pending | Decoy: system entry precedes booking acceptance |
| `ACTUAL_SHIPMENT_DATE` | DATE | Pending | Operational: shipment questions only; NULL until shipped |
| `FY` | INTEGER | Safe metadata | **Canonical** fiscal year (named for ending year) |
| `PD` | INTEGER | Safe metadata | **Canonical** fiscal period (PD1 = October) |
| `REFRESH_DATE` | TIMESTAMP | Safe metadata | Dataset freshness stamp — never a booking date |
| `Source` | VARCHAR | Pending | `ORACLE` / `PA`; preserve on any key logic |
| `OU` | VARCHAR | Pending | Operating unit; not a governed reporting dimension |
| `SO` | BIGINT | Pending classification | **Canonical** Sales Order ID (header) |
| `LINE_NUMBER` | INTEGER | Pending classification | Candidate line key with OU + SO |
| `Booking Type` | VARCHAR | Safe metadata | **Canonical** movement classification |
| `BOOKED_FLAG` | VARCHAR | Safe metadata | Supporting only — never an active/cancel filter |
| `Line Status` | VARCHAR | Safe metadata | Operational current state; not movement classification |
| `Order Status` | VARCHAR | Safe metadata | Operational current state; not movement classification |
| `BU` | VARCHAR | Safe metadata | **Canonical** top of the default hierarchy |
| `HFM PG Name` | VARCHAR | Safe metadata | **Canonical** product level beneath BU |
| `Product Group` | VARCHAR | Pending | Noncanonical source code — not the governed product view |
| `Interco & Trade` | VARCHAR | Safe metadata | **Canonical** Trade/Interco classification |
| `WORLD_AREA` | VARCHAR | Safe metadata | Constant `MEA` — scope metadata |
| `KOB Line` | VARCHAR | Pending | KOB class; flipped by KOB CHANGE pairs |
| `Customer` | BIGINT | Pending classification | **Canonical** Sold-To ID (default customer role) |
| `Customer Name` | VARCHAR | **Restricted — names** | Blocked output. Never select, echo, or display |
| `Customer Country` | VARCHAR | Pending | Sold-To country (role-specific) |
| `Enduser` | BIGINT | Pending classification | **Canonical** End-User ID |
| `Enduser Name` | VARCHAR | **Restricted — names** | Blocked output. Never select, echo, or display |
| `Enduser Country` | VARCHAR | Pending | End-User country (role-specific) |
| `Ship To Country` | VARCHAR | Pending | Shipping destination country (role-specific) |
| `Ultimate Destination` | VARCHAR | Pending | Ultimate-destination country (role-specific) |
| `Qty` | DOUBLE | Pending | Movement quantity; often 0 on CHANGE |
| `Currency` | VARCHAR | Safe metadata | **Canonical** transaction currency |
| `Book Amt` | DOUBLE | Commercially sensitive | **Canonical** signed transaction amount (single-currency use only) |
| `Book Amt WithTax` | DOUBLE | Commercially sensitive | Canonical-conditional: tax-inclusive requests; NULL on PA rows |
| `Fixed Rate` | DOUBLE | Pending | NULL on PA rows — never derive USD from it |
| `USD Fixed Amount` | DOUBLE | Commercially sensitive | **Canonical** net-bookings measure (aggregate-only) |
| `USD GAAP Amount` | DOUBLE | Commercially sensitive | Noncanonical rate basis — not approved for Bookings |
| `Functional Amt` | DOUBLE | Commercially sensitive | Noncanonical — OU functional currency decoy |
| `COGS Amt` | DOUBLE | Commercially sensitive | No approved metric; NULL on PA rows; abstain |
| `GP` | DOUBLE | Commercially sensitive | ~98% NULL, no sanctioned formula; abstain |

# Rules of use

- Governed figures come only from the
  [attested computations](/computations/index.md); ad-hoc aggregation over
  this table violates the
  [booking recognition policy](/policies/booking-recognition.md).
- Security classes are enforced by the
  [security policy](/policies/security-and-disclosure.md): the two name
  columns are blocked outright; IDs join but do not display row-level;
  amount columns are aggregate-only.
- Multiple date and amount columns exist **by design**. The canonical
  choices are `Averio Booking Date` + `FY`/`PD` for time and
  `USD Fixed Amount` (or single-currency `Book Amt`) for value.
