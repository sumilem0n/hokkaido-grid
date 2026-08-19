
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


## Daily source verification — 2026-08-01

Fetched and inspected the live HEPCO daily URLs. Every assumption in §5 was
wrong in some way; corrected below.

### Retention (HEAD requests, HTTP status)
- juyo_01_YYYYMMDD.csv:  Aug 1 & Jul 31 = 200; Jul 30 and older = 404
- YYYYMMDD_hokkaido_jisseki.csv:  Jul 31 = 200; Jul 28 and older = 404
- BOTH daily files are a ~2-day rolling tail. No historical archive at these URLs.

### File shapes
| File | Grain | Content | Units | Curtailment |
|---|---|---|---|---|
| monthly エリア需給 | 30-min | 22-col fuel breakdown | MW | YES (出力制御) |
| daily juyo_01 | hourly (section 3 of a multi-section file) | demand/forecast/usage-rate | 万kW (x10 vs MW) | no |
| daily jisseki | 30-min | total demand / total gen / wind+solar gen | kWh | no (generation, not curtailment) |

### Key findings
- juyo_01 is a MULTI-SECTION file: peak/reserve summary blocks first, then an
  hourly DATE,TIME,当日実績,予測値,使用率,供給力想定値 table starting ~line 10.
  inspect_csv.py's "which line is the header" limit fired here as expected;
  read past it by hand. Confirmed logged limitation + workaround.
- jisseki is a clean single-table 30-min daily preliminary actuals (superseded by the monthly corrected record). Has
  エリア風力・太陽光発電量 (wind+solar GENERATION) — useful as a curtailment
  denominator, but NOT curtailment itself.
- THREE different units across three files (MW / 万kW / kWh). Any loader must
  convert per-source. This is the ×10 unit trap from Day 1, now ×3.
- All three files: cp932/shift_jis decode clean, utf-8 raises. juyo & jisseki
  are LF; monthly is CRLF.

**Partially superseded — see "hepco jisseki (daily) — source picture" (2026-08-03).**
Wrong here: "clean single-table" (two banner lines), "~2-day tail" (one day),
column names (carry unit suffixes).

### Decisions
1. Curtailment (rung 7): MONTHLY file is the sole source. Confirmed.
2. Backfill: CANNOT come from either daily URL (2-day tail). Week 5's "90-day
   backfill from the daily source" is void as written. History must come from
   archived MONTHLY files (check whether HEPCO archives past months — TODO).
3. Daily operational spine: use JISSEKI, not juyo. Cleaner structure, 30-min
   grain matches area_demand, daily preliminary actuals. Cost: kWh->MW conversion,
   hour-floor weather join (loader already does this).
4. Pipeline's real job = FORWARD CAPTURE. Both daily feeds vanish in ~2 days,
   so a missed cron fetch is permanent unrecoverable data loss. Raises the
   stakes on rung 5 (fail loudly) and monitoring.

### Consequences for the plan
- Week 4 rung 1: fetch jisseki (not the guessed juyo URL). URL pattern:
  https://denkiyoho.hepco.co.jp/area/data/YYYYMMDD_hokkaido_jisseki.csv
- Week 5: rewrite "90-day backfill" -> "start daily capture now; backfill
  history from monthly archive if available."
- New loader concern: unit conversion per source (MW / 万kW / kWh).

## hepco jisseki (daily) — source picture

Corrected 2026-08-03. Three assumptions from the original plan were wrong;
all three are recorded here with the measurement that overturned them.

### Retention: 2 days

| date fetched | target | age | result |
|---|---|---|---|
| 2026-08-01 | 2026-07-31 | 1 | 200 |
| 2026-08-01 | 2026-07-28 | 4 | 404 |
| 2026-08-03 | 2026-08-02 | 1 | 200 |
| 2026-08-03 | 2026-08-01 | 2 | 404 |

The window is today and yesterday. One shot per day — a missed cron run
loses that day permanently, with no second attempt possible. §5's "~2-day
tail" is wrong and should read one.

`RETENTION_DAYS = 2` in sources/hepco_daily.py.

### The daily file is 47 rows, not 48

