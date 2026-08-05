-- Q1. Does mean demand and peak-period share differ by day type
--     (weekday / weekend / holiday)?
--   Predicted: 3 rows. weekday mean ~3160 MW, pct_over ~11; weekend mean ~2915,
--   pct_over 0.0; holiday n=1 day (4/29), mean 2850-2980, pct_over 0.0.
--   Secondary, sharper: pulling 4/29 out of Wednesday RAISES Wednesday's mean
--   by roughly 75 MW (one day ~300 MW low, divided across 4 Wednesdays).
--   Falsified if the holiday lands in weekday range, or if weekend pct_over > 0.

--   Actual: 3 rows. weekday n=21, mean 3181.5, pct_over 12.0. weekend n=8,
--   mean 2917.0, pct_over 0.0. holiday n=1, mean 2906.9, pct_over 0.0.
--   Tripwire clean: 1008/384/48 = days x 48 in all three.
--   CONFIRMED on every count. Holiday sits inside weekend range (2906.9 vs
--   2917.0), well clear of weekday — Showa Day loads like a Sunday, not a
--   Wednesday. Weekend max 3421 never reaches 3500, so pct_over 0.0 is a real
--   ceiling, not a threshold artifact.
--   Secondary: predicted +75 MW, actual +62.5 (3156.6 -> 3219.1).
--   Miss fully attributable: 4/29 runs 312 MW below other Wednesdays, and
--   dow=3 has FIVE days not four (confirmed in the weekday sanity check).
--   312/5 = 62.4. The arithmetic was right; the day count in my head was wrong.

.headers on
.mode box

SELECT
    CASE
        WHEN strftime('%Y-%m-%d', datetime_jst) = '2026-04-29' THEN 'holiday'
        WHEN strftime('%w', datetime_jst) IN ('0','6')         THEN 'weekend'
        ELSE 'weekday'
    END                                                AS day_type,
    COUNT(DISTINCT strftime('%Y-%m-%d', datetime_jst)) AS days,
    COUNT(*)                                           AS periods,
    ROUND(AVG(demand_mw), 1)                           AS avg_mw,
    MAX(demand_mw)                                     AS max_mw,
    SUM(CASE WHEN demand_mw > 3500 THEN 1 ELSE 0 END)  AS periods_over_3500,
    ROUND(100.0 * SUM(CASE WHEN demand_mw > 3500 THEN 1 ELSE 0 END)
          / COUNT(*), 1)                               AS pct_over
FROM area_demand
GROUP BY day_type
ORDER BY day_type;

-- Q1 secondary: does pulling 4/29 out of Wednesday raise Wednesday's mean?
-- AVG() skips NULLs, so a CASE with no ELSE excludes the holiday rows from the
-- second column while leaving the first intact. Same rows, two filters.
SELECT
    strftime('%w', datetime_jst) AS dow,
    ROUND(AVG(demand_mw), 1)     AS avg_all,
    ROUND(AVG(CASE WHEN strftime('%Y-%m-%d', datetime_jst) <> '2026-04-29'
                   THEN demand_mw END), 1) AS avg_excl_holiday
FROM area_demand
GROUP BY dow
ORDER BY dow;

-- Q2. What time of day does each day's peak occur, and does that time
--     shift with day of week?
--   Predicted: 30 rows (one per day) if no ties; more means duplicate daily maxima.
--   ~20 weekdays peak in the 09:00-11:00 window; the 8 weekend days and 4/29
--   peak in the evening, 17:00-19:00.
--   Falsified if weekends also peak in the morning - which would kill the
--   "commercial/industrial daytime load" reading in demand_by_hour.sql.

--   Actual:32 rows, not 30. TIE TRIPWIRE FIRED — 2026-04-20 (10:00 and
--   10:30, both 3463) and 2026-04-30 (10:30 and 11:00, both 3444). Adjacent
--   periods, identical values: flat-topped peaks, not coincidence across the day.
--   Weekday timing CONFIRMED: 19 of 21 weekdays peak 09:00-11:00. The two
--   strays are 4/10 (13:00) and 4/17 (11:30).
--   Weekend timing PARTIALLY FALSIFIED. All four Sundays peak evening
--   (18:30, 18:30, 19:00, 19:00) — clean. Saturdays split: 4/4 and 4/11 peak
--   11:30 (morning), 4/18 at 18:30, 4/25 at 04:00. Saturday is not a weekend
--   day for demand purposes — it is its own shape, and the weekday/weekend
--   binary in Q1 hides that.
--   Holiday FALSIFIED: 4/29 peaks 11:30, morning, not evening. Loads like a
--   weekend in MAGNITUDE but not in SHAPE.
--   The commercial/industrial daytime reading in demand_by_hour.sql survives:
--   Sundays move the peak to evening, which is what that hypothesis predicts.


