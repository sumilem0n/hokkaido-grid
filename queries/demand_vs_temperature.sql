-- Half-hourly demand paired with the temperature of the hour it falls in.
-- Hokkaido, April 2026. Units: demand MW, temperature degC.
--
-- GRAIN BRIDGE. area_demand is 30-minute; weather_hourly is hourly. The join
-- floors the demand timestamp to its hour, so 09:00 and 09:30 both take the
-- 09:00 temperature. This duplicates the weather value across two demand rows
-- by design. The alternative is interpolating between hours, which invents
-- data the source never published.
--
-- ROW COUNT. The pairing query returns 1440 -- every 30-min reading keeps its
-- row. An equality join on the raw timestamps returns ~720 and silently drops
-- every :30 reading. The larger number is the correct one for the pairing;
-- verified 0 unmatched rows via a LEFT JOIN check on 2026-08-02 (1440
-- demand_rows, 1440 matched). But 1440 is the correct row count for THIS
-- QUERY and the wrong denominator for a correlation computed on it -- see
-- CORRELATION.
--
-- ============================================================================
-- CORRELATION. Superseded 2026-08-07. The earlier reading here was that the
-- weakly positive pooled r was "the opposite sign from the heating-load
-- hypothesis," explained by Pearson's blindness to a V-shaped curve. The sign
-- observation stands; that explanation for it is withdrawn. Do not reinstate.
--
-- REPRODUCED BY THE QUERIES BELOW, run 2026-08-07 (April 2026, monthly track):
--   Pooled, 30-min grain, n=1440              r =  0.131   [q4]
--   Pooled, hourly :00 rows, n=720            r =  0.135   [q4]
--   Pooled, hourly means, n=720               r =  0.132   [q5]
--   Within hour, hourly :00 rows, n=30/hr     -0.150 .. -0.553, all 24 neg  [q2]
--   Within hour, 30-min grain, n=60/hr        -0.133 .. -0.531, all 24 neg  [q3]
--   Within hour, hourly means, n=30/hr        -0.134 .. -0.546, all 24 neg  [q6]
--   Sign test, any grain                      24/24, p = 2^-24 ~= 6e-8 one-tailed
--
-- 5 AUG RECONCILED (2026-08-07). The 5 Aug session recorded +0.132 pooled and
-- -0.134 to -0.546 within-hour, on a row set that was never written down. It
-- was HOURLY MEANS throughout: q5 returns 0.132, and q6 returns -0.134 (h10)
-- to -0.546 (h22) -- both endpoints exact. Recorded because the failure was
-- not the arithmetic, it was quoting a statistic without its grain. Three
-- defensible definitions of "n=720" exist in this file and they return 0.131,
-- 0.132 and 0.135.
--
-- GRAIN-INVARIANCE. All three within-hour variants agree on sign in all 24
-- hours and on shape -- weakest around 08-14, strongest overnight and evening,
-- endpoints within about 0.02 of each other. The pooled sign flip likewise
-- survives all three grains. The finding does not depend on which grain you
-- pick, and that is what makes it a result rather than an artifact of the
-- bridge. It also means the choice of grain is a reporting decision, not a
-- correctness one -- pick hourly means, say so, and stop re-deciding.
--
-- SIMPSON'S PARADOX. The association reverses sign between the pooled data and
-- every subgroup of it. Hour-of-day is the confounder and it confounds in
-- exactly the direction that produces the flip -- the coldest hours
-- (02:00-05:00) are also the lowest-demand hours because nothing is running,
-- and the warmest hours sit inside the industrial and commercial day. Pooling
-- lets the daily activity cycle dominate a comparison meant to be about
-- temperature. Hold hour constant and demand rises as temperature falls, in
-- all 24 hours. That is the heating-load signal.
--
-- WHAT THIS MEANS FOR THE POOLED NUMBER. It is not a weak version of the
-- within-hour result and it is not evidence against heating load. It answers a
-- different question -- "are warm timestamps busy timestamps?" -- to which the
-- answer is yes, trivially. Every temperature-demand statement in this file is
-- conditioned on hour-of-day, or it is not a statement about temperature.
--
-- STRUCTURE INSIDE THE 24. The correlation is not uniform [q2 figures; q3 and
-- q6 give the same shape]. Overnight and evening hours (00-07, 18-23) run
-- -0.35 to -0.55; the working day (08-14) runs -0.15 to -0.26. The heating
-- signal is cleanest when human activity is lowest and gets buried during the
-- hours when industrial and commercial load dominates the variance. Two
-- consequences: (a) any single pooled figure is a weighted average over hours
-- that behave differently, which is the same defect the pooled r has; (b) the
-- midday weakening is CONSISTENT WITH a competing warm-side effect but is not
-- evidence of one -- low activity-driven variance alone would produce the same
-- shape. Week 8 tests it; this does not.
--
-- WHICH ROWS, ALWAYS. The three pooled figures span 0.131 to 0.135 on the same
-- underlying data, so the grain bridge is not free even for a point estimate.
-- It matters more for inference: at n=1440 each temperature reading is counted
-- twice, so the effective sample is 720 and any significance computed on 1440
-- is overstated. Use hourly rows for inference, 30-min rows for everything
-- else. Never quote an r from this file without its n AND its grain --
-- "n=720" alone is ambiguous between ":00 rows" and "hourly means."
--
-- STILL UNTESTED. The V-shape (demand rising at both extremes, cooling-adjacent
-- load above roughly 22C) is not refuted by anything above; a confounder that
-- explains the flip simply removes the need to invoke non-linearity to explain
-- it. April's range here is -1.1C to 18.2C, so the warm arm is barely sampled
-- and this month cannot test it. The daily-means counterexamples stand and are
-- consistent with either story (Apr 24: coldest day, not highest demand;
-- Apr 7: mid-temp, highest demand). Temperature bucketing is week 8. Do not
-- spend it early, and do not read a V out of a set of linear r values -- a
-- single Pearson r is the one measure that cannot see one.
--
-- PERFORMANCE. Every join below wraps strftime() around d.datetime_jst, so no
-- index on that column can be used -- SQLite computes the expression per row
-- and scans. Irrelevant at 1440 rows; not irrelevant at ten years of capture.
-- The fix, when it matters, is a stored hour-key column with its own index.
-- Deliberately not built. See week 6 (EXPLAIN QUERY PLAN).
--
-- SQLite has no CORR(). Every r below is computed from raw sums:
--   r = (n*Sxy - Sx*Sy) / sqrt(n*Sxx - Sx^2) / sqrt(n*Syy - Sy^2)
-- Requires SQRT(), i.e. a build with SQLITE_ENABLE_MATH_FUNCTIONS.
-- ============================================================================


