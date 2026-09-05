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
from hokkaido_grid.gaps import find_gaps, format_report, has_actionable
from hokkaido_grid.load import load_demand, load_weather, merge_rows
from hokkaido_grid.sources import hepco_daily

SOURCE_NAME = "hepco_daily_jisseki"

# The four rows of the table in errors.py, plus config and one finding code.
# cron reads exit codes, not log levels, and the week 6 backfill driver will
# read the same set:
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

EXIT_GAPS_FOUND = 3   # a finding, not a failure: gaps exist that a
                      # fetch can still fill. Off 1 and 2 for the reason
                      # above; outside the table like EXIT_CONFIG, since no
                      # exception was raised and nothing went wrong.
                      # Out of numeric order deliberately -- it does not
                      # belong to the sysexits run above it. Note this is the
                      # first code a driver can meet that means neither "done"
                      # nor "stop", so the rule that an unrecognised code is
                      # halt now has something real to recognise: a driver
                      # that has not learned 3 halts on a successful report.

EXIT_REFUSED = 4      # init-db found objects already in the database and
                      # declined. Like 3, a finding rather than a failure --
                      # nothing raised, nothing broke, the command simply will
                      # not act on a database it did not create. Its own code
                      # rather than 65, because 65 is row 3's and means a source
                      # file changed shape underneath us. And unlike 3, the
                      # unrecognised-code-is-halt rule costs nothing here: halt
                      # is what a driver meeting this should do anyway.

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

    gaps = sub.add_parser("gaps", help="report missing periods in a loaded source")
    gaps.add_argument("source", help="source name, e.g. hepco_daily_jisseki")
    gaps.add_argument("start", help="YYYY-MM-DD")
    gaps.add_argument("end", help="YYYY-MM-DD")
    sub.add_parser("init-db", help="create the tables in an empty database")
    return parser


def cmd_daily(args, cfg):
    # Yesterday, not today: today's file exists but is still being written to,
    # so today can only ever yield a partial day. How long yesterday stays
    # reachable is hepco_daily.RETENTION_DAYS and is stated there, with the
    # measurements behind it -- restating it here was a second copy that had
    # already gone stale once.
    day = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)

    # Logged before the fetch so the traceback of whatever main() catches has
    # the day sitting directly above it. That is why the except blocks can live
    # in one place instead of once per command.
    log.info("daily: fetching %s", day)
    rows = hepco_daily.fetch(day, raw_dir=cfg.raw_dir)  

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

# A subcommand, not a shell script or a make target, for the same reason
# cmd_gaps reads RETENTION_DAYS out of hepco_daily instead of writing the
# number down again: the database path has one home, and that home is
# load_config. A script or a Makefile would have to work the path out a second
# way, and the second way is the one that goes stale when config.toml moves --
# with the failure being a schema quietly applied to the wrong file. Being in
# here also means --config already works, the log is already configured, and
# the exit code comes out of the same vocabulary as everything else rather than
# being whatever the last command in a recipe happened to return.
#
# sql/schema.sql is the only thing read. Migrations 001 and 002 are already
# folded into it -- the composite key and the precedence view are in the file
# below, not replayed from sql/migrations/. Those files are kept because they
# carry the reasoning (002 has the '<' vs '<=' trap and the 22 Aug
# verification), and reasoning is worth keeping whether or not anything
# executes it. They are a record, not a build step. The schema header says the
# file is regenerated from `.schema` and hand-headed after a migration; that
# regeneration is what keeps this command honest, and it is a human step.
#
# Refuse if anything is already there. This buys one property -- init-db can
# never be the thing that destroyed the database -- at the cost of every other
# property. There is no repair path: a database missing one table has to be
# fixed by hand. There is no re-apply: edit schema.sql and this command will
# not pick the change up, because the moment there is a table it stops. A
# rebuild means deleting the file yourself, which is a deliberate act, taken
# by someone who has looked at what is in there. That asymmetry is the whole
# design -- the cost is inconvenience, and the thing avoided is a DROP.
SCHEMA_PATH = Path(__file__).resolve().parent / "sql" / "schema.sql"


def cmd_init_db(args, cfg):
    # The file existing proves nothing: sqlite3.connect() creates one on the
    # spot, so this very line makes a file appear at a path that had none.
    # Testing for the file would therefore refuse on a database it had just
    # created itself. What is being asked is whether the database has contents,
    # and sqlite_master -- SQLite's own catalogue of tables, views, indexes and
    # triggers -- is where the contents are named. Empty catalogue, empty
    # database.
    log.info("init-db: %s", cfg.db_path)
    conn = sqlite3.connect(cfg.db_path)
    try:
        (objects,) = conn.execute("SELECT count(*) FROM sqlite_master;").fetchone()
        if objects:
            # stderr, not the log: whoever ran this is watching a terminal, and
            # the refusal is the whole output of the run.
            print(
                f"{cfg.db_path}: already holds {objects} "
                f"object{'' if objects == 1 else 's'}, nothing was touched",
                file=sys.stderr,
            )
            return EXIT_REFUSED

        # executescript, not execute: execute takes exactly one statement and
        # raises on a file holding several, so it cannot apply this one at all.
        # Splitting on ';' would be a third parser in the repo and a wrong one.
        # Three of the semicolons in schema.sql sit inside the header comment,
        # and '--' only comments out the rest of its own line -- cut there and
        # the text after the cut arrives as bare SQL. CREATE TABLE
        # weather_hourly is attached to one of those fragments, so the naive
        # splitter builds area_demand and the view, silently loses the weather
        # table, and reports four of its seven pieces as fine on the way past.
        #
        # No `with conn:` around it. executescript commits whatever transaction
        # is open before it starts, so the block would be decoration claiming
        # an atomicity it does not provide. A script that dies halfway leaves a
        # half-built database, which the check above will then refuse to touch
        # -- correctly, and that is the case the paragraph about the missing
        # repair path is describing.
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    finally:
        conn.close()

    print(f"{cfg.db_path}: schema applied from {SCHEMA_PATH}")
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


def cmd_gaps(args, cfg):
    log.info("gaps: %s %s..%s", args.source, args.start, args.end)
    conn = sqlite3.connect(cfg.db_path)
    try:
        # tail_days is passed by keyword, so this call does not depend on where
        # it sits in the signature. RETENTION_DAYS is read from the module that
        # measured it rather than restated here: gaps.py requires the argument
        # precisely so the number has one home, and a literal at this call site
        # would put a second copy back.
        found = find_gaps(
            conn,
            args.source,
            date.fromisoformat(args.start),
            date.fromisoformat(args.end),
            tail_days=hepco_daily.RETENTION_DAYS,
        )
    finally:
        conn.close()
    # stdout, not the log: this is a report for a person, and it should survive
    # being piped somewhere while the log goes wherever the config sends it.
    print(format_report(found))
    return EXIT_GAPS_FOUND if has_actionable(found) else EXIT_OK


COMMANDS = {
    "daily": cmd_daily,
    "monthly": cmd_monthly,
    "weather": cmd_weather,
    "gaps": cmd_gaps,
    "init-db": cmd_init_db,
}


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
