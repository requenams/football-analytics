# Attacking left-back — Indian Super League 2021/22

A self-contained scouting exercise: within one full-season league, identify the
most productive *attacking* left-back and back the call with data.

The point isn't the individual player — it's the workflow a recruitment
department actually runs: define a profile, verify the data is fit for purpose,
filter the pool honestly, rank on per-90 metrics, and write a recommendation
that is clear about its own limits.

## Why this league
The brief called for a **recent** season with **complete** coverage — you can't
rank a pool if you only hold a fraction of its matches. Before committing, I
checked what the StatsBomb free tier actually exposes (`coverage_check.py`):

- **MLS 2023** — only 6 matches available. Unusable.
- **La Liga** — open data covers Barcelona's fixtures only, not the league.
- **Indian Super League 2021/22** — a full season (115 matches, 11 teams), the
  only competition with a rankable, full-population sample.

So the ISL wasn't a fallback — it was the one league that met the criteria, and
confirming that up front is itself part of the method.

## Approach
1. `coverage_check.py` — competition due-diligence (above).
2. `isl.py` — load & cache events, compute minutes, build a clean pool of genuine
   left-backs (modal position, 900+ minutes).
3. `01_left_back_offensive_profile.ipynb` — attacking metrics per-90, ranked as
   within-league percentiles, visualised as pizza charts.
4. `report.md` — the scouting write-up.

## Read next
- **Full analysis:** [`01_left_back_offensive_profile.ipynb`](01_left_back_offensive_profile.ipynb)
- **Scouting report:** [`report.md`](report.md)

*Data: StatsBomb Open Data.*