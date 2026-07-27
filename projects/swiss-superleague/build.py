"""Build the database from the transfermarkt-datasets CSVs.

    python build.py --csv-dir ./data/transfermarkt --competitions C1
    python build.py --self-test

Download the CSVs from Kaggle (davidcariboo/player-scores) or from the
dcaribou/transfermarkt-datasets repo. Minimum required files:
    competitions.csv  clubs.csv  players.csv  games.csv
    appearances.csv   game_lineups.csv  game_events.csv  player_valuations.csv

ONE LIMITATION TO KEEP IN MIND
------------------------------
Four statuses can be derived from these CSVs: started, substitute_on,
unused_sub and not_in_squad. `injured` CANNOT be derived, because the dataset
carries no injury data.

That is exactly the distinction the model most needs: separating "the manager
doesn't rate him" from "he wasn't available". Without it, every injured player
looks like a selection decision, which is precisely the error this project
exists to correct.

The fix is to scrape Transfermarkt's injury pages separately. Until then,
`not_in_squad` conflates the two and any published result has to say so.
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

import duckdb
import pandas as pd

import availability

SCHEMA = Path(__file__).parent / "schema.sql"

NEEDED = [
    "competitions", "clubs", "players", "games",
    "appearances", "game_lineups", "game_events", "player_valuations",
]


def normalize_name(name: str) -> str:
    """Strip accents and lowercase, so names match across sources.

    'Sergi Roberto' and 'Sergi Robertó' must collide; FBref and Transfermarkt
    disagree on accents constantly.
    """
    if not isinstance(name, str):
        return ""
    stripped = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return " ".join(stripped.lower().split())


def load_csvs(csv_dir: Path) -> dict[str, pd.DataFrame]:
    frames = {}
    for name in NEEDED:
        path = csv_dir / f"{name}.csv"
        if not path.exists():
            print(f"  {name}.csv missing -- skipped")
            continue
        frames[name] = pd.read_csv(path, low_memory=False)
        print(f"  {name}.csv: {len(frames[name]):,} rows")
    return frames


def derive_availability(
    lineups: pd.DataFrame, apps: pd.DataFrame, games: pd.DataFrame
) -> pd.DataFrame:
    """Cross squad lists with recorded minutes to get each player's status.

    game_lineups says who was in the eleven and who was on the bench.
    appearances says who played and for how long. The gap between them -- named
    but with no minutes -- is the `unused_sub`, the cleanest selection signal
    available in public data: the manager had him available and still left him
    on the bench.
    """
    valid_games = set(games["game_id"])
    lu = lineups[lineups["game_id"].isin(valid_games)].copy()

    played = apps[["game_id", "player_id", "minutes_played", "goals", "assists"]].copy()
    played = played.rename(columns={"minutes_played": "minutes"})
    played["minutes"] = pd.to_numeric(played["minutes"], errors="coerce").fillna(0)

    merged = lu.merge(played, on=["game_id", "player_id"], how="left")
    merged["minutes"] = merged["minutes"].fillna(0)
    merged["goals"] = merged["goals"].fillna(0)
    merged["assists"] = merged["assists"].fillna(0)

    is_starter = merged["type"].astype(str).str.contains("start", case=False, na=False)
    merged["status"] = "unused_sub"
    merged.loc[is_starter, "status"] = "started"
    merged.loc[~is_starter & (merged["minutes"] > 0), "status"] = "substitute_on"

    out = merged[[
        "game_id", "player_id", "club_id", "status", "minutes", "goals", "assists"
    ]].copy()
    return out.drop_duplicates(subset=["game_id", "player_id"])


def reset_tables(con) -> None:
    """Clear every table, children before parents.

    The build has to be re-runnable. Clearing only `competitions` failed on the
    second run, because the foreign key from `clubs` still referenced it -- and
    the insert would then have collided with the primary key anyway.

    Order matters: DuckDB enforces the declared foreign keys, so a parent
    cannot be emptied while a child still points at it.
    """
    for table in (
        "data_audit",            # no FKs, but stale audit results mislead
        "player_season_stats",
        "player_xref",
        "match_availability",
        "squad_memberships",
        "matches",
        "players",
        "clubs",                 # references competitions
        "competitions",
    ):
        con.execute(f"DELETE FROM {table}")


def build(csv_dir: Path, competitions: list[str], db_path: Path) -> None:
    print(f"Reading CSVs from {csv_dir}")
    f = load_csvs(csv_dir)
    missing = [n for n in ("competitions", "clubs", "players", "games") if n not in f]
    if missing:
        raise SystemExit(f"Essential tables missing: {missing}")

    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA.read_text(encoding="utf-8"))
    reset_tables(con)

    comps = f["competitions"]
    comps = comps[comps["competition_id"].isin(competitions)]
    if comps.empty:
        available = sorted(f["competitions"]["competition_id"].unique())[:40]
        raise SystemExit(
            f"None of {competitions} are in the dataset.\n"
            f"Available (first 40): {available}"
        )
    # Explicitly warn about requested competitions that don't exist. They used
    # to be dropped silently, which made it easy to believe they were processed.
    found = set(comps["competition_id"])
    absent = [c for c in competitions if c not in found]
    if absent:
        print(f"\n  WARNING: not in the dataset, skipping: {absent}")
        all_ids = sorted(f["competitions"]["competition_id"].astype(str).unique())
        print(f"  Available codes: {', '.join(all_ids)}")
    print(f"\nTarget competitions: {sorted(found)}")

    comp_ids = set(comps["competition_id"])
    clubs = f["clubs"][f["clubs"]["domestic_competition_id"].isin(comp_ids)]
    games = f["games"][f["games"]["competition_id"].isin(comp_ids)]

    con.execute(
        "INSERT INTO competitions SELECT competition_id, name, country_name, "
        "TRY_CAST(NULLIF(regexp_extract(CAST(tier AS VARCHAR), '\\d+'), '') AS INTEGER), "
        "'transfermarkt' FROM comps"
        if "tier" in comps.columns and "country_name" in comps.columns
        else "INSERT INTO competitions SELECT competition_id, name, NULL, NULL, "
             "'transfermarkt' FROM comps"
    )

    con.register("clubs_df", clubs)
    con.execute(
        "INSERT INTO clubs SELECT club_id, name, domestic_competition_id FROM clubs_df"
    )

    players = f["players"].copy()
    # Scope is defined by SQUAD MEMBERSHIP, not by having played.
    #
    # An earlier version filtered on who appeared in appearances.csv, which only
    # contains players who logged minutes. That erased from the database exactly
    # the players this project exists to rescue. The self-test caught it.
    #
    # game_lineups includes the bench, so the union of both sources captures
    # everyone who was named in a squad, played or not.
    in_scope: set = set()
    if "appearances" in f:
        in_scope |= set(
            f["appearances"].loc[
                f["appearances"]["competition_id"].isin(comp_ids), "player_id"
            ]
        )
    if "game_lineups" in f:
        game_ids = set(games["game_id"])
        in_scope |= set(
            f["game_lineups"].loc[
                f["game_lineups"]["game_id"].isin(game_ids), "player_id"
            ]
        )
    if in_scope:
        players = players[players["player_id"].isin(in_scope)]
    players["name_normalized"] = players["name"].map(normalize_name)
    con.register("players_df", players)
    con.execute("""
        INSERT INTO players
        SELECT player_id, name, name_normalized,
               TRY_CAST(date_of_birth AS DATE), position, sub_position, foot,
               TRY_CAST(height_in_cm AS INTEGER), country_of_citizenship
        FROM players_df
    """)

    # Backfill players who appear in game_lineups but are absent from
    # players.csv. There were 162 of these in the Swiss data, about 1% of rows.
    #
    # The tempting fix is to drop those availability rows. That would be a
    # mistake here: players missing from Transfermarkt's own player table are
    # disproportionately the obscure ones -- one-off youth call-ups, short-lived
    # squad fillers -- which is precisely the population this project exists to
    # analyse. Dropping them would bias the sample in the same direction as the
    # minutes threshold we are trying to correct.
    #
    # So we keep the rows and insert minimal placeholder players instead, with
    # the name from the lineup and everything else NULL. They stay visible, and
    # a NULL date_of_birth makes it obvious which ones are incomplete.
    if "game_lineups" in f:
        known = set(players["player_id"])
        game_ids = set(games["game_id"])
        lu = f["game_lineups"][f["game_lineups"]["game_id"].isin(game_ids)]
        orphan = lu[~lu["player_id"].isin(known)][["player_id", "player_name"]]
        orphan = orphan.drop_duplicates(subset=["player_id"]).copy()
        if len(orphan):
            orphan["name_normalized"] = orphan["player_name"].map(normalize_name)
            con.register("orphan_df", orphan)
            con.execute("""
                INSERT INTO players
                SELECT player_id, player_name, name_normalized,
                       NULL, NULL, NULL, NULL, NULL, NULL
                FROM orphan_df
            """)
            print(f"\nBackfilled {len(orphan):,} placeholder players absent from "
                  f"players.csv")
            print("  (kept deliberately: dropping them would bias against the")
            print("   obscure players this project is about)")

    con.register("games_df", games)
    con.execute("""
        INSERT INTO matches
        SELECT game_id, competition_id, TRY_CAST(season AS INTEGER),
               TRY_CAST(date AS DATE), CAST(round AS VARCHAR),
               home_club_id, away_club_id, home_club_goals, away_club_goals,
               home_club_manager_name, away_club_manager_name
        FROM games_df
    """)

    # Availability. Prefer appearances.csv where it covers the competition,
    # since that is the official figure; otherwise reconstruct from events.
    if "game_lineups" in f:
        apps_here = 0
        if "appearances" in f:
            apps_here = int(
                f["appearances"]["game_id"].isin(set(games["game_id"])).sum()
            )
        if apps_here > 0:
            print(f"\nAvailability from appearances.csv ({apps_here:,} rows).")
            avail = derive_availability(f["game_lineups"], f["appearances"], games)
            avail["on_minute"] = None
            avail["off_minute"] = None
        elif "game_events" in f:
            print("\nappearances.csv does not cover this competition:")
            print("reconstructing minutes from game_lineups + game_events.")
            avail = availability.reconstruct(f["game_lineups"], f["game_events"], games)
        else:
            print("\nNeither appearances nor game_events: no minutes possible.")
            avail = None
        if avail is not None and len(avail):
            avail = avail[["game_id", "player_id", "club_id", "status",
                           "on_minute", "off_minute", "minutes", "goals", "assists"]]
            con.register("avail_df", avail)
            con.execute("INSERT INTO match_availability SELECT * FROM avail_df")
            print(f"Availability: {len(avail):,} player-match rows")
            print(f"  statuses: {avail['status'].value_counts().to_dict()}")
            total = int(avail["minutes"].sum())
            # Plausibility check. Every match is 2 teams x 11 players x 90
            # minutes = 1,980 player-minutes on the pitch, regardless of how
            # many substitutions happen. Anything far below that means minutes
            # failed to join -- the exact failure that previously slipped
            # through looking like a healthy 15,353-row table.
            expected = len(games) * 1980
            ratio = total / expected if expected else 0
            print(f"  total minutes: {total:,} "
                  f"(theoretical {expected:,}, ratio {ratio:.2f})")
            if ratio < 0.80:
                print("  WARNING: implausibly low. Minutes likely did not join.")
                print("  Run diagnose.py before trusting this database.")
            elif ratio > 1.05:
                print("  WARNING: above the theoretical maximum. Check for")
                print("  duplicated lineup rows or extra-time handling.")
    else:
        print("No game_lineups: availability cannot be derived.")

    if "player_valuations" in f:
        pv = f["player_valuations"].copy()
        pv["season"] = pd.to_datetime(pv["date"], errors="coerce").dt.year
        pv = pv[pv["player_id"].isin(set(players["player_id"]))]
        pv = pv.sort_values("date").groupby(["player_id", "season"]).last().reset_index()
        con.register("pv_df", pv)
        con.execute("""
            INSERT INTO squad_memberships
            SELECT player_id, TRY_CAST(current_club_id AS BIGINT), season,
                   NULL, NULL, NULL, TRY_CAST(market_value_in_eur AS BIGINT), NULL
            FROM pv_df
            WHERE current_club_id IS NOT NULL
        """)

    print()
    for table in ("competitions", "clubs", "players", "matches",
                  "match_availability", "squad_memberships"):
        n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        print(f"  {table:22} {n:>10,}")

    con.close()
    print(f"\nDatabase written to {db_path}")


def self_test() -> int:
    """Build the database from synthetic CSVs, to validate the schema offline."""
    import tempfile

    print("SELF-TEST -- building from synthetic CSVs\n")
    tmp = Path(tempfile.mkdtemp())

    pd.DataFrame({
        "competition_id": ["C1"], "name": ["Super League"],
        "country_name": ["Switzerland"], "tier": ["first_tier"],
    }).to_csv(tmp / "competitions.csv", index=False)

    pd.DataFrame({
        "club_id": [1, 2], "name": ["FC Zurich", "FC Basel"],
        "domestic_competition_id": ["C1", "C1"],
    }).to_csv(tmp / "clubs.csv", index=False)

    pd.DataFrame({
        "player_id": [10, 11, 12],
        "name": ["Sergi Robertó", "Hans Müller", "Jean Dupont"],
        "date_of_birth": ["1998-03-01", "2004-07-15", "1996-11-30"],
        "position": ["Midfield", "Attack", "Defender"],
        "sub_position": ["Central Midfield", "Centre-Forward", "Left-Back"],
        "foot": ["right", "left", "left"], "height_in_cm": [180, 175, 185],
        "country_of_citizenship": ["Spain", "Switzerland", "France"],
    }).to_csv(tmp / "players.csv", index=False)

    pd.DataFrame({
        "game_id": [100, 101], "competition_id": ["C1", "C1"],
        "season": [2025, 2025], "date": ["2025-08-10", "2025-08-17"],
        "round": ["1", "2"], "home_club_id": [1, 2], "away_club_id": [2, 1],
        "home_club_goals": [1, 2], "away_club_goals": [0, 2],
        "home_club_manager_name": ["Ancelotti", "Xhaka"],
        "away_club_manager_name": ["Xhaka", "Ancelotti"],
    }).to_csv(tmp / "games.csv", index=False)

    # Player 12 is named in both squads but never gets a minute: the unused_sub
    # that conventional analysis wipes off the map.
    pd.DataFrame({
        "game_lineups_id": range(6), "game_id": [100] * 3 + [101] * 3,
        "club_id": [1, 1, 1, 1, 1, 1], "player_id": [10, 11, 12] * 2,
        "type": ["starting_lineup", "substitutes", "substitutes"] * 2,
        "player_name": ["Sergi Robertó", "Hans Müller", "Jean Dupont"] * 2,
    }).to_csv(tmp / "game_lineups.csv", index=False)

    pd.DataFrame({
        "appearance_id": ["a", "b", "c"], "game_id": [100, 100, 101],
        "player_id": [10, 11, 10], "player_club_id": [1, 1, 1],
        "competition_id": ["C1"] * 3, "minutes_played": [90, 20, 85],
        "goals": [1, 0, 0], "assists": [0, 1, 0],
    }).to_csv(tmp / "appearances.csv", index=False)

    pd.DataFrame({
        "game_event_id": ["e1"], "game_id": [100], "minute": [70],
        "type": ["Substitutions"], "club_id": [1], "player_id": [10],
        "player_in_id": [11], "description": [""], "player_assist_id": [None],
    }).to_csv(tmp / "game_events.csv", index=False)

    pd.DataFrame({
        "player_id": [10, 11, 12], "date": ["2025-06-01"] * 3,
        "market_value_in_eur": [2_000_000, 500_000, 300_000],
        "current_club_id": [1, 1, 1],
    }).to_csv(tmp / "player_valuations.csv", index=False)

    db = tmp / "test.duckdb"
    build(tmp, ["C1", "CH2"], db)

    con = duckdb.connect(str(db))
    print("\nChecks:")
    ok = True

    rows = con.execute(
        "SELECT status, count(*) FROM match_availability GROUP BY status ORDER BY 1"
    ).fetchall()
    print(f"  derived statuses: {dict(rows)}")
    expected = {"started": 2, "substitute_on": 1, "unused_sub": 3}
    if dict(rows) != expected:
        print(f"  FAIL: expected {expected}")
        ok = False

    invisible = con.execute("""
        SELECT p.name, count(*) AS squad_appearances, sum(a.minutes) AS minutes
        FROM match_availability a JOIN players p USING (player_id)
        GROUP BY p.name HAVING sum(a.minutes) = 0
    """).fetchall()
    print(f"  players named but with zero minutes: {invisible}")
    if not invisible:
        print("  FAIL: the project's central case is not being detected.")
        ok = False

    norm = con.execute(
        "SELECT name_normalized FROM players WHERE player_id = 10"
    ).fetchone()[0]
    print(f"  name normalization: 'Sergi Robertó' -> '{norm}'")
    if norm != "sergi roberto":
        print("  FAIL: accents are not being stripped.")
        ok = False

    mgr = con.execute("SELECT count(DISTINCT home_manager) FROM matches").fetchone()[0]
    print(f"  distinct managers stored: {mgr}")
    if mgr < 2:
        print("  FAIL: managers are not being stored.")
        ok = False

    con.close()
    print("\n" + ("OK -- schema holds and derivations are correct."
                  if ok else "FAILURES PRESENT."))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv-dir", type=Path)
    ap.add_argument("--competitions", nargs="+", default=["C1"])
    ap.add_argument("--db", type=Path, default=Path("football.duckdb"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.csv_dir:
        ap.error("--csv-dir is required (or use --self-test)")
    build(args.csv_dir, args.competitions, args.db)
    return 0


if __name__ == "__main__":
    sys.exit(main())