SELECT
    strftime('%Y-%m-%d', d.datetime_jst) AS day,
    strftime('%w',       d.datetime_jst) AS dow,
    strftime('%H:%M',    d.datetime_jst) AS peak_time,
    d.demand_mw                          AS peak_mw
FROM area_demand AS d
JOIN (
    SELECT strftime('%Y-%m-%d', datetime_jst) AS day,
           MAX(demand_mw)                     AS peak_mw
    FROM area_demand
    GROUP BY day
) AS m
  ON strftime('%Y-%m-%d', d.datetime_jst) = m.day
 AND d.demand_mw = m.peak_mw
ORDER BY day;

-- Q3. Why is 2026-04-20 at 0.0% when it is a Monday?
--   Predicted: 48 rows present, 0 NULLs (joins_practice Q4 already established
--   30 complete days). So not a data gap.
--   Max demand 3300-3500 MW - just under the threshold, not a genuinely low day.
--   Temperature does NOT explain it: 4/20 within 3 degC of the April Monday mean.
--   Falsified if max < 3200 (a real anomaly needing another cause), or if
--   4/20 is >5 degC warmer than other Mondays (then temperature does explain it).

--   Actual:48 rows, 48 values — not a data gap, as predicted.
--   Max 3463, inside the predicted 3300-3500. periods_over_3400 = 4, so the
--   day did reach 3400 four times and stopped short of 3500. Near-miss
--   CONFIRMED, not an anomaly.
--   But avg 3021.8 vs weekday mean 3181.5 — the whole day sat ~160 MW low,
--   so it is BOTH a near-miss at the ceiling and a genuinely soft day.
--   Temperature does NOT explain it, as predicted: 4/20 at 8.1C vs Monday
--   mean 8.0C — 0.1C off, nowhere near the 5C falsification bar.
--   COUNTEREXAMPLE on record: 4/27 is 3.0C WARMER (11.1C) and has both a
--   higher max (3535) and a higher mean (3061.6). Warmer, higher demand.
--   Cause still unidentified. Not weather, not a gap, not the threshold.
-- 3a. Is it a data gap? Expect 48 / 48.
SELECT strftime('%Y-%m-%d', datetime_jst) AS day,
       COUNT(*)                 AS rows_present,
       COUNT(demand_mw)         AS values_present,
       ROUND(AVG(demand_mw), 1) AS avg_mw,
       MAX(demand_mw)           AS max_mw
FROM area_demand
WHERE strftime('%Y-%m-%d', datetime_jst) = '2026-04-20';

-- 3b. Is 4/20 low, or is the 3500 threshold just above its ceiling?
--     A day at 3480 max is "near miss"; a day at 3100 max is a real anomaly.
SELECT strftime('%Y-%m-%d', datetime_jst) AS day,
       ROUND(AVG(demand_mw), 1) AS avg_mw,
       MAX(demand_mw)           AS max_mw,
       SUM(CASE WHEN demand_mw > 3400 THEN 1 ELSE 0 END) AS periods_over_3400,
       SUM(CASE WHEN demand_mw > 3500 THEN 1 ELSE 0 END) AS periods_over_3500
FROM area_demand
WHERE strftime('%w', datetime_jst) = '1'
GROUP BY day
ORDER BY day;

-- 3c. Does temperature explain it? All Mondays, demand and temp side by side.
WITH d AS (
    SELECT strftime('%Y-%m-%d', datetime_jst) AS day,
           AVG(demand_mw)                     AS avg_mw,
           MAX(demand_mw)                     AS max_mw
    FROM area_demand
    WHERE strftime('%w', datetime_jst) = '1'
    GROUP BY day
),
w AS (
    SELECT strftime('%Y-%m-%d', datetime_jst) AS day,
           AVG(temperature_c)                 AS avg_temp_c,
           MIN(temperature_c)                 AS min_temp_c,
           MAX(temperature_c)                 AS max_temp_c
    FROM weather_hourly
    WHERE strftime('%w', datetime_jst) = '1'
    GROUP BY day
)
SELECT d.day,
       ROUND(d.avg_mw, 1)     AS avg_mw,
       d.max_mw,
       ROUND(w.avg_temp_c, 1) AS avg_temp_c,
       w.min_temp_c,
       w.max_temp_c
FROM d JOIN w ON d.day = w.day
ORDER BY d.day;

