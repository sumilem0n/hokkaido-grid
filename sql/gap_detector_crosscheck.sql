-- gap_detector_crosscheck.sql — independent check on `main.py gaps`
--
-- Written 3 Sep 2026. Boundary-based coverage check over area_demand_current, kept as a
-- second opinion on gaps.py. The two implementations share no code: gaps.py walks an
-- expected-timestamp sequence per source and reports runs; this walks the rows that exist
-- and reports the seams between them. Agreement between them is evidence about the rule,
-- not about one implementation.
--
--
-- WHAT THIS QUERY RETURNS
--
-- Twelve boundaries over the view, for the range currently loaded:
--
--   prev_jst          next_jst          gap_minutes
--   2026-04-30 23:30  2026-08-06 00:00  139710.000000224   <- cross-source seam, see below
--   2026-08-06 23:00  2026-08-09 00:00  2939.99999977648
--   2026-08-09 23:00  2026-08-15 00:00  7259.99999977648
--   2026-08-15 23:00  2026-08-21 00:00  7259.99999977648
--   2026-08-21 23:00  2026-08-22 00:00  59.9999997764826   <- day boundary, nothing behind it
--   2026-08-22 23:00  2026-08-23 00:00  59.9999997764826   <- day boundary
--   2026-08-23 23:00  2026-08-25 00:00  1499.99999977648
--   2026-08-25 23:00  2026-08-26 00:00  59.9999997764826   <- day boundary
--   2026-08-26 23:00  2026-08-30 00:00  4379.99999977648
--   2026-08-30 23:00  2026-08-31 00:00  59.9999997764826   <- day boundary
--   2026-08-31 23:00  2026-09-01 00:00  59.9999997764826   <- day boundary
--   2026-09-01 23:00  2026-09-02 00:00  59.9999997764826   <- day boundary
--
-- Six of the twelve are pure artifact of the 47-row day. Five are real daily-series gaps.
-- One is the seam between sources.
--
--
-- WHAT gaps.py RETURNS FOR THE SAME WINDOW
--
--   $ python main.py gaps hepco_daily_jisseki 2026-08-06 2026-09-02
--   unrecoverable  2026-08-07 00:00 -> 2026-08-08 23:00  (  94 periods)
--   unrecoverable  2026-08-10 00:00 -> 2026-08-14 23:00  ( 235 periods)
--   unrecoverable  2026-08-16 00:00 -> 2026-08-20 23:00  ( 235 periods)
--   unrecoverable  2026-08-24 00:00 -> 2026-08-24 23:00  (  47 periods)
--   unrecoverable  2026-08-27 00:00 -> 2026-08-29 23:00  ( 141 periods)
--   5 gaps, 752 periods, 0 actionable
--
--
-- CONVERSION RULE
--
--   days    = (gap_minutes - 60) / 1440
--   periods = days * 47
--
-- The 60 comes off once per gap, not once per day: the boundary itself spans 23:00 -> 00:00,
-- and the only slot inside it is the 23:30 that never exists in a 47-row day. The 47 is the
-- same fact applied per whole missing day.
--
--   2940 -> (2940-60)/1440 = 2 days -> 94    matches 2026-08-07..08
--   7260 -> (7260-60)/1440 = 5 days -> 235   matches 2026-08-10..14
--   7260 -> (7260-60)/1440 = 5 days -> 235   matches 2026-08-16..20
--   1500 -> (1500-60)/1440 = 1 day  -> 47    matches 2026-08-24
--   4380 -> (4380-60)/1440 = 3 days -> 141   matches 2026-08-27..29
--                                     ----
--                                      752
--
-- The rule holds only while every gap runs 23:00 -> 00:00. A gap that starts or ends mid-day
-- breaks it silently — (minutes - 60) will not divide cleanly by 1440, and the periods figure
-- will drift from gaps.py rather than fail loudly. Non-integer days is the signal to stop and
-- look; so is any gap_minutes that is not a multiple of 30, which would mean an off-grid
-- timestamp rather than a missing row.
--
--
-- TWO STRUCTURAL DIFFERENCES — the outputs are not interchangeable
--
-- 1. A boundary detector cannot see the ends of the range. It only reports space between two
--    rows that exist, so a gap before the first row or after the last one is invisible to it
--    by construction. gaps.py takes an explicit start and end and checks against them, so it
--    can report a truncated head or tail. Do not read "twelve boundaries" as "twelve gaps in
--    the requested window" — this query has no requested window.
--
-- 2. This runs over the view, across both sources. gaps.py takes source as a required
--    parameter and runs one source at a time. That is why row 1 above exists here and will
--    never appear in gaps.py output: 2026-04-30 23:30 is a monthly row (48-row day, hence the
--    23:30), 2026-08-06 00:00 is where the daily series starts, and the 139710 minutes between
--    them is a seam between two sources rather than a hole in either. The 47-per-day rule does
--    not govern that span — neither day-shape convention applies across it — so it is excluded
--    from the 752 rather than converted. The honest reading of row 1 is 97 days with no
--    coverage from either source.
--
--
-- STATUS
--
-- The two agree exactly on all five daily gaps, in the same order, same day counts, same
-- period counts, same total of 752. That is two independent implementations of one rule
-- landing on the same answer, which is worth more than one implementation checked twice —
-- but it is still only evidence that the 47-row-day rule is applied consistently. If the rule
-- itself is wrong about HEPCO's day shape, both are wrong together and this file will not
-- catch it. See FIELDS.md for where the 47 comes from.

WITH stepped AS (
    SELECT
        datetime_jst,
        LAG(datetime_jst) OVER (ORDER BY datetime_jst) AS prev_jst,
        (julianday(datetime_jst)
         - julianday(LAG(datetime_jst) OVER (ORDER BY datetime_jst))
        ) * 1440 AS gap_minutes
    FROM area_demand_current
)
SELECT
    prev_jst,
    datetime_jst AS next_jst,
    gap_minutes,
    -- (minutes - 60) / 1440, guarded: only meaningful for 23:00 -> 00:00 boundaries.
    CAST(ROUND((gap_minutes - 60) / 1440) AS INTEGER)      AS missing_days,
    CAST(ROUND((gap_minutes - 60) / 1440) AS INTEGER) * 47 AS missing_periods
FROM stepped
WHERE prev_jst IS NOT NULL
  -- 30.001, not 30: julianday is floating point, so a clean 30-minute step can land a
  -- fraction above 30 and read as a gap. The threshold clears that noise by ten orders of
  -- magnitude and sits nowhere near the 60 that a real gap produces.
  AND gap_minutes > 30.001
ORDER BY datetime_jst;
