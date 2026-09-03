"""
Capstone loader — Hokkaido grid demand + Sapporo weather -> SQLite.

Loads two already-fetched files into sql/hokkaido.db (schema built on Day 1):
  data/hepco_demand_2026-04.csv     (HEPCO area actuals, CP932, CRLF, MW, 30-min) -> area_demand
  data/weather_sapporo_2026-04.json (Open-Meteo ERA5, JST, hourly)                -> weather_hourly

Run from the repo root (~/hokkaido-grid):
    uv run python hokkaido_grid/load.py

The paths below are relative to the working directory, which is why that
instruction exists. config.py anchors its paths to __file__ instead and does not
need it; this module keeps the constraint until it is given the same treatment.

Three writers, three delete scopes, and one rule under all of them: a DELETE
must be a subset of the key range the INSERT in the same transaction
authoritatively owns. Amended 2026-08-21, from "a subset of what the INSERT can
supply" -- month-scoped replace_rows deliberately deletes a period the insert
may not refill, because a retracted period is exactly the ghost row this writer
exists to collect. load_weather keeps the stricter form (its span is derived
from the rows themselves) and merge_rows deletes nothing at all.

Since the composite key (datetime_jst, source) landed on 2026-08-21, every
DELETE here is also scoped by source. Two tracks legitimately hold the same
half-hour, so a time-only DELETE destroys the other track -- the unscoped-delete
bug wearing the fix that was supposed to end it.
"""

import csv
import json
import logging
from datetime import datetime, timedelta

from hokkaido_grid.errors import SchemaChanged

logger = logging.getLogger(__name__)

KEY_COLUMN = "datetime_jst"
# The full primary key as of the 2026-08-21 migration. ON CONFLICT targets must
# name this exact column set; see FIELDS.md, "Decision — wind/solar schema and
# primary key, 19 Aug 2026".
KEY_COLUMNS = ("datetime_jst", "source")
AUTHORITATIVE_SOURCE = "hepco_monthly_areajukyu"

# Every column parse_monthly_demand reads. The point of naming them here is that
# every read below is a `.get()`, and a `.get()` on a renamed column returns
# None, which _to_float turns into NULL, which loads clean. That is the 20->22
# break, in this file. Row 3 of the table in errors.py exists for it.
REQUIRED_DEMAND_COLUMNS = (
    "DATE", "TIME", "エリア需要", "太陽光発電実績", "風力発電実績", "合計",
)

REQUIRED_WEATHER_KEYS = (
    "time", "temperature_2m", "relative_humidity_2m",
    "wind_speed_10m", "precipitation", "snowfall",
)


