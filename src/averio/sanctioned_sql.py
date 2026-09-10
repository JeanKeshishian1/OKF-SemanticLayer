"""Sanctioned SQL for the governed Averio MEA Bookings metrics.

This module is the harness-side **single source of truth** for the governed
computations. The same SQL text is duplicated, deliberately, in the ```sql
fences of ``bundle/computations/*.md`` - that copy is what the semantic-layer
agent resolves and what the attester compares receipts against, while this
copy is what produced the eval answer key. ``tests/test_bundle_consistency.py``
keeps the two copies token-identical (whitespace-normalized), because if they
drift an agent could pass attestation while disagreeing with ground truth,
and every eval number would become meaningless. **Edit one copy, edit the
other in the same change.**

Parameter model (bound by the executor, never by the agent):

    $fiscal_year   int   - FY named for its ending calendar year (trap F1)
    $pd_start      int   - first fiscal period of the window, inclusive
    $pd_end        int   - last fiscal period of the window, inclusive
                           (pd, pd) = one period, (1, 12) = full FY,
                           (1, n) = YTD through PDn
    $currency      text  - transaction metrics only; a single ISO code,
                           because transaction-currency amounts are never
                           summed across currencies (trap B4)
    $trade_scope   text  - net bookings only; 'operational' keeps all
                           recorded MEA activity, 'trade' filters
                           "Interco & Trade" = 'Trade' (trap T1)

The agent's only surface is semantic: (fiscal_year, fiscal_period, ytd,
currency, trade_scope). It may never author, edit, or re-indent SQL; the
executor derives the PD window and binds every parameter.

Column identifiers are quoted because they reproduce the real extract's
labels verbatim, spaces and all - the baseline agent must face the authentic
schema ambiguity ("USD Fixed Amount" vs "USD GAAP Amount" vs "Functional
Amt"), so the harness cannot quietly rename columns into something safer.
"""

# --- Shared fragments -------------------------------------------------------
#
# Every governed metric filters the same way: the movement's canonical FY/PD
# stamp (derived from "Averio Booking Date"; the generator hard-asserts the
# stamp agrees with the fiscal calendar on every row). Composing the metric
# SQL from one fragment keeps the period semantics identical across all
# seven metrics - a metric that filtered time differently would be a new
# governed decision, not a formatting choice.

_PERIOD_FILTER = """"FY" = $fiscal_year
  AND "PD" BETWEEN $pd_start AND $pd_end"""

# --- Governed metrics -------------------------------------------------------

# Net Bookings USD - THE headline metric. Signed sum: negative movements
# (CANCELs, negative CHANGEs, the minus leg of KOB pairs) are legitimate
# de-bookings and MUST stay in (trap B1). The trade_scope guard implements
# trap T1: 'operational' means all recorded MEA activity (Interco included,
# as recorded - no elimination), 'trade' is the external-market view.
NET_BOOKINGS_SQL = f"""SELECT SUM("USD Fixed Amount") AS value
FROM bookings
WHERE {_PERIOD_FILTER}
  AND ($trade_scope = 'operational' OR "Interco & Trade" = 'Trade')"""

# Positive Booking Movements USD - analytical diagnostic ONLY. Positive
# movements include positive CHANGE corrections and the +leg of KOB
# reclassification pairs, so this is NOT "Gross New Bookings" (trap B3);
# no approved gross-new metric exists (open item: Booking Type dictionary).
POSITIVE_MOVEMENTS_SQL = f"""SELECT SUM("USD Fixed Amount") AS value
FROM bookings
WHERE {_PERIOD_FILTER}
  AND "USD Fixed Amount" > 0"""

# De-bookings USD - negative movements, returned SIGNED (a negative number).
# Absolute display is a presentation choice callers must make explicitly.
DEBOOKINGS_SQL = f"""SELECT SUM("USD Fixed Amount") AS value
FROM bookings
WHERE {_PERIOD_FILTER}
  AND "USD Fixed Amount" < 0"""

# Cancellation De-bookings USD - the CANCEL subset of de-bookings, selected
# by Booking Type and never by BOOKED_FLAG: cancelled movements still carry
# BOOKED_FLAG = 'Y', which is exactly why the flag is banned as a filter
# (trap B1's flag variant).
CANCEL_DEBOOKINGS_SQL = f"""SELECT SUM("USD Fixed Amount") AS value
FROM bookings
WHERE {_PERIOD_FILTER}
  AND "Booking Type" = 'CANCEL'"""

