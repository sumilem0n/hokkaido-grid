-- demand_by_temperature_3c_apr2026.sql — hokkaido-grid capstone
-- Mean hourly Hokkaido area demand (MW) per 3 °C temperature bucket, April 2026.
--
-- SOURCE: reads area_demand_current, not area_demand. area_demand can hold two rows per
-- half-hour (daily + monthly). The view keeps one per timestamp, monthly beating daily, so
-- no half-hour is counted twice.
--
-- HOURLY DEMAND: AVG, not SUM. demand_mw is a rate (a half-hour average MW), not an energy
-- amount. Two half-hours at 3,000 and 3,200 MW mean the hour ran at 3,100 MW. 
-- SUM would report 6,200, which is not a load at all: MW readings do not add. 
-- Each hour :00 takes its :00 and :30 half-hours (minute floored to the hour, as in FIELDS.md) 
-- and pairs with the :00 instant temperature.
--
-- SCOPE: April 2026 only ('2026-04-01 00:00' up to, not including, '2026-05-01 00:00').
-- weather_hourly ends 30 Apr, so later demand hours would have no temperature to match.
--
-- BUCKETS: 3 °C wide, lower bound inclusive, upper exclusive: [-3, 0), [0, 3), [3, 6) ...
-- The lower bound is floor(t / 3) * 3. -1.1 °C → floor(-0.367) = -1 → -3, bucket [-3, 0).
-- Not CAST(t / 3 AS INTEGER): CAST truncates toward zero, giving 0 and putting -1.1 °C
-- in [0, 3) with +1.1 °C. The floor is written out with CAST plus a correction so it
-- does not depend on SQLite being built with math functions.

WITH hourly_demand AS (
    SELECT substr(datetime_jst, 1, 14) || '00' AS hour_jst,   -- 'YYYY-MM-DD HH:00'
           AVG(demand_mw)                     AS demand_mw
    FROM area_demand_current
    WHERE datetime_jst >= '2026-04-01 00:00'
      AND datetime_jst <  '2026-05-01 00:00'
    GROUP BY hour_jst
),
hourly_matched AS (
    SELECT d.hour_jst,
           d.demand_mw,
           w.temperature_c
    FROM hourly_demand AS d
    JOIN weather_hourly AS w
      ON w.datetime_jst = d.hour_jst
    WHERE w.temperature_c IS NOT NULL
),
bucketed AS (
    SELECT demand_mw,
           ( CAST(temperature_c / 3.0 AS INTEGER)
             - (temperature_c / 3.0 < CAST(temperature_c / 3.0 AS INTEGER)) ) * 3 AS bucket_lo_c
    FROM hourly_matched
)
SELECT bucket_lo_c,
       bucket_lo_c + 3           AS bucket_hi_c,
       ROUND(AVG(demand_mw), 1)  AS avg_demand_mw,
       COUNT(*)                  AS n_hours
FROM bucketed
GROUP BY bucket_lo_c
ORDER BY bucket_lo_c;
