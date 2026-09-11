-- forward_step.sql — forward step size and continuity class, one row per period.
-- REV 2, after reading FIELDS.md and gaps.py. Rev 1 is wrong in one place; the
-- correction is recorded below rather than silently applied.
--
-- QUESTION: for each row, how far forward is the next row, and is that distance
-- normal? EXPECTED STEP = 1800 seconds = 30 minutes. Every other distance is
-- given a name, not left as a number for the reader to interpret.
--
-- WHY FORWARD, AND WHY THIS IS NOT half_hour_delta.sql WITH A NEW FUNCTION NAME
-- Over one ordered series the forward step on row n and the backward step on row
-- n+1 are the same seconds. What differs is which row carries it:
--   LAG  attaches the break to the FIRST row after the hole — "is this row's
--        predecessor trustworthy?", the question you must answer before
--        subtracting. It guards arithmetic. That is half_hour_delta.sql's job.
--   LEAD attaches the break to the LAST GOOD ROW BEFORE the hole — "where does
--        coverage stop?" A statement about the loader, not about a demand value.
-- Forward is wanted here because the flagged row is the resume point: next_ts on
-- a break row is the timestamp the next fetch should target, and the row itself
-- is the last timestamp safe to record as loaded. LAG cannot hand you that
-- without a second lookup.
--
-- READS: area_demand_current (the precedence view), NOT area_demand.
-- FIELDS.md, "Two smaller decisions" (27 Aug), makes gaps the ONE documented
-- exemption from the view, and says in terms that it is "Not licence to bypass
-- the view anywhere else." This file is not exempt, and the reason it does not
-- need to be is that it asks the view's question, not gaps' question: gaps asks
-- WHICH SOURCE failed to supply a timestamp, which precedence is built to hide;
-- this asks how far apart the best-available rows are.
-- Two independent mechanical reasons as well:
--   a. Under PK (datetime_jst, source) the base table can hold two rows for one
--      half-hour. ORDER BY datetime_jst then ties, LEAD picks between them
--      arbitrarily, and the step alternates 0 / 1800 by tie-break order. Making
--      it deterministic means ORDER BY datetime_jst, source — at which point the
--      query measures source duplication, not elapsed time.
--   b. The view yields at most one row per timestamp by construction, so
--      ZERO_STEP cannot be produced by a second source. That is what makes the
--      zero case diagnostic rather than routine.
-- The view exposes a.source, and this query uses it — see EXCLUDED_SLOT.
-- No WHERE source = ... filter: moving_average.sql filters the base table to the
-- monthly source because it needs one grain; filtering here would drop the daily
-- August days and silently shorten the range this file claims to cover.
--
-- CORRECTION TO REV 1 — the 23:00 -> 00:00 step is not a gap.
-- Rev 1 classified all five August day boundaries as GAP with one period
-- missing. FIELDS.md, "The daily file is 47 rows, not 48": 23:30-24:00 is never
-- filled in the daily feed at any age, so gaps.py excludes that slot from the
-- expected calendar entirely — "Not a gap -- outside this source's domain."
-- Rev 1 invented five findings that the project has already decided are not
-- findings. EXCLUDED_SLOT is that decision, carried into this file under the
-- name gaps.py already uses for it.
-- Test: step = 3600 AND the row's own time is 23:00 AND source is
-- hepco_daily_jisseki. Using the 23:00 row's source as the proxy for "who owed
-- 23:30" is sound because the monthly source carries all 48 slots, so a 23:30
-- absent from the VIEW means no source held it, which means that day is
-- daily-only. Self-clearing: load the monthly archive for that month and 23:30
-- appears, the step becomes 1800, and the class disappears without an edit here.
--
-- CLASS VOCABULARY IS NOT gaps' VOCABULARY. Do not report a row of this output
-- as recoverable / unrecoverable / early_publication. Those need `today`,
-- `tail_days` and position within the expected calendar, none of which this
-- query has. GAP here means only "the next row is further away than one period
-- and the 23:30 exclusion does not explain it". Which of gaps' three classes it
-- is, is gaps' call.
--   Worked consequence: the 46-row day of FIELDS.md ("A 46-row day — OBSERVED
--   2026-08-25") is missing 23:00 as well as 23:30, so it surfaces here as GAP
--   from a 22:30 row with clock_periods_missing = 2.0, NOT as EXCLUDED_SLOT.
--   That is the wanted behaviour: this query flags the shape, gaps decides
--   whether it is early publication or a source change (open, 29 Aug).
--
-- ZERO STEP. Two adjacent rows sharing a timestamp give step_seconds = 0. Over
-- this view that cannot happen, so ZERO_STEP is not a data class, it is an
-- assertion failure: the precedence view or the PK has stopped holding. If one
-- appears, do not suspect the delta or the average — suspect the view, and read
-- migrations/002_precedence_view.sql first. The branch exists because "no such
-- rows today" is a fact about the data, not a property of the schema.
-- SHORT_STEP (0 < step < 1800) is the same kind of branch: no sub-30-minute feed
-- is loaded, nothing in the schema forbids one.
-- step_seconds cannot be negative; ORDER BY is ascending. No branch for it.
--
-- UNIT: integer epoch seconds, from strftime('%s', ...). Not float hours — 1800
-- is exact where 0.5 is not (cf. span_hours printing 23.4999999962747 in
-- moving_average.sql). strftime reads the JST string as if UTC, but the offset
-- cancels in a subtraction, and Japan has no DST, so no hour is duplicated.
--
-- RANGE: the whole of area_demand_current, unfiltered. The range is set by what
-- is loaded, not by this file, which is why statement 3 prints MIN / MAX /
-- COUNT — the output states its own window instead of trusting a date literal
-- that goes stale. At the 26 Aug 2026 run that window was April 2026 (1440
-- monthly rows) + seven August days (7 x 47 = 329 daily rows) = 1769.
--
-- BLINDNESS — why this supplements gaps and cannot replace it. gaps.py already
-- says it, in expected_periods: LAG/LEAD only see rows that exist, so they find
-- holes BETWEEN loaded rows and are structurally blind at both ends, and "LEAD
-- over area_demand_current is a cross-check on this module's output, never a
-- substitute for it." Concretely:
--   * The last row has no successor: END_OF_RANGE, never NORMAL. A hole AFTER
--     the final loaded row is invisible, exactly as a hole before the first row
--     is invisible to LAG. If the series ends 25 Aug and today is 9 Sep, this
--     reports END_OF_RANGE on the last row and says nothing about the fifteen
--     absent days. Row-to-row comparison has no calendar to miss.
--   * clock_periods_missing COUNTS CLOCK SLOTS, NOT EXPECTED SLOTS, and the
--     name says so. It overcounts by one for every day boundary crossed inside
--     daily-covered range, because it does not know 23:30 is not owed. The
--     skipped day below spans two boundaries: it prints 49.0 where gaps, using
--     slots_for(), counts 47 real missing periods. Read it as a magnitude, and
--     take counts from gaps.
--   * REAL division on purpose: a step that is not a multiple of 1800 shows a
--     fraction (a 45-minute step gives 0.5) instead of truncating to a clean
--     integer. Only meaningful on GAP rows; 0.0 on NORMAL, 1.0 on EXCLUDED_SLOT,
--     -1.0 on ZERO_STEP are artefacts of the formula, not counts.
--   * Blind to per-source coverage, by construction — that is exactly the
--     question the view hides and gaps reads the base table to answer.
--
-- COST: one pass over the view, one window, no extra table access.
--   The view's correlated NOT EXISTS is one covering-index lookup per row —
--   1769 of them, the same bill half_hour_delta.sql and moving_average.sql pay.
--   The window's ORDER BY datetime_jst is free: the view scans
--   sqlite_autoindex_area_demand_1, already in that order.
--   Expect USE TEMP B-TREE FOR ORDER BY, for the reason half_hour_delta.sql
--   records: a CTE hides the source ordering from the consumer, so the final
--   ORDER BY cannot reuse the index. REVERSED FROM REV 1, which avoided the CTE
--   by inlining the LEAD call into the CASE and paid for it in repetition. That
--   trade was defensible at four branches. EXCLUDED_SLOT makes six, and the
--   expression would appear eight times in a file whose whole purpose is to be
--   read at 00:35. Taking the temp b-tree instead — negligible at 1769 rows, and
--   the same cost the LAG file already accepted.
--
-- STATUS: NOT RUN AGAINST sql/hokkaido.db. Exercised 9 Sep 2026 against an
-- in-memory database built from schema.sql with eight hand-written rows, which
-- tests the SQL and the branch logic and nothing about the real data:
--   3600 s out of a daily 23:00        -> EXCLUDED_SLOT (1.0)      as designed
--   3600 s out of a MONTHLY 23:00      -> GAP (1.0)                source test works
--   5400 s out of a daily 22:30        -> GAP (2.0)                46-row shape, not absorbed
--   90000 s across the skipped 24th    -> GAP (49.0)               clock, not expected, count
--   last row                           -> END_OF_RANGE, NULL step
-- Plan on the fixture, confirming the COST note above as printed:
--   |--CO-ROUTINE stepped
--   |  |--CO-ROUTINE (subquery-6)
--   |  |  |--SCAN a USING INDEX sqlite_autoindex_area_demand_1
--   |  |  `--CORRELATED SCALAR SUBQUERY 5
--   |  |     `--SEARCH b USING COVERING INDEX sqlite_autoindex_area_demand_1 (datetime_jst=?)
--   |  `--SCAN (subquery-6)
--   |--SCAN stepped
--   `--USE TEMP B-TREE FOR ORDER BY
-- ZERO_STEP and SHORT_STEP were NOT exercised — the view cannot produce the
-- first, and no fixture row can produce the second without inventing a feed.
-- The counts below remain predictions. Do not stamp this file verified until
-- they are checked against the real database.
--   Predicted census at the 26 Aug shape (1769 rows, 8 runs, 7 breaks):
--     NORMAL 1761 | EXCLUDED_SLOT 5 | GAP 2 | END_OF_RANGE 1
--     ZERO_STEP 0 | SHORT_STEP 0
--   The 2 GAPs: April -> August (one large clock count), and the skipped 24th,
--   23:00 on the 23rd -> 00:00 on the 25th = 90000 s, clock 49.0, true 47.
--   Same 8 non-NORMAL rows LAG suppressed, on different rows: LAG loses the
--   first row of each run, LEAD the last. Rev 1 predicted GAP 7; that prediction
--   was wrong for the reason in CORRECTION, and is left here to be read.
--
-- No stored columns added, no schema change. If a class ever needs persisting,
-- that is a finding for FIELDS.md, not an ALTER at 00:35.

-- 1. Per-row forward step and class.
WITH stepped AS (
    SELECT datetime_jst,
           source,
           demand_mw,
           LEAD(datetime_jst) OVER w AS next_ts,
           LEAD(CAST(strftime('%s', datetime_jst) AS INTEGER)) OVER w
             - CAST(strftime('%s', datetime_jst) AS INTEGER) AS step_seconds
    FROM area_demand_current
    WINDOW w AS (ORDER BY datetime_jst)
),
classified AS (
    SELECT datetime_jst,
           source,
           demand_mw,
           next_ts,
           step_seconds,
           (step_seconds - 1800) / 1800.0 AS clock_periods_missing,
           CASE
             -- no successor: last row in the range, not a continuous series
             WHEN step_seconds IS NULL THEN 'END_OF_RANGE'
             -- the expected step: 1800 seconds = 30 minutes
             WHEN step_seconds = 1800  THEN 'NORMAL'
             -- duplicate timestamp: impossible through this view; see header
             WHEN step_seconds = 0     THEN 'ZERO_STEP'
             -- daily feed never carries 23:30; outside the source's domain
             WHEN step_seconds = 3600
                  AND source = 'hepco_daily_jisseki'
                  AND strftime('%H:%M', datetime_jst) = '23:00'
                                       THEN 'EXCLUDED_SLOT'
             WHEN step_seconds > 1800  THEN 'GAP'
             -- 0 < step < 1800; no sub-30-min feed loaded, schema allows one
             ELSE 'SHORT_STEP'
           END AS step_class
    FROM stepped
)
SELECT datetime_jst, source, demand_mw, next_ts,
       step_seconds, clock_periods_missing, step_class
FROM classified
ORDER BY datetime_jst;


-- 2. Class census. Window results cannot be grouped in the SELECT that computes
-- them (GROUP BY runs first), so the class is built in a CTE and counted outside
-- it — same shape as the coverage check in moving_average.sql.
WITH stepped AS (
    SELECT datetime_jst,
           source,
           LEAD(CAST(strftime('%s', datetime_jst) AS INTEGER)) OVER w
             - CAST(strftime('%s', datetime_jst) AS INTEGER) AS step_seconds
    FROM area_demand_current
    WINDOW w AS (ORDER BY datetime_jst)
),
classified AS (
    SELECT step_seconds,
           (step_seconds - 1800) / 1800.0 AS clock_periods_missing,
           CASE
             WHEN step_seconds IS NULL THEN 'END_OF_RANGE'
             WHEN step_seconds = 1800  THEN 'NORMAL'
             WHEN step_seconds = 0     THEN 'ZERO_STEP'
             WHEN step_seconds = 3600
                  AND source = 'hepco_daily_jisseki'
                  AND strftime('%H:%M', datetime_jst) = '23:00'
                                       THEN 'EXCLUDED_SLOT'
             WHEN step_seconds > 1800  THEN 'GAP'
             ELSE 'SHORT_STEP'
           END AS step_class
    FROM stepped
)
SELECT step_class,
       COUNT(*)                   AS rows,
       MIN(step_seconds)          AS min_step_seconds,
       MAX(step_seconds)          AS max_step_seconds,
       MAX(clock_periods_missing) AS max_clock_periods_missing
FROM classified
GROUP BY step_class
ORDER BY rows DESC;


-- 3. Range stamp. Prints the window statement 1 actually covered, so a saved
-- result set is self-describing and no date literal in this file can go stale.
SELECT MIN(datetime_jst) AS range_start,
       MAX(datetime_jst) AS range_end,
       COUNT(*)          AS rows
FROM area_demand_current;
