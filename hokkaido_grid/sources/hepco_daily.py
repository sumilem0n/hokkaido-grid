"""Fetch one day of HEPCO Hokkaido area demand (jisseki) as half-hourly rows.

Retention on this feed is roughly two days, so a missed capture is permanent.
This module therefore never returns [] for a day it could not get: every
failure leaves by exception, classified as permanent or retryable.

File shape observed 2026-08-03 (for 2026-08-02):

    line 1  ファイル更新日,ファイル更新時間,対象年月日
    line 2  20260802,23:42:44,20260802
    line 3  日付,時間コマ,時間帯_自,時間帯_至,エリア総需要量(kWh),
            エリア総発電量(kWh),エリア風力・太陽光発電量(kWh)
    line 4  20260802,1,0:00,0:30,1193000,1338500,165000

Two banner lines, then the header. Dates are %Y%m%d with no separators, not
the slashed form the plan assumed. Both measurement columns carry their unit
in the name -- see _resolve_col.

That same file was generated at 23:42:44 and uploaded at 23:59:03, before its
last period (時間コマ 48, 23:30-24:00) had closed, and was never rewritten. The
row exists with its date, index and both boundary times filled in and all
three measurement columns empty, at every age the file was reachable. So a
complete daily file is 47 rows, not 48, and the missing period comes from the
monthly file. Retention is two days: today and yesterday, one shot per day.

エリア総発電量(kWh) is in the header and deliberately NOT mapped (2026-08-22).
It is total area generation; area_demand.supply_total_mw is the monthly file's
合計 (col 21), a different quantity. Mapping one into the other would make a
column mean two things depending on which loader wrote the row -- the same
failure the wind/solar fork was decided to avoid. Recorded in FIELDS.md.
"""

import csv
import datetime
import io
import re

import requests

from hokkaido_grid.errors import SourceTransientError, SourceUnavailable

BASE_URL = "https://denkiyoho.hepco.co.jp/area/data/{stamp}_hokkaido_jisseki.csv"

# Retention boundary in days, measured rather than guessed.
#   2026-08-01: 2026-07-31 (age 1) -> 200, 2026-07-28 (age 4) -> 404
#   2026-08-03: 2026-08-02 (age 1) -> 200, 2026-08-01 (age 2) -> 404
# The age-2 404 pins the edge: the window is today and yesterday only. An
# earlier draft assumed 3 and would have kept retrying a day that was
# already gone. One capture per day is the whole margin there is.
RETENTION_DAYS = 2

DATE_COL = "日付"
TIME_COL = "時間帯_自"

# Observed 20260802, not 2026/8/2. The plan assumed slashes; the file
# disagreed. strptime rejects anything else, which is what we want.
DATE_FORMAT = "%Y%m%d"

# The demand column is エリア総需要量(kWh) -- the unit is part of the name.
# Prefix and unit are checked separately: bracket width is punctuation and
# carries no meaning, while the unit governs KWH_PER_30MIN_TO_MW. Strict on
# the unit, tolerant of the punctuation -- strict where being wrong is
# silent, tolerant where it is cosmetic. A spurious raise on a feed with a
# two-day tail costs a day that cannot be refetched.
DEMAND_PREFIX = "エリア総需要量"
DEMAND_UNIT = "kWh"

# The daily file publishes wind and solar SUMMED into one column; the monthly
# file publishes them separately. Same prefix/unit treatment as demand, and
# the same equality-not-membership rule in _resolve_col.
WIND_SOLAR_PREFIX = "エリア風力・太陽光発電量"
WIND_SOLAR_UNIT = "kWh"

# The parenthesised unit at the tail of a header name, half- or full-width.
_UNIT_SUFFIX = re.compile(r"[(（]\s*([^)）]+?)\s*[)）]\s*$")


ROWS_PER_DAY = 47

# 47, not 48, and asserted exactly. The daily file is finalised before its
# last period closes -- 2026-08-02 was generated 23:42:44, uploaded 23:59:03,
# and never rewritten, leaving 時間コマ 48 (23:30-24:00) empty at every age it
# was reachable. That period is structurally unavailable from this feed and
# comes from the monthly file instead.
# Exact rather than a floor, because the assert is the detector: a 48-row day
# means HEPCO changed its publishing behaviour, and a count check that
# accepted "47 or more" would let that pass unremarked. One observation so
# far, so the first firing may be confirmation rather than a change.
EXPECTED_GAP_START = "23:30"  # 時間コマ 48, the period that never arrives

