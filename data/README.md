
# data/

Raw source files for the Hokkaido grid capstone. **Not committed** (see `.gitignore`) —
regenerable from the sources below.

**Exception — the daily jisseki track is NOT regenerable.** Both daily HEPCO
feeds are ~2-day rolling tails. A file older than the tail cannot be re-fetched
by any means. test_jisseki.csv is a captured artifact, not a reproducible one;
the "regenerable" claim above covers the monthly archive and ERA5 only.

## hepco_demand_2026-04.csv
HEPCO area supply-demand actuals (エリア需給実績), April 2026. CP932, CRLF,
30-minute grain, MW. Local rename of `eria_jukyu_202604_01.csv`.

Regenerate:
    curl -sS "https://www.hepco.co.jp/network/con_service/public_document/supply_demand_results/csv/eria_jukyu_202604_01.csv" -o data/hepco_demand_2026-04.csv

Verified byte-identical to the source on 2026-08-08 (downloaded 2026-07-25).
NOTE: HEPCO may correct past months retroactively, without notice, and does not
publish pre-correction versions. Re-fetching is not guaranteed to reproduce this file.

## Monthly archive check — 2026-08-08

**Question:** does HEPCO archive past monthly エリア需給 files? (gates week 5)
**Answer: YES, back to 2016年度.**

Index (was recorded nowhere in this repo before today):
  https://www.hepco.co.jp/network/con_service/public_document/supply_demand_results/index.html
Monthly, 202404 onward:  .../csv/eria_jukyu_YYYYMM_01.csv
Quarterly, before that:  .../csv/sup_dem_results_YYYY_Nq.csv  (2018_2q is .xls)
  -> OUT OF SCOPE. Separate schema, separate parser. Not a gap; a decision.

**Provenance:** data/hepco_demand_2026-04.csv is byte-identical (124,600 B) to
eria_jukyu_202604_01.csv, fetched 2026-08-08, downloaded 2026-07-25.
Unchanged over 15 days — one observation, not a retention guarantee.

**TWO LAYOUTS, not one** (tools/check_monthly_schema.py, 28 months probed):
  layout 1  20 cols  202404..202503
  layout 2  22 cols  202504..202607  (+火力出力制御量, +バイオマス出力制御量)
The page announces a 様式変更 at 2024-04 and does not mention this one.
Both breaks fall on 1 April (年度 boundary); predict the next at 202704.

**Index-based parsing is unsafe across the break.** Position 8 = 水力 in
layout 1, 火力出力制御量 in layout 2. Resolve columns BY NAME and raise when
a name is absent. Same rule as the daily unit guard.

**Backfill scope: 28 months (202404-202607), not 16.** The four columns the
current schema loads — エリア需要 / 太陽光発電実績 / 風力発電実績 / 合計 —
exist in both layouts. The split constrains rung 7 only:
  solar + wind curtailment  -> comparable across all 28 months
  thermal + biomass         -> 202504 onward only
A summed "total curtailment" series would step at 2025-04 for reporting
reasons, not grid reasons. Week 10 decision, evidence recorded now.

**Mutability.** The page states past data may be corrected retroactively,
without notice, with no pre-correction version provided. A backfill is a
SNAPSHOT. Capture date is provenance. This justifies the monthly track's
full-reload DELETE+INSERT: newest correction wins.

**Revision suffix:** `_02` on 202404 returns 404; `_01` is constant as of today.
If a correction ever publishes as `_02`, URL construction 404s silently.

## weather_sapporo_2026-04.json
Open-Meteo ERA5 historical reanalysis. Sapporo (lat 43.06, lon 141.35 requested; ERA5
grid-cell centre 43.058, 141.429), April 2026, hourly, timezone Asia/Tokyo.
Endpoint: https://archive-api.open-meteo.com/v1/archive

Regenerate:
    curl "https://archive-api.open-meteo.com/v1/archive?latitude=43.06&longitude=141.35&start_date=2026-04-01&end_date=2026-04-30&hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,snowfall&timezone=Asia/Tokyo" -o data/weather_sapporo_2026-04.json

Grain: hourly, against half-hourly demand. Aggregate demand UP to hourly;
do not interpolate weather down — temperature between readings is unmeasured.
The column is MW, so hourly aggregation is a MEAN, not a SUM. Summing two
~2600 MW readings gives a plausible ~5200 and is wrong.

Spatial: one ERA5 grid cell (43.058, 141.429) standing in for area-wide
demand. Defensible for temperature — Sapporo metro carries much of the load.
NOT defensible for wind at rung 7: Hokkaido wind capacity is in Soya and
Tokachi, so wind_speed_10m here is a poor proxy for area wind output.

Latency: ERA5 reanalysis publishes on a delay; the daily demand feed expires
in ~2 days. LATENCY FIGURE NOT YET VERIFIED against Open-Meteo's docs. If the
delay exceeds the tail, the two sources cannot be fetched in one pass and
joined immediately — forward capture must store them separately and join later.

Licence: CC BY 4.0 — attribution required:
> Open-Meteo.com, CC BY 4.0. Zippenfenig, P. (2023). Open-Meteo.com Weather API.
> Zenodo. https://doi.org/10.5281/ZENODO.7970649
> ERA5 data by ECMWF / Copernicus Climate Change Service.
