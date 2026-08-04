-- joins_practice.sql
-- 2026-08-04 - JOIN drills against real April 2026 data.
-- Each block states the question, the predicted row count, and the measured one.
-- Predictions were written before running. Where they disagreed, the disagreement is the finding.

-- Q1. Every 30-min demand reading with its hour's weather (hour-floor bridge).
--     Predicted 1440: LEFT side fully preserved; weather_hourly PK is unique so no fanout.
--     Actual 1440.
SELECT COUNT(*) AS matched_rows
FROM area_demand AS d
JOIN weather_hourly AS w
  ON strftime('%Y-%m-%d %H:00', d.datetime_jst) = w.datetime_jst;

-- Q2. The same join with exact equality instead of the hour floor - the bug, kept deliberately.
--     Predicted ~720. Actual 720 = 30 days x 24 hours: every :30 reading is discarded.
--     Confirmed separately: 0 surviving rows do NOT end in ':00'.
--     Silent 50% data loss, no error raised. This is why the floored key exists.
SELECT COUNT(*) AS matched_rows_exact
FROM area_demand AS d
JOIN weather_hourly AS w
  ON d.datetime_jst = w.datetime_jst;

-- Q3. Anti-join: demand periods with no matching weather hour.
--     Predicted 0. Actual 0 (see the self-test at the bottom - the detector is known to fire).
--     Tests the KEY column, not a measurement column: a matched row may legitimately
--     carry a NULL measurement, and the two failures must not look alike.
SELECT d.datetime_jst
FROM area_demand AS d
LEFT JOIN weather_hourly AS w
       ON strftime('%Y-%m-%d %H:00', d.datetime_jst) = w.datetime_jst
WHERE w.datetime_jst IS NULL
ORDER BY d.datetime_jst;

-- Q4. Daily completeness: days whose period count is not 48, split rows-present vs values-present.
--     COUNT(*) counts rows; COUNT(col) counts non-NULL values. The gap between them is
--     "row exists but carries nothing" - the shape the daily feed's 23:30-24:00 period takes.
--     Predicted 0 rows for April (sourced from the monthly file). Actual 0 rows;
--     inverted check confirms 30 complete days, so the empty result means clean, not broken.
--     Prediction on record: the first daily-captured day will show 47.
SELECT strftime('%Y-%m-%d', datetime_jst) AS day,
       COUNT(*)         AS rows_present,
       COUNT(demand_mw) AS values_present
FROM area_demand
GROUP BY day
HAVING COUNT(*) <> 48 OR COUNT(demand_mw) <> 48
ORDER BY day;

-- Q5. Conditional aggregation: per-day mean demand plus a count of peak periods.
--     Filtering moves from the row level to the column level, so one pass produces
--     several differently-filtered measures. Same shape as rung 7's curtailment share.
--     100.0 not 100: integer division would floor the ratio to 0 before the multiply.
--     Predicted: 30 rows, one per April day. Actual ____.
SELECT strftime('%Y-%m-%d', datetime_jst) AS day,
       ROUND(AVG(demand_mw), 1)                          AS avg_mw,
       SUM(CASE WHEN demand_mw > 3500 THEN 1 ELSE 0 END) AS periods_over_3500,
       ROUND(100.0 * SUM(CASE WHEN demand_mw > 3500 THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_over
FROM area_demand
GROUP BY day
ORDER BY day;

-- Q6. <SQLZoo pattern that was shakiest today, rewritten against this schema.>
--     Predicted ____. Actual ____.


-- ---------------------------------------------------------------------------
-- Self-test for Q3, commented out. Run by hand; never part of the report.
-- An empty anti-join result is ambiguous: no orphans, or a broken query.
-- This blocks one weather hour at match time, so exactly two demand rows
-- (03:00 and 03:30) must go unmatched. Expected 2; measured 2 on 2026-08-04.
-- The exclusion belongs in ON, not WHERE: in WHERE it runs after NULL padding,
-- NULL <> '...' is not true, and the orphans are deleted instead of found.
--
-- SELECT COUNT(*) FROM area_demand AS d
-- LEFT JOIN weather_hourly AS w
--        ON strftime('%Y-%m-%d %H:00', d.datetime_jst) = w.datetime_jst
--       AND w.datetime_jst <> '2026-04-15 03:00'
-- WHERE w.datetime_jst IS NULL;
-- ---------------------------------------------------------------------------