-- Q4.  Within a single hour, how far does demand move between the :00 reading
--     and the :30 reading, and when is that gap largest? This is exactly the
--     movement that averaging to hourly erases; a swing across an hour
--     boundary survives resampling and is not the question here.
--     Predicted: largest intra-hour ramp 150-250 MW, positive (up-ramp), occurring
--     in the morning rise 06:00-09:00. Reasoning: trough ~2800 to morning peak
--     ~3400 = 600 MW across ~6 h, so the average step is ~50 MW; the steepest
--     single step should be 3-5x that.
--     Grain decision, stated as a threshold BEFORE running: if the largest
--     intra-hour ramp exceeds 5% of daily mean demand, 30-min grain is justified
--     and resampling to hourly loses real signal. Predicted ~6-7% -> justified.
--     Falsified if max ramp < 100 MW, or if the largest ramps are evening
--     down-ramps rather than morning up-ramps.

--     Actual:720 pairs (tripwire clean). Max intra-hour ramp 288 MW, positive,
--   2026-04-04 08:30 — hour 8, inside the predicted 06:00-09:00 window.
--   Direction and timing CONFIRMED. Magnitude MISSED HIGH: 288 vs predicted
--   150-250. That is ~5.8x the average step, above the 3-5x assumption.
--   The miss is in the multiplier, not in the data — the morning rise is
--   peakier than a smooth-climb model implies.
--   mean_abs_ramp 55.7 MW, against a predicted ~50 MW average step. The
--   arithmetic underneath the prediction was sound; only the peakiness guess
--   was off.
--   GRAIN DECISION: 9.28% of mean demand, against a 5% threshold set before
--   running. Predicted 6-7%, actual 9.28 — same side of the line, decisively.
--   30-min grain justified; resampling to hourly loses real signal.
--   The 100-155 MW ambiguity band never materialised.
--   4c: hour 8 mean_signed = mean_abs = 112.3, i.e. EVERY hour-8 pair in all
--   30 days is an up-ramp. Same total consistency at hours 1, 2, 17 (all up)
--   and 0, 19, 20, 21, 22, 23 (all down). Biggest single ramp is a Saturday.


-- 4a. The ten largest swings, signed.
SELECT
    cur.datetime_jst                    AS half_hour,
    strftime('%w', cur.datetime_jst)    AS dow,
    prev.demand_mw                      AS mw_at_00,
    cur.demand_mw                       AS mw_at_30,
    cur.demand_mw - prev.demand_mw      AS ramp_mw
FROM area_demand AS cur
JOIN area_demand AS prev
  ON prev.datetime_jst = strftime('%Y-%m-%d %H:%M', cur.datetime_jst, '-30 minutes')
WHERE strftime('%M', cur.datetime_jst) = '30'
ORDER BY ABS(cur.demand_mw - prev.demand_mw) DESC
LIMIT 10;

-- 4b. The grain decision, against the threshold written before running.
WITH ramps AS (
    SELECT CAST(strftime('%H', cur.datetime_jst) AS INTEGER) AS hour_of_day,
           cur.demand_mw - prev.demand_mw                    AS ramp_mw
    FROM area_demand AS cur
    JOIN area_demand AS prev
      ON prev.datetime_jst = strftime('%Y-%m-%d %H:%M', cur.datetime_jst, '-30 minutes')
    WHERE strftime('%M', cur.datetime_jst) = '30'
)
SELECT COUNT(*)                AS pairs,
       MAX(ABS(ramp_mw))       AS max_abs_ramp_mw,
       MAX(ramp_mw)            AS largest_up_ramp_mw,
       MIN(ramp_mw)            AS largest_down_ramp_mw,
       ROUND(AVG(ABS(ramp_mw)), 1) AS mean_abs_ramp_mw,
       ROUND(100.0 * MAX(ABS(ramp_mw))
             / (SELECT AVG(demand_mw) FROM area_demand), 2) AS pct_of_mean_demand
FROM ramps;

-- 4c. Where in the day the movement lives — up-ramps and down-ramps separated,
--     because averaging signed ramps cancels them to near zero.
WITH ramps AS (
    SELECT CAST(strftime('%H', cur.datetime_jst) AS INTEGER) AS hour_of_day,
           cur.demand_mw - prev.demand_mw                    AS ramp_mw
    FROM area_demand AS cur
    JOIN area_demand AS prev
      ON prev.datetime_jst = strftime('%Y-%m-%d %H:%M', cur.datetime_jst, '-30 minutes')
    WHERE strftime('%M', cur.datetime_jst) = '30'
)
SELECT hour_of_day,
       COUNT(*)                    AS pairs,
       ROUND(AVG(ramp_mw), 1)      AS mean_signed_ramp,
       ROUND(AVG(ABS(ramp_mw)), 1) AS mean_abs_ramp,
       MAX(ramp_mw)                AS max_up,
       MIN(ramp_mw)                AS max_down
