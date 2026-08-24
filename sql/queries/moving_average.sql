-- 24-hour moving average of demand, guarded against gaps in the series.
-- The frame counts ROWS, not time: 48 rows is 24 hours only when those rows
-- are consecutive half-hours. span_hours proves it; without the guard a frame
-- straddling missing days returns a plausible, wrong average.
-- Tolerance rather than = 23.5: julianday returns a float, and on contiguous
-- April data span_hours prints 23.4999999962747 / 23.5000000074506, never 23.5.
-- An equality test would suppress all 1440 rows and look like a working guard.

SELECT datetime_jst,
       demand_mw,
       COUNT(*) OVER w AS rows_in_window,
       (julianday(datetime_jst) - julianday(MIN(datetime_jst) OVER w)) * 24 AS span_hours,
       CASE WHEN COUNT(*) OVER w = 48
             AND ABS((julianday(datetime_jst) - julianday(MIN(datetime_jst) OVER w)) * 24 - 23.5) < 0.01
            THEN AVG(demand_mw) OVER w END AS ma_24h_mw
FROM area_demand_current
WHERE source = 'hepco_monthly_areajukyu'
WINDOW w AS (ORDER BY datetime_jst ROWS BETWEEN 47 PRECEDING AND CURRENT ROW)
ORDER BY datetime_jst;

-- Coverage check. Window functions cannot be filtered in the same SELECT that
-- computes them (WHERE runs first), so the column is computed in a subquery and
-- counted outside it. April 2026: 1440 total, 1393 reported, 47 suppressed --
-- the 47 are the start of the series, not a hole in it.

SELECT COUNT(*) AS total,
       SUM(ma_24h_mw IS NOT NULL) AS reported,
       SUM(ma_24h_mw IS NULL)     AS suppressed
FROM (
  SELECT CASE WHEN COUNT(*) OVER w = 48
               AND ABS((julianday(datetime_jst) - julianday(MIN(datetime_jst) OVER w)) * 24 - 23.5) < 0.01
              THEN AVG(demand_mw) OVER w END AS ma_24h_mw
  FROM area_demand_current
  WHERE source = 'hepco_monthly_areajukyu'
  WINDOW w AS (ORDER BY datetime_jst ROWS BETWEEN 47 PRECEDING AND CURRENT ROW)
);
