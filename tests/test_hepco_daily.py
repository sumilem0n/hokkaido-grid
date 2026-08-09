"""Unit-guard tests for the daily source parser. No network in this file.

The guard exists because KWH_PER_30MIN_TO_MW is only correct while the
header says kWh accumulated over the period. A rename to kWh/h leaves a
figure already expressed per hour, and dividing it by 500 doubles every
value -- inside the bounds check for any period under 3000 MW true demand.
"""

import pytest

from hokkaido_grid.errors import SourceUnavailable
from hokkaido_grid.sources.hepco_daily import _resolve_demand_col

FIELDS = [
    "日付", "時間コマ", "時間帯_自", "時間帯_至",
    "エリア総需要量(kWh)", "エリア総発電量(kWh)", "エリア風力・太陽光発電量(kWh)",
]


def test_resolves_the_demand_column():
    assert _resolve_demand_col(FIELDS) == "エリア総需要量(kWh)"


def test_rejects_a_unit_that_merely_contains_kwh():
    """The regression. 'kWh' is a substring of 'kWh/h'; membership passed it."""
    with pytest.raises(SourceUnavailable):
        _resolve_demand_col(FIELDS[:4] + ["エリア総需要量(kWh/h)"])


def test_tolerates_full_width_parentheses():
    """Punctuation width carries no meaning; only the unit does."""
    fields = FIELDS[:4] + ["エリア総需要量（kWh）"]
    assert _resolve_demand_col(fields) == "エリア総需要量（kWh）"


def test_rejects_a_missing_unit():
    with pytest.raises(SourceUnavailable):
        _resolve_demand_col(FIELDS[:4] + ["エリア総需要量"])


def test_rejects_a_missing_column():
    with pytest.raises(SourceUnavailable):
        _resolve_demand_col(["日付", "時間コマ"])


def test_rejects_two_demand_columns():
    with pytest.raises(SourceUnavailable):
        _resolve_demand_col(["エリア総需要量(kWh)", "エリア総需要量(MWh)"])
