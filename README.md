# Football Analytics Portfolio ⚽ — Miguel Requena Micó

> Maths + Computer Engineering background with ML/AI research experience, moving into football data & recruitment analysis. This repository turns open event data into scouting-grade insight (one self-contained project per folder).

**Certifications:** Level 2 Technical Scouting in Football (PFSA, 2026)

**Focus:** player evaluation · recruitment shortlisting · data visualisation

**Stack:** Python · statsbombpy · soccerdata · mplsoccer · pandas · scikit-learn · Power BI (DAX)

**Data sources:** StatsBomb · FBref

📍 Murcia, Spain (open to relocation) · 🇪🇸 Native Spanish · 🇬🇧 Professional English · 🇩🇪 Basic German
🔗 [LinkedIn](https://www.linkedin.com/in/miguel-requena-mico) · ✉️ [requenams.data@gmail.com](mailto:requenams.data@gmail.com)

---

## Projects

| # | Project | What it demonstrates |
|---|---------|----------------------|
| 01 | [Attacking left-back — Indian Super League 2021/22](projects/isl-left-back) | Recruitment workflow with StatsBomb data: coverage due diligence, position filtering, per-90 within league percentiles, and a scouting report |
| 02 | [Swiss Super League forwards — scouting under data scarcity](projects/swiss-forwards) | A second data source (FBref via `soccerdata`) and honest handling of a basic-data league: what you can and cannot conclude without xG |
| 03 | [LaLiga 2015/16 Power BI scouting dashboard](https://github.com/requenams/laliga-powerbi-dashboard) | Star schema built from StatsBomb event data and a four page Power BI dashboard: per 90 rankings with a minutes threshold, position percentiles, shot maps and the title race |

*More on the way — see the roadmap.*

## Roadmap

- **Comparison of strikers in the Swiss league**
- **Recruitment shortlist tool**: percentile-ranked, with an interactive front end.

## Repository layout

```
data/        shared data cache (gitignored) + small processed outputs
projects/    one self-contained folder per project (code, notebook, report, figures)
```

## Data & credits

- **StatsBomb Open Data** — https://github.com/statsbomb/open-data (projects 01 and 03)
- **FBref** via `soccerdata` — https://fbref.com (project 02)

Data is not redistributed here. It is pulled at runtime and cached locally.
