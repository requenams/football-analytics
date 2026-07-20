# Swiss Super League forwards — scouting under data scarcity (2025/26)

> 🚧 **Work in progress.** The data pipeline and percentile charts are in progress, 
> so the written scouting report is still not written.

A scouting exercise on three young Super League forwards (Maluvunu, Efekele,
Zvonarek) — and a deliberate test of what's possible when the data is thin.

The point here is as much method as players: on FBref, this league exposes only
*basic* data — goals, shots, fouls, aerials — with no xG, creation or dribbling.
This project shows how to profile honestly under that constraint, and where it
breaks down.

## Why a second data source
Switzerland isn't in the StatsBomb free tier, so this project pulls from **FBref
via `soccerdata`** — a different pipeline (a scraper, not an API) and a chance to
work across providers rather than a single source.

## What the data supports — and what it doesn't
- **Supports:** output and shot profile, against a large peer group (n≈71), which
  keeps the percentiles stable.
- **Doesn't:** no xG, so finishing quality can't be separated from variance; no
  creation or carrying, so a forward's link play is invisible; and it flatters
  poachers while burying creative players — e.g. Zvonarek, a creative attacker,
  scores low on a pure-finishing profile that simply can't see his game.

## Files
- `forwards_report.py` — the basic-data pizza (what Switzerland actually allows).
- `engine.py` — a general FBref / `soccerdata` engine for leagues *with* advanced
  data; kept for reuse, though its advanced metrics don't populate for Switzerland.

*Data: FBref via `soccerdata`.*