"""
Capstone loader — Hokkaido grid demand + Sapporo weather -> SQLite.

Loads two already-fetched files into sql/hokkaido.db (schema built on Day 1):
  data/hepco_demand_2026-04.csv     (HEPCO area actuals, CP932, CRLF, MW, 30-min) -> area_demand
  data/weather_sapporo_2026-04.json (Open-Meteo ERA5, JST, hourly)                -> weather_hourly

Run from the repo root (~/hokkaido-grid):
    uv run python hokkaido_grid/load.py

The paths below are relative to the working directory, which is why that
instruction exists. main.py anchors its paths to __file__ instead and does not
need it; this module keeps the constraint until it is given the same treatment.
"""

import csv
import json
import logging
import sqlite3
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DB_PATH = "sql/hokkaido.db"
DEMAND_CSV = "data/hepco_demand_2026-04.csv"
WEATHER_JSON = "data/weather_sapporo_2026-04.json"
KEY_COLUMN = "datetime_jst"
AUTHORITATIVE_SOURCE = "hepco_monthly_areajukyu"


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
        for raw in reader:
            # strip whitespace off keys and values (guards the '\r'/trailing-space gotcha)
            row = {(k.strip() if k else k): (v.strip() if v else v)
                   for k, v in raw.items()}
            if not row.get("DATE"):        # ~48 trailing all-comma rows -> empty DATE
                dropped += 1
                continue
            dt = datetime.strptime(f"{row['DATE']} {row['TIME']}", "%Y/%m/%d %H:%M")
            rows.append({
                "datetime_jst":    dt.strftime("%Y-%m-%d %H:%M"),  # canonical: zero-padded, space
                "demand_mw":       _to_float(row.get("エリア需要")),      # NO x10, already MW
                "solar_mw":        _to_float(row.get("太陽光発電実績")),
                "wind_mw":         _to_float(row.get("風力発電実績")),
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


def replace_rows(conn, table, rows, source, *, day=None):
    """Insert dict-rows into `table`, replacing what is already there.

    Scope is the caller's decision because only the caller knows its cadence.
    day=None replaces the whole table -- the monthly track's full reload.
    day=<date> replaces one day, which is what forward capture needs. Running
    the daily fetch through a whole-table DELETE would have wiped every other
    day in the table; same idempotency guarantee, two scopes.

    day=None will not survive the backfill: 28 monthly files loaded one at a
    time would each wipe the previous 27. Week 6 needs a month-scoped window,
    and merge_rows depends on it -- that reload is what collects the ghost
    rows merge cannot delete.
    """
    columns, payload = _prepare(table, rows, source)

    with conn:                             # one transaction: DELETE + INSERT together
        if day is None:
            deleted = conn.execute(f"DELETE FROM {table};").rowcount
        else:
            # Half-open window. datetime_jst is fixed-width ISO TEXT, so
            # lexicographic order is chronological order -- the property that
            # made the TEXT primary key safe, leaned on here for the first time.
            start = f"{day.isoformat()} 00:00"
            end = f"{(day + timedelta(days=1)).isoformat()} 00:00"
            deleted = conn.execute(
                f"DELETE FROM {table} WHERE datetime_jst >= ? AND datetime_jst < ?;",
                (start, end),
            ).rowcount
        _insert(conn, table, columns, payload)

    logger.info("%s: deleted %s, inserted %s (%s, scope=%s)",
                table, deleted, len(payload), source, day or "all")


def merge_rows(conn, table, rows, source):
    """Fragment append: INSERT with conflict handling, no DELETE.

    For a source that holds part of a key range rather than all of it. The
    daily feed is 47 rows of a 48-period day, so it must not delete the day:
    the 23:30 row it cannot supply came from the monthly file and has to
    survive the run.

    Precedence lives in the SQL, not in the schedule. Monthly overwrites
    daily; daily never overwrites monthly; either source refreshing its own
    rows always wins. Order-independent, so backfill order and cron drift
    converge on the same table.

    Nothing here deletes, so the table can only grow. Ghost rows -- a
    retraction, a corrected short file -- die at month grain when the
    month-scoped replace_rows reloads over them. Week 6, before the 30 Aug
    backfill; without it there is no collector.
    """
    columns, payload = _prepare(table, rows, source)
    if KEY_COLUMN not in columns:
        raise ValueError(f"{table}: merge needs {KEY_COLUMN} to resolve conflicts")

    # Update every column the rows carry, except the key -- setting the key
    # to itself is a no-op. AUTHORITATIVE_SOURCE and the column names are
    # module constants and schema, not input; same reason table is already
    # interpolated. Parameterising the constant would append it to all 47
    # payload tuples for no gain. The values stay parameterised.
    assignments = ", ".join(f"{c} = excluded.{c}"
                            for c in columns + ["source"] if c != KEY_COLUMN)
    tail = (
        f" ON CONFLICT({KEY_COLUMN}) DO UPDATE SET {assignments}"
        f" WHERE excluded.source = '{AUTHORITATIVE_SOURCE}'"
        f" OR {table}.source = excluded.source"
    )

    with conn:
        written = _insert(conn, table, columns, payload, tail)

    logger.info("%s: %s of %s rows written, %s left to a better source (%s, merge)",
                table, written, len(payload), len(payload) - written, source)


def load_demand(conn, path):
    rows, dropped = parse_monthly_demand(path)
    replace_rows(conn, "area_demand", rows, "hepco_monthly_areajukyu")
    logger.info("area_demand: dropped %s blank rows", dropped)


def load_weather(conn, path):
    # Third write strategy in this module, deliberately: neither replace_rows
    # nor merge_rows. weather_hourly has no source column, because there is
    # one weather source and no provenance question -- so there is nothing for
    # merge's guard to compare and nothing for replace's stamp to record.
    # Inconsistent on purpose; revisit when openmeteo.py becomes a fetcher.
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    h = data["hourly"]                     # parallel arrays: time[], temperature_2m[], ...
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
    with conn:
        conn.execute("DELETE FROM weather_hourly;")
        conn.executemany(
            "INSERT INTO weather_hourly "
            "(datetime_jst, temperature_c, relative_humidity_pct, wind_speed_kmh, "
            " precipitation_mm, snowfall_cm) "
            "VALUES (?, ?, ?, ?, ?, ?);",
            rows,
        )
    logger.info("weather_hourly: inserted %s rows", len(rows))


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    conn = sqlite3.connect(DB_PATH)
    try:
        load_demand(conn, DEMAND_CSV)
        load_weather(conn, WEATHER_JSON)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
