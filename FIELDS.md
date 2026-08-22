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
- area_demand rows are keyed on (datetime_jst, source), not datetime_jst alone. The same half-hour
  legitimately appears twice — once from the daily feed, once from the corrected monthly file. See
  "Decision — wind/solar schema and primary key".


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

### Columns — mapped and unmapped, 22 Aug 2026

Seven fields in the header. Four are mapped:

| Header | Maps to | Conversion |
|---|---|---|
| `日付` + `時間帯_自` | `datetime_jst` | strptime `%Y%m%d`, hour zero-padded |
| `エリア総需要量(kWh)` | `demand_mw` | ÷ 500 |
| `エリア風力・太陽光発電量(kWh)` | `wind_solar_mw` | ÷ 500, added 22 Aug |

**`エリア総発電量(kWh)` is deliberately NOT mapped.** It is total area *generation*.
`area_demand.supply_total_mw` is the monthly file's 合計 (col 21), a different quantity.
Mapping one into the other would make a column mean two things depending on which loader
wrote the row — the failure the wind/solar fork was decided to avoid. Revisit only with a
decision about what the column should mean, not by filling it because it is empty.

`時間コマ` and `時間帯_至` are unmapped and need no decision: the period index is
derivable and the end boundary is the next row's start.

**`wind_solar_mw` bounds: MIN 0.0 / MAX 3000.0.** The floor is 0.0 because wind and solar
legitimately produce nothing, and that costs the second unit guard — a double-converted
value lands near 2 MW, inside the band, where the same error on demand lands at ~5 and is
rejected by MIN_MW. For this column the header assertion in `_resolve_col` is the only
guard of that class. Max observed 579000 kWh = 1158 MW (`data/test_jisseki.csv`,
2026-08-01, summer); ceiling set above plausible installed capacity, not above the sample.

**Blank is unobserved.** Every row of the 2026-08-01 file carries a value — wind runs at
night, so the column never reached zero and never showed whether HEPCO writes `0` or ``.
Blank is read as `None`: the absence of a claim, not a claim of zero output. Not collected
into `pending`, because a spurious raise costs a day that cannot be refetched. If a blank
is ever seen alongside a published demand figure, revisit.

## Decision — wind/solar schema and primary key, 19 Aug 2026

A standing decision about the area_demand schema, not a note about one source.

Two separate choices below: how renewable output is laid out in columns, and what the
primary key is. The options are numbered rather than lettered, because "Option A" already
means the grain decision at the top of this file and a reader six weeks out should not be
able to read a rejection here as if it applied to the grain.

### Columns — chosen: column option 3, split plus derived total

Three columns: `wind_mw`, `solar_mw`, `wind_solar_mw`.

- Monthly rows carry all three. `wind_mw` and `solar_mw` come from cols 15 and 13; the
  loader writes their sum to `wind_solar_mw`.
- Daily rows carry `wind_solar_mw` only, from エリア風力・太陽光発電量 (kWh ÷ 500).
  `wind_mw` and `solar_mw` are NULL on every daily row, permanently. That NULL means
  "this source does not publish the split", not "not loaded yet" — nothing will ever fill it.

Costed rejections:

Column option 1 — store only the combined `wind_solar_mw` on both tracks. The loader adds
wind and solar before insert and keeps only the total, which is a one-way operation. 50 + 30
and 70 + 10 both land in the table as 80, and no query can tell them apart afterward.
Recovering the split means a schema migration, re-fetching every monthly CSV in the backfill,
and a full re-ingest. The sum is derivable from the parts on demand; the parts are never
derivable from the sum. This also forecloses rung 7 (curtailment against wind specifically),
which needs `wind_mw` alone.

Column option 2 — split columns only, no `wind_solar_mw`. The daily track publishes a combined
figure and nothing else, so under a two-column schema it has nowhere to put it: the value is
parsed and thrown away, and both renewable columns are NULL on every daily row. Rung 7 survives
(it draws on the monthly track alone), but the agreement check that the composite key exists to
make possible is then limited to total demand. The one renewable number the daily feed actually
publishes cannot be compared against the corrected monthly record, and the discrepancy that
check is meant to catch — a daily capture that disagrees with the archive on renewables — stays
invisible. Option 2 avoids the self-contradiction risk described below and buys nothing else.

