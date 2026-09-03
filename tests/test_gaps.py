import sqlite3
from datetime import date, datetime

import pytest

from hokkaido_grid.gaps import (
    classify,
    expected_periods,
    group_runs,
    has_actionable,
    loaded_periods,
    missing_periods,
    slots_for,
)

DAILY = "hepco_daily_jisseki"
MONTHLY = "hepco_monthly_areajukyu"


def test_daily_calendar_is_47_per_day():
    assert len(expected_periods(DAILY, date(2026, 8, 24), date(2026, 8, 24))) == 47


def test_monthly_calendar_is_48_per_day():
    assert len(expected_periods(MONTHLY, date(2026, 4, 1), date(2026, 4, 1))) == 48


def test_unknown_source_raises():
    with pytest.raises(KeyError):
        slots_for("hepco_daily_juyo_01")


def test_trailing_run_is_early_publication():
    run = [datetime(2026, 8, 24, 23, 0)]
    assert classify(DAILY, run, today=date(2026, 8, 26), tail_days=2).kind == "early_publication"


def test_whole_day_is_not_early_publication():
    """The trap: a whole missing day also ends at the day's last slot."""
    day = date(2026, 8, 26)
    run = expected_periods(DAILY, day, day)
    g = classify(DAILY, run, today=date(2026, 8, 27), tail_days=2)
    assert g.kind != "early_publication"
    assert g.kind == "recoverable"
    assert g.periods == 47


def test_interior_run_inside_tail_is_recoverable():
    run = [datetime(2026, 8, 26, 10, 0), datetime(2026, 8, 26, 10, 30)]
    assert classify(DAILY, run, today=date(2026, 8, 27), tail_days=2).kind == "recoverable"


def test_old_run_is_unrecoverable():
    run = [datetime(2026, 8, 8, 3, 0)]
    assert classify(DAILY, run, today=date(2026, 8, 27), tail_days=2).kind == "unrecoverable"

def test_age_equals_tail_is_unrecoverable():
    """Age 2 with tail_days=2: the boundary HEPCO 404'd on 31 Aug."""
    run = [datetime(2026, 8, 29, 10, 0)]
    g = classify(DAILY, run, today=date(2026, 8, 31), tail_days=2)
    assert g.kind == "unrecoverable"

def test_runs_join_across_midnight():
    missing = [datetime(2026, 8, 24, 23, 0), datetime(2026, 8, 25, 0, 0)]
    assert len(group_runs(DAILY, missing)) == 1


def test_separate_gaps_do_not_join():
    missing = [datetime(2026, 8, 24, 3, 0), datetime(2026, 8, 24, 5, 0)]
    assert len(group_runs(DAILY, missing)) == 2


def test_missing_is_expected_minus_present():
    exp = expected_periods(DAILY, date(2026, 8, 24), date(2026, 8, 24))
    assert len(missing_periods(exp, set(exp[:40]))) == 7


def test_only_recoverable_is_actionable():
    recent = classify(DAILY, [datetime(2026, 8, 26, 10, 0)], today=date(2026, 8, 27), tail_days=2)
    old = classify(DAILY, [datetime(2026, 8, 8, 3, 0)], today=date(2026, 8, 27), tail_days=2)
    assert has_actionable([recent]) is True
    assert has_actionable([old]) is False


# ---------------------------------------------------------------------------
# loaded_periods -- the one impure function in gaps.py.
#
# Everything above this line tests a pure function and needs no database. These
# five take the fixture chain in conftest.py: `schema` for an empty table,
# `dataset` for the known five rows. The split is why the tests above run
# without a schema file existing at all.
# ---------------------------------------------------------------------------

COLUMNS = (
    "datetime_jst, demand_mw, solar_mw, wind_mw, "
    "wind_solar_mw, supply_total_mw, source"
)
INSERT = f"INSERT INTO area_demand ({COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)"

JAN15 = date(2026, 1, 15)


def _insert(conn, datetime_jst, demand_mw=3000.0, source=DAILY):
    """One daily row. Monthly rows need three further non-NULL columns to
    satisfy the derivation CHECK, so these build daily rows unless the point
    is the source filter itself."""
    conn.execute(INSERT, (datetime_jst, demand_mw, None, None, 80.0, None, source))
    conn.commit()


