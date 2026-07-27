"""Diagnostic: why appearances come out with zero minutes.

    python diagnose.py --csv-dir ./data/transfermarkt --competition C1

Three hypotheses, in order of likelihood, and this script distinguishes them:

  H1. appearances.csv has no rows for this competition. The Swiss league was
      added to the dataset recently and may only exist in game_lineups.
  H2. game_id or player_id dtypes differ between the two tables. pandas merges
      without complaining and returns NaN for everything.
  H3. The known 2024/25 appearances gap is still open and affects these seasons.

If H1 or H3 holds, minutes can be reconstructed from game_events: starters
begin at minute 0, and substitution events say who went off, who came on, and
when. More work, but the data is there.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv-dir", type=Path, required=True)
    ap.add_argument("--competition", default="C1")
    args = ap.parse_args()
    d, comp = args.csv_dir, args.competition

    print("=" * 68)
    print(f"DIAGNOSTIC -- competition {comp}")
    print("=" * 68)

    # ---- What competitions exist ---------------------------------------
    comps = pd.read_csv(d / "competitions.csv")
    print(f"\nCOMPETITIONS IN DATASET: {len(comps)}")
    swiss = comps[comps.get("country_name", pd.Series(dtype=str))
                  .astype(str).str.contains("Switz", case=False, na=False)]
    if len(swiss):
        print("  Swiss competitions found:")
        for _, r in swiss.iterrows():
            print(f"    {r['competition_id']:>6}  {r['name']}  ({r.get('type','?')})")
    else:
        print("  No Swiss competitions.")
    print("\n  All available codes:")
    print("   ", ", ".join(sorted(comps["competition_id"].astype(str))))

    # ---- Match coverage -------------------------------------------------
    games = pd.read_csv(d / "games.csv", low_memory=False)
    g = games[games["competition_id"] == comp]
    print(f"\nMATCHES FOR {comp}: {len(g):,}")
    if len(g):
        print(g.groupby("season").size().to_string())
    target_games = set(g["game_id"])

    # ---- H1: do appearances exist for this competition? -----------------
    apps = pd.read_csv(d / "appearances.csv", low_memory=False)
    n_by_comp = (apps["competition_id"] == comp).sum()
    by_gameid = apps["game_id"].isin(target_games).sum()
    print(f"\nH1 -- APPEARANCES FOR {comp}")
    print(f"  rows with competition_id == '{comp}':  {n_by_comp:,}")
    print(f"  rows whose game_id belongs to {comp}:  {by_gameid:,}")
    if by_gameid == 0:
        print(f"  >> H1 CONFIRMED: appearances.csv does not cover {comp}.")
    else:
        print("  >> H1 ruled out: appearances do exist.")

    # ---- H2: compatible dtypes? -----------------------------------------
    lineups = pd.read_csv(d / "game_lineups.csv", low_memory=False)
    print("\nH2 -- JOIN KEY DTYPES")
    for col in ("game_id", "player_id"):
        ta, tl = apps[col].dtype, lineups[col].dtype
        flag = "" if ta == tl else "  <-- INCOMPATIBLE"
        print(f"  {col:10} appearances={str(ta):10} game_lineups={str(tl):10}{flag}")

    lu = lineups[lineups["game_id"].isin(target_games)]
    print(f"\n  game_lineups rows for {comp}: {len(lu):,}")
    if len(lu) and by_gameid:
        common = set(lu["player_id"]) & set(
            apps.loc[apps["game_id"].isin(target_games), "player_id"]
        )
        print(f"  player_ids common to both: {len(common):,}")

    # ---- H3: per-year gaps in appearances -------------------------------
    print("\nH3 -- GLOBAL APPEARANCE VOLUME BY YEAR")
    apps["year"] = pd.to_datetime(apps["date"], errors="coerce").dt.year
    vol = apps.groupby("year").size()
    med = vol.median()
    for year, n in vol.items():
        if pd.isna(year):
            continue
        share = n / med if med else 0
        flag = "  <-- GAP" if share < 0.70 else ""
        print(f"  {int(year)}  {n:>10,}  ({share:.2f}x median){flag}")
    print("  Note: the first and last years are usually partial, not broken.")

    # ---- Rescue path ----------------------------------------------------
    ev_path = d / "game_events.csv"
    print("\nRESCUE PATH -- game_events")
    if ev_path.exists():
        ev = pd.read_csv(ev_path, low_memory=False)
        ev_target = ev[ev["game_id"].isin(target_games)]
        print(f"  events for {comp}: {len(ev_target):,}")
        if len(ev_target):
            print("  event types present:")
            print(ev_target["type"].value_counts().to_string())
            subs = ev_target[ev_target["type"].astype(str)
                             .str.contains("Substitut", case=False, na=False)]
            print(f"\n  substitutions: {len(subs):,}")
            if len(subs):
                print("  >> Minutes CAN be reconstructed: starters from minute 0,")
                print("     plus substitutions for players on and off.")
    else:
        print("  game_events.csv is not in the directory.")


if __name__ == "__main__":
    main()