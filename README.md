# hokkaido-grid

Half-hourly electricity demand for the Hokkaido area, taken from two public HEPCO
feeds and stored in SQLite. The daily feed is fetched unattended by cron; the
monthly archive is loaded from a file. Both land in one table keyed on
`(datetime_jst, source)`, so that a same-week capture and HEPCO's later corrected
figure for one half-hour coexist rather than overwrite each other, with a view
that picks between them at query time. A CLI covers loading and reporting missing
periods; everything else is a SQL query against the database.

## What this is for

Holding a continuous half-hourly demand series that outlives its source. The daily
HEPCO feed serves today and yesterday and 404s at age 2 (measured), so a day not
captured within the window is gone from that feed permanently. The monthly archive
publishes the same periods later, corrected. Keeping both, tagged by origin, is
what lets the record survive the retention window.

## What it does not do

- **Not a forecasting system.** There is no model and no prediction anywhere in the
  repo. Every number stored is a published observation.
- **Not a real-time feed.** The daily job targets yesterday. The monthly archive is
  corrected after the fact. Nothing here is current within the day.
- **Not a replacement for HEPCO's own publication.** HEPCO is the authority and
  states that past months may be corrected retroactively, without notice, with no
  pre-correction version published. Anything here is a snapshot, and the capture
  date is part of the provenance.
- **Not a demand/weather product.** `weather_hourly` exists and April 2026 is
  loaded, but there is no weather fetcher. Weather files are downloaded by hand and
  passed to `main.py weather`.
- **Not installable.** See Known gaps.

## What would sit next to it

The curtailment series beyond April 2026 (the monthly file is the sole source for it), the 28-month archive backfill that extending it depends on, and Postgres plus Azure Monitor when this moves off a laptop.

## Curtailment, April 2026                                     

