-- 002_precedence_view.sql — 2026-08-22
--
-- One row per timestamp, from the best available source.
--
-- Since 001_composite_pk.sql the key is (datetime_jst, source), so one
-- half-hour can hold both a daily capture and a monthly archive row.
-- Monthly is HEPCO's corrected record and wins. This view is the only
-- place that rule lives; queries read the view, never area_demand.
--
-- Columns are named, never a.*: positions shift when a column is added,
-- and Postgres (Phase 3) freezes a '*' at view-creation time while SQLite
-- does not. Named columns behave identically on both.
--
-- A view is not carried by a table definition. Anything that rebuilds
-- area_demand must recreate this, so it also lives in sql/schema.sql.

DROP VIEW IF EXISTS area_demand_current;

CREATE VIEW area_demand_current AS
SELECT a.datetime_jst, a.source, a.demand_mw, a.wind_mw, a.solar_mw,
       a.wind_solar_mw, a.supply_total_mw
FROM area_demand AS a
WHERE NOT EXISTS (

    -- Keep a only if no row at the same timestamp outranks it. The CASE
    -- maps a source name to a rank; lower wins. SELECT 1 is a placeholder
    -- — EXISTS counts rows and never reads them.
    --
    -- STRICT '<', never '<='. The sweep does not exclude a itself, so a
    -- always appears as its own challenger at an equal rank. With '<='
    -- every row eliminates itself and the view returns ZERO rows, silently.
    -- Verified 22 Aug: '<=' returned 0; '<' returned 1581.
    --
    -- The two-level rank is sound only while the source CHECK on
    -- area_demand permits exactly two values. A third source would rank 1
    -- alongside daily, and two rows would survive one timestamp with no
    -- error. The guard is that CHECK, not this view.
    SELECT 1
    FROM area_demand AS b
    WHERE b.datetime_jst = a.datetime_jst
      AND CASE b.source WHEN 'hepco_monthly_areajukyu' THEN 0 ELSE 1 END
        < CASE a.source WHEN 'hepco_monthly_areajukyu' THEN 0 ELSE 1 END
);
-- Verified 22 Aug against sql/hokkaido.db (1440 monthly + 141 daily):
--   the two tracks currently share ZERO timestamps, so the clause cannot
--   be validated by row counts alone. Collision test in a transaction:
--   one colliding daily row inserted -> 1582 rows, view 1581, winner
--   hepco_monthly_areajukyu; ROLLBACK.
--   EXPLAIN QUERY PLAN, date-ranged: SEARCH a USING INDEX
--   sqlite_autoindex_area_demand_1 (datetime_jst>? AND datetime_jst<?)
--   with the correlated subquery as SEARCH b USING COVERING INDEX.
--   The date filter is pushed through the view into the outer table.
