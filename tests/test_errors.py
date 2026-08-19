"""The failure table in errors.py, asserted.

Everything here is about the shape of the hierarchy rather than about any
behaviour, because the shape is what a refactor can change without breaking
anything that runs. A SchemaChanged that quietly became a subclass of
SourceUnavailable would pass every other test in the repo and lose twelve
months of data in the backfill.
"""

import pytest

import main
from hokkaido_grid.errors import (
    ConfigError,
    SchemaChanged,
    SourceTransientError,
    SourceUnavailable,
)

TABLE_TYPES = (SourceTransientError, SourceUnavailable, SchemaChanged)


def test_skip_does_not_catch_halt():
    """SchemaChanged is not a subclass of SourceUnavailable, so no
    `except SourceUnavailable` can catch it.

    Asserted through an except block rather than through issubclass so that
    the failure message names the consequence: the backfill loop is written
    `except SourceUnavailable: continue`, and a subclass relationship would
    make it swallow row 3. That loop is not exercised here -- this is a fact
    about the two classes, and it protects the loop only for as long as the
    loop still catches SourceUnavailable and not something wider.
    """
    with pytest.raises(SchemaChanged):
        try:
            raise SchemaChanged("header moved")
        except SourceUnavailable:                      # the shape the loop uses
            pytest.fail("skip caught halt: SchemaChanged is a subclass again")


@pytest.mark.parametrize("a", TABLE_TYPES)
@pytest.mark.parametrize("b", TABLE_TYPES)
def test_no_table_type_catches_another(a, b):
    """Siblings, not a hierarchy: no except block can shadow another."""
    assert (a is b) == issubclass(a, b)


def test_no_shared_base_below_exception():
    """A shared base would make `except ThatBase` collapse all three rows."""
    for cls in TABLE_TYPES + (ConfigError,):
        assert cls.__bases__ == (Exception,)


def test_exit_codes_are_distinct_and_not_the_interpreters():
    codes = [main.EXIT_OK, main.EXIT_HALT, main.EXIT_SKIP,
             main.EXIT_BUG, main.EXIT_TRANSIENT, main.EXIT_CONFIG]
    assert len(set(codes)) == len(codes)
    # 1 is an unhandled exception and 2 is argparse's usage error; both belong
    # to the interpreter, and a driver cannot tell ours from those.
    assert 1 not in codes and 2 not in codes
