"""The schema file itself loads, and the fixture built from it is usable.

Separate module rather than conftest.py: pytest imports conftest as a plugin
and does not collect tests from it, so a test function written there is silently
never run -- which is the same class of failure the rest of this suite exists to
catch.
"""


def test_schema_loads(schema):
    tables = {row[0] for row in schema.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table';")}
    assert {"area_demand", "weather_hourly"} <= tables
