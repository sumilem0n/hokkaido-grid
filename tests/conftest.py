"""Shared fixtures.

The database every test writes to is the real schema, not a hand-rolled CREATE
TABLE that agrees with the loader by construction. A test database built inside
the test file would drift from sql/schema.sql the first time a column is added
there, and the round-trip test would keep passing against the old shape.

Paths are anchored to __file__, the way main.py does it, so `pytest` works from
anywhere. load.py is the module that still requires the repo root as cwd; the
suite does not inherit that constraint.
"""

import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "sql" / "schema.sql"


@pytest.fixture
def conn():
    """An in-memory database with the project schema applied.

    Function-scoped: each test gets an empty database. replace_rows(day=None)
    deletes the whole table, so a shared connection would let one test's DELETE
    decide what another test sees.
    """
    connection = sqlite3.connect(":memory:")
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        yield connection
    finally:
        connection.close()
