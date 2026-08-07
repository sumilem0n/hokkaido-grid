-- schema.sql — hokkaido-grid capstone
-- SQLite DDL. Two independently-sourced tables, joined on a JST timestamp.
--
-- Grain: area_demand = 30-min, weather_hourly = 60-min — each stored at its SOURCE-NATIVE grain
-- (Option A). No interpolation is baked into storage; to correlate, floor the demand minute to the
-- hour in a query (see FIELDS.md). That keeps the bridge reversible and documented, not fabricated.
--
-- datetime_jst is a JST local-time TEXT string. Safe as a primary key because Japan observes no DST,
-- so no local hour is ever duplicated or skipped (no key collision).
--
-- The HEPCO file is ALREADY in MW (banner row: 単位[MW平均]) — no ×10 conversion on load.

CREATE TABLE area_demand (
    datetime_jst    TEXT NOT NULL PRIMARY KEY,  -- 'YYYY-MM-DD HH:MM' JST, 30-min (DATE + TIME merged)
    demand_mw       REAL NOT NULL,              -- エリア需要 (col 2), MW
    solar_mw        REAL,                        -- 太陽光発電実績 (col 13), MW — weather-sensitive
    wind_mw         REAL,                        -- 風力発電実績 (col 15), MW — weather-sensitive
    supply_total_mw REAL,                        -- 合計 (col 21), MW — equals demand in a balanced grid
    source TEXT NOT NULL
        CHECK (source IN ('hepco_daily_jisseki', 'hepco_monthly_areajukyu')),
    CHECK (demand_mw >= 0),
    CHECK (solar_mw IS NULL OR solar_mw >= 0),
    CHECK (wind_mw  IS NULL OR wind_mw  >= 0)
    -- NB: if you later add 揚水/蓄電池/連系線 (cols 17-19), do NOT give them >= 0 checks — those go negative.
);

CREATE TABLE weather_hourly (
    datetime_jst          TEXT NOT NULL PRIMARY KEY,  -- 'YYYY-MM-DD HH:MM' JST, hourly (:00 only)
    temperature_c         REAL,  -- temperature_2m, °C, instant
    relative_humidity_pct REAL,  -- relative_humidity_2m, %, instant
    precipitation_mm      REAL,  -- precipitation, mm, preceding-hour sum
    snowfall_cm           REAL,  -- snowfall, cm, preceding-hour sum
    wind_speed_kmh        REAL,  -- wind_speed_10m, km/h, instant
    CHECK (relative_humidity_pct IS NULL OR relative_humidity_pct BETWEEN 0 AND 100)
);
