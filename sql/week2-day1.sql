-- Week 2 Day 1: SELECT through JOIN, from memory after sqlbolt 1-12.
-- Schema foreshadows the HEPCO capstone: regions and the plants that feed them.

CREATE TABLE prefectures (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,
    region   TEXT NOT NULL,
    population_millions REAL
);

CREATE TABLE power_plants (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    type          TEXT NOT NULL,          -- 'hydro' | 'thermal' | 'solar' | 'wind'
    capacity_mw   REAL,
    prefecture_id INTEGER                 -- references prefectures.id; NULL allowed on purpose
);

INSERT INTO prefectures VALUES
    (1, 'Hokkaido', 'Hokkaido', 5.1),
    (2, 'Aomori',   'Tohoku',   1.2),
    (3, 'Osaka',    'Kansai',   8.8),
    (4, 'Okinawa',  'Kyushu-Okinawa', 1.5),
    (5, 'Nagano',   'Chubu',    2.0);

INSERT INTO power_plants VALUES
    (1, 'Tomato-Atsuma', 'thermal', 1650, 1),
    (2, 'Kyogoku',       'hydro',    600, 1),
    (3, 'Higashidori',   'thermal',  600, 2),
    (4, 'Sakai Solar',   'solar',     10, 3),
    (5, 'Azumi',         'hydro',    623, 5),
    (6, 'Floating Test', 'wind',      5, NULL);   -- deliberately unassigned 
-- 1. All prefectures, name and population only.
SELECT name, population_millions FROM prefectures;

-- 2. Plants over 500 MW, largest first.
SELECT name, capacity_mw FROM power_plants
WHERE capacity_mw > 500
ORDER BY capacity_mw DESC;

-- 3. The 2 largest plants overall (LIMIT needs ORDER BY or "first 2" is arbitrary).
SELECT name, capacity_mw FROM power_plants
ORDER BY capacity_mw DESC
LIMIT 2;

-- 4. Distinct plant types. (DISTINCT)
SELECT DISTINCT type FROM power_plants;

-- 5. Plants whose name starts with 'T'. (LIKE)
SELECT name FROM power_plants
WHERE name LIKE 'T%';

-- 6. Every plant with its prefecture name. (INNER JOIN)
SELECT power_plants.name, prefectures.name
FROM power_plants
INNER JOIN prefectures ON power_plants.prefecture_id = prefectures.id;

--7. Every prefecture, including ones with no plants. (LEFT JOIN)
SELECT prefectures.name, power_plants.name
FROM prefectures
LEFT JOIN power_plants ON prefectures.id = power_plants.prefecture_id;

--8. Plants not assigned to any prefecture. (IS NULL)
SELECT name FROM power_plants WHERE prefecture_id IS NULL;
