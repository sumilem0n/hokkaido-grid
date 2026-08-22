"""Unit-guard tests for the daily source parser. No network in this file.

The guard exists because KWH_PER_30MIN_TO_MW is only correct while the
header says kWh accumulated over the period. A rename to kWh/h leaves a
figure already expressed per hour, and dividing it by 500 doubles every
value -- inside the bounds check for any period under 3000 MW true demand.
"""

import pytest

from hokkaido_grid.errors import SourceUnavailable
from hokkaido_grid.sources.hepco_daily import _parse_row, _resolve_col

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
