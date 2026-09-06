"""replace_rows' shrink guard: does the month survive a truncated file.

Four tests, and only three of them protect anything. The third records a hole
deliberately left open.

The guard is one line -- `if deleted and written < deleted: raise` -- but it
sits inside `with conn:`, after the INSERT, and that position is the whole
design. The DELETE has already run by then. Raising there rolls the DELETE
back with it; raising anywhere after the block reports a truncation the same
run that made it permanent. So the assertion that matters in test 1 is not
that an exception came out, it is that the row count went back.

Everything here goes through load_demand, so the file on disk is the input and
the guard is reached the way the monthly track reaches it. Nothing calls
replace_rows directly: a test that hands it a list of dicts would skip
parse_monthly_demand and stop being able to say anything about a truncated
*file*, which is the failure this exists for.
"""

import calendar

import pytest

from conftest import MONTHLY
from hokkaido_grid.load import load_demand

PERIODS_PER_DAY = 48                 # monthly cadence. The daily track is 47,
                                     # by design, which is why the guard
                                     # compares two counts instead of checking
                                     # one against a number.

APRIL = "2026-04"
MARCH = "2026-03"

APRIL_ROWS = 30 * PERIODS_PER_DAY    # 1440
MARCH_ROWS = 31 * PERIODS_PER_DAY    # 1488

# 4 days and 6 periods. Not a whole number of days on purpose: a truncated
# download stops wherever the connection died, and a guard that only noticed
# whole missing days would walk past this one.
TRUNCATED_ROWS = 198

# The real file's first line is the unit banner, which parse_monthly_demand
# skips by count rather than by content, and its last ~48 lines are all-comma
# blanks that the DATE check drops. Both are reproduced here so the row counts
# below are visibly not line counts: a full April is 1490 lines and 1440 rows.
BANNER = "エリア需給実績 単位[MW平均]"
HEADER = ("DATE", "TIME", "エリア需要", "太陽光発電実績", "風力発電実績", "合計")
TRAILING_BLANKS = 48

# Six columns, not the file's twenty-one. parse_monthly_demand reads by name
# through DictReader and every read is a .get(), so the columns it does not
# name cannot change what it returns. REQUIRED_DEMAND_COLUMNS is the contract
# and this fixture writes exactly that; if a column is added to the contract
# this file stops parsing, which is the correct place to find out.


def _month_lines(year, month, *, limit=None, blanks=TRAILING_BLANKS):
    """The lines of one monthly CSV. `limit` truncates the data rows."""
    lines = [BANNER, ",".join(HEADER)]

    data = []
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        for period in range(PERIODS_PER_DAY):
            hour, minute = divmod(period * 30, 60)
            # Legal under every CHECK in the table: demand is positive, the
            # two parts are non-NULL and non-negative, and wind_solar_mw --
            # which the parser derives rather than reads -- lands on their sum
            # exactly, well inside the 0.05 the monthly derivation CHECK
            # allows. A row that failed a CHECK would raise IntegrityError and
            # this suite would go red for a reason that has nothing to do with
            # the guard.
            demand = 3000.0 + period
            data.append(
                f"{year}/{month:02d}/{day:02d},{hour:02d}:{minute:02d},"
                f"{demand},120.0,80.0,{demand}"
            )

    if limit is not None:
        # Cut, not filtered: the tail of the file is simply absent, blank rows
        # included, which is what a connection dropping mid-transfer leaves
        # behind.
        return lines + data[:limit]

    return lines + data + ["," * (len(HEADER) - 1)] * blanks


def _month_csv(tmp_path, name, year, month, *, limit=None):
    """Write one monthly CSV under tmp_path and return its path.

    cp932 and CRLF, because that is what parse_monthly_demand opens the file
    expecting; a UTF-8 fixture would pass through a decoder that the real file
    never meets. tmp_path, because a fixture built by hand once is green until
    the day someone cleans out /tmp and red forever after.
    """
    path = tmp_path / name
    path.write_bytes(
        "\r\n".join(_month_lines(year, month, limit=limit)).encode("cp932") + b"\r\n"
    )
    return path


def _rows_in(conn, month, source=MONTHLY):
    """How many rows of `source` the database holds for one calendar month.

    Counted from the database, not from the file: the two differ by the header,
    the banner and the trailing blanks, and it is the database side the guard
    is defending. Scoped by month so the March assertion in the last test can
    be about March.
    """
    return conn.execute(
        "SELECT count(*) FROM area_demand WHERE source = ? AND datetime_jst LIKE ?",
        (source, f"{month}%"),
    ).fetchone()[0]


