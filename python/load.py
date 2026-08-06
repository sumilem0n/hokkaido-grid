

"""
Capstone loader — Hokkaido grid demand + Sapporo weather -> SQLite.

Loads two already-fetched files into sql/hokkaido.db (schema built on Day 1):
  data/hepco_demand_2026-04.csv     (HEPCO area actuals, CP932, CRLF, MW, 30-min) -> area_demand
  data/weather_sapporo_2026-04.json (Open-Meteo ERA5, JST, hourly)                -> weather_hourly

Run from the repo root (~/hokkaido-grid):
    uv run python python/load.py
"""

import csv
import json
import sqlite3
from datetime import datetime

import logging

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


def load_demand(conn, path):
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
            datetime_jst = dt.strftime("%Y-%m-%d %H:%M")   # canonical: zero-padded, space
            rows.append((
                datetime_jst,
                _to_float(row.get("エリア需要")),          # demand_mw   — NO x10, already MW
                _to_float(row.get("太陽光発電実績")),      # solar_mw
                _to_float(row.get("風力発電実績")),        # wind_mw
                _to_float(row.get("合計")),                # supply_total_mw
            ))
    with conn:                             # one transaction: DELETE + INSERT together
        conn.execute("DELETE FROM area_demand;")
        conn.executemany(
            "INSERT INTO area_demand "
            "(datetime_jst, demand_mw, solar_mw, wind_mw, supply_total_mw) "
            "VALUES (?, ?, ?, ?, ?);",
            rows,
        )
    logger.info("area_demand: inserted %s rows, dropped %s blank", len(rows), dropped)

def load_weather(conn, path):
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
