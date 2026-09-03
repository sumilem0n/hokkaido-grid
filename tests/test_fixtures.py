"""Tests on the fixtures, not on the project.

Both check that something is missing: no tables, no rows. If one fails, don't
change the expected number to match -- that just deletes the alarm. It means a
later fixture's work has moved into an earlier one, and the fix belongs in
conftest.py.

No other test can catch that. Everything else asks for `dataset` and would be
just as happy if all three fixtures were secretly one.
"""
def test_connection_is_empty(connection):
    n = connection.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    assert n == 0

def test_schema_has_no_rows(schema):
    n = schema.execute("SELECT count(*) FROM area_demand").fetchone()[0]
    assert n == 0
