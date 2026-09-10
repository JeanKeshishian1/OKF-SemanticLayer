"""Averio fiscal calendar - trap F1 made executable.

Averio's fiscal year runs **October 1 through September 30** and is named
for the calendar year in which it *ends*: FY2026 = 2025-10-01 .. 2026-09-30.
Fiscal periods are calendar months renumbered so that **PD1 = October** and
PD12 = September. Both facts are exactly what a naive agent gets wrong
(reading "FY2026" as calendar 2026, or assuming PD1 = January), which is why
this module exists as a single, testable implementation instead of ad-hoc
date arithmetic scattered through the harness.

Every range in this module is half-open ``[start, end)``. Half-open ranges
compose without off-by-one-day bugs (end of one period == start of the next)
and match how the sanctioned SQL binds its period filters.

Deliberate non-sharing: the attester in
``bundle/references/attesters/sql_equality.py`` re-implements this calendar
independently and MUST NOT import this module. If executor and attester
shared date code, a single bug would corrupt the parameter binding and the
check of that binding identically, and attestation would pass vacuously.
``tests/test_bundle_consistency.py`` cross-checks the two implementations
over FY2023-FY2030 instead.
"""

from __future__ import annotations

from datetime import date, timedelta

# PD1 is October: month index 9 when counting Jan=0. Kept as a named
# constant because this single number *is* the fiscal calendar - change it
# and every FY/PD label in the dataset and every ground-truth figure moves.
_FY_START_MONTH_INDEX = 9  # October, 0-based from January


def fiscal_year_bounds(fy: int) -> tuple[date, date]:
    """Half-open calendar bounds of fiscal year ``fy``.

    FY is named for its *ending* year, so FY2026 starts 2025-10-01 and the
    half-open end is 2026-10-01 (i.e. the last covered day is 2026-09-30).
    """
    return date(fy - 1, 10, 1), date(fy, 10, 1)


def fiscal_period_bounds(fy: int, pd: int) -> tuple[date, date]:
    """Half-open calendar bounds of one fiscal period (month) ``pd`` of ``fy``.

    PD p is the calendar month that starts ``p - 1`` months after October of
    the fiscal year's starting calendar year (fy - 1). The arithmetic is done
    in 0-based months-since-January-of-(fy-1) so that the wrap from December
    (index 11) into January (index 12 -> next calendar year) falls out of a
    divmod instead of a special case.
    """
    if not 1 <= pd <= 12:
        raise ValueError(f"fiscal period must be 1..12, got {pd}")
    start_index = _FY_START_MONTH_INDEX + (pd - 1)  # months since Jan of fy-1
    start_year = fy - 1 + start_index // 12
    start_month = start_index % 12 + 1
    end_index = start_index + 1  # periods are exactly one month long
    end_year = fy - 1 + end_index // 12
    end_month = end_index % 12 + 1
    return date(start_year, start_month, 1), date(end_year, end_month, 1)


def period_range_bounds(fy: int, pd_start: int, pd_end: int) -> tuple[date, date]:
    """Half-open bounds of an inclusive PD range within one fiscal year.

    This is the shape the executor binds: (pd, pd) for a single period,
    (1, 12) for the full FY, (1, n) for YTD-through-PDn. A range spanning
    fiscal years is not a governed reporting window, so it is rejected here
    rather than silently producing a plausible-looking date span.
    """
    if pd_start > pd_end:
        raise ValueError(f"pd_start {pd_start} > pd_end {pd_end}")
    start, _ = fiscal_period_bounds(fy, pd_start)
    _, end = fiscal_period_bounds(fy, pd_end)
    return start, end


def fiscal_of(d: date) -> tuple[int, int]:
    """Map a calendar date to its (fiscal_year, fiscal_period).

    October-December belong to the *next* calendar year's FY (they open it);
    January-September belong to the FY that shares their calendar year.
    """
    if d.month >= 10:  # Oct/Nov/Dec -> PD1/2/3 of the FY ending next year
        return d.year + 1, d.month - 9
    return d.year, d.month + 3  # Jan..Sep -> PD4..PD12 of the FY ending this year


def last_closed_period(as_of: date) -> tuple[int, int]:
    """Most recent fiscal period fully completed before ``as_of``.

    "Closed" means every day of the period is strictly before ``as_of``, so
    on the 1st of a month the previous month has just closed, and mid-month
    the current period is still open. This is the period the eval treats as
    the freshest servable one - figures for the open period would silently
    change as more movements land.
    """
    last_day_of_prev_month = date(as_of.year, as_of.month, 1) - timedelta(days=1)
    return fiscal_of(last_day_of_prev_month)


def last_closed_year(as_of: date) -> int:
    """Most recent fiscal year fully completed before ``as_of``."""
    fy, _ = fiscal_of(as_of)
    # The FY containing as_of is by definition still open (as_of is inside
    # it), so the last closed one is simply the previous FY - unless as_of
    # is exactly an FY start (Oct 1), in which case fiscal_of already rolled
    # us into the new year and the previous FY closed yesterday. Both cases
    # reduce to "the FY before the one containing as_of".
    return fy - 1
