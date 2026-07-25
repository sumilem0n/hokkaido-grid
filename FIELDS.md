
# Data dictionary — hokkaido-grid

## Grain decision (Option A — store native, bridge at query time)
- area_demand is stored at 30-min; weather_hourly at 60-min. Both exactly as the source gives them.
  Nothing is interpolated into storage.
- To correlate, floor the demand minute to the hour in the query:

    SELECT d.datetime_jst, d.demand_mw, w.temperature_c
    FROM area_demand d
    JOIN weather_hourly w
      ON strftime('%Y-%m-%d %H:00', d.datetime_jst) = w.datetime_jst;

  This carries each hour's weather across its :00 and :30 demand rows. The choice lives in the query,
  so it is reversible and documented — not fabricated in the tables.
- datetime_jst is a JST local-time string. Safe as a key because Japan has no DST (no duplicated or
  skipped local hour → no collision). In a DST zone you would key on UTC instead.

## Source A — HEPCO area supply-demand actuals
- File: data/hepco_demand_2026-04.csv  (monthly, one file per month)
- Publisher: 北海道電力ネットワーク (Hokkaido Electric Power Network)
- Encoding: CP932 (Shift-JIS superset). NOT UTF-8 — loader must open(..., encoding="cp932").
- Line endings: CRLF (Windows-authored).
- Unit: MW (the banner row reads 単位[MW平均]). NO ×10 — this file is already MW, not 万kW.
- Structure: line 1 = unit/group banner (SKIP 1); line 2 = header; lines 3..1442 = data
  (30 days × 48 half-hours = 1440 rows); then ~48 trailing all-comma blank rows (DROP — empty DATE).
- Grain: 30-min, JST.
- Caveats: values are retroactively corrected; rounding can make components not sum exactly; solar
  self-consumption is excluded (shows up as reduced demand). 合計 = sum of all supply components and
  equals エリア需要 in a balanced grid.

Column inventory (index -> field). Kept columns marked [x]; the rest exist and can be added later.

| idx | raw (JP)              | meaning              | unit | notes                                   |
|-----|----------------------|----------------------|------|-----------------------------------------|
| 0   | DATE                 | date                 | -    | -> datetime_jst (with TIME)             |
| 1   | TIME                 | half-hour            | -    | -> datetime_jst                         |
| 2   | エリア需要            | area demand          | MW   | [x] demand_mw                           |
| 3   | 原子力                | nuclear              | MW   | supply                                  |
| 4   | 火力(LNG)            | thermal LNG          | MW   | supply                                  |
| 5   | 火力(石炭)           | thermal coal         | MW   | supply                                  |
| 6   | 火力(石油)           | thermal oil          | MW   | supply                                  |
| 7   | 火力(その他)         | thermal other        | MW   | supply                                  |
| 8   | 火力出力制御量        | thermal curtailment  | MW   |                                         |
| 9   | 水力                  | hydro                | MW   | supply                                  |
| 10  | 地熱                  | geothermal           | MW   | supply                                  |
| 11  | バイオマス            | biomass              | MW   | supply                                  |
| 12  | バイオマス出力制御量   | biomass curtailment  | MW   |                                         |
| 13  | 太陽光発電実績        | solar output         | MW   | [x] solar_mw — weather-sensitive        |
| 14  | 太陽光出力制御量      | solar curtailment    | MW   |                                         |
| 15  | 風力発電実績          | wind output          | MW   | [x] wind_mw — weather-sensitive         |
| 16  | 風力出力制御量        | wind curtailment     | MW   |                                         |
| 17  | 揚水                  | pumped storage       | MW   | can be NEGATIVE                         |
| 18  | 蓄電池                | battery              | MW   | can be NEGATIVE                         |
| 19  | 連系線                | interconnector       | MW   | can be NEGATIVE                         |
| 20  | その他                | other                | MW   |                                         |
| 21  | 合計                  | total supply         | MW   | [x] supply_total_mw; = demand balanced  |

## Source B — Open-Meteo Historical (ERA5)
- File: data/weather_sapporo_2026-04.json
- Endpoint: https://archive-api.open-meteo.com/v1/archive
- Requested point: lat 43.06, lon 141.35 (Sapporo). ERA5 grid-cell centre returned: 43.058, 141.429
  (~6 km E), elevation 26 m — a documented approximation, not an error.
- Timezone: Asia/Tokyo, utc_offset_seconds 32400 (JST). Timestamps are JST local, hourly on the hour.
- Structure: "hourly" holds parallel arrays — time[], temperature_2m[], ... all equal length; index i
  is one hour. Loader zips them into rows.
- Licence: CC BY 4.0 — attribution in data/README.md.

| field                | meaning       | unit        | valid time          | notes                          |
|----------------------|---------------|-------------|---------------------|--------------------------------|
| time                 | timestamp     | ISO8601 JST | -                   | -> datetime_jst                |
| temperature_2m       | air temp @2m  | °C          | instant             | -> temperature_c               |
| relative_humidity_2m | RH @2m        | %           | instant             | -> relative_humidity_pct       |
| precipitation        | precipitation | mm          | preceding-hour SUM  | -> precipitation_mm            |
| snowfall             | snowfall      | cm          | preceding-hour SUM  | -> snowfall_cm; 7 cm ~= 10 mm  |
| wind_speed_10m       | wind @10m     | km/h        | instant             | -> wind_speed_kmh              |

## Canonical key
- datetime_jst: TEXT 'YYYY-MM-DD HH:MM', JST. area_demand at :00 and :30; weather_hourly at :00 only.
