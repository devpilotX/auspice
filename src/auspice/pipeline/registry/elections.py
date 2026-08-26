"""Election calendars, derived from a rule rather than typed as a list.

``months_to_next_election`` is a live feature. Section 3.4 makes the argument for it: the
more political this becomes, the more predictable it becomes, because electoral incentives
are public and documented.

The temptation is to paste a list of election dates into the registry. That list rots, and
a wrong date silently corrupts a feature that the model relies on. So the registry records
the *rule* instead: the term length, one year in which an election for this body is known to
have happened, and whether seats are staggered. Everything else is derived.

United States general election day is the Tuesday after the first Monday in November. That
is federal statute for federal offices and, in practice, the day almost every state and
county holds its own general election too. Where a jurisdiction genuinely deviates, the
registry records explicit dates and this module leaves them alone.
"""

from __future__ import annotations

import calendar
from datetime import date

MIN_YEAR = 1900
MAX_YEAR = 2200


def general_election_date(year: int) -> date:
    """The Tuesday after the first Monday in November of ``year``.

    Not "the first Tuesday in November". When 1 November is a Tuesday the election is on
    8 November, and getting that wrong shifts a feature by a week in exactly the years
    where it matters most.
    """
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise ValueError(f"year out of range: {year}")

    first_weekday, _ = calendar.monthrange(year, 11)
    # calendar.monthrange returns Monday=0. Days until the first Monday:
    days_to_first_monday = (calendar.MONDAY - first_weekday) % 7
    first_monday = 1 + days_to_first_monday
    return date(year, 11, first_monday + 1)


def primary_filing_deadline(election: date) -> date:
    """A conservative stand in for the candidate filing deadline.

    Filing deadlines are state law and vary widely, so the registry carries the real date
    where it is known. Where it is not, this returns 120 days before the general election,
    which is inside the range every state uses. The feature that consumes it is
    ``months_to_next_election``, which is not sensitive to a few weeks; the field exists so
    a later, better source has somewhere to land.
    """
    return date.fromordinal(election.toordinal() - 120)


def derive_elections(
    *,
    anchor_year: int,
    term_years: int,
    horizon_start: date,
    horizon_end: date,
    stagger_offset_years: int | None = None,
    explicit_dates: list[date] | None = None,
) -> list[date]:
    """Every general election date for a body between two dates, inclusive.

    ``anchor_year`` is any year in which a general election for this body is known to have
    been held. ``stagger_offset_years`` handles the common pattern where roughly half the
    seats are elected two years out of phase with the other half: pass 2 and the returned
    list includes both cycles.

    ``explicit_dates`` are merged in and always kept. They are for jurisdictions that do
    not follow the November general election, and for special elections.
    """
    if term_years <= 0:
        raise ValueError("term_years must be positive")
    if stagger_offset_years is not None and not 0 < stagger_offset_years < term_years:
        raise ValueError("stagger_offset_years must be between 1 and term_years - 1")
    if horizon_end < horizon_start:
        raise ValueError("horizon_end precedes horizon_start")

    offsets = [0] if stagger_offset_years is None else [0, stagger_offset_years]
    years: set[int] = set()

    for offset in offsets:
        base = anchor_year + offset
        # Walk backwards and forwards from the anchor in term length steps.
        first = base - term_years * ((base - horizon_start.year) // term_years + 2)
        year = first
        while year <= horizon_end.year + term_years:
            if year >= MIN_YEAR:
                years.add(year)
            year += term_years

    dates = {
        d
        for d in (general_election_date(y) for y in sorted(years))
        if horizon_start <= d <= horizon_end
    }
    if explicit_dates:
        dates.update(d for d in explicit_dates if horizon_start <= d <= horizon_end)

    return sorted(dates)


def months_to_next_election(as_of: date, elections: list[date]) -> float | None:
    """Months from ``as_of`` to the next election on or after it, or None if none is known.

    None is a real answer and is handled as a missing feature rather than a large number.
    Silently substituting "no election for 99 months" for "we do not know the calendar"
    would make a thin jurisdiction look safe.
    """
    future = [d for d in elections if d >= as_of]
    if not future:
        return None
    return (future[0].toordinal() - as_of.toordinal()) / 30.44
