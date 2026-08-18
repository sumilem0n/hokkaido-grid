"""Exceptions this pipeline can fail with.

Hoisted from hepco_daily 2026-08-07: openmeteo needs the same two types, and
a source module importing them from a sibling source module is the wrong
direction -- sources are peers, not a hierarchy.


FAILURE TABLE
-------------
The contract. Every raise site and every except block implements a row. A new
failure that does not fit a row changes the table first and the code second.

  what happened               exception             caller does      exit
  --------------------------  --------------------  ---------------  ----------------
  the network failed, or the  SourceTransientError  retry with       75
  file arrived intact but                           backoff, then    (EX_TEMPFAIL)
  incomplete                                        escalate

  the day is outside the      SourceUnavailable     skip it, the     69
  ~2-day retention tail                             loop continues   (EX_UNAVAILABLE)

  the file is not the file    SchemaChanged         halt the run     65
  we expect                                                          (EX_DATAERR)

  anything else               (no type of ours)     halt the run     70
                                                                     (EX_SOFTWARE)

The fourth row is residual and deliberate: a failure we never thought about has
to fail closed, not skip. Backoff and escalation live in the caller -- cron
today, the week 6 backfill driver later. This module only names the cases.
ConfigError sits outside the table and exits 78/EX_CONFIG: it fails before any
source is touched.

Nothing in the table uses 0, 1 or 2. Those belong to the interpreter -- 1 for an
unhandled exception, 2 for argparse's usage error -- and a driver that read 1 as
"skip this day" would read every stray ValueError, sqlite3.OperationalError on a
locked database, and plain bug as a day that was merely gone. That is the same
argument that kept ConfigError off argparse's 2, applied to every row instead of
one of them. Row 4 catches most of it; moving skip off 1 is what makes a 1 that
still escapes mean something on its own.


SIBLINGS, NOT SUBCLASSES
------------------------
SchemaChanged is a sibling of SourceUnavailable, not a subclass, and the reason
is row 2.

The backfill loop is `except SourceUnavailable: continue` -- that is row 2
working as designed. `except Parent` catches every child, and that is the only
thing inheritance does for exceptions. So if SchemaChanged inherited from
SourceUnavailable, that same `continue` would swallow it and row 3 would never
run. The backfill would not halt on the 20->22 column break. It would walk past
it, `.get()` a column name that no longer exists, and write NULL -- or 水力 --
into the curtailment column for twelve months. Every number plausible, nothing
raised, nothing in the log, and no way to tell afterwards which months are real.

Subclassing would be right if skip were the correct fallback for anything more
specific than SourceUnavailable. Here it is the opposite: the more specific case
is the more serious one. Flat, so the two cannot be caught together by accident.
tests/test_errors.py asserts exactly that, because it is the one property a
refactor can break without breaking anything that runs.

No shared project base class either -- all four inherit Exception directly. A
base would only earn its place if something wanted to catch all four at once,
and main() wants the reverse: four different exit codes.

requests.exceptions is deep and multiply-inherited -- RequestException(IOError),
ConnectTimeout(ConnectionError, Timeout), MissingSchema(RequestException,
ValueError) -- because a library cannot see its callers' except clauses and has
to land in the ones they already wrote; ours is flat because it has one caller
and we can edit it.
"""


class SourceTransientError(Exception):
    """Row 1. The fetch failed for a reason that may resolve on a later attempt.

    Includes a file that arrived intact but incomplete: HEPCO publishes before
    the day's last periods have closed, leaving placeholder rows. Retrying is
    the only way to get them, so a partial day leaves as this rather than as a
    permanent failure -- even though it means a day that never backfills will
    retry until the file drops out of retention and the 404 branch calls it
    what it is.
    """


class SourceUnavailable(Exception):
    """Row 2. The data is gone. Past retention, unrecoverable. Skippable.

    Narrowed 2026-08-18. This used to carry schema complaints as well, on the
    grounds that both meant "do not retry". They do. But they do not mean the
    same thing to the loop, which is what the exception type is for -- see
    SchemaChanged and the note above.

    `status_code` is set when the refusal came from HTTP, and is None for every
    other case. fetch.get_text() cannot decide what a 404 means -- that depends
    on the day's age against retention, which only the source module knows --
    so it attaches the number and lets the caller classify.
    """

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class SchemaChanged(Exception):
    """Row 3. The file is not the file we expect. Nothing is lost; the shape moved.

    No header found, wrong demand column, unparseable rows, a row count that
    cannot be right, values outside the plausible band.

    Halts rather than skips because the failure is not about one day. Whatever
    changed the header changed it for every file after it, so a loop that skips
    this day either meets it 300 more times or -- the case that matters -- does
    not meet it at all and quietly writes the wrong column.

    Raise sites, all of them previously SourceUnavailable: _find_header,
    _resolve_demand_col, the unparseable-row re-raise in fetch(), the row-count
    check, and the bounds check in _parse_row(). Plus, new, the header check in
    load.parse_monthly_demand and the key/length checks in load.load_weather.

    No status_code. A schema complaint has no HTTP number to report, and the
    one on SourceUnavailable only exists because retention classification needs
    it. If this ever needs one, that is a signature change, not a default.
    """


class ConfigError(Exception):
    """config.toml is missing, unreadable, or holds a value that cannot be used.

    Outside the table: raised before any source is touched, so none of retry,
    skip or halt applies. Exits 78/EX_CONFIG.
    """

