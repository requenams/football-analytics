# Swiss Super League — scouting the playeres

A player database and scouting tool for the Swiss Super League.

**Live app:** _(add your Streamlit Cloud URL here once deployed)_

## The problem

Public football analysis filters players below roughly 900 minutes and throws
them away. The threshold is arbitrary — a peer-reviewed 2025 paper on defensive
valuation removes 53 of 348 players on exactly this basis and states in the text
that the cutoff is arbitrary but sufficient in the authors' opinion.

Two things follow, and neither is usually examined:

1. **The exclusion is not random.** Minutes are allocated by the manager, so
   filtering on minutes conditions the sample on a decision made by the best
   informed observer in the building. That is a selection effect, not a
   sample-size adjustment.

2. **The discarded group is the affordable one.** A 19-year-old with 400 minutes
   at Basel is invisible to every public radar, and he is precisely who a
   mid-budget club can sign. The players who *are* rankable are, by
   construction, the ones already playing and already priced accordingly.

In the two Swiss seasons covered here, **186 player-seasons** fall in the
270–899 minute band, and a further 59 per season were named in matchday squads
without ever playing a minute.

## What this repository does

Builds a DuckDB database in which absence is recorded rather than dropped, and
serves it through a Streamlit tool where the low-minute players are the default
view instead of the excluded remainder.

```
schema.sql        DuckDB schema
build.py          ingest transfermarkt-datasets CSVs
availability.py   reconstruct per-player minutes from lineups + events
audit.py          data quality checks
diagnose.py       source-data troubleshooting
queries.py        query layer (all SQL, self-tested)
app.py            Streamlit interface
```

## Reconstructed minutes

`appearances.csv` in the source dataset does not cover the Swiss Super League —
zero rows. Minutes are therefore rebuilt from `game_lineups` (who started, who
was benched) and `game_events` (who came on and off, and when), handling
substitutions, second substitutions and red cards.

The reconstruction is **better than the missing original**: `appearances.csv`
gives only a minutes total, whereas this recovers the on and off minute for
every appearance. Validated at 762,490 total minutes against a theoretical
ceiling of 851,400 (2 × 11 × 90 × 430 matches) — a ratio of 0.90, consistent
with the ~10% of matches that have incomplete lineup data.

## The three columns that don't exist elsewhere

Minutes and goals are available anywhere. These come out of the reconstruction:

| Column | Meaning |
|---|---|
| `bench_rate` | Share of matchday squads spent watching. The manager's opinion, quantified. |
| `avg_on_minute` | When he actually comes on. 55' is trust; 85' is garbage time. |
| `start_rate` | Share of squads where he was in the eleven. |

Two players with identical minutes can differ completely across these three,
which is the difference between a prospect and squad filler.

## Running it

```bash
pip install -r requirements.txt

# Download the source CSVs from Kaggle: davidcariboo/player-scores
# into ./data/transfermarkt/
python build.py --csv-dir ./data/transfermarkt --competitions C1
python audit.py --db football.duckdb

streamlit run app.py
```

Every module has a `--self-test` that runs without network or source data:

```bash
python availability.py --self-test   # 6 hand-computed minute cases
python build.py --self-test          # schema + ingestion on synthetic CSVs
python queries.py --self-test        # 9 consistency checks on the query layer
```

## Limitations

Stated because they constrain what the data can support, not as boilerplate.

**Injuries are not distinguishable.** Four statuses are derivable — `started`,
`substitute_on`, `unused_sub`, `not_in_squad` — but not `injured`, because the
source carries no injury data. That is the distinction the analysis most needs:
without it, a player who missed half a season injured looks identical to one the
manager rejected. Fixing it requires scraping Transfermarkt injury pages
separately.

**The invisible population is a floor, not a total.** Availability derives from
matchday squads, so anyone at a club all season who never made a single bench is
absent from the source entirely. The most extreme cases of rejection are the
ones missing.

**`squad_memberships` is not squad membership.** It is populated from valuation
records, so it carries market values but does not establish who was contracted
to a club in a given season.

**19 placeholder players** appear in lineups but not in the source player table.
They are kept, with a name and nothing else, rather than dropped — excluding
players missing from Transfermarkt's own records would bias the sample in the
same direction as the minutes threshold this project exists to question. Their
age is `NULL`, and filters treat that as unknown rather than as zero.

**Two seasons only** (2024/25 and 2025/26), with 20 managerial changes. Enough
for a scouting tool; not enough for the longitudinal modelling this database was
also designed to support. That work needs a multi-league panel.

## Data

Derived from [transfermarkt-datasets](https://github.com/dcaribou/transfermarkt-datasets)
by dcaribou, itself scraped from Transfermarkt. The committed `football.duckdb`
contains transformed and aggregated data, not the source files. Check the
upstream dataset's licence terms before reusing.