# jisseki opens with a two-line metadata banner, not the data header. The
# day-1 assumption that this file was banner-free was wrong, so the header
# is located by content rather than by a fixed offset -- a banner that grows
# a line should not need a code change. The search is bounded so a file that
# has become something else entirely fails instead of scanning to the end.
HEADER_SEARCH_LIMIT = 10

KWH_PER_30MIN_TO_MW = 500.0  # E[kWh] / 0.5 h = kW; / 1000 = MW

# Measured 2026-08-03 from area_demand: min 2440.0, max 3948.0 over 1440 rows
# (30 days). One month of shoulder season, so the band widens on both sides
# for the winter peak and summer trough the sample does not contain.
# The test these bounds must pass is that every other unit convention lands
# outside them: raw kWh ~1.2e6, double-converted ~5-8, 万kW either ~250-400
# or ~24000-40000. All four are rejected. Sanity check against the observed
# file: 1193000 kWh / 500 = 2386 MW at 00:00, inside the band.
MIN_MW = 1500.0
MAX_MW = 6000.0

# Floor is 0.0, not a demand-style lower bound: wind and solar legitimately
# produce nothing. That costs the second unit guard. A double-converted value
# lands near 2 MW -- inside this band -- where the same error on demand lands
# at ~5 and is rejected by MIN_MW. For this column the header assertion in
# _resolve_col is the ONLY guard against that class, where demand has two.
# Max observed 579000 kWh = 1158 MW (data/test_jisseki.csv, 2026-08-01,
# summer). Ceiling set above plausible installed capacity, not above the
# sample, because one summer day is not the annual maximum.
MIN_WIND_SOLAR_MW = 0.0
MAX_WIND_SOLAR_MW = 3000.0


