-- 001 — composite primary key (datetime_jst, source) + wind_solar_mw
-- Decision: FIELDS.md, "Decision — wind/solar schema and primary key, 19 Aug 2026"
-- SQLite cannot ALTER a primary key or ADD a CHECK, so this is a table rebuild.

BEGIN;

CREATE TABLE area_demand_new (
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

-- Columns named on both sides: positional copy would silently misalign now that a column is added.
-- CASE with no ELSE yields NULL, so daily rows keep NULL and monthly rows get the derived sum.
INSERT INTO area_demand_new
    (datetime_jst, demand_mw, solar_mw, wind_mw, wind_solar_mw, supply_total_mw, source)
SELECT
     datetime_jst, demand_mw, solar_mw, wind_mw,
     CASE WHEN source = 'hepco_monthly_areajukyu' THEN wind_mw + solar_mw END,
     supply_total_mw, source
FROM area_demand;

DROP TABLE area_demand;
ALTER TABLE area_demand_new RENAME TO area_demand;

COMMIT;