-- 1. The pairing itself. LIMIT 10: this query's job is to show the shape of
--    the join, not to print the table. Drop the LIMIT to export the full set.
SELECT
    d.datetime_jst,
    d.demand_mw,
    w.temperature_c
FROM area_demand AS d
JOIN weather_hourly AS w
  ON strftime('%Y-%m-%d %H:00', d.datetime_jst) = w.datetime_jst
ORDER BY d.datetime_jst
LIMIT 10;


-- 2. Within hour-of-day, HOURLY :00 ROWS (n=30 per hour = 30 days).
--    The headline result: all 24 negative.
SELECT
    hour_of_day,
    n,
    ROUND((n * sxy - sx * sy)
          / (SQRT(n * sxx - sx * sx) * SQRT(n * syy - sy * sy)), 3) AS r
FROM (
    SELECT
        CAST(strftime('%H', d.datetime_jst) AS INTEGER) AS hour_of_day,
        COUNT(*)                                        AS n,
        SUM(w.temperature_c)                            AS sx,
        SUM(d.demand_mw)                                AS sy,
        SUM(w.temperature_c * d.demand_mw)              AS sxy,
        SUM(w.temperature_c * w.temperature_c)          AS sxx,
        SUM(d.demand_mw * d.demand_mw)                  AS syy
    FROM area_demand AS d
    JOIN weather_hourly AS w
      ON w.datetime_jst = strftime('%Y-%m-%d %H:00', d.datetime_jst)
    WHERE strftime('%M', d.datetime_jst) = '00'
    GROUP BY hour_of_day
)
ORDER BY hour_of_day;


-- 3. Within hour-of-day, 30-MIN GRAIN (n=60 per hour). Each temperature counted
--    twice. Did not match 5 Aug; kept as the grain-invariance check.
SELECT
    hour_of_day,
    n,
    ROUND((n * sxy - sx * sy)
          / (SQRT(n * sxx - sx * sx) * SQRT(n * syy - sy * sy)), 3) AS r
