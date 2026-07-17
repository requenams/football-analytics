# ⚽ Football Analytics Portfolio — Miguel [Last Name]

> Maths + Computer Engineering background with ML/AI research experience,
> moving into football data & recruitment analysis. This is where I turn
> open event data into scouting-grade insight.

**Focus:** player evaluation · recruitment shortlisting · data visualisation
**Stack:** Python · statsbombpy · mplsoccer · pandas · scikit-learn
**Data:** StatsBomb Open Data (credited under their terms)

📍 Zürich · 🇪🇸 Native Spanish · 🇬🇧 Professional English · 🇩🇪 German (A2)
🔗 [LinkedIn](URL) · [X / Twitter](URL) · ✉️ [email]

---

## Featured project

### Finding an attacking left-back in the Indian Super League (2021/22)
A data-driven scouting exercise: define an attacking left-back profile, rank
every genuine LB in a full-season league on per-90 metrics, and surface the
standout target — the workflow a recruitment department actually runs.

Highlights the parts that matter to a club: honest data due-diligence (which
competitions even have usable coverage), position filtering that removes
mis-tagged players, per-90 normalisation, and within-league percentiles with
their sample-size caveats stated up front.

→ Notebook: [`notebooks/01_left_back_offensive_profile.ipynb`](notebooks/01_left_back_offensive_profile.ipynb)

---

## Roadmap
- **Defensive left-back profile** — the second job the same position can do.
- **Expected-goals model** — my own xG model trained on StatsBomb shot data.
- **Recruitment shortlist tool** — percentile-ranked, with an interactive front end.

## Repository structure
```
data/          raw cache (gitignored) + small processed outputs
scripts/       one-off data checks (e.g. competition coverage)
src/           reusable pipeline: loading, minutes, pool building
notebooks/     analysis + reports
reports/       finished figures and write-ups
```

## Data & credits
StatsBomb Open Data — https://github.com/statsbomb/open-data
Not redistributed here; pulled at runtime via `statsbombpy` and cached locally.