FROM ramps
GROUP BY hour_of_day
ORDER BY hour_of_day;

-- Q5. Holding hour-of-day fixed, does colder mean higher demand? -- (Within each hour-of-day bucket, n=30 days: correlate temperature_c -- against demand_mw, rather than pooling all 1440 rows.)
-- Predicted: pooled r = 0.131 is confounded by hour-of-day. Controlling for it,
--   the sign flips negative in overnight/early-morning hours (00:00-06:00),
--   r roughly -0.3 to -0.5 - residential heating load. Midday hours
--   (11:00-15:00) stay near zero: commercial load, temperature-insensitive.
--   The prediction is the PATTERN (systematic sign flip across the day),
--   not any single bucket's number.
--   Falsified if r stays positive across all 24 hours, or if the sign varies
--   with no relationship to time of day.

--     Actual: n=30 in every bucket (tripwire clean). Pooled r = 0.132,
--   reproducing the 0.131 from demand_vs_temperature.sql — formula verified.
--   PATTERN CONFIRMED, and more strongly than predicted. All 24 hourly r
--   values are NEGATIVE. Range -0.134 (hour 10) to -0.546 (hour 22).
--   Overnight 00:00-06:00: -0.544 to -0.413, inside the predicted -0.3/-0.5.
--   Midday 11:00-15:00: -0.171 to -0.283 — weakly negative, not the predicted
--   near-zero, but these are the weakest values and all sit below the
--   |r| > 0.36 significance bar at n=30.
--   14 of 24 hours clear that bar: 00-06 and 17-23. All negative. The
--   significant hours are exactly the non-commercial hours.
--   THE FINDING: pooled r is POSITIVE while every subgroup is NEGATIVE.
--   Simpson's paradox. Hot hours (midday, 12.2C) are also high-demand hours
--   (~3400 MW); cold hours (overnight, 4.5C) are low-demand hours (~2800 MW).
--   Pooling makes temperature a proxy for time of day, and the diurnal cycle
--   swamps the weather effect and inverts its sign. Controlling for hour
--   removes the confound and the heating-load signal appears as predicted.
--   The 0.131 in demand_vs_temperature.sql is not weak evidence of a weak
--   positive relationship. It is an artifact. That comment needs rewriting.

-- 5a. Formula check first: reproduce the pooled r before trusting the buckets.
--     Should land near 0.131 (the pooled figure uses 30-min grain, so expect
--     agreement to ~2 decimal places, not exactness).
WITH hourly AS (
    SELECT strftime('%Y-%m-%d %H:00', datetime_jst) AS hour_key,
           AVG(demand_mw)                           AS demand_mw
    FROM area_demand
    GROUP BY hour_key
),
paired AS (
    SELECT w.temperature_c AS x, h.demand_mw AS y
    FROM hourly AS h
    JOIN weather_hourly AS w ON h.hour_key = w.datetime_jst
    WHERE w.temperature_c IS NOT NULL AND h.demand_mw IS NOT NULL
)
SELECT COUNT(*) AS n,
       ROUND( (COUNT(*)*SUM(x*y) - SUM(x)*SUM(y))
              / ( sqrt(COUNT(*)*SUM(x*x) - SUM(x)*SUM(x))
                * sqrt(COUNT(*)*SUM(y*y) - SUM(y)*SUM(y)) ), 3) AS pooled_r
FROM paired;

-- 5b. The same r, one hour-of-day bucket at a time.
WITH hourly AS (
    SELECT strftime('%Y-%m-%d %H:00', datetime_jst) AS hour_key,
           AVG(demand_mw)                           AS demand_mw
    FROM area_demand
    GROUP BY hour_key
),
paired AS (
    SELECT CAST(strftime('%H', h.hour_key) AS INTEGER) AS hour_of_day,
           w.temperature_c                             AS x,
           h.demand_mw                                 AS y
    FROM hourly AS h
    JOIN weather_hourly AS w ON h.hour_key = w.datetime_jst
    WHERE w.temperature_c IS NOT NULL AND h.demand_mw IS NOT NULL
)
SELECT hour_of_day,
       COUNT(*)                 AS n,
       ROUND(AVG(x), 1)         AS avg_temp_c,
       ROUND(AVG(y), 1)         AS avg_demand_mw,
       ROUND( (COUNT(*)*SUM(x*y) - SUM(x)*SUM(y))
              / ( sqrt(COUNT(*)*SUM(x*x) - SUM(x)*SUM(x))
                * sqrt(COUNT(*)*SUM(y*y) - SUM(y)*SUM(y)) ), 3) AS pearson_r
FROM paired
GROUP BY hour_of_day
ORDER BY hour_of_day;
