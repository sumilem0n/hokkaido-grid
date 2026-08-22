-- schema.sql — hokkaido-grid capstone
-- SQLite DDL. Two independently-sourced tables, joined on a JST timestamp.
--
-- Grain: area_demand = 30-min, weather_hourly = 60-min — each stored at its SOURCE-NATIVE grain
-- (Option A). No interpolation is baked into storage; to correlate, floor the demand minute to the
-- hour in a query (see FIELDS.md). That keeps the bridge reversible and documented, not fabricated.
--
-- datetime_jst is a JST local-time TEXT string. Safe in a key because Japan observes no DST,
-- so no local hour is ever duplicated or skipped (no key collision).
--
-- area_demand's key is COMPOSITE: (datetime_jst, source). The same half-hour legitimately holds
-- one daily row and one monthly row, which is what makes the two-track agreement check askable.
-- Column order in the key is deliberate — datetime_jst first, so existing range seeks keep their
-- SEARCH plan. See FIELDS.md, "Decision — wind/solar schema and primary key, 19 Aug 2026".
--
-- UNITS ARE PER SOURCE. There is no single unit rule for this table:
--   monthly エリア需給  — already MW (banner: 単位[MW平均]), no conversion
--   daily jisseki       — kWh, converted on load (÷ 500 for a half-hour average MW)
--   daily juyo_01       — 万kW (×10), not currently loaded
-- Every value stored here is MW; the conversion happens per loader, never in the schema.
--
-- This file is generated from `.schema` after a migration and hand-headed. Comments inside a
-- table body survive; anything above the first CREATE does not. Re-add this block after any
-- regeneration. Migrations live in sql/migrations/.
CREATE TABLE weather_hourly (
    datetime_jst          TEXT NOT NULL PRIMARY KEY,  -- 'YYYY-MM-DD HH:MM' JST, hourly (:00 only)
    temperature_c         REAL,  -- temperature_2m, °C, instant
    relative_humidity_pct REAL,  -- relative_humidity_2m, %, instant
    precipitation_mm      REAL,  -- precipitation, mm, preceding-hour sum
    snowfall_cm           REAL,  -- snowfall, cm, preceding-hour sum
    wind_speed_kmh        REAL,  -- wind_speed_10m, km/h, instant
    CHECK (relative_humidity_pct IS NULL OR relative_humidity_pct BETWEEN 0 AND 100)
);
CREATE TABLE IF NOT EXISTS "area_demand" (
    datetime_jst    TEXT NOT NULL,              -- 'YYYY-MM-DD HH:MM' JST, 30-min (DATE + TIME merged)
    demand_mw       REAL NOT NULL,              -- エリア需要 (col 2), MW
    solar_mw        REAL,                       -- 太陽光発電実績 (col 13), MW — monthly only
    wind_mw         REAL,                       -- 風力発電実績 (col 15), MW — monthly only
    wind_solar_mw   REAL,                       -- monthly: derived sum. daily: エリア風力・太陽光発電量 ÷ 500
    supply_total_mw REAL,                       -- 合計 (col 21), MW — equals demand in a balanced grid
    source TEXT NOT NULL
        -- NB: 'hepco_monthly_areajukyu' also appears in load_demand, in the ON CONFLICT
        -- guard, and as AUTHORITATIVE_SOURCE. A rename must find all four.
        CHECK (source IN ('hepco_daily_jisseki', 'hepco_monthly_areajukyu')),

    PRIMARY KEY (datetime_jst, source),

    CHECK (demand_mw >= 0),
    CHECK (solar_mw IS NULL OR solar_mw >= 0),
    CHECK (wind_mw  IS NULL OR wind_mw  >= 0),
    CHECK (wind_solar_mw IS NULL OR wind_solar_mw >= 0),

    -- Derivation guard, monthly rows only. No IS NULL escape by decision: a monthly row
    -- carrying a total with no parts is column option 1's failure mode, one row at a time.
    -- Sound only while source is NOT NULL — a NULL source makes this expression NULL,
    -- which SQLite treats as satisfied.
    CHECK (
        source <> 'hepco_monthly_areajukyu'
        OR (
            wind_mw       IS NOT NULL
            AND solar_mw       IS NOT NULL
            AND wind_solar_mw  IS NOT NULL
            AND abs(wind_solar_mw - (wind_mw + solar_mw)) < 0.05
        )
    )
    -- NB: if you later add 揚水/蓄電池/連系線 (cols 17-19), do NOT give them >= 0 checks — those go negative.
);
-- Precedence view: one row per timestamp, monthly beats daily.
-- Rationale, the '<' vs '<=' trap, and 22 Aug verification:
-- sql/migrations/002_precedence_view.sql

DROP VIEW IF EXISTS area_demand_current;

CREATE VIEW area_demand_current AS
SELECT a.datetime_jst, a.source, a.demand_mw, a.wind_mw, a.solar_mw,
       a.wind_solar_mw, a.supply_total_mw
FROM area_demand AS a
WHERE NOT EXISTS (
    SELECT 1
    FROM area_demand AS b
    WHERE b.datetime_jst = a.datetime_jst
      AND CASE b.source WHEN 'hepco_monthly_areajukyu' THEN 0 ELSE 1 END
        < CASE a.source WHEN 'hepco_monthly_areajukyu' THEN 0 ELSE 1 END
);