# Transaction Booking Amount - signed sum in ONE transaction currency.
# The $currency parameter is required precisely so the metric cannot be
# asked to sum dirhams with dollars (trap B4).
TRANSACTION_BOOKINGS_SQL = f"""SELECT SUM("Book Amt") AS value
FROM bookings
WHERE {_PERIOD_FILTER}
  AND "Currency" = $currency"""

# Transaction Booking Amount With Tax - tax-inclusive twin of the above.
# Never mixed with "Book Amt" or any USD measure in one figure. NULL on
# PA-source rows by design (matches the real extract), so this metric is
# implicitly Oracle-source only - documented in the bundle caveat.
TRANSACTION_BOOKINGS_TAX_SQL = f"""SELECT SUM("Book Amt WithTax") AS value
FROM bookings
WHERE {_PERIOD_FILTER}
  AND "Currency" = $currency"""

# Distinct Sales Orders - order-header distinctness. SO identifies the
# Sales Order, not the movement row, so COUNT(DISTINCT) is the only sane
# aggregation; global SO uniqueness across Source/OU is not technically
# proven (open item), which the bundle records as a caveat.
SALES_ORDER_COUNT_SQL = f"""SELECT COUNT(DISTINCT "SO") AS value
FROM bookings
WHERE {_PERIOD_FILTER}"""

# Metric key -> sanctioned SQL. These keys are the vocabulary shared by the
# generator (ground truth), the drift test's FENCE_TO_METRIC map, and the
# resolver. Adding a metric here without adding its bundle computation (and
# the FENCE_TO_METRIC entry) will fail tests - by design.
SANCTIONED = {
    "net_bookings_usd": NET_BOOKINGS_SQL,
    "positive_booking_movements_usd": POSITIVE_MOVEMENTS_SQL,
    "debookings_usd": DEBOOKINGS_SQL,
    "cancel_debookings_usd": CANCEL_DEBOOKINGS_SQL,
    "transaction_bookings": TRANSACTION_BOOKINGS_SQL,
    "transaction_bookings_tax": TRANSACTION_BOOKINGS_TAX_SQL,
    "sales_order_count": SALES_ORDER_COUNT_SQL,
}

# --- Naive variants (harness-side ONLY - never shipped in the bundle) -------
#
# Each variant implements the "one rule off" counterfactual for one numeric
# trap: it is the query a competent-but-ungoverned analyst would write after
# misreading exactly one governed rule. Two rules apply when touching these:
#
#   1. Each variant drops EXACTLY ONE governed rule. Dropping two makes the
#      measured delta unattributable - and two errors can cancel.
#   2. Variants stay harness-side. Shipping them in the bundle would hand
#      the baseline agent the very knowledge whose absence is being measured.
#
# ``separation_report()`` in generate_data.py evaluates each variant against
# its reference and hard-asserts a >= 1% relative delta; if a data change
# drops a trap below that, the eval can no longer distinguish the agents and
# the generator fails loudly. Fix the data, don't lower the bar.
#
# Extra parameters some variants bind (derived harness-side from the same
# FY/PD window): $period_start/$period_end (calendar dates of the governed
# window, for the shipment-date misread) and $cal_start/$cal_end (Jan 1
# bounds of the calendar-year misread of an FY label).

