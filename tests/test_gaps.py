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

COLLISION_TS = "2026-01-15 00:00"


def test_the_view_keeps_the_monthly_row_at_a_collision(dataset):
    """Precedence at a collision: one row survives, and it is the right one.

    The five assertions fail under different edits.

    The row count is an equality against a positive integer because the failure
    it is aimed at returns zero, not two. A `<=` in the rank clause admits no
    row at all, and `assert rows` or `>= 1` reads that as an ordinary absence.

    Source and demand_mw assert the same fact from two sides. The label alone
    survives a rank inversion if it is being read off the losing row's alias;
    3125.0 is carried only by the monthly row, so it ties the surviving row's
    identity to its content.

    The count of 2 in the raw table is what stops the rest from passing
    vacuously. INSERT OR IGNORE drops a conflicting row silently here, so a
    fixture that stored one row instead of two satisfies everything above it
    while proving nothing about precedence.

    The last pair is scope. `<=` does not only empty the collision, it empties
    every timestamp: a row always finds itself in the subquery, its own rank is
    never strictly less than its own, and `<=` turns that self-match into an
    exclusion for every row in the table. 4 against 5 catches that where a
    collision-local count cannot -- the surplus row is 2026-02-01, a different
    month with no collision anywhere near it.
    """
    rows = dataset.execute(
        "SELECT source, demand_mw FROM area_demand_current WHERE datetime_jst = ?",
        (COLLISION_TS,),
    ).fetchall()

    assert len(rows) == 1

    source, demand_mw = rows[0]
    assert source == MONTHLY
    assert demand_mw == 3125.0

    raw = dataset.execute(
        "SELECT COUNT(*) FROM area_demand WHERE datetime_jst = ?", (COLLISION_TS,)
    ).fetchone()[0]
    assert raw == 2

    assert dataset.execute("SELECT COUNT(*) FROM area_demand_current").fetchone()[0] == 4
    assert dataset.execute("SELECT COUNT(*) FROM area_demand").fetchone()[0] == 5

# The demand_mw carried by the daily row at COLLISION_TS -- the row the view
# discards. A literal, not a query: computing it from the fixture would make
# the assertion below true by construction and it would pass under any view at
# all. It lives next to COLLISION_TS because the two are one fact about the
# dataset fixture, and a change to either has to move the other.
DISCARDED_DAILY_MW = 3120.0


def test_the_view_removes_one_reading_and_leaves_every_other_untouched(dataset):
    """Precedence measured by value, which the counts above cannot do.

    The neighbouring test counts. It establishes that one row survives the
    collision, that the survivor is the monthly one, and that 5 raw rows become
    4 in the view. All three are statements about which rows exist. None of
    them is a statement about what those rows carry away from the collision, or
    about the four timestamps that never collide at all -- outside COLLISION_TS
    the view's readings are asserted nowhere in this file.

    That leaves a view that filters correctly and reports wrongly. The edits
    that do it are the ones sparing the collision row and touching the rest: a
    CASE or a unit conversion applied to daily rows in the SELECT list leaves
    3125.0 at COLLISION_TS alone, leaves the row count at 4, and changes what
    the other three rows report. Every assertion above stays green, because
    none of them reads a value anywhere except COLLISION_TS. This one does
    not, because the sum reads all five rows.

    An edit that alters the collision row itself -- averaging the two sources
    rather than choosing between them -- is already caught above by
    `demand_mw == 3125.0`. This test is not a second copy of that assertion.
    It covers the four timestamps that assertion does not reach.

    The assertion is the difference, not the view total. Raw minus view equals
    the discarded daily row -- a relationship between two numbers the fixture
    produces, the same shape as 4-against-5 above, so it survives a fixture
    that grows a sixth row and fails honestly if the discarded row changes
    value. A hardcoded 13145 would go red on any edit to the fixture with
    nothing in the failure to say which edit.

    It is an equality, not an inequality. `raw_total != view_total` is true
    whenever the view drops any row, including the monthly one -- it is green
    under the exact precedence inversion the test beside it exists to catch.

    No JOIN, and no source filter. Joining the table to the view on
    datetime_jst multiplies the collision timestamp against itself and measures
    the join instead of the view. Filtering to one source removes the collision
    from one side or the other, and the collision is the whole subject.

    Both sums are over the whole table, not over COLLISION_TS. A
    collision-local sum agrees with a view that over-excludes somewhere else --
    the same reason the count above is 4 against 5 globally rather than 1 at
    the collision, and the same surplus row (2026-02-01) is what carries the
    check past the month where the collision sits.

    Exact `==` holds while every fixture value is exactly representable as a
    float. If one ever is not, this becomes pytest.approx(abs=1e-9) -- and that
    tolerance would be about REAL round-tripping, not about the number, which
    stays exact.
    """
    raw_total = dataset.execute(
        "SELECT sum(demand_mw) FROM area_demand"
    ).fetchone()[0]

    view_total = dataset.execute(
        "SELECT sum(demand_mw) FROM area_demand_current"
    ).fetchone()[0]

    assert raw_total - view_total == DISCARDED_DAILY_MW
