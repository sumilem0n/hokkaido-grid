#!/usr/bin/env python
"""hokkaido-grid -- fetch one day of daily jisseki and load it.

Usage: python main.py [YYYY-MM-DD]   (default: yesterday)

argparse subcommands land week 5; sys.argv is one line and honest about being
temporary.
"""
import logging
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from hokkaido_grid.errors import SourceTransientError, SourceUnavailable
from hokkaido_grid.load import load_rows
from hokkaido_grid.sources import hepco_daily

# Anchored to the file, never to the working directory. sys.path[0] is the
# script's directory, which is what makes the imports above work from any cwd
# -- but data paths get no such help. open("sql/hokkaido.db") under cron
# resolves against cron's cwd and silently creates an empty database, which is
# where the three stray .db files came from.
REPO_ROOT = Path(__file__).resolve().parent
DB_PATH = REPO_ROOT / "sql" / "hokkaido.db"

SOURCE_NAME = "hepco_daily_jisseki"

log = logging.getLogger("main")


def main(argv):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Yesterday, not today: today's file exists but is still being written to,
    # and retention is two days, so yesterday is both complete and still there.
    day = date.fromisoformat(argv[1]) if len(argv) > 1 else date.today() - timedelta(days=1)

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

    conn = sqlite3.connect(DB_PATH)
    try:
        # scope=day, not the whole table. The monthly reload owns the table;
        # this owns one day of it.
        load_rows(conn, "area_demand", rows, SOURCE_NAME, day=day)
    finally:
        # with conn: manages the transaction, not the connection.
        conn.close()

    log.info("ok: %s, %d rows", day, len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