NAIVE_VARIANTS = {
    # B1: "bookings can't be negative" - filters out de-bookings, overstating
    # net. Numerically identical to serving Positive Movements as Net.
    "no_B1_signed": {
        "trap": "B1",
        "reference": "net_bookings_usd",
        "description": "Drops negative movements from Net Bookings",
        "sql": f"""SELECT SUM("USD Fixed Amount") AS value
FROM bookings
WHERE {_PERIOD_FILTER}
  AND "USD Fixed Amount" > 0""",
    },
    # B2: times bookings by shipment date instead of Averio Booking Date.
    # Unshipped lines (NULL shipment date) silently vanish and shipped lines
    # migrate into the period they shipped in, not the period they booked in.
    "no_B2_datebasis": {
        "trap": "B2",
        "reference": "net_bookings_usd",
        "description": "Times bookings by ACTUAL_SHIPMENT_DATE",
        "sql": """SELECT SUM("USD Fixed Amount") AS value
FROM bookings
WHERE "ACTUAL_SHIPMENT_DATE" >= $period_start
  AND "ACTUAL_SHIPMENT_DATE" < $period_end""",
    },
    # B3: labels all positive movements "Gross New Bookings". The reference
    # here is a strict new-movement-only sum (NEW plus the PA equivalents),
    # which is NOT a sanctioned metric - it exists only to measure how much
    # positive CHANGE/KOB contamination the mislabel hides.
    "no_B3_grossnew": {
        "trap": "B3",
        "reference_sql": f"""SELECT SUM("USD Fixed Amount") AS value
FROM bookings
WHERE {_PERIOD_FILTER}
  AND "USD Fixed Amount" > 0
  AND "Booking Type" IN ('NEW', 'ORIGINAL', 'ADDITIONAL')""",
        "description": "Labels all positive movements as Gross New Bookings",
        "sql": f"""SELECT SUM("USD Fixed Amount") AS value
FROM bookings
WHERE {_PERIOD_FILTER}
  AND "USD Fixed Amount" > 0""",
    },
    # B4: sums transaction-currency amounts as if they were one currency.
    # AED/SAR/QAR are ~3.7 units per USD, so the cross-currency sum is not
    # subtly wrong, it is wildly wrong - which is the point.
    "no_B4_currency": {
        "trap": "B4",
        "reference": "net_bookings_usd",
        "description": "Sums Book Amt across currencies without conversion",
        "sql": f"""SELECT SUM("Book Amt") AS value
FROM bookings
WHERE {_PERIOD_FILTER}""",
    },
    # B5: picks the wrong USD basis. USD GAAP Amount is converted at daily
    # GAAP rates, not the FY-pinned fixed rate, so it drifts a few percent -
    # close enough to look right, wrong enough to matter.
    "no_B5_usdbasis": {
        "trap": "B5",
        "reference": "net_bookings_usd",
        "description": "Uses USD GAAP Amount instead of USD Fixed Amount",
        "sql": f"""SELECT SUM("USD GAAP Amount") AS value
FROM bookings
WHERE {_PERIOD_FILTER}""",
    },
    # F1: reads "FY2026" as calendar 2026. The governed FY2026 window opened
    # 2025-10-01; the calendar misread drops Oct-Dec 2025 entirely (and would
    # include Oct-Dec 2026, which postdates the snapshot).
    "no_F1_fiscal": {
        "trap": "F1",
        "reference": "net_bookings_usd",
        "description": "Reads the FY label as a calendar year",
        "sql": """SELECT SUM("USD Fixed Amount") AS value
FROM bookings
WHERE "Averio Booking Date" >= $cal_start
  AND "Averio Booking Date" < $cal_end""",
    },
    # M1: counts End Users when asked about customers. Sold-To and End User
    # are parallel transaction roles with disjoint ID ranges; the End-User
    # population is deliberately much larger, so the miscount is material.
    # (Distinct-party counts are not sanctioned metrics; both sides are
    # harness-side probes of the same dimension misread.)
    "no_M1_custrole": {
        "trap": "M1",
        "reference_sql": f"""SELECT COUNT(DISTINCT "Customer") AS value
FROM bookings
WHERE {_PERIOD_FILTER}""",
        "description": "Counts End Users as customers",
        "sql": f"""SELECT COUNT(DISTINCT "Enduser") AS value
FROM bookings
WHERE {_PERIOD_FILTER}""",
    },
    # T1: serves an "external market" figure without filtering out Interco.
    # The reference is the sanctioned net-bookings SQL bound with
    # trade_scope='trade'; the naive side simply forgets the scope exists.
    "no_T1_tradescope": {
        "trap": "T1",
        "reference_sql": f"""SELECT SUM("USD Fixed Amount") AS value
FROM bookings
WHERE {_PERIOD_FILTER}
  AND "Interco & Trade" = 'Trade'""",
        "description": "Includes Interco in an external-market view",
        "sql": f"""SELECT SUM("USD Fixed Amount") AS value
FROM bookings
WHERE {_PERIOD_FILTER}""",
    },
}