`20260802_hokkaido_jisseki.csv`:
- internal stamp `20260802,23:42:44,20260802`
- `last-modified: Sun, 02 Aug 2026 14:59:03 GMT` (23:59:03 JST)
- `時間コマ 48` (23:30–24:00): date, index and both boundary times present,
  all three measurement columns empty
- still empty when re-fetched 2026-08-03; the file is never rewritten

The file is finalised before its last period closes, so 23:30–24:00 never
appears in the daily feed at any age. A complete daily file is 47 rows.
That period comes from the monthly file — this is why the two-track design
exists, every day, not as a backfill for missed runs.

One observation. `ROWS_PER_DAY = 47` is asserted exactly rather than as a
floor, so a 48-row day fails loudly: that assert firing is how we find out
HEPCO changed its publishing behaviour.

### File shape

    line 1  ファイル更新日,ファイル更新時間,対象年月日
    line 2  20260802,23:42:44,20260802
    line 3  日付,時間コマ,時間帯_自,時間帯_至,エリア総需要量(kWh),
            エリア総発電量(kWh),エリア風力・太陽光発電量(kWh)
    line 4  20260802,1,0:00,0:30,1193000,1338500,165000

Two banner lines, then the header — the plan said this file was banner-free.
Dates are `%Y%m%d`, not slashed. The demand column carries its unit in the
name; the code matches the prefix and asserts `kWh` separately, because a
change to 万kW would silently break the ÷500 conversion.

Encoding CP932. 404 responses are UTF-8 HTML, so status is checked before
decoding.

### Bounds

MIN_MW 1500 / MAX_MW 6000, set 2026-08-03 from area_demand: measured
2440.0–3948.0 over 1440 rows (30 days). Headroom widened both ways because
the sample is one shoulder-season month with no winter peak or summer
trough. Every wrong unit convention lands outside: raw kWh ~1.2e6,
double-converted ~5–8, 万kW ~250–400 or ~24000–40000. Observed daily file
checks out: 1193000 ÷ 500 = 2386 MW at 00:00.

### Decision — wind/solar schema, 19 Aug 2026

Chosen: Option B on columns (keep wind_mw and solar_mw separate; combine in the query via CASE source). Option C on the key (PRIMARY KEY (datetime_jst, source)).

Costed rejections:

Option A — store only the combined wind_solar_mw. The loader adds wind and solar before insert and keeps only the total, which is a one-way operation. 50 + 30 and 70 + 10 both land in the table as 80, and no query can tell them apart afterward. Recovering the split means a schema migration, re-fetching every monthly CSV in the backfill, and a full re-ingest. The sum is derivable from the parts on demand; the parts are never derivable from the sum. This also forecloses rung 7 (curtailment against wind specifically), which needs wind_mw alone.

Single-column PK on datetime_jst. One timestamp admits one row, so a daily row and a monthly row for the same half-hour cannot coexist. The Q1 agreement check becomes unaskable — the self-join collapses both sides onto the same row and then requires it to carry two sources at once, so no data state satisfies it. Worse than unaskable: it fails silently. The query returns zero rows whether the sources agree or whether the comparison was never possible, and those two outcomes are indistinguishable at the point of reading. Load-time behaviour is equally lossy — the monthly backfill reaching an already-captured timestamp either aborts on the unique constraint or overwrites the daily row, destroying the comparison in the act of setting it up.

Consequences:

Loaders take an ON CONFLICT (datetime_jst, source) target; bare INSERT OR REPLACE is now unsafe and banned.
Every DELETE and UPDATE must be scoped by source, not timestamp range alone.
Both loaders rewritten: monthly stops summing at load, daily writes wind_solar_mw only.
A precedence view (monthly wins over daily where both exist) is required for reporting, since the table now legitimately holds duplicate timestamps.
Q1 must ship with a half_hours_compared count so an empty disagreement set is readable as a pass rather than a no-op.

Re-ask trigger: the monthly archive gaining a published combined column, or the daily feed gaining a wind/solar split. Either collapses the source→column asymmetry that the CASE currently keys on, at which point the combine rule should be re-derived rather than patched. A third source (JEPX, OCCTO) is a weaker trigger for the column question but forces re-examination of the precedence view.

