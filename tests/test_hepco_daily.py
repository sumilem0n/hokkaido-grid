"""Unit-guard tests for the daily source parser. No network in this file.

The guard exists because KWH_PER_30MIN_TO_MW is only correct while the
header says kWh accumulated over the period. A rename to kWh/h leaves a
figure already expressed per hour, and dividing it by 500 doubles every
value -- inside the bounds check for any period under 3000 MW true demand.
"""

import datetime

import pytest
import requests

from hokkaido_grid.errors import SourceTransientError, SourceUnavailable
from hokkaido_grid.sources.hepco_daily import _parse_row, _resolve_col, fetch


FIELDS = [
    "日付", "時間コマ", "時間帯_自", "時間帯_至",
    "エリア総需要量(kWh)", "エリア総発電量(kWh)", "エリア風力・太陽光発電量(kWh)",
]


def test_resolves_the_demand_column():
    assert _resolve_col(FIELDS, "エリア総需要量", "kWh") == "エリア総需要量(kWh)"


def test_rejects_a_unit_that_merely_contains_kwh():
    """The regression. 'kWh' is a substring of 'kWh/h'; membership passed it."""
    with pytest.raises(SourceUnavailable):
        _resolve_col(FIELDS[:4] + ["エリア総需要量(kWh/h)"], "エリア総需要量", "kWh")


def test_tolerates_full_width_parentheses():
    """Punctuation width carries no meaning; only the unit does."""
    fields = FIELDS[:4] + ["エリア総需要量（kWh）"]
    assert 	_resolve_col(fields, "エリア総需要量", "kWh") == "エリア総需要量（kWh）"


def test_rejects_a_missing_unit():
    with pytest.raises(SourceUnavailable):
        _resolve_col(FIELDS[:4] + ["エリア総需要量"], "エリア総需要量", "kWh")


def test_rejects_a_missing_column():
    with pytest.raises(SourceUnavailable):
        _resolve_col(["日付", "時間コマ"], "エリア総需要量", "kWh")


def test_rejects_two_demand_columns():
    with pytest.raises(SourceUnavailable):
        _resolve_col(["エリア総需要量(kWh)", "エリア総需要量(MWh)"], "エリア総需要量", "kWh")


def test_resolves_the_wind_solar_column():
    assert _resolve_col(
        FIELDS, "エリア風力・太陽光発電量", "kWh"
    ) == "エリア風力・太陽光発電量(kWh)"


def test_rejects_wind_solar_renamed_to_per_hour():
    # The same kWh/h trap as demand, and it bites harder here: this column's
    # floor is 0.0, so its range check cannot reject a doubled value the way
    # MIN_MW does. The header assertion is the only guard of this class.
    with pytest.raises(SourceUnavailable):
        _resolve_col(
            FIELDS[:6] + ["エリア風力・太陽光発電量(kWh/h)"],
            "エリア風力・太陽光発電量", "kWh",
        )


def test_rejects_wind_solar_column_absent():
    with pytest.raises(SourceUnavailable):
        _resolve_col(FIELDS[:6], "エリア風力・太陽光発電量", "kWh")

def test_converts_wind_solar_kwh_to_mw():
    # MIN_MW raises before the wind/solar branch is ever reached, so breaking
    # KWH_PER_30MIN_TO_MW surfaces as a demand error and this assertion never
    # runs. Splitting the tests did not change that -- they share the
    # constant. Control this one by breaking the EXPECTED value instead:
    # 330.0 -> 999.0 went red naming "Obtained: 330.0" (22 Aug).
    # This column has no MIN_MW-style backstop of its own -- 165000/1000 =
    # 165 MW sits inside [0, 3000] -- so this assert IS the guard.

    row = {
        "日付": "20260802", "時間帯_自": "0:00",
        "エリア総需要量(kWh)": "1193000",
        "エリア風力・太陽光発電量(kWh)": "165000",
    }
    parsed = _parse_row(row, "エリア総需要量(kWh)", "エリア風力・太陽光発電量(kWh)")
    assert parsed["wind_solar_mw"] == pytest.approx(330.0)


def test_wind_solar_blank_is_none_not_zero():
    # None is the absence of a claim; 0.0 claims renewables produced nothing.
    row = {
        "日付": "20260802", "時間帯_自": "0:00",
        "エリア総需要量(kWh)": "1193000",
        "エリア風力・太陽光発電量(kWh)": "",
    }
    parsed = _parse_row(row, "エリア総需要量(kWh)", "エリア風力・太陽光発電量(kWh)")
    assert parsed["wind_solar_mw"] is None

def _finished_short_day_bytes():
    # A finished day's file for 24 Aug 2026 in which only periods 1 to 46
    # were ever filled. Periods 47 and 48 are present but blank.
    lines = [
        "ファイル更新日,ファイル更新時間,対象年月日",
        "20260824,23:13:00,20260824",
        "日付,時間コマ,時間帯_自,時間帯_至,"
        "エリア総需要量(kWh),エリア総発電量(kWh),エリア風力・太陽光発電量(kWh)",
    ]
    for period in range(1, 47):
        start = (period - 1) * 30
        end = period * 30
        lines.append(
            f"20260824,{period},"
            f"{start // 60}:{start % 60:02d},{end // 60}:{end % 60:02d},"
            "1000000,1000000,100000"
        )
    lines.append("20260824,47,23:00,23:30,,,")
    lines.append("20260824,48,23:30,24:00,,,")
    return "\n".join(lines).encode("cp932")

@pytest.mark.xfail(
    raises=SourceTransientError,
    strict=True,
    reason="no-retry decision 1 is not built: a finished short day still raises",
)

def test_fetch_returns_46_rows_for_a_finished_day(monkeypatch):
    
    sample_bytes = _finished_short_day_bytes()

    class StandInResponse:
        status_code = 200
        content = sample_bytes

        def raise_for_status(self):
            return None

    def stand_in_get(*args, **kwargs):
        return StandInResponse()

    monkeypatch.setattr(requests, "get", stand_in_get)

    rows = fetch(datetime.date(2026, 8, 24), today=datetime.date(2026, 8, 25))

    assert len(rows) == 46
