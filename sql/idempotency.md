# Two idempotency strategies, two cadences

Monthly track: DELETE + INSERT. Daily track: INSERT with a guarded ON CONFLICT.
Written 11 Aug 2026, week 5 day 2.

## 1. Why the monthly track deletes and reloads

The file is the whole month. Everything the delete removes is in the list about
to go back in. Same scope both sides, so the table ends up equal to the file.

## 2. Why the daily track must not

The daily file has 47 rows. The day has 48 periods. The delete window covers
all 48. It removes one more row than it can replace, every run.

## 3. What the rule means for each

Monthly deletes a month and holds a month — allowed. Daily deletes a day and
holds 47/48 — not allowed. It isn't about how big the delete is, it's about
whether you hold everything inside it.

## 4. Which clause, and what it does on a repeat

Guarded `ON CONFLICT DO UPDATE`, with the daily delete removed. The daily track
stops deleting and merges instead. The update sets all five value columns
(demand_mw, solar_mw, wind_mw, supply_total_mw, source).

- Same source rewriting its own row -> updates.
- Monthly landing on a daily row -> updates.
- Daily landing on a monthly row -> does nothing.

## 5. What happens when the other source hits that timestamp

Today: the delete matches on time and ignores source, so a daily run over a
monthly-loaded day wipes all 48 monthly rows, writes back 47, and flips
`source` to daily for the whole day. One row of data lost, a full day of
provenance lost, and nothing in the row count shows it.

Under the guard: daily no-ops on monthly rows. 23:30 survives, the rest stay
monthly. Monthly wins regardless of which job ran first — that
order-independence is the point.

## 6. What the alternatives cost, and what mine costs

`OR REPLACE` is unconditional: last writer wins. Daily would still overwrite
monthly, just without the delete. `OR IGNORE` is the opposite failure — first
writer wins, so a corrected file never lands.

But the bigger cost applies to my own choice too. Once the daily path stops
deleting, nothing on that path ever removes a row. A retraction, or a corrected
file with fewer rows, leaves the old rows sitting there. Idempotency drops from
*table equals file* to *table contains file* — and the row count won't tell you
which one you've got.

The answer to that is the monthly track. It deletes a whole month and reloads it
from a file that holds a whole month, so any ghost rows the daily merge left
behind die there. The shrink property isn't lost, just deferred to month grain —
provided week 6 builds the month-scoped window, which the 30 Aug backfill
deadline depends on.

## Note

The source names in the ON CONFLICT guard also live in the `source` CHECK
constraint in `schema.sql`. One fact, two homes. A third source turns the
literal into data — a rank column or a precedence table.

## Measured 11 Aug

**`rowcount` counts rows the guard let through, not rows whose values changed.**
A re-run with identical data reported 47 of 47 — SQLite counts a `DO UPDATE`
that writes a column its existing value as a write. With one monthly row planted
at a timestamp the daily file covers, it reported 46 of 47. So "left to a better
source" is measured, not inferred; it does not mean "rows that differ."

**`fetch` refuses an incomplete day, so a partial day never reaches merge.**
Observed at 18:56 on 10 Aug: 10 of 47 periods unpublished, `SourceTransientError`
raised. Merge exists so a later run can top up a day, but that path is blocked
upstream. Week 6's cron decision: one run late enough to be safe, or repeated
runs with `fetch` returning partial days and merge filling the gaps. The second
is only possible if the completeness check moves out of `fetch`.
