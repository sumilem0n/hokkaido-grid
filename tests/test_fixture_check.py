import sqlite3


def test_initialised_db_holds_the_schema(initialised_db):
    conn = sqlite3.connect(initialised_db)
    try:
        rows = conn.execute("SELECT count(*) FROM sqlite_master").fetchall()
    finally:
        conn.close()
    assert rows == [(5,)]
