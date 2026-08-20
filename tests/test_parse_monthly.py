"""parse_monthly_demand against manufactured files.

The files are built here rather than checked in as fixtures because every test
below needs a file that differs from the real one in exactly one way -- a column
removed, a date malformed -- and a directory of near-identical 3MB CSVs hides
which byte is the point of each.

What the builder has to reproduce from the real HEPCO file is only its shape:
the 単位[MW平均] banner on line 1 that the parser skips, the header on line 2,
cp932, CRLF, and the trailing all-comma rows. Two data rows are enough; the
parser does the same thing to row 3 as to row 2.
"""

import pytest

from hokkaido_grid.errors import SchemaChanged
from hokkaido_grid.load import load_demand, parse_monthly_demand

BANNER = "エリア需給実績 単位[MW平均]"

HEADER = ("DATE", "TIME", "エリア需要", "太陽光発電実績", "風力発電実績", "合計")

# The first row is deliberately not zero-padded and the second is. Real files
# write 2026/4/1; the canonical key is 2026-04-01. If both rows were padded
# already, the "zero-padded" half of that promise would go untested -- strftime
# would only be changing the separators.
DATA_ROWS = (
    ("2026/4/1", "0:00", "2450.5", "0", "120.3", "2570.8"),
    ("2026/04/01", "00:30", "2380.1", "0", "118.7", "2498.8"),
)

EXPECTED = [
    {"datetime_jst": "2026-04-01 00:00", "demand_mw": 2450.5,
     "solar_mw": 0.0, "wind_mw": 120.3, "supply_total_mw": 2570.8},
    {"datetime_jst": "2026-04-01 00:30", "demand_mw": 2380.1,
     "solar_mw": 0.0, "wind_mw": 118.7, "supply_total_mw": 2498.8},
]


def write_demand_csv(tmp_path, *, drop_column=None, data_rows=DATA_ROWS):
    """Write one manufactured monthly file into tmp_path and return its path.

    Written as bytes, not text: encoding="cp932" with newline="\\r\\n" would
    work, but the encoding and the line endings are two of the things this file
    exists to reproduce, and bytes leave no room for the platform to translate
    either of them on the way out.
    """
    kept = [column for column in HEADER if column != drop_column]
    lines = [BANNER, ",".join(kept)]
    for row in data_rows:
        lines.append(",".join(
            cell for column, cell in zip(HEADER, row) if column != drop_column))
    lines.append("," * (len(kept) - 1))     # one of the ~48 all-comma trailers

    path = tmp_path / "hepco_demand_2026-04.csv"
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp932"))
    return path


def test_good_file_parses(tmp_path):
    """The happy path, asserted as whole rows rather than field by field.

    Equality on the dict is what catches a column landing in the wrong field:
    solar and wind are both small numbers next to demand, and an assertion that
    only checked datetime_jst and demand_mw would pass with them swapped.
    """
    rows, dropped = parse_monthly_demand(write_demand_csv(tmp_path))

    assert rows == EXPECTED
    assert dropped == 1                    # the all-comma row, counted not returned


@pytest.mark.parametrize(
    "missing",
    # Written out by hand, not imported from REQUIRED_DEMAND_COLUMNS. Generating
    # the cases from the tuple under test means deleting a name from the tuple
    # deletes a case, and the suite stays green through the change it exists to
    # catch. This list is the independent copy of the expectation.
    ["DATE", "TIME", "エリア需要", "太陽光発電実績", "風力発電実績", "合計"],
)
def test_missing_required_column_raises(tmp_path, missing):
    """Each required column, absent, stops the load.

    Six cases rather than one because the mechanism and the list are different
    claims. One case proves the header check fires; six prove the list is the
    six columns the parser actually reads. Drop 太陽光発電実績 from the tuple
    while tidying and every other test still passes -- the parser just .get()s
    a name that is no longer required, writes NULL through solar_mw for the
    month, and raises nothing.
    """
    path = write_demand_csv(tmp_path, drop_column=missing)

    with pytest.raises(SchemaChanged, match=missing):
        parse_monthly_demand(path)


def test_unparseable_datetime_raises_schema_changed(tmp_path):
    """A malformed DATE leaves as SchemaChanged, not as the ValueError beneath it.

    ISO dashes where the file uses slashes: strptime raises ValueError, and the
    parser is supposed to convert it. The conversion is the whole test. A raw
    ValueError reaching main() matches none of the three except blocks, exits 1,
    and the backfill driver reads that as a day that was merely gone.

    __cause__ is checked because `raise ... from exc` is what keeps the original
    error in the traceback; a bare `raise SchemaChanged(...)` would pass the
    first assertion and lose it.
    """
    path = write_demand_csv(
        tmp_path,
        data_rows=(("2026-04-01", "0:00", "2450.5", "0", "120.3", "2570.8"),),
    )

    with pytest.raises(SchemaChanged) as excinfo:
        parse_monthly_demand(path)

    assert isinstance(excinfo.value.__cause__, ValueError)


def test_round_trip_through_loader(tmp_path, conn):
    """Parse, load, select back: the only test that crosses both modules.

    Everything above stops at what parse_monthly_demand returns, which cannot
    catch a disagreement between the keys it emits and the columns the schema
    holds -- _prepare builds its column list from the rows, so a renamed key
    becomes a renamed column and fails at the INSERT, not before it.

    source is selected too: the stamp is the loader's, and merge_rows'
    precedence rule is a comparison against this exact string.
    """
    load_demand(conn, write_demand_csv(tmp_path))

    written = conn.execute(
        "SELECT datetime_jst, demand_mw, solar_mw, wind_mw, supply_total_mw, source "
        "FROM area_demand ORDER BY datetime_jst;"
    ).fetchall()

    assert written == [
        ("2026-04-01 00:00", 2450.5, 0.0, 120.3, 2570.8, "hepco_monthly_areajukyu"),
        ("2026-04-01 00:30", 2380.1, 0.0, 118.7, 2498.8, "hepco_monthly_areajukyu"),
    ]
