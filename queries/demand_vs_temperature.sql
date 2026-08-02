
-- Half-hourly demand paired with the temperature of the hour it falls in.
-- Hokkaido, April 2026. Units: demand MW, temperature degC.
--
-- GRAIN BRIDGE. area_demand is 30-minute; weather_hourly is hourly. The join
-- floors the demand timestamp to its hour, so 09:00 and 09:30 both take the
-- 09:00 temperature. This duplicates the weather value across two demand rows
-- by design. The alternative is interpolating between hours, which invents
-- data the source never published.
--
-- ROW COUNT. Returns 1440 — every 30-min reading keeps its row. An equality
-- join on the raw timestamps returns ~720 and silently drops every :30
-- reading. The larger number is the correct one; verified 0 unmatched rows
-- via a LEFT JOIN check on 2026-08-02 (1440 demand_rows, 1440 matched).
--
-- PERFORMANCE. The join wraps strftime() around d.datetime_jst, so no index
-- on that column can be used — SQLite computes the expression per row and
-- scans. Irrelevant at 1440 rows; not irrelevant at ten years of capture.
-- The fix, when it matters, is a stored hour-key column with its own index.
-- Deliberately not built today. See week 6 (EXPLAIN QUERY PLAN).

-- CORRELATION. Pearson's r = 0.131 (n=1440), weakly positive -- the opposite
-- sign from the heating-load hypothesis, and near zero in magnitude either
-- way. Read as: April sits on the transition out of heating season (temp
-- range -1.1C to 18.2C across the month), and Pearson's r only detects
-- LINEAR relationships. A V-shaped demand curve (high at both cold and warm
-- extremes -- heating vs. commercial/cooling-adjacent load) would wash out
-- to something near zero under a linear measure regardless of true sign.
-- The daily-means table already shows counterexamples to a simple linear
-- read (Apr 24: coldest day, not highest demand; Apr 7: mid-temp, highest
-- demand). Week 8's temperature-bucketed analysis is where the non-linearity
-- gets tested properly -- this number is not the final word on the
-- relationship, just evidence that a naive linear read is insufficient.

SELECT
    d.datetime_jst,
    d.demand_mw,
    w.temperature_c
FROM area_demand AS d
JOIN weather_hourly AS w
  ON strftime('%Y-%m-%d %H:00', d.datetime_jst) = w.datetime_jst
ORDER BY d.datetime_jst

;
