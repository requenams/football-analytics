"""Competition coverage check.

Before committing to a league, verify how much of it StatsBomb open data
actually covers. This is what ruled MLS 2023 out (only 6 matches) and revealed
that La Liga open data is Barcelona's matches only, leaving the Indian Super
League 2021/22 as the one option with a full-season, rankable pool.

Run: python scripts/coverage_check.py
"""
from statsbombpy import sb
import warnings

warnings.filterwarnings("ignore")

COMPETITIONS = {
    "La Liga 2020/21":   (11, 90),
    "MLS 2023":          (44, 107),
    "Indian SL 2021/22": (1238, 108),
}

for name, (competition_id, season_id) in COMPETITIONS.items():
    matches = sb.matches(competition_id=competition_id, season_id=season_id)
    teams = sorted(set(matches["home_team"]) | set(matches["away_team"]))
    print(f"{name}: {len(matches)} matches | {len(teams)} teams")
    print("   ", teams, "\n")
