#!/usr/bin/env python
"""hokkaido-grid -- capture and load Hokkaido grid demand data."""
import argparse
import logging
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from hokkaido_grid.config import load_config
from hokkaido_grid.errors import ConfigError, SourceTransientError, SourceUnavailable
from hokkaido_grid.load import load_demand, load_weather, merge_rows
from hokkaido_grid.sources import hepco_daily

SOURCE_NAME = "hepco_daily_jisseki"

log = logging.getLogger("main")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="hokkaido-grid",
        description="Capture and load Hokkaido grid demand data.",
    )
    parser.add_argument(
        "--config", type=Path, default=None,
        help="path to config.toml (default: the one at the repo root)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    daily = sub.add_parser("daily", help="fetch one day of jisseki over HTTP and merge it")
    daily.add_argument("date", nargs="?", default=None, help="YYYY-MM-DD (default: yesterday)")

    monthly = sub.add_parser(
        "monthly",
        help="load a monthly areajukyu CSV -- REPLACES every row of the monthly "
             "source, not only that month's. Do not loop this until week 6 "
             "scopes replace_rows by month.",
    )
    monthly.add_argument("path", type=Path, help="path to a monthly CSV")

    weather = sub.add_parser("weather", help="load a weather JSON file")
    weather.add_argument("path", type=Path, help="path to an Open-Meteo JSON file")

    return parser


def cmd_daily(args, cfg):
    # Yesterday, not today: today's file exists but is still being written to,
    # and retention is two days, so yesterday is both complete and still there.
    day = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)

    try:
        rows = hepco_daily.fetch(day)
    except SourceTransientError:
        # 75 is EX_TEMPFAIL. The two exception types get different exit codes
        # because that distinction is the entire reason the hierarchy exists,
        # and cron reads exit codes, not log levels.
        log.exception("%s: transient, another attempt may succeed", day)
        return 75
    except SourceUnavailable:
        log.exception("%s: permanent, this day will never arrive", day)
        return 1

    conn = sqlite3.connect(cfg.db_path)
    try:
        # Merge, not replace: this file holds 47 of the day's 48 periods, so a
        # scoped delete would destroy the 23:30 row it cannot put back.
        # Precedence is in the SQL -- monthly rows survive this run.
        merge_rows(conn, "area_demand", rows, SOURCE_NAME)
    finally:
        # with conn: manages the transaction, not the connection.
        conn.close()

    log.info("ok: %s, %d rows", day, len(rows))
    return 0


def cmd_monthly(args, cfg):
    conn = sqlite3.connect(cfg.db_path)
    try:
        load_demand(conn, args.path)
    finally:
        conn.close()
    return 0


def cmd_weather(args, cfg):
    conn = sqlite3.connect(cfg.db_path)
    try:
        load_weather(conn, args.path)
    finally:
        conn.close()
    return 0


COMMANDS = {"daily": cmd_daily, "monthly": cmd_monthly, "weather": cmd_weather}


def main(argv=None):
    args = build_parser().parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        # Logging is not configured yet -- its level comes from the file that
        # just failed to load. stderr directly, and 78 is EX_CONFIG, kept
        # distinct from argparse's own exit 2 for a usage error.
        print(f"config error: {exc}", file=sys.stderr)
        return 78

    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    return COMMANDS[args.command](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