Curtailment is generation a grid operator orders off: output a solar or wind plant could have
produced but was told not to. In April 2026 solar or wind was curtailed in 141 of 1,440
half-hours on the Hokkaido grid. In Germany, the Bundesnetzagentur reports 9,379 GWh of renewable
generation curtailed for grid congestion in 2025, 3.5% of all renewable generation
([SMARD, 30 March 2026](https://www.smard.de/page/en/topic-article/5892/220534/volume-of-measures-stable-in-the-year-as-a-whole)).
The Hokkaido file records the volume curtailed but not the reason, so the two figures are not the
same measurement. The monthly half-hourly record from Hokkaido Electric Power Network (downloaded
25 July 2026) shows solar and wind curtailed on separate schedules, not as one block. On 12 April
the solar order ended after 15:30 while solar was still generating 405 MW at 16:00, and the wind
order ran on to 17:00. Across the month, 12 half-hours carried curtailment of solar or wind but
not both, 6 solar and 6 wind, and all 12 fell in daylight. The two were curtailed in the same
number of periods, 135 each, but not at the same scale: solar lost 15,895.5 MWh and wind
2,692.0 MWh, about a sixth as much. Wind's curtailment was 0.97% of its actual output for the
month. This is one month from one utility. A backfill across the monthly archive would test
whether both findings hold outside April.

## Provenance

```
HEPCO daily jisseki                     HEPCO monthly eria_jukyu
denkiyoho.hepco.co.jp                   hepco.co.jp/network/...
30-min, kWh, CP932                      30-min, MW, CP932
48 rows/day, 47 stored                  48 rows/day, 48 stored
~2-day retention                        archived to 2016年度
        │                                            │
   cron → bin/fetch_daily.sh                    by hand
   main.py daily YYYY-MM-DD              main.py monthly <path>
        │                                            │
   data/raw/  (raw bytes retained)                   │
        │                                            │
   merge: ON CONFLICT(datetime_jst,               replace: DELETE+INSERT,
   source) DO UPDATE, no delete                   month-scoped
        └────────────────────┬───────────────────────┘
                             ▼
              area_demand   PK (datetime_jst, source)
                             │
                             ▼
              area_demand_current   ← precedence lives here, monthly outranks daily
```

```
Open-Meteo ERA5  →  by hand  →  main.py weather <path>  →  weather_hourly
```

Units differ per source and are normalised on load, never in the schema: the
monthly file is already MW, the daily file is kWh and is divided by 500 for a
half-hour average. The two idempotency strategies differ for a reason the row
counts make plain — the monthly file holds a whole month so it can safely delete
and reload one, while the daily file supplies 47 of the day's 48 periods and a
day-scoped delete would destroy the 23:30 row it cannot put back. Neither loader
decides between the tracks: under the composite key a daily insert and a monthly
row carry different keys and cannot collide, so the only conflict the merge can
meet is a re-fetch of the same day by the same source. Cross-source precedence is
the view's job. Demand is stored at 30 minutes and weather at 60, each at its
source-native grain, with the bridge between them written in the query rather than
baked into storage.

## Data quality

**A 97-day hole, May to August 2026.** The last loaded period is
`2026-04-30 23:30` and the next is `2026-08-06 00:00`. Between them 4656
half-hour periods are missing; at 48 periods per day that is 97 whole days, and
the run is clean at both ends — it begins at `00:00` on 1 May and ends at `23:30`
on 5 August, with no partial day at either edge. The cause is that daily capture
began in August and April is the only month loaded from the archive. None of the
97 days is recoverable from the daily feed, which is two days deep. All of them
are available from the monthly archive, which is not yet acquired.

**23:30 is missing from every daily-source day and present in every monthly one.**
HEPCO writes all 48 rows and fills the ones closed at publication, and 23:30
cannot close before midnight, so that row is published empty at every age the
file is reachable — measured on `20260802_hokkaido_jisseki.csv`, still empty
when re-fetched on 3 August, and recorded in `FIELDS.md`.

As of 23 September 2026 the daily track is missing 17 days between 6 August and 22 September (799 half-hour periods): twelve early-August days from before scheduling was automated, three days the machine was off, and two days whose run failed with a retryable error and was never retried. The daily feed keeps about two days, so none of these can be re-fetched from it; the monthly archive is the recovery route.

## How it runs

`bin/fetch_daily.sh` wraps `main.py daily <yesterday>` and runs from cron at
`0 8` and `0 13`, plus an `@reboot` line added as interim cover. 
Each slot fires only if the machine is up at that time. From 14 to 19 September the machine booted after 08:00 every day, so every morning capture came from `@reboot`, and `0 13` did not run on the 17th or 18th. `@reboot` is in practice the primary capture path. Re-runs are harmless — the daily path merges rather than replaces, so a second fetch of the same day updates rows in place and changes nothing. On 2026-09-12 the machine was up at 08:00 and the job ran four times against the two scheduled.

- `state/last_success` — one ISO-8601 line, truncated on each write, written only
  on exit 0. The heartbeat.
- `logs/failures.log` — one appended line per non-zero exit, carrying the code and
  the target day.
- `logs/cron.log` — everything the run printed.

Both `logs/` and `state/` are gitignored. A `last_success` restored from a clone
would be a false claim that the pipeline ran.

Exit codes carry the failure taxonomy: 75 retry, 69 skip, 65 and 70 halt, 78
config, 3 gaps found, 4 init-db refused. None of them is 0, 1 or 2, which belong
to the interpreter. The full inventory and the reasoning is in
`hokkaido_grid/errors.py`.

## Schema

`area_demand` is half-hourly, one row per `(datetime_jst, source)`. The key is
composite so that a daily row and a monthly row for the same half-hour coexist
rather than overwrite each other. `area_demand_current` collapses it to one row
per timestamp with monthly outranking daily, and is the only place that rule
lives. The rule for reads is view-first, with `gaps` the one documented
exemption: decided 27 August and cited in `hokkaido_grid/gaps.py`, `FIELDS.md`
and `sql/queries/forward_step.sql`, on the grounds that the view hides source
identity and a gap report needs it. The queries under `queries/` predate the view
and have never been audited against the rule; `sql/queries/` holds the ones
written after it, each against the view. `weather_hourly` is hourly and
keyed on `datetime_jst` alone.

Column meanings, units, source layouts and the reasoning behind each decision live
in `FIELDS.md`. They are not restated here.

## Tests

66 tests, `uv run pytest`.

The suite pins the decisions that would otherwise break silently: that the four
error types stay siblings rather than a hierarchy, so a backfill loop's
`except SourceUnavailable: continue` cannot swallow a schema change; that a
month-scoped reload leaves the month beside it intact; that `init-db` refuses a
database that already holds objects; that a daily day is counted as 47 periods and
not 48. It does not show that the numbers in the database are right.

## Known gaps

- **The backfill is not acquired.** Closing the 97-day hole needs the 2026-05,
  2026-06 and 2026-07 monthly files plus the first five days of 2026-08. The wider
  archive runs 202404–202607, 28 months.
- **The two tracks have never overlapped.** Monthly holds April 2026; daily capture
  began in August. No half-hour in `area_demand` carries both a daily and a monthly
  row, so the composite key's collision case has never occurred with real data:
  `area_demand_current` has never had to choose, the two-track agreement check has
  never been askable, and the daily feed's `÷ 500` kWh conversion has never been
  compared against a monthly MW figure for the same period. That the daily column
  is kWh rests on the header assertion in the loader, not on a cross-check. The
  backfill is what would first test all three.
- **Curtailment covers April 2026 only**, and the monthly file is its only source. The archive has two layouts: 20 columns for 202404–202503 and 22 for 202504 onward, both breaking on a 年度 boundary. The 22-column layout adds 火力出力制御量 and バイオマス出力制御量 (observed by header name, 8 August); solar and wind curtailment are expected in both layouts, which is unverified until a 20-column file is on disk. A thermal or biomass total would step at 2025-04 for reporting reasons rather than grid reasons. Columns must be resolved by name: position 9 (counting from 1) is 火力出力制御量 in the 22-column layout and a different column in the 20-column one. 
- **`pyproject.toml` has no packages stanza.** No build backend is declared and no
  package discovery is configured, so the project cannot be installed. Tests pass
  only because `[tool.pytest.ini_options]` sets `pythonpath = ["."]`, and anything
  importing `hokkaido_grid` from outside the repo root fails.
- **The retry layer is not wired in.** `hokkaido_grid/fetch.py` implements backoff,
  `Retry-After` handling and a deadline, but `hepco_daily.fetch` calls
  `requests.get` directly. The only importer of `get_text` is `tools/try_get.py`.
  On a feed this shallow, one network blip is currently one lost day.
- **No weather fetcher.** `weather_hourly` is fed by hand.
