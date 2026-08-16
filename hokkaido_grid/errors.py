"""Exceptions this pipeline can fail with.

Hoisted from hepco_daily 2026-08-07: openmeteo needs the same two types, and
a source module importing them from a sibling source module is the wrong
direction -- sources are peers, not a hierarchy.
"""


class SourceUnavailable(Exception):
    """The data cannot be obtained now and retrying will not change that.

    This currently carries two distinct meanings that week 6 separates:

      1. The data is gone. Past retention, unrecoverable. This is the
         meaning the name describes.
      2. The file is not the file we expect. No header found, wrong demand
         column, unparseable rows, values outside the plausible band.
         Nothing is lost; the source changed shape. Week 6 names this
         SchemaChanged.

    Both are "do not retry", which is why one type is enough for now.
    When SchemaChanged arrives, cases (2) move to it: _find_header,
    _resolve_demand_col, the unparseable-row re-raise in fetch(), the
    row-count check, and the bounds check in _parse_row(). The retention
    branch stays here.

    `status_code` is set when the refusal came from HTTP, and is None for
    every other case. fetch.get_text() cannot decide what a 404 means -- that
    depends on the day's age against retention, which only the source module
    knows -- so it attaches the number and lets the caller classify. Optional
    with a None default so the existing raise sites, all of them schema
    complaints with no status to report, keep working unedited.
    """

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class SourceTransientError(Exception):
    """The fetch failed for a reason that may resolve on a later attempt.

    Includes a file that arrived intact but incomplete: HEPCO publishes
    before the day's last periods have closed, leaving placeholder rows.
    Retrying is the only way to get them, so a partial day leaves as this
    rather than as a permanent failure -- even though it means a day that
    never backfills will retry until the file drops out of retention and
    the 404 branch calls it what it is.
    """


class ConfigError(Exception):
    """config.toml is missing, unreadable, or holds a value that cannot be used."""
