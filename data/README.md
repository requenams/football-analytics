# Data

Raw event data is **not** committed. It is pulled once via `statsbombpy` and
cached locally at `data/raw/isl_2122_events.pkl` (see `src/isl.py`).

- `data/raw/`        → gitignored source/cache data
- `data/processed/`  → small curated outputs used by notebooks/reports (committable)

StatsBomb free competitions & licence: https://github.com/statsbomb/open-data
