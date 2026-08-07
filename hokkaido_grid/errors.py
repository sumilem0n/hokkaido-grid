"""Exceptions shared by every source module.

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
    """


class SourceTransientError(Exception):
    """The fetch failed for a reason that may resolve on a later attempt.

    Includes a file that arrived intact but incomplete: HEPCO publishes
    before the day's last periods have closed, leaving placeholder rows.
    Retrying is the only way to get them, so a partial day leaves as this
    rather than as a permanent failure -- even though it means a day that
    never backfills will retry until the file drops out of retention and
    the 404 branch calls it what it is.
    """
