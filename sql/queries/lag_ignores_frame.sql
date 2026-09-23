-- lag_ignores_frame.sql
--
-- What this shows: a frame clause changes AVG and changes nothing for LAG.
-- LAG reaches a fixed number of rows back in the ORDER BY sequence, and
-- SQLite ignores any frame given to it. AVG uses whatever the frame holds.
--
-- Data: April 2026, monthly track, read through area_demand_current
-- (the view, never the table). 1440 half-hourly rows.
--
-- The frame is the narrowest possible: the current row only. If LAG obeyed
-- it, the previous row would sit outside the frame, every lag_framed value
-- would be NULL, and lag_rows_changed would be 1439, not 0.
-- AVG is the control: it shows the frame clause is applied at all.
--
-- IS NOT, not <>: a <> comparison against NULL gives NULL, SUM skips it,
-- and a LAG that obeyed the frame would print a blank instead of 1439.
WITH april AS (
  SELECT datetime_jst, demand_mw
  FROM area_demand_current
  WHERE datetime_jst >= '2026-04-01'
    AND datetime_jst <  '2026-05-01'
),
w AS (
  SELECT
    datetime_jst,
    demand_mw,
    LAG(demand_mw) OVER (ORDER BY datetime_jst) AS lag_plain,
    LAG(demand_mw) OVER (ORDER BY datetime_jst
                         ROWS BETWEEN CURRENT ROW AND CURRENT ROW) AS lag_framed,
    AVG(demand_mw) OVER (ORDER BY datetime_jst) AS avg_plain,
    AVG(demand_mw) OVER (ORDER BY datetime_jst
                         ROWS BETWEEN CURRENT ROW AND CURRENT ROW) AS avg_framed
  FROM april
)
SELECT
  COUNT(*)                         AS n_rows,
  SUM(lag_plain IS NOT lag_framed) AS lag_rows_changed,
  SUM(avg_plain IS NOT avg_framed) AS avg_rows_changed
FROM w;