def fetch(date, today=None):
    """Return one day of half-hourly demand for `date` (ROWS_PER_DAY rows).

    Each row is {"datetime_jst": "YYYY-MM-DD HH:MM", "demand_mw": float,
    "wind_solar_mw": float|None}, keyed to match area_demand so the loader
    needs no translation layer.

    `today` is injected rather than read from the clock so the retention
    branch is testable at any boundary without monkeypatching.

    Raises SourceUnavailable when the day is permanently gone or the file is
    not the file we expect. Raises SourceTransientError when another attempt
    may succeed. Never returns an empty list, and never lets a third
    exception type escape from row parsing.
    """
    today = today or datetime.date.today()
    url = BASE_URL.format(stamp=date.strftime("%Y%m%d"))

    try:
        resp = requests.get(url, timeout=(5, 30))
    except requests.RequestException as exc:
        # No HTTP response arrived at all: DNS, refused, dead network, stall.
        # Always transient-shaped, so no inspection needed to classify.
        raise SourceTransientError(f"request failed for {date}") from exc

    if resp.status_code == 404:
        # Same status, opposite meanings. Retention is a fact about HEPCO's
        # feed, so the module decides which. How loudly to react to each is
        # a fact about intent, and that stays with the caller.
        age = (today - date).days
        if age >= RETENTION_DAYS:
            raise SourceUnavailable(
                f"{date}: 404 at age {age}d, past retention, unrecoverable"
            )
        raise SourceTransientError(
            f"{date}: 404 at age {age}d, likely not yet published"
        )

    # A 403 is not transient. It has never fired, so it does not get its own
    # type today. Week 5 splits it if it ever does.
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        raise SourceTransientError(f"HTTP {resp.status_code} for {date}") from exc

    # Never resp.text. A byte that is not valid CP932 means the file changed,
    # and UnicodeDecodeError is the correct loud failure. errors="replace"
    # would turn a schema change into question marks that load cleanly.
    text = resp.content.decode("cp932", errors="strict")

    lines = text.splitlines(keepends=True)
    header_idx = _find_header(lines)
    reader = csv.DictReader(io.StringIO("".join(lines[header_idx:]), newline=""))
    fields = reader.fieldnames or []
    demand_col = _resolve_col(fields, DEMAND_PREFIX, DEMAND_UNIT)
    wind_solar_col = _resolve_col(fields, WIND_SOLAR_PREFIX, WIND_SOLAR_UNIT)

    rows = []
    pending = []
    # header_idx is 0-based, so the first data row is that line + 2 in the
    # file. Reporting the real file line matters: with a banner, an index
    # into the parsed rows no longer matches what you see in an editor.
    for lineno, raw in enumerate(reader, start=header_idx + 2):
        # The monthly file ends with 48 all-comma lines (FIELDS.md, day 1).
        # DictReader yields those as dicts of empty strings, and strptime("")
        # would raise a bare ValueError out of fetch() -- a third exception
        # type the caller cannot classify -- before the row-count check ever
        # runs to explain what happened. Drop them here, by structure rather
        # than by position, so the same code handles a file with none.
        if _is_blank(raw):
            continue
        # A row with its time skeleton filled in and no measurement is a
        # period HEPCO had not closed when it published. Distinct from the
        # all-comma padding above, which has nothing in it at all. The last
        # period is always this shape and is expected; anywhere else means
        # the file was caught genuinely mid-publication. Collect rather than
        # raise, so the message can name every missing period instead of
        # only the first one found.
        #
        # Demand alone gates this, not wind/solar. A row with demand present
        # and wind/solar blank therefore loads with a NULL rather than being
        # collected as pending -- knowingly, because a blank in that column
        # has never been observed at all (see _parse_row) and a spurious
        # raise costs a day that cannot be refetched.
        if not str(raw.get(demand_col) or "").strip():
            if str(raw.get(TIME_COL) or "").strip() != EXPECTED_GAP_START:
                pending.append(str(raw.get(TIME_COL) or f"line {lineno}").strip())
            continue
        try:
            rows.append(_parse_row(raw, demand_col, wind_solar_col))
        except (ValueError, AttributeError, TypeError) as exc:
            # Anything that survives the blank filter and still will not
            # parse is a file that changed shape: a reformatted date, a
            # ragged short row (missing keys arrive as None), a demand
            # field that is no longer a number. All schema-shaped, so they
            # leave as SourceUnavailable rather than as themselves.
            raise SourceUnavailable(f"line {lineno}: unparseable row {raw}") from exc

    # Before the count check, because it is the more specific complaint.
    # Reaching the count check with pending periods would report "got 47",
    # which is true and tells you nothing about why.
    if pending:
        raise SourceTransientError(
            f"{date}: {len(pending)} of {ROWS_PER_DAY} periods not yet "
            f"published ({', '.join(pending)}); source stamp "
            f"{_source_stamp(lines, header_idx)}"
        )

    # A partial file caught mid-publication produces a plausible-looking
    # short day. A second table stacked below the first lands here as a
    # count well over 47. And 48 means HEPCO started publishing the final
    # period -- a change worth being told about, not silently absorbed.
    if len(rows) != ROWS_PER_DAY:
        raise SourceUnavailable(
            f"{date}: expected {ROWS_PER_DAY} rows, got {len(rows)}"
            + (f" -- {EXPECTED_GAP_START} may now be published"
               if len(rows) == ROWS_PER_DAY + 1 else "")
        )

    return rows


def _find_header(lines):
    """Return the index of the data header line, skipping the banner."""
    # splitlines is safe here because no field in this file contains a
    # newline. If one ever does, this splits mid-record and the header
    # search fails loudly rather than reading half a row as a header.
    #
    # DEMAND_PREFIX alone, deliberately: this function locates a line, and
    # one measurement prefix plus both time columns is enough to identify
    # it. Requiring WIND_SOLAR_PREFIX too would make a dropped column report
    # as "no header found" -- blaming the wrong thing. _resolve_col is what
    # speaks for a column that is missing from a header that is present.
    for index, line in enumerate(lines[:HEADER_SEARCH_LIMIT]):
        fields = next(csv.reader([line]), [])
        if DATE_COL in fields and TIME_COL in fields:
            if any(f.startswith(DEMAND_PREFIX) for f in fields):
                return index
    preview = [line.strip() for line in lines[:HEADER_SEARCH_LIMIT]]
    raise SourceUnavailable(
        f"no header with {DATE_COL}, {TIME_COL}, {DEMAND_PREFIX}* in first "
        f"{HEADER_SEARCH_LIMIT} lines: {preview}"
    )


def _source_stamp(lines, header_idx):
    """Return the banner's value line, or '?' if there is no banner."""
    # The line above the header holds HEPCO's own publication timestamp.
    # In the partial-day message this is the number that tells you whether
    # retrying is worth anything: a stamp that has not moved since the last
    # attempt means the source has not republished.
    if header_idx == 0:
        return "?"
    return lines[header_idx - 1].strip()