Cost of option 3, accepted: on monthly rows `wind_solar_mw` is derived from two other columns
in the same row, so the row can contradict itself if a loader bug lands. A CHECK ties them
together rather than leaving the derived column free:

    CHECK (
      source <> 'hepco_monthly_areajukyu'
      OR (
        wind_mw       IS NOT NULL
        AND solar_mw       IS NOT NULL
        AND wind_solar_mw  IS NOT NULL
        AND abs(wind_solar_mw - (wind_mw + solar_mw)) < 0.05
      )
    )

Tolerance rather than equality because the source carries one decimal place and the columns are
REAL; 0.05 sits below the resolution of the data and above binary float noise. The constraint is
scoped to monthly rows because on daily rows `wind_solar_mw` is not derived from anything — it is
the measurement, and the two split columns are legitimately NULL.

The source literal is the exact string the loader writes, `'hepco_monthly_areajukyu'`, not the
shorthand "monthly" used in prose throughout this file. A CHECK against a literal no row ever
carries is a constraint that passes on every row, which is indistinguishable from no constraint
at all until someone reads the schema.

NULL semantics, decided rather than left open: on monthly rows all three columns are required to
be present. There is deliberately no `IS NULL` escape. SQLite treats a CHECK evaluating to NULL as
satisfied, so escapes would let a monthly row carry `wind_solar_mw` with `wind_mw` missing and pass
— a derived total with no parts, which is column option 1's failure mode reappearing one row at a
time and passing the constraint that exists to catch it. Requiring all three means a monthly row
with a blank in col 13 or 15 aborts the insert instead of loading half-formed. If HEPCO ever
publishes such a blank, that abort is how we find out, in the same spirit as `ROWS_PER_DAY = 47`
being asserted exactly rather than as a floor.

This constraint is only sound while `source` is `NOT NULL`. A NULL source makes `source <> '...'`
evaluate to NULL, which SQLite treats as satisfied, so the whole CHECK passes on any row with a NULL
source. Relaxing that column silently disables this constraint rather than loosening it.

### Primary key — chosen: composite, `PRIMARY KEY (datetime_jst, source)`

Costed rejection:

Single-column PK on `datetime_jst`. One timestamp admits one row, so a daily row and a monthly
row for the same half-hour cannot coexist. The Q1 agreement check becomes unaskable — the
self-join collapses both sides onto the same row and then requires it to carry two sources at
once, so no data state satisfies it. Worse than unaskable: it fails silently. The query returns
zero rows whether the sources agree or whether the comparison was never possible, and those two
outcomes are indistinguishable at the point of reading. Load-time behaviour is equally lossy —
the monthly backfill reaching an already-captured timestamp either aborts on the unique
constraint or overwrites the daily row, destroying the comparison in the act of setting it up.

### Consequences

- Loaders take an `ON CONFLICT (datetime_jst, source)` target; bare `INSERT OR REPLACE` is now
  unsafe and banned.
- Every DELETE and UPDATE must be scoped by source, not timestamp range alone.
- Both loaders rewritten: monthly keeps `wind_mw` and `solar_mw` separate and additionally writes
  their sum to `wind_solar_mw`; daily writes `wind_solar_mw` only and leaves both split columns NULL.
- A precedence view (monthly wins over daily where both exist) is required for reporting, since the
  table now legitimately holds duplicate timestamps.
- Q1 compares `demand_mw` and `wind_solar_mw` across the two sources. `wind_solar_mw` is the column
  that makes the renewable half of that check answerable at all, and is the reason option 3 was taken
  over option 2.
- Q1 must ship with a `half_hours_compared` count so an empty disagreement set is readable as a pass
  rather than a no-op.
- Rung 7 (curtailment against wind specifically) reads `wind_mw` from monthly rows only and ignores
  `wind_solar_mw` entirely.

## Decision — gap alerting and acknowledgement, 21 Aug 2026