def _to_float(value):
    """Blank/missing cell -> None (NULL); a real number -> float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_monthly_demand(path):
    """Read the monthly エリア需給 file into canonical rows. No database.

    Split out of load_demand 2026-08-07 so parsing is testable without a
    connection -- which is most of what week 7's pytest work needs.
    """
    rows = []
    dropped = 0
    with open(path, encoding="cp932", newline="") as f:
        f.readline()                       # skip line 1: the 単位[MW平均] banner (skip exactly 1)
        reader = csv.DictReader(f)         # line 2 becomes the header

        # Header check before the first row, not during. Stripped the same way
        # the row keys are stripped below, or the '\r' on the last field name
        # reports itself as a missing column.
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED_DEMAND_COLUMNS if c not in header]
        if missing:
            raise SchemaChanged(f"{path}: header is missing {missing}; got {header}")

        for raw in reader:
            # strip whitespace off keys and values (guards the '\r'/trailing-space gotcha)
            row = {(k.strip() if k else k): (v.strip() if v else v)
                   for k, v in raw.items()}
            if not row.get("DATE"):        # ~48 trailing all-comma rows -> empty DATE
                dropped += 1
                continue
            try:
                dt = datetime.strptime(f"{row['DATE']} {row['TIME']}", "%Y/%m/%d %H:%M")
            except (KeyError, TypeError, ValueError) as exc:
                # An unparseable row is a shape complaint, not a lost day.
                raise SchemaChanged(
                    f"{path}: unparseable DATE/TIME "
                    f"{row.get('DATE')!r} {row.get('TIME')!r}"
                ) from exc
            solar = _to_float(row.get("太陽光発電実績"))
            wind = _to_float(row.get("風力発電実績"))
            rows.append({
                "datetime_jst":    dt.strftime("%Y-%m-%d %H:%M"),  # canonical: zero-padded, space
                "demand_mw":       _to_float(row.get("エリア需要")),      # NO x10, already MW
                "solar_mw":        solar,
                "wind_mw":         wind,
                # Derived, not read: the monthly file publishes the two parts and
                # no total, while the daily file publishes the total and no parts.
                # wind_solar_mw is the one column both tracks can fill, which is
                # what makes the two-track agreement check answerable on
                # renewables at all. Not in REQUIRED_DEMAND_COLUMNS: nothing is
                # read for it.
                #
                # None when either part is missing, because None + float raises.
                # The *rule* -- that a monthly row may not carry a total without
                # its parts -- is enforced by the schema's monthly-scoped CHECK,
                # not here. A blank in col 13 or 15 therefore aborts the load
                # rather than storing a half-formed row, in the same spirit as
                # ROWS_PER_DAY = 47 being asserted exactly rather than as a floor.
                "wind_solar_mw":   None if (solar is None or wind is None) else solar + wind,
                "supply_total_mw": _to_float(row.get("合計")),
            })
    return rows, dropped


def _prepare(table, rows, source):
    """Validate rows and build the payload tuples. Shared by both writers.

    The empty check earns its place twice over. For merge, no rows means the
    fetch failed silently. For replace, no rows means deleting a month and
    putting nothing back -- the loudest possible case of the rule that a
    delete must be a subset of what the insert can supply. fetch() guarantees
    it raises rather than returning [], but a loader that silently accepts an
    empty list is one refactor away from being a truncation.

    Still ValueError, not SchemaChanged: this is a loader invariant about its
    own arguments, not a claim about what a source file looks like. The header
    check in parse_monthly_demand is what speaks for the file. main()'s row-4
    block is what stops that ValueError reaching the driver as a skip.

    Rows are dicts, not tuples, so the column list comes from the data and
    this stays source-agnostic: a tuple carries no column names and would need
    one hardcoded shape per source.
    """
    if not rows:
        raise ValueError(f"{table}: refusing to run with no rows")

    columns = sorted(rows[0])
    if any(sorted(r) != columns for r in rows):
        raise ValueError(f"{table}: rows have inconsistent keys")
    if "source" in columns:
        raise ValueError("source is stamped by the loader, not the source module")

    payload = [tuple(r[c] for c in columns) + (source,) for r in rows]
    return columns, payload


def _insert(conn, table, columns, payload, tail=""):
    """Shared: assemble the INSERT and run it. Returns rows actually written."""
    insert_cols = columns + ["source"]
    placeholders = ", ".join("?" * len(insert_cols))
    sql = (f"INSERT INTO {table} ({', '.join(insert_cols)}) "
           f"VALUES ({placeholders}){tail}")
    return conn.executemany(sql, payload).rowcount


def _month_window(rows):
    """The half-open [start, end) span of the single calendar month in `rows`.

    datetime_jst is fixed-width ISO TEXT, so the first seven characters are the
    month and no parsing is needed to group by it. Raising on more than one
    month is the guard that keeps the DELETE honest: a mixed-month payload
    would make "the month being replaced" ambiguous, and the loader would pick
    one and quietly orphan the rest.
    """
    months = {r[KEY_COLUMN][:7] for r in rows}
    if len(months) != 1:
        raise ValueError(f"month scope needs exactly one month, got {sorted(months)}")
    scope = months.pop()
    year, mon = int(scope[:4]), int(scope[5:7])
    start = f"{scope}-01 00:00"
    end = (f"{year + 1}-01-01 00:00" if mon == 12
           else f"{year}-{mon + 1:02d}-01 00:00")
    return scope, start, end


def replace_rows(conn, table, rows, source, *, day=None):
    """Insert dict-rows into `table`, replacing this source's rows in one span.

    Scope is the caller's decision because only the caller knows its cadence.
    day=None replaces one calendar month, derived from the rows -- the monthly
    track's reload. day=<date> replaces one day, which is what forward capture
    needs.

    Two things scope the DELETE, and both are load-bearing:

    Time. Month-scoping landed 2026-08-21 and unblocks the 28-file backfill:
    the previous whole-table DELETE would have had each file wipe the previous
    27. It is also the ghost collector merge_rows depends on -- a retracted
    period leaves a row merge cannot delete, and the month window is what
    finally removes it. Note this deliberately breaks the stricter form of the
    module rule: the window can be larger than what the insert refills, and for
    a retraction that is the entire point.

    Source. Mandatory since the composite key, not defensive. Under
    (datetime_jst, source) a daily row and a monthly row legitimately share a
    timestamp, so a DELETE filtered on time alone destroys the other track --
    and the daily track is the unrecoverable one.
    """
    columns, payload = _prepare(table, rows, source)

    if day is None:
        scope, start, end = _month_window(rows)
    else:
        # Half-open window. datetime_jst is fixed-width ISO TEXT, so
        # lexicographic order is chronological order -- the property that
        # made the TEXT key safe, leaned on here and in _month_window.
        scope = day.isoformat()
        start = f"{scope} 00:00"
        end = f"{(day + timedelta(days=1)).isoformat()} 00:00"

    with conn:                             # one transaction: DELETE + INSERT together
        deleted = conn.execute(
            f"DELETE FROM {table} "
            "WHERE source = ? AND datetime_jst >= ? AND datetime_jst < ?;",
            (source, start, end),
        ).rowcount
        _insert(conn, table, columns, payload)

    logger.info("%s: deleted %s, inserted %s (%s, scope=%s)",
                table, deleted, len(payload), source, scope)


def merge_rows(conn, table, rows, source):
    """Fragment append: INSERT with conflict handling, no DELETE.

    For a source that holds part of a key range rather than all of it. The
    daily feed is 47 rows of a 48-period day, so it must not delete the day:
    the 23:30 row it cannot supply came from the monthly file and has to
    survive the run.

    Cross-source precedence used to live here, in a WHERE on the DO UPDATE.
    It is gone as of 2026-08-21 and this is the reason: under the composite key
    a conflict can only occur when the two rows carry the same source, so the
    guard was unreachable. Monthly no longer overwrites daily because the two
    no longer collide -- they coexist, which is what the fork was for. Query-time
    precedence now belongs to a view, in one place, rather than to the loader.

    What survives is the idempotency guarantee: re-running a source over its own
    rows refreshes them and writes nothing new.

    Nothing here deletes, so the table can only grow. Ghost rows -- a
    retraction, a corrected short file -- die at month grain when the
    month-scoped replace_rows reloads over them.
    """
    columns, payload = _prepare(table, rows, source)
    if KEY_COLUMN not in columns:
        raise ValueError(f"{table}: merge needs {KEY_COLUMN} to resolve conflicts")

    # Update every column the rows carry except the key columns -- setting a key
    # to itself is a no-op. The conflict target must name the key's column set
    # exactly or SQLite raises, which is the behaviour wanted: a schema change
    # that moves the key should stop the loader, not be absorbed by it.
    assignments = ", ".join(f"{c} = excluded.{c}"
                            for c in columns if c not in KEY_COLUMNS)
    tail = f" ON CONFLICT({', '.join(KEY_COLUMNS)}) DO UPDATE SET {assignments}"

    with conn:
        written = _insert(conn, table, columns, payload, tail)

    logger.info("%s: %s of %s rows written (%s, merge)",
                table, written, len(payload), source)


def load_demand(conn, path):
    rows, dropped = parse_monthly_demand(path)
    replace_rows(conn, "area_demand", rows, AUTHORITATIVE_SOURCE)
    logger.info("area_demand: dropped %s blank rows", dropped)


def load_weather(conn, path):
    # Third write strategy in this module, deliberately: neither replace_rows
    # nor merge_rows. weather_hourly has no source column, because there is
    # one weather source and no provenance question -- so there is nothing for
    # merge's guard to compare and nothing for replace's stamp to record.
    # Inconsistent on purpose; revisit when openmeteo.py becomes a fetcher.
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    try:
        h = data["hourly"]                 # parallel arrays: time[], temperature_2m[], ...
    except (KeyError, TypeError) as exc:
        raise SchemaChanged(f"{path}: no 'hourly' object") from exc

    missing = [k for k in REQUIRED_WEATHER_KEYS if k not in h]
    if missing:
        raise SchemaChanged(f"{path}: hourly is missing {missing}")

    # zip() stops at the shortest array without complaining, so a renamed or
    # truncated series would silently shorten the month. Same failure mode as
    # the demand header, same row of the table.
    lengths = {k: len(h[k]) for k in REQUIRED_WEATHER_KEYS}
    if len(set(lengths.values())) != 1:
        raise SchemaChanged(f"{path}: hourly arrays disagree in length: {lengths}")

    rows = []
    for t, temp, hum, wind, prec, snow in zip(
        h["time"],
        h["temperature_2m"],
        h["relative_humidity_2m"],
        h["wind_speed_10m"],
        h["precipitation"],
        h["snowfall"],
    ):
        # 'T' -> ' ' via parse+reformat, so it matches the demand key format exactly
        datetime_jst = datetime.fromisoformat(t).strftime("%Y-%m-%d %H:%M")
        rows.append((datetime_jst, temp, hum, wind, prec, snow))
    if not rows:
        raise ValueError("weather_hourly: refusing to run with no rows")

    # Scoped, 2026-08-18. This was `DELETE FROM weather_hourly;` -- the third
    # unscoped delete in the module, after replace_rows(day=None) and the
    # original one it replaced. Harmless only while the table holds a single
    # month: the first second month of ERA5 would have destroyed the first on
    # load. The span comes from the rows being written, so the delete is a
    # subset of what the insert supplies by construction, and the same
    # fixed-width-ISO-TEXT ordering that scopes replace_rows scopes this.
    # Inclusive, not half-open, because the endpoints are the keys themselves
    # rather than a calendar boundary.
    keys = [r[0] for r in rows]
    first, last = min(keys), max(keys)     # min/max, not [0]/[-1]: sorted input is
                                           # an assumption about the file, not a fact
    with conn:
        deleted = conn.execute(
            "DELETE FROM weather_hourly WHERE datetime_jst >= ? AND datetime_jst <= ?;",
            (first, last),
        ).rowcount
        conn.executemany(
            "INSERT INTO weather_hourly "
            "(datetime_jst, temperature_c, relative_humidity_pct, wind_speed_kmh, "
            " precipitation_mm, snowfall_cm) "
            "VALUES (?, ?, ?, ?, ?, ?);",
            rows,
        )
    logger.info("weather_hourly: deleted %s, inserted %s (scope=%s..%s)",
                deleted, len(rows), first, last)
