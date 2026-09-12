"""Shared fixtures, one responsibility each.

The chain is connection -> schema -> dataset. Each fixture names the one
before it as a parameter; that parameter is the entire wiring mechanism, and
it is also what keeps them separate. Asking for `connection` runs only the
first, which is why an empty database is still reachable.

One connection travels the whole chain. sqlite3.connect(":memory:") makes a
private database per call, so a second connect() anywhere below would give the
later fixtures a different, empty database than the one the test holds.

Paths are anchored to __file__, the way config.py does it, so `pytest` works
from any working directory. load.py is the module that still requires the repo root as cwd; the suite does not inherit that constraint.
"""

import sqlite3
from pathlib import Path

import pytest

from hokkaido_grid.config import Config
from main import build_parser, cmd_init_db

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "sql" / "schema.sql"


@pytest.fixture
def connection():
    """An open connection to an empty in-memory database. No tables.

    Function-scoped, the default: a fresh database per test. Right for a
    database, and required here -- replace_rows(day=None) deletes a whole
    table, so a shared connection would let one test's DELETE decide what
    another test sees.
    """
    conn = sqlite3.connect(":memory:")
    try:
        yield conn
    finally:
        # After the yield is teardown. It runs on pass, fail and error,
        # because pytest resumes the generator with next() when the test is
        # done regardless of how it ended.
        conn.close()


@pytest.fixture
def schema(connection):
    """The same connection, with sql/schema.sql applied.

    executescript, not execute: schema.sql is many statements and execute()
    takes one.

    The real schema file, not a hand-rolled CREATE TABLE. A table written
    inside the suite would agree with the loader by construction and would
    drift from sql/schema.sql the first time a column is added there, leaving
    the round-trip test passing against the old shape.

    Returns rather than yields: it has nothing to undo. Closing the connection
    is fixture 1's job and happens after this one is finished with.
    """
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return connection


DAILY = "hepco_daily_jisseki"
MONTHLY = "hepco_monthly_areajukyu"

# Five rows, chosen to be legal under every CHECK in the table and to contain
# the one interesting shape: a timestamp held by both sources at once.
#
#   datetime_jst, demand_mw, solar_mw, wind_mw, wind_solar_mw, supply_total_mw, source
ROWS = [
    # Daily rows leave solar and wind NULL -- the daily file has no separate
    # columns for them, only the combined figure. The monthly-only derivation
    # CHECK is written to let that through.
    ("2026-01-15 00:00", 3120.0, None, None, 84.0, 3120.0, DAILY),
    ("2026-01-15 00:30", 3080.0, None, None, 91.0, 3080.0, DAILY),
    ("2026-01-15 01:00", 3040.0, None, None, 88.0, 3040.0, DAILY),

    # Same timestamp as the first row, other source. The primary key is
    # (datetime_jst, source), so both rows survive; which one a reader should
    # see is the question area_demand_current answers. A dataset without this
    # collision cannot exercise precedence at all.
    ("2026-01-15 00:00", 3125.0, 0.0, 210.0, 210.0, 3125.0, MONTHLY),

    # A different month, so a monthly load scoped to January has something it
    # is supposed to leave alone. Parts sum to the total within the 0.05
    # tolerance the CHECK allows, as every monthly row must.
    ("2026-02-01 12:00", 3900.0, 145.0, 260.0, 405.0, 3900.0, MONTHLY),
]


@pytest.fixture
def dataset(schema):
    """The same connection again, holding ROWS and nothing else.

    Committed, not left in an open transaction: a test that exercises code
    which rolls back should lose its own writes, not the baseline it started
    from.

    Every value here has to satisfy the table's CHECKs, which makes this
    fixture a second reader of the schema -- if a constraint is tightened in
    sql/schema.sql and these rows stop being legal, the failure is loud and
    lands here rather than in whatever test happened to run first.
    """
    schema.executemany(
        """
        INSERT INTO area_demand (
            datetime_jst, demand_mw, solar_mw, wind_mw,
            wind_solar_mw, supply_total_mw, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ROWS,
    )
    schema.commit()
    return schema

@pytest.fixture
def initialised_db(tmp_path):
    """A path to a database file that `init-db` built, by running `init-db`.

    Not part of the chain above, and cannot be. Those three share one
    in-memory connection; cmd_init_db opens its own connection from
    cfg.db_path, so an in-memory database handed to it would be ignored --
    it would build a second, private one and the test would be left holding
    the empty original.

    So this one deals in a file. tmp_path is fresh per test, which keeps the
    per-test isolation the chain gets from :memory:.

    The command is called, not imitated. Applying SCHEMA_PATH here by hand
    would be a second implementation of init-db that agrees with the real one
    only until someone changes it -- and SCHEMA_PATH is the schema fixture's,
    not this one's. cmd_init_db reads its own.

    Returns a path, not a connection: there is no open handle to close, so a
    test opens what it needs and owns the lifetime of it.
    """
    # No file is made here -- sqlite3.connect() inside cmd_init_db creates it,
    # which is the case init-db's "is anything already in there" check exists
    # to survive.
    db_path = tmp_path / "initialised.db"

    cfg = Config({"paths": {"db": str(db_path)}}, source="initialised_db fixture")
    args = build_parser().parse_args(["init-db"])
    cmd_init_db(args, cfg)

    return db_path