FROM (
    SELECT
        CAST(strftime('%H', d.datetime_jst) AS INTEGER) AS hour_of_day,
        COUNT(*)                                        AS n,
        SUM(w.temperature_c)                            AS sx,
        SUM(d.demand_mw)                                AS sy,
        SUM(w.temperature_c * d.demand_mw)              AS sxy,
        SUM(w.temperature_c * w.temperature_c)          AS sxx,
        SUM(d.demand_mw * d.demand_mw)                  AS syy
    FROM area_demand AS d
    JOIN weather_hourly AS w
      ON w.datetime_jst = strftime('%Y-%m-%d %H:00', d.datetime_jst)
    GROUP BY hour_of_day
)
ORDER BY hour_of_day;


-- 4. Pooled, 30-min grain vs hourly :00 rows. Ran 0.131 / 0.135 on 2026-08-07.
SELECT '30-min (n=1440)' AS grain, n,
       ROUND((n*sxy - sx*sy) / (SQRT(n*sxx - sx*sx) * SQRT(n*syy - sy*sy)), 3) AS r
FROM (
    SELECT COUNT(*) AS n, SUM(w.temperature_c) AS sx, SUM(d.demand_mw) AS sy,
           SUM(w.temperature_c * d.demand_mw) AS sxy,
           SUM(w.temperature_c * w.temperature_c) AS sxx,
           SUM(d.demand_mw * d.demand_mw) AS syy
    FROM area_demand AS d
    JOIN weather_hourly AS w
      ON w.datetime_jst = strftime('%Y-%m-%d %H:00', d.datetime_jst)
)
UNION ALL
SELECT 'hourly :00 rows (n=720)', n,
       ROUND((n*sxy - sx*sy) / (SQRT(n*sxx - sx*sx) * SQRT(n*syy - sy*sy)), 3)
FROM (
    SELECT COUNT(*) AS n, SUM(w.temperature_c) AS sx, SUM(d.demand_mw) AS sy,
           SUM(w.temperature_c * d.demand_mw) AS sxy,
           SUM(w.temperature_c * w.temperature_c) AS sxx,
           SUM(d.demand_mw * d.demand_mw) AS syy
    FROM area_demand AS d
    JOIN weather_hourly AS w
      ON w.datetime_jst = strftime('%Y-%m-%d %H:00', d.datetime_jst)
    WHERE strftime('%M', d.datetime_jst) = '00'
);


-- 5. Pooled on hourly MEANS -- both half-hour readings averaged into one value
--    per hour. Also n=720, a different 720 rows than q4's second branch.
--    Matched 5 Aug's pooled figure exactly (0.132).
SELECT 'hourly means (n=720)' AS grain, n,
       ROUND((n*sxy - sx*sy) / (SQRT(n*sxx - sx*sx) * SQRT(n*syy - sy*sy)), 3) AS r
FROM (
    SELECT COUNT(*) AS n, SUM(t) AS sx, SUM(dm) AS sy,
           SUM(t*dm) AS sxy, SUM(t*t) AS sxx, SUM(dm*dm) AS syy
    FROM (
        SELECT strftime('%Y-%m-%d %H:00', d.datetime_jst) AS hour_key,
               AVG(d.demand_mw)                           AS dm,
               AVG(w.temperature_c)                       AS t
        FROM area_demand AS d
        JOIN weather_hourly AS w
          ON w.datetime_jst = strftime('%Y-%m-%d %H:00', d.datetime_jst)
        GROUP BY hour_key
    )
);


-- 6. Within hour-of-day on hourly MEANS (n=30 per hour). Matched 5 Aug's
--    within-hour range exactly: -0.134 (h10) to -0.546 (h22).
--    AVG(w.temperature_c) averages one distinct value across two identical
--    rows -- a no-op by construction. If it ever isn't, the grain bridge broke.
SELECT
    hour_of_day,
    n,
    ROUND((n*sxy - sx*sy) / (SQRT(n*sxx - sx*sx) * SQRT(n*syy - sy*sy)), 3) AS r
FROM (
    SELECT CAST(strftime('%H', hour_key) AS INTEGER) AS hour_of_day,
           COUNT(*) AS n, SUM(t) AS sx, SUM(dm) AS sy,
           SUM(t*dm) AS sxy, SUM(t*t) AS sxx, SUM(dm*dm) AS syy
    FROM (
        SELECT strftime('%Y-%m-%d %H:00', d.datetime_jst) AS hour_key,
               AVG(d.demand_mw)                           AS dm,
               AVG(w.temperature_c)                       AS t
        FROM area_demand AS d
        JOIN weather_hourly AS w
          ON w.datetime_jst = strftime('%Y-%m-%d %H:00', d.datetime_jst)
        GROUP BY hour_key
    )
    GROUP BY hour_of_day
)
ORDER BY hour_of_day;