def test_a_truncated_file_over_a_populated_month_leaves_the_month_intact(schema, tmp_path):
    """The guard's whole reason for existing.

    Three assertions, and the first is the least interesting. That the load
    raises says only that something objected. Anything can raise -- a CHECK, a
    typo, a missing column -- and a run that raised *after* committing the
    DELETE has raised and destroyed the month at the same time. That is the
    outcome this guard exists to prevent, and it is indistinguishable from the
    good outcome if the count is never checked.

    So the second assertion is the test. 1440 back means the DELETE was rolled
    back with the raise, which is only true while the raise is inside
    `with conn:`. Move it below the block and this line reports 198.

    The third is scope within the month: 23:30 on the 30th is past the point
    the truncated file stops, so it can only be present if the original rows
    came back rather than being rewritten from the short file. Without it,
    1440 could in principle be read as the guard never having fired at all --
    it cannot here, because a re-INSERT over surviving rows would hit the
    primary key instead, but the assertion costs one line and does not depend
    on that argument holding.
    """
    load_demand(schema, _month_csv(tmp_path, "april.csv", 2026, 4))
    assert _rows_in(schema, APRIL) == APRIL_ROWS

    short = _month_csv(tmp_path, "april_short.csv", 2026, 4, limit=TRUNCATED_ROWS)
    with pytest.raises(ValueError):
        load_demand(schema, short)

    assert _rows_in(schema, APRIL) == APRIL_ROWS

    survivor = schema.execute(
        "SELECT count(*) FROM area_demand WHERE source = ? AND datetime_jst = ?",
        (MONTHLY, "2026-04-30 23:30"),
    ).fetchone()[0]
    assert survivor == 1


def test_a_full_reload_of_the_same_month_is_silent(schema, tmp_path):
    """The false-positive test, and the one that decides whether the loader is
    usable at all.

    1440 deleted, 1440 written. Nothing has gone wrong and nothing may be
    raised. A monthly reload is the ordinary operation -- HEPCO republishes a
    corrected month and it is loaded over itself -- so a guard that fires on
    equality fires on the normal path, every time, and the loader has to be
    bypassed to do its job.

    It goes red under exactly one edit: a comparison written as `written <=
    deleted`, or as `deleted >= written`, which is the same mistake spelled
    the other way. Both look right in isolation and both survive every other
    test in this file, because every other test supplies counts that differ.

    No pytest.raises here on purpose. The absence of an exception is the
    assertion; wrapping it in anything would only weaken it. The row count is
    asserted after it so the test cannot pass by loading nothing.
    """
    april = _month_csv(tmp_path, "april.csv", 2026, 4)

    load_demand(schema, april)
    load_demand(schema, april)

    assert _rows_in(schema, APRIL) == APRIL_ROWS


def test_first_load_is_unguarded(schema, tmp_path):
    """A truncated file into an empty database loads, and nothing objects.

    This records a hole. It does not protect anything, and it should not be
    read as approval.

    The guard compares what the DELETE removed against what the INSERT wrote.
    On a first load the DELETE removes nothing, so there is no prior count to
    be smaller than and the comparison has nothing to say. 198 rows land and
    the run reports success. The `deleted and` in the condition is that fact
    written down: without it, `written < deleted` is False for deleted=0
    anyway, so the clause changes no behaviour -- it is there to be read.

    Closing this needs a different fact than the one replace_rows has. The
    number of periods a complete month should hold is in gaps.py, which knows
    that monthly is 48 a day and daily is 47, and the honest fix is to compare
    against that calendar rather than against the previous load. Until then the
    detector for a short first load is `gaps`, after the fact, run by a person.

    If someone closes it, this test fails. That failure is the signal that the
    docstring above has become wrong, not that the new guard has.
    """
    short = _month_csv(tmp_path, "april_short.csv", 2026, 4, limit=TRUNCATED_ROWS)

    load_demand(schema, short)

    assert _rows_in(schema, APRIL) == TRUNCATED_ROWS


def test_the_rollback_does_not_reach_the_previous_month(schema, tmp_path):
    """The guard's blast radius is one month, the same as the DELETE's.

    A rollback undoes the transaction, and the transaction is scoped to April
    by _month_window -- so March should be untouched by a failed April load.
    That is what the month-scoping in 8689791 bought, and this is the test that
    it is still true now that something inside the transaction raises on
    purpose.

    March is 1488 rows against April's 1440 because March has 31 days. The two
    counts being different is the point: a guard or a window that lost track of
    which month it was working on would show up as one number where the other
    belongs, and two months of equal length would hide that.

    Both months are asserted after the failure. April says the rollback
    happened, March says it stopped where it should have.
    """
    load_demand(schema, _month_csv(tmp_path, "march.csv", 2026, 3))
    load_demand(schema, _month_csv(tmp_path, "april.csv", 2026, 4))
    assert _rows_in(schema, MARCH) == MARCH_ROWS

    short = _month_csv(tmp_path, "april_short.csv", 2026, 4, limit=TRUNCATED_ROWS)
    with pytest.raises(ValueError):
        load_demand(schema, short)

    assert _rows_in(schema, MARCH) == MARCH_ROWS
    assert _rows_in(schema, APRIL) == APRIL_ROWS
