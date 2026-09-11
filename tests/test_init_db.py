"""cmd_init_db: applies sql/schema.sql to an empty database, refuses anything else.

Every test gets its own tmp_path, so every database here is a real file no other
test can see. The conftest fixtures don't fit this command: they hold an
in-memory connection, and cmd_init_db opens its own connection from a path.
"""

import sqlite3

import pytest

from hokkaido_grid.config import Config
from main import EXIT_OK, EXIT_REFUSED, build_parser, cmd_init_db


def run_init_db(db_path):
    """Call cmd_init_db the way main() does, pointed at db_path."""
    # A real Config, not a stand-in object: if the attribute cmd_init_db reads
    # is ever renamed, this breaks here instead of passing against a fake.
    # db_path is absolute, so Config._resolve hands it back unchanged.
    cfg = Config({"paths": {"db": str(db_path)}}, source="test_init_db")
    args = build_parser().parse_args(["init-db"])
    return cmd_init_db(args, cfg)


def fetch_all(db_path, sql):
    """Open db_path, run one query, close, return the rows."""
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


@pytest.fixture
def occupied_db(tmp_path):
    """A database file that already holds one table with three rows."""
    db_path = tmp_path / "occupied.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE keep_me (n INTEGER)")
        conn.executemany("INSERT INTO keep_me VALUES (?)", [(1,), (2,), (3,)])
        conn.commit()
    finally:
        conn.close()
    return db_path


# --- empty database: the schema goes in -----------------------------------------


def test_empty_database_returns_ok(tmp_path):
    assert run_init_db(tmp_path / "grid.db") == EXIT_OK


def test_empty_database_gets_every_schema_object(tmp_path):
    db_path = tmp_path / "grid.db"
    run_init_db(db_path)

    rows = fetch_all(db_path, "SELECT count(*) FROM sqlite_master")

    # 2 tables, 2 indexes SQLite builds for the non-INTEGER primary keys, 1 view:
    #   weather_hourly, sqlite_autoindex_weather_hourly_1,
    #   area_demand,    sqlite_autoindex_area_demand_1,
    #   area_demand_current
    # Update this number when schema.sql gains or loses an object.
    assert rows == [(5,)]


def test_success_message_goes_to_stdout(tmp_path, capsys):
    run_init_db(tmp_path / "grid.db")

    captured = capsys.readouterr()

    assert "schema applied from" in captured.out
    assert "schema applied from" not in captured.err


# --- occupied database: refused, untouched ---------------------------------------


def test_occupied_database_returns_refused(occupied_db):
    assert run_init_db(occupied_db) == EXIT_REFUSED


def test_refusal_leaves_existing_table_and_rows(occupied_db):
    run_init_db(occupied_db)

    rows = fetch_all(occupied_db, "SELECT n FROM keep_me ORDER BY n")

    assert rows == [(1,), (2,), (3,)]

def test_refusal_adds_no_objects(occupied_db):
    run_init_db(occupied_db)

    rows = fetch_all(occupied_db, "SELECT count(*) FROM sqlite_master")

    # keep_me and nothing else. 6 would mean the schema went in on top of it.
    assert rows == [(1,)]

def test_refusal_message_goes_to_stderr(occupied_db, capsys):
    run_init_db(occupied_db)

    captured = capsys.readouterr()

    assert "nothing was touched" in captured.err
    assert "nothing was touched" not in captured.out
