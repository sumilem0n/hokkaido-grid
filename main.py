#!/usr/bin/env python
"""hokkaido-grid -- capture and load Hokkaido grid demand data."""
import argparse
import logging
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from hokkaido_grid.config import load_config
from hokkaido_grid.errors import (
    ConfigError,
    SchemaChanged,
    SourceTransientError,
    SourceUnavailable,
)
from hokkaido_grid.load import load_demand, load_weather, merge_rows
from hokkaido_grid.sources import hepco_daily

SOURCE_NAME = "hepco_daily_jisseki"

# The four rows of the table in errors.py, plus config. cron reads exit codes,
# not log levels, and the week 6 backfill driver will read the same set:
# 75 -> sleep and retry, 69 -> next day, 65 and 70 -> stop.
#
# None of these is 0, 1 or 2. The interpreter owns those: 1 for an unhandled
# exception, 2 for argparse's usage error. Skip used to be 1, which meant a
# locked database, a stray ValueError out of _prepare, or any bug at all would
# have reached the driver wearing row 2's code and been walked past. The driver
# should treat an unrecognised code as halt for the same reason.
EXIT_OK = 0
EXIT_HALT = 65       # row 3: EX_DATAERR
EXIT_SKIP = 69       # row 2: EX_UNAVAILABLE
EXIT_BUG = 70        # row 4: EX_SOFTWARE, the residual
EXIT_TRANSIENT = 75  # row 1: EX_TEMPFAIL
EXIT_CONFIG = 78     # EX_CONFIG, kept distinct from argparse's own 2 for usage

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

    MONTHLY_HELP = (
        "load a monthly areajukyu CSV -- deletes and rewrites only the "
        "rows for the month this file covers. Other months and the daily "
        "track are untouched."
    )
    monthly = sub.add_parser("monthly", help=MONTHLY_HELP, description=MONTHLY_HELP)

    monthly.add_argument("path", type=Path, help="path to a monthly CSV")

    weather = sub.add_parser("weather", help="load a weather JSON file")
    weather.add_argument("path", type=Path, help="path to an Open-Meteo JSON file")

    return parser


def cmd_daily(args, cfg):
    # Yesterday, not today: today's file exists but is still being written to,
    # and retention is two days, so yesterday is both complete and still there.
    day = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)

    # Logged before the fetch so the traceback of whatever main() catches has
    # the day sitting directly above it. That is why the except blocks can live
    # in one place instead of once per command.
    log.info("daily: fetching %s", day)
    rows = hepco_daily.fetch(day)

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
    return EXIT_OK


def cmd_monthly(args, cfg):
    log.info("monthly: loading %s", args.path)
    conn = sqlite3.connect(cfg.db_path)
    try:
        load_demand(conn, args.path)
    finally:
        conn.close()
    return EXIT_OK


def cmd_weather(args, cfg):
    log.info("weather: loading %s", args.path)
    conn = sqlite3.connect(cfg.db_path)
    try:
        load_weather(conn, args.path)
    finally:
        conn.close()
    return EXIT_OK


COMMANDS = {"daily": cmd_daily, "monthly": cmd_monthly, "weather": cmd_weather}


def main(argv=None):
    args = build_parser().parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        # Logging is not configured yet -- its level comes from the file that
        # just failed to load. stderr directly.
        print(f"config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # One handler for all three commands, one block per row of the table in
    # errors.py. The order of the first three is cosmetic, because those types
    # are siblings and none can shadow another -- if that ever stops being true,
    # the fix is the hierarchy, not the ordering here. Row 4 must stay last,
    # and it is the one block whose position is load-bearing.
    try:
        return COMMANDS[args.command](args, cfg)
    except SourceTransientError:
        log.exception("transient: another attempt may succeed")
        return EXIT_TRANSIENT
    except SourceUnavailable:
        log.exception("permanent: this day will never arrive, skip it")
        return EXIT_SKIP
    except SchemaChanged:
        log.exception("schema changed: halting, every later file is suspect")
        return EXIT_HALT
    except Exception:
        # Row 4. Not defensive tidiness: without this the traceback goes to
        # stderr, which cron mails somewhere nobody reads, and the exit code is
        # 1. Here it lands in the log with everything else, and the driver gets
        # a code that means halt. Exception, not BaseException -- KeyboardInterrupt
        # and SystemExit are the operator's, and swallowing them is its own bug.
        log.exception("unhandled: not a case the failure table names, halting")
        return EXIT_BUG


if __name__ == "__main__":
    sys.exit(main())
