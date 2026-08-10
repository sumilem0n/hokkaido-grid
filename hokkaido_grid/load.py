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


def replace_rows(conn, table, rows, source, *, day=None):
    """Insert dict-rows into `table`, replacing what is already there.

    Scope is the caller's decision because only the caller knows its cadence.
    day=None replaces the whole table -- the monthly track's full reload.
    day=<date> replaces one day, which is what forward capture needs. Running
    the daily fetch through a whole-table DELETE would have wiped every other
    day in the table; same idempotency guarantee, two scopes.

    Rows are dicts, not tuples, so the column list comes from the data and this
    function stays source-agnostic: a tuple carries no column names and would
    need one hardcoded shape per source.
    """
    if not rows:
        # fetch() guarantees it raises rather than returning [], but a loader
        # that silently accepts an empty list is one refactor away from being
        # a truncation.
        raise ValueError(f"{table}: refusing to run with no rows")

    columns = sorted(rows[0])
    if any(sorted(r) != columns for r in rows):
        raise ValueError(f"{table}: rows have inconsistent keys")
    if "source" in columns:
        raise ValueError("source is stamped by the loader, not the source module")

    insert_cols = columns + ["source"]
    placeholders = ", ".join("?" * len(insert_cols))
    payload = [tuple(r[c] for c in columns) + (source,) for r in rows]

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
        conn.executemany(
            f"INSERT INTO {table} ({', '.join(insert_cols)}) VALUES ({placeholders});",
            payload,
        )
    logger.info("%s: deleted %s, inserted %s (%s, scope=%s)",
                table, deleted, len(payload), source, day or "all")


def load_demand(conn, path):
    rows, dropped = parse_monthly_demand(path)
    replace_rows(conn, "area_demand", rows, "hepco_monthly_areajukyu")
    logger.info("area_demand: dropped %s blank rows", dropped)


def load_weather(conn, path):
    # Deliberately not routed through replace_rows: weather_hourly has no source
    # column, because there is one weather source and no provenance question.
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
