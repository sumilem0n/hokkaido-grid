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

  the day is past the source  SourceUnavailable     skip it, the     69
  module's retention window                         loop continues   (EX_UNAVAILABLE)

  the file is not the file    SchemaChanged         halt the run     65
  we expect                                                          (EX_DATAERR)

  the file is shorter than    ShortFile             halt the run     65
  what it replaces                                                   (EX_DATAERR)

  anything else               (no type of ours)     halt the run     70
                                                                     (EX_SOFTWARE)

The fifth row is residual and deliberate: a failure we never thought about has
to fail closed, not skip. Backoff and escalation live in the caller -- cron
today, the week 6 backfill driver later. This module only names the cases.

Row 2 names no number. How wide the retention window is, and the measurements
behind it, live in hepco_daily.RETENTION_DAYS; each source has its own. A copy
here was a second place to update, and it went stale -- the table is the
contract, so a stale figure in it is worse than the same figure stale anywhere
else. Anything that needs the value reads it from the source module.

ConfigError sits outside the table and exits 78/EX_CONFIG: it fails before any
source is touched. EXIT_GAPS_FOUND is outside it too, and differently: 3
is not a failure at all but a finding -- the gaps report ran, and found
something a fetch can still fill. No exception is raised on that path, so it
implements no row. It is named here only so this file remains the whole
inventory of exit codes; a driver that reads codes must learn 3 or its
unrecognised-code rule will halt on a report that worked.
EXIT_REFUSED, 4, is the same kind: init-db declining a database it did not create.

Nothing in the table uses 0, 1 or 2. Those belong to the interpreter -- 1 for an
unhandled exception, 2 for argparse's usage error -- and a driver that read 1 as
"skip this day" would read every stray ValueError, sqlite3.OperationalError on a
locked database, and plain bug as a day that was merely gone. That is the same
argument that kept ConfigError off argparse's 2, applied to every row instead of
one of them. Row 5 catches most of it; moving skip off 1 is what makes a 1 that
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

No shared project base class either -- all five inherit Exception directly. A
base would only earn its place if something wanted to catch all five at once,
and main() wants the reverse: a separate except block for each.

requests.exceptions is deep and multiply-inherited -- RequestException(IOError),
ConnectTimeout(ConnectionError, Timeout), MissingSchema(RequestException,
ValueError) -- because a library cannot see its callers' except clauses and has
to land in the ones they already wrote; ours is flat because it has one caller
and we can edit it.
"""

# The five rows of the table above, plus config and two finding codes.
# cron reads exit codes, not log levels, and the week 6 backfill driver will
# read the same set:
# 75 -> sleep and retry, 69 -> next day, 65 and 70 -> stop.
#
# None of these is 0, 1 or 2. The interpreter owns those: 1 for an unhandled
# exception, 2 for argparse's usage error. Skip used to be 1, which meant a
# locked database, a stray ValueError out of _prepare, or any bug at all would
# have reached the driver wearing row 2's code and been walked past. The driver
# should treat an unrecognised code as halt for the same reason.
EXIT_OK = 0
EXIT_HALT = 65       # rows 3 and 4: EX_DATAERR
EXIT_SKIP = 69       # row 2: EX_UNAVAILABLE
EXIT_BUG = 70        # row 5: EX_SOFTWARE, the residual
EXIT_TRANSIENT = 75  # row 1: EX_TEMPFAIL
EXIT_CONFIG = 78     # EX_CONFIG, kept distinct from argparse's own 2 for usage

EXIT_GAPS_FOUND = 3   # a finding, not a failure: gaps exist that a
                      # fetch can still fill. Off 1 and 2 for the reason
                      # above; outside the table like EXIT_CONFIG, since no
                      # exception was raised and nothing went wrong.
                      # Out of numeric order deliberately -- it does not
                      # belong to the sysexits run above it. Note this is the
                      # first code a driver can meet that means neither "done"
                      # nor "stop", so the rule that an unrecognised code is
                      # halt now has something real to recognise: a driver
                      # that has not learned 3 halts on a successful report.

EXIT_REFUSED = 4      # init-db found objects already in the database and
                      # declined. Like 3, a finding rather than a failure --
                      # nothing raised, nothing broke, the command simply will
                      # not act on a database it did not create. Its own code
                      # rather than 65, because 65 is rows 3 and 4's and means a
                      # source file changed shape underneath us or came up short.
                      # And unlike 3, the unrecognised-code-is-halt rule costs 
                      # nothing here: 
                      # halt is what a driver meeting this should do anyway.


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

class ShortFile(Exception):
    """Row 4. The file is shorter than what it replaces.

    Halts the run, exit 65/EX_DATAERR.
    Not SchemaChanged, because the file's shape is intact and only its ending
    is missing. SchemaChanged halts on the grounds that every later file is
    suspect, and that is false for a short file: the next one is as likely to
    be complete as any other.
    """

class ConfigError(Exception):
    """config.toml is missing, unreadable, or holds a value that cannot be used.

    Outside the table: raised before any source is touched, so none of retry,
    skip or halt applies. Exits 78/EX_CONFIG.
    """
