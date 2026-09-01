"""Missed-period detection for a single source.

This module is the ONE place in the codebase that reads `area_demand`
directly instead of `area_demand_current`. The precedence view answers
"what is the best value for this timestamp"; it cannot answer "which
source failed to supply this timestamp", because hiding precedence is
what the view is for. A hole in the perishable daily track becomes
invisible through the view the moment the monthly archive covers the
same period. Not licence to bypass the view anywhere else.

The module classifies. It does not decide how loudly anyone should react
to a classification -- that is a fact about intent and it stays with the
caller, the same split hepco_daily.py makes at its 404 branch.

Taxonomy and the position rule: see FIELDS.md, "gaps -- missed-period
detection (decided 27 Aug 2026)".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

PERIOD = timedelta(minutes=30)

# Stored timestamp shape, confirmed against the database 27 Aug: no seconds.
# A mismatch here fails silently -- the range filter matches nothing and every
# period reports as missing, which reads as data loss rather than a format bug.
FMT = "%Y-%m-%d %H:%M"

ALL_SLOTS = tuple(time(h, m) for h in range(24) for m in (0, 30))

# Which slots each source is expected to carry. 47/day is DERIVED from this,
# never written down as a constant: ROWS_PER_DAY = 47 was a measurement of two
# normal days that turned out not to be a fact.
EXCLUDED_SLOTS = {
    # HEPCO writes all 48 rows and fills the ones closed at publication.
    # 23:30 cannot close before midnight, so the daily file carries that row
    # with its date and both boundary times filled in and the measurement
    # columns empty, at every age the file is reachable; the fetcher drops it
    # rather than loading an empty period. Not a gap -- outside this source's
    # domain. One exclusion, stated once.
    "hepco_daily_jisseki": frozenset({time(23, 30)}),
    # Corrected after the fact; carries all 48. Measured: 1440 rows / 30 days.
    "hepco_monthly_areajukyu": frozenset(),
}

KIND_RECOVERABLE = "recoverable"
KIND_UNRECOVERABLE = "unrecoverable"
KIND_EARLY_PUBLICATION = "early_publication"


def slots_for(source: str) -> tuple[time, ...]:
    """The slots `source` is expected to carry.

    Raises KeyError on an unknown source, deliberately. A default of "all 48"
    would silently invent a false gap at 23:30 every night for any source
    added later.
    """
    excluded = EXCLUDED_SLOTS[source]
    return tuple(t for t in ALL_SLOTS if t not in excluded)


@dataclass(frozen=True)
class Gap:
    """One contiguous run of missing periods, classified.

    Frozen: a classified gap is a conclusion, and a conclusion later code can
    quietly edit is how a report ends up disagreeing with the query behind it.
    """

    source: str
    start: datetime
    end: datetime
    periods: int
    kind: str
    reason: str


def expected_periods(source: str, start: date, end: date) -> list[datetime]:
    """Every period `source` should carry, start..end inclusive.

    This is the part a window function cannot do. LAG/LEAD only see rows that
    exist, so they find holes *between* loaded rows and are structurally blind
    to a gap at either end of the range. LEAD over area_demand_current is a
    cross-check on this module's output, never a substitute for it.
    """
    slots = slots_for(source)
    out: list[datetime] = []
    day = start
    while day <= end:
        out.extend(datetime.combine(day, s) for s in slots)
        day += timedelta(days=1)
    return out


def loaded_periods(conn, source: str, start: date, end: date) -> set[datetime]:
    """Periods that carry an actual reading, start..end inclusive.

    The only impure function in this module: takes `conn` rather than opening
    one, the same affordance every function in load.py has, so it can be
    tested against in-memory SQLite later.

    `demand_mw IS NOT NULL` caught nothing on 27 Aug (measured: 0 NULL rows,
    376 daily rows over 8 days = 47.0 exactly, because the fetcher skips the
    unfilled trailing row instead of inserting it). It stays because that
    behaviour is documented nowhere: if the loader ever starts inserting
    unclosed periods as NULL, this clause turns a silent miscount into a
    visible gap. A row is not a reading.
    """
    sql = """
        SELECT datetime_jst
          FROM area_demand
         WHERE source = ?
           AND datetime_jst >= ?
           AND datetime_jst <  ?
           AND demand_mw IS NOT NULL
    """
    lo = datetime.combine(start, time(0, 0))
    hi = datetime.combine(end + timedelta(days=1), time(0, 0))
    rows = conn.execute(sql, (source, lo.strftime(FMT), hi.strftime(FMT))).fetchall()
    return {datetime.strptime(r[0], FMT) for r in rows}


def missing_periods(
    expected: list[datetime], present: set[datetime]
) -> list[datetime]:
    """Calendar minus reality, order preserved.

    O(n) over the calendar rather than O(n*m): irrelevant at 987 periods, not
    irrelevant against ten years of monthly archive.
    """
    have = set(present)
    return [t for t in expected if t not in have]


def group_runs(source: str, missing: list[datetime]) -> list[list[datetime]]:
    """Collapse consecutive missing periods into runs.

    611 missing periods is 611 lines nobody reads; four runs is a finding.
    """
    slots = slots_for(source)
    first_slot, last_slot = slots[0], slots[-1]
    runs: list[list[datetime]] = []
    for t in missing:
        if runs and _adjacent(runs[-1][-1], t, first_slot, last_slot):
            runs[-1].append(t)
        else:
            runs.append([t])
    return runs


def _adjacent(
    previous: datetime, current: datetime, first_slot: time, last_slot: time
) -> bool:
    """Is `current` the next expected period after `previous`?

    The midnight case is why this is not a bare `== PERIOD` test. Excluding
    23:30 puts a 60-minute step between 23:00 and the next 00:00, so an
    equality test against PERIOD splits every single midnight and returns
    thirteen runs where there are four.
    """
    if current - previous == PERIOD:
        return True
    return (
        previous.time() == last_slot
        and current.time() == first_slot
        and current.date() - previous.date() == timedelta(days=1)
    )


def classify(source: str, run: list[datetime], tail_days: int, today: date) -> Gap:
    """Label one run. Position first, then age.

    All three conditions of the early-publication test are load-bearing. Drop
    `not starts_at_day_start` and a completely missing day is classified as a
    normal early publication and never reported, because a whole day also ends
    at the day's last slot.

    `age` is measured from the run's FIRST timestamp -- its oldest end -- so a
    run spanning several days is judged by its worst case. Stated limitation.

    `tail_days` has no default. The tail is a property of the source's feed,
    measured where the feed is fetched, and a default here would be a second
    copy of that measurement free to drift from the first -- and free to be
    read as an answer rather than as an input. The comparison is `age <
    tail_days`, not `<=`: the tail counts days still reachable starting at
    age 0, so a tail of N stops at age N-1. `<=` classified the first
    unreachable day as recoverable and sent an operator to re-fetch a 404.

    The value in force goes into the reason string. "inside the tail" is a
    verdict with its premise removed: a report written under one tail and read
    under another agrees with neither, and nothing in the line says which. The
    tail has already moved once. Recording it is what makes an old report
    re-checkable instead of merely re-readable.
    """
    slots = slots_for(source)
    first, last = run[0], run[-1]
    one_day = first.date() == last.date()
    ends_at_day_end = last.time() == slots[-1]
    starts_at_day_start = first.time() == slots[0]

    if one_day and ends_at_day_end and not starts_at_day_start:
        return Gap(
            source,
            first,
            last,
            len(run),
            KIND_EARLY_PUBLICATION,
            "trailing run: not closed when the file was published",
        )

    age = (today - first.date()).days
    if age < tail_days:
        return Gap(
            source,
            first,
            last,
            len(run),
            KIND_RECOVERABLE,
            f"inside the ~{tail_days}-day tail; re-fetch {first.date()}",
        )
    return Gap(
        source,
        first,
        last,
        len(run),
        KIND_UNRECOVERABLE,
        f"{age} days old; past the ~{tail_days}-day tail (a raw capture may exist)",
    )


def find_gaps(
    conn,
    source: str,
    start: date,
    end: date,
    tail_days: int,
    today: date | None = None,
) -> list[Gap]:
    """Compose the pieces. The only place they meet.

    `today` defaults to the real date HERE rather than inside classify(): a
    function that reads the clock internally can only be tested on the day it
    happens to run, which is exactly the boundary that matters.
    """
    today = today or date.today()
    expected = expected_periods(source, start, end)
    present = loaded_periods(conn, source, start, end)
    runs = group_runs(source, missing_periods(expected, present))
    return [classify(source, run, tail_days, today) for run in runs]


def format_report(gaps: list[Gap]) -> str:
    """One line per gap, plus a total. Human output, not a data structure."""
    if not gaps:
        return "no gaps"
    lines = [
        f"{g.kind:18} {g.start:%Y-%m-%d %H:%M} -> {g.end:%Y-%m-%d %H:%M} "
        f"({g.periods:4d} periods)  {g.reason}"
        for g in gaps
    ]
    actionable = sum(1 for g in gaps if g.kind == KIND_RECOVERABLE)
    total = sum(g.periods for g in gaps)
    lines.append(
        f"\n{len(gaps)} gaps, {total} periods, {actionable} actionable"
    )
    return "\n".join(lines)


def has_actionable(gaps: list[Gap]) -> bool:
    """Whether anything here can still be acted on.

    A predicate, not a policy: what a caller does with it -- exit status,
    alert, silence -- is the caller's to choose, and the choice is worth
    making carefully. A caller that reacts to the unrecoverable class as
    urgently as to the recoverable one alerts about 8 August every night
    forever, and within a fortnight the alert is ignored -- at which point a
    recoverable gap, the only kind that can still be fixed, arrives inside
    noise trained to be skipped.
    """
    return any(g.kind == KIND_RECOVERABLE for g in gaps)
