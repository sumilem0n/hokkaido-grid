-- trailing_mean_age.sql — 2-hour trailing mean of demand, gap-guarded, with row age.
--
-- READS: area_demand_current (the precedence view), NOT area_demand. Under
-- PK (datetime_jst, source) the base table can hold one monthly and one daily
-- row for the same half-hour; a frame over it would count that half-hour twice.
-- The two tracks have not overlapped yet, so the base table would look right
-- today and go wrong the first time they do.
--
-- AGGREGATE: AVG, not SUM. A sum of MW readings has no unit (energy would be
-- sum x 0.5 MWh). The mean of four half-hour MW averages is a 2-hour MW average.
--
-- FRAME: ROWS BETWEEN 3 PRECEDING AND CURRENT ROW = 4 rows. Four rows is two
-- hours only if they are consecutive half-hours. The guard reports the mean only
-- when the frame holds 4 rows AND the first row is exactly 5400 s (90 min) before
-- the current one. Otherwise mean_2h_mw is NULL.
--   Integer epoch seconds, not julianday hours: = 5400 is exact, and
--   moving_average.sql records julianday giving 23.4999999962747 for 23.5.
--   MIN(datetime_jst) works on the TEXT key: 'YYYY-MM-DD HH:MM' sorts as time.
--   Expected suppressions: the first 3 rows of the range, the first 3 rows after
--   any GAP, and on daily-only days the 3 rows after 00:00 (the daily feed has no
--   23:30, so a frame reaching back past midnight spans 7200 s, not 5400).
--
-- AGE: whole days from the row's JST date to today's JST date, the unit that
-- hepco_daily.py compares with `age >= RETENTION_DAYS`. RETENTION_DAYS is NOT
-- copied here; errors.py says the value lives in hepco_daily. Compare in Python.
--   date('now', '+9 hours') is today in JST ('now' is UTC). Japan has no DST.
--   Both julianday() arguments are midnights, so the difference is an exact
--   whole number; CAST only changes 3.0 to 3.
--   Depends on the run date: the same database gives different age_days tomorrow.
--

SELECT datetime_jst,
       source,
       demand_mw,
       COUNT(*) OVER w AS rows_in_frame,
       CAST(strftime('%s', datetime_jst) AS INTEGER)
         - CAST(strftime('%s', MIN(datetime_jst) OVER w) AS INTEGER) AS frame_span_seconds,
       CASE
         WHEN COUNT(*) OVER w = 4
          AND CAST(strftime('%s', datetime_jst) AS INTEGER)
            - CAST(strftime('%s', MIN(datetime_jst) OVER w) AS INTEGER) = 5400
         THEN AVG(demand_mw) OVER w
       END AS mean_2h_mw,
       CAST(julianday(date('now', '+9 hours'))
          - julianday(date(datetime_jst)) AS INTEGER) AS age_days
FROM area_demand_current
WINDOW w AS (ORDER BY datetime_jst ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)
ORDER BY datetime_jst;
--
-- PLAN, recorded 2026-09-16, EXPLAIN QUERY PLAN output whole:
--   QUERY PLAN
--   |--CO-ROUTINE (subquery-4)
--   |  |--SCAN a USING INDEX sqlite_autoindex_area_demand_1
--   |  `--CORRELATED SCALAR SUBQUERY 3
--   |     `--SEARCH b USING COVERING INDEX sqlite_autoindex_area_demand_1 (datetime_jst=?)
--   `--SCAN (subquery-4)