def test_empty_range_does_not_raise(schema):
    """The guarded property is the absence of an exception, not the value.

    The assertion below cannot fail on its own terms: loaded_periods builds
    its result with a set comprehension over the fetched rows, and a
    comprehension over zero rows returns an empty set. There is no code path
    where the query finds nothing and the function returns something else. As
    a claim about the value this test is a tautology, and it is kept only as a
    cheap secondary check.

    What it does guard is the line nobody has written yet. It goes red the
    moment someone adds a step that assumes at least one row -- an unguarded
    `rows[0]`, a `min()` or `max()` over the timestamps to bound the range, a
    `statistics` call on the readings. Each of those raises on the empty case
    and returns fine on every other test in this file, because every other
    test hands the function rows to find.

    A source with no data yet is not an error condition. Callers reach here
    through find_gaps, which subtracts this set from the full calendar; an
    exception at that point aborts a report instead of producing one that
    correctly says everything is missing.
    """
    assert loaded_periods(schema, DAILY, JAN15, JAN15) == set()


def test_source_filter_excludes_the_other_source(dataset):
    """The dataset holds four rows on 15 Jan: three daily, one monthly.

    Both directions are asserted and only the second earns its place. The
    monthly row sits at 00:00, the same timestamp as the first daily row, so
    the daily answer is three timestamps whether the source filter runs or
    not -- the returned set absorbs the duplicate and the count is unchanged.
    Checked by mutation: deleting the WHERE clause leaves the daily assertion
    green.

    Asked from the monthly side the collision discriminates instead of hiding.
    One of the four rows is monthly, so an unfiltered query answers with three
    timestamps where one is correct.
    
    Re-checked 3 Sep: deleting the WHERE clause and its binding leaves the
    daily assertion green and fails the monthly one, which returns 00:30 and
    01:00 alongside 00:00. The monthly assertion is the load-bearing one; the
    daily assertion cannot go red under this mutation. 
  
    """
    daily = loaded_periods(dataset, DAILY, JAN15, JAN15)
    monthly = loaded_periods(dataset, MONTHLY, JAN15, JAN15)

    assert daily == {
        datetime(2026, 1, 15, 0, 0),
        datetime(2026, 1, 15, 0, 30),
        datetime(2026, 1, 15, 1, 0),
    }
    assert monthly == {datetime(2026, 1, 15, 0, 0)}


def test_range_includes_the_end_day_and_stops_before_the_next(schema):
    """The half-open upper bound, which is the edit nothing catches.

    hi is midnight at the START of end+1 and the comparison is `<`. Both
    halves are load-bearing: `<=` pulls in the next day's 00:00 row, and
    computing hi from `end` rather than `end + 1` drops the whole last day of
    the range.

    Neither mistake raises. The first invents a period the caller never asked
    about; the second reports 47 missing periods for a day that loaded fine.
    Both arrive as a plausible-looking gap report.
    """
    _insert(schema, "2026-01-15 00:00")
    _insert(schema, "2026-01-16 00:00")

    assert loaded_periods(schema, DAILY, JAN15, JAN15) == {
        datetime(2026, 1, 15, 0, 0)
    }


def test_demand_mw_cannot_be_null_so_the_guard_cannot_fire(schema):
    """`demand_mw IS NOT NULL` in loaded_periods is unreachable.

    The column is declared NOT NULL, so a NULL reading cannot be stored: an
    explicit NULL, an omitted column and a later UPDATE all raise
    IntegrityError, and INSERT OR IGNORE drops the row rather than storing one.
    The clause therefore excludes nothing on any database matching the current
    schema.

    That makes it insurance against a schema change, not against loader
    behaviour -- which is not what its docstring in gaps.py claims. The clause
    is worth keeping; the paragraph above it is not accurate as written.

    The assertion is on the constraint rather than on the clause. If NOT NULL
    is ever dropped this test fails, and that failure is the signal that the
    guard has become live code needing a test of its own.
    """
    with pytest.raises(sqlite3.IntegrityError):
        schema.execute(
            INSERT, ("2026-01-15 00:00", None, None, None, 84.0, None, DAILY)
        )


def test_the_set_is_for_lookup_not_deduplication(dataset):
    """What the returned set actually guarantees, which is less than it looks.

    Returning a set implies the query might produce duplicates. It cannot.
    `source` is a required parameter, so every call sees exactly one source,
    and (datetime_jst, source) is the primary key -- a repeated timestamp
    within one source is rejected before it can reach the query.

    So the duplicate 00:00 in the dataset is invisible from either side: the
    daily call and the monthly call each see their own row and neither sees
    both. The set is here because missing_periods does O(1) membership tests
    against it over the whole calendar, not because anything needs collapsing.
    """
    daily = loaded_periods(dataset, DAILY, JAN15, JAN15)
    monthly = loaded_periods(dataset, MONTHLY, JAN15, JAN15)

    collision = datetime(2026, 1, 15, 0, 0)
    assert collision in daily
    assert collision in monthly
    assert daily != monthly

    # One source cannot supply a timestamp twice, so there is nothing for the
    # set to collapse in the first place.
    with pytest.raises(sqlite3.IntegrityError):
        _insert(dataset, "2026-01-15 00:00")
