-- Half-hour demand delta, gap-guarded.
--
-- LAG returns the previous ROW, not the previous HALF-HOUR. prev_ts is carried
-- forward so the 30-minute gap can be asserted before subtracting.
--
-- Integer epoch seconds, not float hours: = 1800 is exact where = 0.5 is not
-- (cf. span_hours printing 23.4999999962747 on contiguous April rows, 24 Aug).
--
-- Reads the view, never the table: under PK (datetime_jst, source) the row
-- above can be the same half-hour from the other source, and the delta would
-- compare sources instead of periods.
--
-- Verified 26 Aug 2026. Predicted 1769 | 1761 | 8 before running; confirmed.
-- 8 runs = April (1) + seven August days (7); the daily file has no 23:30, so
-- 23:00 -> 00:00 is 60 min and every day boundary breaks the run.
-- Suppressed rows listed and all 8 are boundaries; no within-day row suppressed.
-- Surviving deltas: min -260.0, max +328.0, avg +0.3 MW.
--
-- KNOWN LIMIT: this test cannot distinguish a normal night (1 period missing)
-- from a day never loaded (24 Aug, 49 periods missing). (gap_seconds/1800)-1
-- gives the count. `gaps` must make that distinction; this query does not.

WITH ordered AS (
    SELECT datetime_jst, demand_mw,
           LAG(demand_mw)    OVER w AS prev_demand_mw,
           LAG(datetime_jst) OVER w AS prev_ts
    FROM area_demand_current
    WINDOW w AS (ORDER BY datetime_jst)
),
flagged AS (
    SELECT datetime_jst, demand_mw, prev_demand_mw,
           CASE
             WHEN prev_ts IS NULL THEN NULL
             WHEN CAST(strftime('%s', datetime_jst) AS INTEGER)
                - CAST(strftime('%s', prev_ts)      AS INTEGER) = 1800
             THEN demand_mw - prev_demand_mw
             ELSE NULL
           END AS delta_mw
    FROM ordered
)
SELECT datetime_jst, demand_mw, prev_demand_mw, delta_mw
FROM flagged
ORDER BY datetime_jst;

-- PLAN (26 Aug, sql/hokkaido.db):
--   CO-ROUTINE ordered -> CO-ROUTINE (subquery-6)
--     -> SCAN a USING INDEX sqlite_autoindex_area_demand_1
--     -> CORRELATED SCALAR SUBQUERY 5 -> SEARCH b USING COVERING INDEX
--   SCAN ordered -> USE TEMP B-TREE FOR ORDER BY
--
-- The correlated subquery belongs to the view (the precedence lookup), not to
-- this query. The temp b-tree is NEW against Monday's baseline and was NOT
-- predicted: wrapping the window in a CTE hides the source ordering from the
-- consumer, so the final ORDER BY cannot reuse the PK index and sorts 1769 rows.
-- The window's own ordering was still free. Cost of the two-layer structure,
-- which is required because a window function's output cannot be tested in the
-- SELECT that creates it. Negligible here; note the shape, not the number.
