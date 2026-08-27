from datetime import date, datetime

from hokkaido_grid.gaps import (
    classify,
    expected_periods,
    group_runs,
    has_actionable,
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
    import pytest
    with pytest.raises(KeyError):
        slots_for("hepco_daily_juyo_01")


def test_trailing_run_is_early_publication():
    run = [datetime(2026, 8, 24, 23, 0)]
    assert classify(DAILY, run, today=date(2026, 8, 26)).kind == "early_publication"


def test_whole_day_is_not_early_publication():
    """The trap: a whole missing day also ends at the day's last slot."""
    day = date(2026, 8, 26)
    run = expected_periods(DAILY, day, day)
    g = classify(DAILY, run, today=date(2026, 8, 27))
    assert g.kind != "early_publication"
    assert g.kind == "recoverable"
    assert g.periods == 47


def test_interior_run_inside_tail_is_recoverable():
    run = [datetime(2026, 8, 26, 10, 0), datetime(2026, 8, 26, 10, 30)]
    assert classify(DAILY, run, today=date(2026, 8, 27)).kind == "recoverable"


def test_old_run_is_unrecoverable():
    run = [datetime(2026, 8, 8, 3, 0)]
    assert classify(DAILY, run, today=date(2026, 8, 27)).kind == "unrecoverable"


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
    recent = classify(DAILY, [datetime(2026, 8, 26, 10, 0)], today=date(2026, 8, 27))
    old = classify(DAILY, [datetime(2026, 8, 8, 3, 0)], today=date(2026, 8, 27))
    assert has_actionable([recent]) is True
    assert has_actionable([old]) is False
