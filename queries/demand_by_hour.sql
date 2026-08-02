
-- Average area demand by hour of day — Hokkaido, April 2026.
-- Source: monthly エリア需給 file. Units: MW.
-- Grain: area_demand is 30-minute, so each hour-of-day bucket holds
-- 2 readings/day x 30 days = 60 readings. `readings` is the tripwire:
-- anything other than 60 means the load is incomplete.

-- Observed: late-morning peak (09:00-11:00, ~3400 MW) exceeds the evening
-- peak (19:00, ~3269 MW), with a midday dip (14:00-15:00, ~3000 MW) between
-- them. Overnight trough 00:00-02:00 (~2800 MW). Shape suggests commercial/
-- industrial daytime load competing with or exceeding residential evening
-- demand -- not a purely residential curve. Worth revisiting once weekday/
-- weekend is split out (not done in this pass).

SELECT
    CAST(strftime('%H', datetime_jst) AS INTEGER) AS hour_of_day,
    COUNT(*)                                      AS readings,
    COUNT(*) - COUNT(demand_mw)                   AS null_readings,
    ROUND(AVG(demand_mw), 1)                      AS avg_demand_mw,
    MIN(demand_mw)                                AS min_demand_mw,
    MAX(demand_mw)                                AS max_demand_mw
FROM area_demand
GROUP BY hour_of_day
ORDER BY hour_of_day
;