A standing decision about how `gaps` reports, not a note about one source.

Options are lettered A/B/C here and scoped to alerting. "Option A" at the top of this file is the
grain decision and the wind/solar entry numbers its options for the same reason; a reader six weeks
out should not be able to read alert option A as either of those.

### Scope of the detector

`gaps` covers the daily jisseki track only — rows with `source = 'hepco_daily_jisseki'`. Everything
below about recoverable and permanent applies to that track and no other. If the loader writes a
different literal, fix it here first, for the same reason as the monthly literal in the wind/solar
CHECK.

Two exclusions, both of which would otherwise produce mail every night forever:

- The monthly track is not a gap source. A month not yet loaded is a backlog item, not a loss:
  the archive does not expire on a two-day clock, and there is no moment at which a missing month
  becomes unrecoverable. Treating monthly absence as gaps at day grain would mail 28–31 times for
  a single unloaded month, which is alert option A's failure mode arriving on day one.
- The 23:30–24:00 half-hour is never a daily gap. The daily file is finalised before its last
  period closes, so a complete daily capture is 47 rows and that period always comes from monthly.
  A detector working at half-hour grain without this exclusion reports one gap per day, forever,
  on a pipeline that is working correctly.

"Recoverable" is per source, not per date. The same date can be permanently gone from the daily
track and still pending from monthly, and those two facts are unrelated. Hence `gap_ack` is keyed
on (gap_date, source): acknowledging a permanent daily loss must not silence anything on the
monthly side.

### The window is one night, not two

From the retention measurements above: on day X the daily file for X−1 returns 200 and the file for
X−2 returns 404. `RETENTION_DAYS = 2` counts today and yesterday, which is one fetchable day behind
the current one, not two.

So for a missing day D:

| run          | age of D | state           |
|--------------|----------|-----------------|
| night of D+1 | 1        | recoverable     |
| night of D+2 | 2        | newly permanent |
| night of D+3 | 3+       | permanent       |

Exactly one nightly run ever sees D as recoverable. There is no second look — the run that mails
"this is still fixable" is the only run that will ever say so, and the window closes before the next
one. This is the arithmetic behind the two states; the states themselves are unchanged:

- Recoverable — the fetch can still be re-run, for the remainder of that one day.
- Permanent — the file is gone from HEPCO, nothing recovers it. There is no degraded or partial
  recovery between the two.

`gaps` runs nightly under cron; a non-zero exit mails. The decision is which of those two states
mails.

### Alerting — chosen: alert option C, mail through the transition, then acknowledge

One small table of gaps seen and accepted. The rule: mail while a gap is recoverable, mail again
when it crosses into permanent and every night after that until it is acknowledged, then silent
forever.

    CREATE TABLE gap_ack (
      gap_date TEXT NOT NULL,     -- 'YYYY-MM-DD', JST
      source   TEXT NOT NULL,
      acked_at TEXT NOT NULL,
      PRIMARY KEY (gap_date, source)
    );

Mailing until acknowledged rather than exactly once at the crossing, because a single crossing mail
is exactly as losable as the recoverable mails that preceded it — same inbox, same unchecked folder,
same broken cron. An option that announces a permanent loss once and then goes quiet on its own is
option B with the silence moved one night later. Only a human action ends the mail, so the mail
cannot end by accident. The noise is bounded because acknowledging is one command, and it is bounded
in a way A's is not: A's floor rises forever with no action available to lower it.

What this buys is a distinction the other two options cannot express: "8 August, known, already
mourned, don't tell me again" versus "a day just died last night and you didn't catch it". Under C
those are a silent night and a mailed night. Silence then means nothing new was lost — a claim
silence can only make if every loss is noisy until answered.

Costed rejections:

Alert option A — mail in both states. Every night, forever, a mail about 8 August, a day nothing can
fix. The permanent set only grows, so the noise floor only rises. Two weeks in the mail goes
unopened, and the night it finally carries a recoverable gap — the one night it was worth reading,
and with the corrected arithmetic there is only ever one — it is not read. The failure is not that A
is noisy; it is that A trains the reader to ignore the channel, which disables the recoverable alert
too. An alert that is reliably ignored is worse than no alert, because the absence of an alerting
system at least does not feel like coverage.