def _resolve_col(fields, prefix, unit):
    """Return the column named `prefix`*, asserting its declared unit."""
    matches = [f for f in fields if f.startswith(prefix)]
    if len(matches) != 1:
        raise SourceUnavailable(
            f"expected exactly one {prefix}* column, found {matches}"
        )
    col = matches[0]
    match = _UNIT_SUFFIX.search(col.strip())
    found = match.group(1) if match else None
    # Equality, not membership. "kWh" is a substring of "kWh/h", so
    # `unit not in col` passed the one rename this guard exists to catch:
    # a figure already expressed per hour still gets divided by 500, and
    # every value lands at exactly double -- inside [MIN_MW, MAX_MW] for any
    # period below 3000 MW true demand, which is most of the night.
    # The old comment cited 万kW, which membership does catch. Picking the
    # example that works is how this survived review.
    #
    # This matters more for wind/solar than for demand: that column's floor
    # is 0.0, so its range check cannot reject a doubled value the way
    # MIN_MW does. Here the assertion is the only guard of its class.
    if found != unit:
        raise SourceUnavailable(
            f"{prefix} column is {col!r}, unit {found!r}, expected {unit!r}: "
            f"the /{KWH_PER_30MIN_TO_MW:.0f} conversion no longer holds"
        )
    return col


def _is_blank(raw):
    """True only when every field in the row is empty or whitespace."""
    # str() rather than .strip() directly: a ragged long row puts its
    # overflow under the None key as a list, and a list is not blank.
    return not any(str(value or "").strip() for value in raw.values())


def _parse_row(raw, demand_col, wind_solar_col):
    # strptime, not string surgery. 日付 arrives as 20260802; a hand-built
    # f"{y}-{m}-{d}" from the pieces would produce 2026-8-2 on a single-digit
    # month, which sorts after 2026-1-1 and before 2026-10-01 and never
    # errors. strptime fails loudly if the format ever changes again.
    d = datetime.datetime.strptime(raw[DATE_COL].strip(), DATE_FORMAT).date()

    # 時間帯_自 is the period start, so 24:00 never appears and there is no
    # day-boundary case to handle. 時間帯_至 on the last row does read 24:00.
    # Zero-padded to match datetime_jst exactly: these are TEXT keys and
    # compare as strings, so "0:00" would insert cleanly and never join.
    hour, minute = (int(part) for part in raw[TIME_COL].strip().split(":"))
    stamp = f"{d.isoformat()} {hour:02d}:{minute:02d}"

    # float() on "", "-" or a thousands separator raises ValueError. fetch()
    # catches it and re-raises as SourceUnavailable, because a demand field
    # that is not a number means the file changed. That is a narrower claim
    # than the general validation layer week 7 adds, and it does not replace
    # it: this only fires when the value cannot be read at all.
    mw = float(raw[demand_col]) / KWH_PER_30MIN_TO_MW

    # Raise, never clamp. A clamped value is a wrong number that passes every
    # downstream check.
    if not MIN_MW <= mw <= MAX_MW:
        raise SourceUnavailable(
            f"{stamp}: {mw:.1f} MW outside [{MIN_MW}, {MAX_MW}]"
        )

    # BLANK IS UNOBSERVED (2026-08-22). Every row of data/test_jisseki.csv
    # carries a value -- wind runs through the night, so this column never
    # reached zero and never showed whether HEPCO writes "0" or "". Blank is
    # therefore read as None: the absence of a claim, not a claim of zero
    # output. Reading unpublished as 0.0 would invent renewable generation
    # that did not happen; the reverse loses data that cannot be refetched.
    # If a blank is ever seen alongside a published demand figure, revisit --
    # it may belong in `pending` instead.
    raw_ws = str(raw.get(wind_solar_col) or "").strip()
    if raw_ws:
        ws = float(raw_ws) / KWH_PER_30MIN_TO_MW
        if not MIN_WIND_SOLAR_MW <= ws <= MAX_WIND_SOLAR_MW:
            raise SourceUnavailable(
                f"{stamp}: wind+solar {ws:.1f} MW outside "
                f"[{MIN_WIND_SOLAR_MW}, {MAX_WIND_SOLAR_MW}]"
            )
    else:
        ws = None

    # The key is emitted unconditionally, None or not. load.py's _prepare
    # takes its column list from sorted(rows[0]) and raises ValueError if any
    # row's keys differ, so a conditionally-present key would break every day
    # that contains one blank.
    return {"datetime_jst": stamp, "demand_mw": mw, "wind_solar_mw": ws}