Alert option B — mail only while a gap is recoverable. Sensible, and what most people would build.
The hole is what happens when nobody is reading. A gap opens Saturday; B mails once, on the Sunday
run; the mail lands in an unchecked folder, or cron itself is broken, or it is a long weekend. By
the Monday run the day has aged past the window, and B goes quiet — it now classes the day as
unfixable, and unfixable things do not mail. So the moment the loss becomes irreversible, the single
most important thing that happened all week, produces silence. B is loudest when the problem is
smallest and stops exactly when the damage becomes permanent. Afterwards nothing anywhere records
that a permanent loss occurred; there is only a day quietly absent from the database,
indistinguishable on inspection from a day that was never expected. Under B, "no mail last night"
and "a day died last night" are the same observation.

Cost of option C, accepted: one table, one state transition, one flag or subcommand to acknowledge,
and one test asserting that a gap passes recoverable → newly-permanent → acknowledged without ever
going quiet in the middle step. With a one-night window that test is three runs, not four: run 1
mails recoverable, run 2 mails the crossing, run 3 after acknowledgement is silent. It should also
assert that run 3 without the acknowledgement still mails, since that is the clause separating C
from B. The middle step is the one B drops, so it is the one that has to be pinned. About 25
minutes, next week; today is the PK migration and the loaders.

### Consequences

- `gaps` exits non-zero for any daily-track gap not present in `gap_ack`, regardless of state, and
  zero once it is acknowledged. State changes the message, not the exit code.
- The crossing mail is a distinct message from the recoverable one — it reports a loss, not a task.
  Reading them as the same alert reintroduces B's ambiguity at the human end.
- Acknowledgement is an explicit action taken by a person. Nothing in the pipeline writes `gap_ack`
  automatically; an auto-ack on age is alert option B with extra steps.
- `gap_ack` is the only record in the project that a permanent loss happened on a given date. Treat
  it as data, not as alert state: it belongs in backup, and rows are never deleted.
- Silence from `gaps` is now load-bearing. Any future change that suppresses an unacknowledged gap —
  a rate limit, a digest, a severity filter — breaks the claim silence makes and needs this entry
  read first.

### Open

- "Recoverable" assumes the nightly run lands inside the one-day window. That depends on the cron
  schedule, which is decided at rung 4 on Sunday — a run time that drifts past the retention
  boundary collapses the recoverable state to zero runs and makes every gap a crossing.
- Acknowledgement must refuse a gap that is still recoverable. Acking a fixable day converts it to a
  permanent one by hand.

## Decision — A2, retain raw bytes, 21 Aug 2026

**Status: decided 21 Aug, NOT BUILT.** No fetcher has been touched.

The pipeline parses and discards. On a two-day feed that means a mapping bug can never be re-parsed
against what actually arrived — the hole we were standing in during the NULL-column diagnosis.
Fetchers will write the raw response to `data/raw/` gzipped before parsing.

Four pins:

- **Write before parse.** Fetch → write raw → parse. If the parse raises, the bytes are already on
  disk. Writing after a successful parse retains exactly the files that were never needed.
- **Filename is `{source}_{period}_{captured_at}.csv.gz`.** The monthly archive is retroactively
  corrected without notice, so `202607` fetched in August and `202607` fetched in December are two
  different files and the second must not overwrite the first. Capture date is provenance, not
  decoration.
- **Retain as received, before decoding.** Bytes, not text — the CP932 decode happens downstream of
  the write. This also means a failed fetch retains its UTF-8 404 HTML, which is the artifact that
  explains why a day is missing.
- **This does not fix `data/` being gitignored.** Raw retention protects against a parser bug and
  does nothing about a dead laptop. The off-machine copy is a separate open item in data/README.md
  and stays open.

Also, unrelated to any rung: line 1 of the jisseki file carries HEPCO's own file-update timestamp,
currently skipped. It is the only provenance the source volunteers — capture it.

Pruning: none yet. A daily CSV is single-digit KB.
