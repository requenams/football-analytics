"""Data quality audit for the built database.

    python audit.py --db football.duckdb

This is not optional. transfermarkt-datasets is an automated scrape with
documented gaps -- the most serious reported one lost roughly 66% of all
appearances for the entire 2024/25 season across every competition, with
players like Haaland showing zero records despite playing all year. Your
download may or may not have that fixed.

A hole like that is invisible in a notebook: per-90 figures look plausible and
rankings look reasonable. It only shows up if you go looking for it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import duckdb


def _record(con, name: str, scope: str, passed: bool, detail: str) -> None:
    con.execute(
        "INSERT INTO data_audit VALUES (?, ?, ?, ?, ?)",
        [datetime.now(), name, scope, passed, detail],
    )


def check_season_volume(con) -> bool:
    """Flag seasons with an anomalous volume of recorded appearances.

    Compares each season against the median. A sharp drop nearly always means
    an incomplete scrape, not an unusual season.
    """
    rows = con.execute("""
        SELECT m.season,
               count(*) FILTER (WHERE a.minutes > 0) AS with_minutes,
               count(DISTINCT a.player_id)           AS players,
               count(DISTINCT m.game_id)             AS matches
        FROM match_availability a JOIN matches m USING (game_id)
        GROUP BY m.season ORDER BY m.season
    """).fetchall()
    if not rows:
        print("  nothing to audit")
        return False

    per_game = [(s, c / p if p else 0, c, j, p) for s, c, j, p in rows]
    ratios = sorted(r for _, r, _, _, _ in per_game)
    median = ratios[len(ratios) // 2]

    print(f"  {'season':>7} {'matches':>9} {'appear.':>9} {'per match':>11}")
    ok = True
    for season, ratio, with_min, _players, matches in per_game:
        share = ratio / median if median else 0
        flag = ""
        if share < 0.70:
            flag = "  <-- GAP"
            ok = False
        elif share < 0.85:
            flag = "  <-- thin"
        print(f"  {season:>7} {matches:>9,} {with_min:>9,} {ratio:>11.1f}{flag}")

    if not ok:
        print("\n  Some seasons have serious gaps. Before using them, check")
        print("  whether the appearances issue is still open and pull a newer")
        print("  release of the dataset, or exclude those seasons.")
    return ok


def check_availability_statuses(con) -> bool:
    """Verify the project's central signal exists and is plausible.

    If unused_sub comes out at zero, game_lineups didn't load and the whole
    premise of the selection model has no data behind it.
    """
    rows = con.execute("""
        SELECT status, count(*) AS n,
               round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
        FROM match_availability GROUP BY status ORDER BY n DESC
    """).fetchall()
    for status, n, pct in rows:
        print(f"  {status:16} {n:>10,}  {pct:>5}%")

    counts = {r[0]: r[1] for r in rows}
    if counts.get("unused_sub", 0) == 0:
        print("\n  unused_sub is zero: game_lineups is missing. Without that")
        print("  table there is no selection signal and no project.")
        return False
    if counts.get("substitute_on", 0) == 0:
        print("\n  substitute_on is zero: minutes never joined. Either")
        print("  appearances.csv doesn't cover this competition, or the")
        print("  reconstruction failed. Run diagnose.py.")
        return False
    return True


def check_invisible_population(con) -> bool:
    """Size the market: players named in squads with very few minutes.

    This is the population the conventional threshold discards. If it is small,
    the project may be methodologically right and still not worth doing *here*.
    """
    rows = con.execute("""
        WITH per_season AS (
            SELECT a.player_id, m.season,
                   sum(a.minutes) AS minutes,
                   count(*)       AS squad_appearances
            FROM match_availability a JOIN matches m USING (game_id)
            GROUP BY a.player_id, m.season
        )
        SELECT season,
               count(*)                                            AS in_squad,
               count(*) FILTER (WHERE minutes < 900)                AS below_threshold,
               count(*) FILTER (WHERE minutes BETWEEN 270 AND 899)  AS useful_band,
               count(*) FILTER (WHERE minutes = 0)                  AS never_played
        FROM per_season GROUP BY season ORDER BY season
    """).fetchall()
    print(f"  {'season':>7} {'in squad':>9} {'<900min':>9} {'270-899':>9} {'0 min':>7}")
    total_useful = 0
    for season, squad, below, useful, never in rows:
        pct = 100.0 * below / squad if squad else 0
        total_useful += useful
        print(f"  {season:>7} {squad:>9,} {below:>9,} {useful:>9,} {never:>7,}"
              f"   ({pct:.0f}% below threshold)")
    print(f"\n  Total in the 270-899 minute band: {total_useful:,} player-seasons.")
    print("  This is the market conventional analysis cannot see.")
    return total_useful > 0


def check_manager_changes(con) -> bool:
    """Count managerial changes: the paper's identification strategy."""
    n = con.execute("""
        WITH team_matches AS (
            SELECT home_club_id AS club_id, season, match_date, home_manager AS mgr
            FROM matches WHERE home_manager IS NOT NULL
            UNION ALL
            SELECT away_club_id, season, match_date, away_manager
            FROM matches WHERE away_manager IS NOT NULL
        ), with_previous AS (
            SELECT club_id, season, mgr,
                   lag(mgr) OVER (PARTITION BY club_id ORDER BY match_date) AS previous
            FROM team_matches
        )
        SELECT count(*) FROM with_previous
        WHERE previous IS NOT NULL AND mgr <> previous
    """).fetchone()[0]
    print(f"  changes detected: {n}")
    if n < 50:
        print("  Not enough for manager-change identification. This league alone")
        print("  won't get there: the model will have to be fitted on a")
        print("  multi-league panel and applied here, as already planned.")
    return True


def check_orphans(con) -> bool:
    """Referential integrity: rows pointing at nothing."""
    ok = True
    for label, sql, fatal in [
        ("availability rows with no player",
         "SELECT count(*) FROM match_availability a "
         "LEFT JOIN players p USING (player_id) WHERE p.player_id IS NULL", True),
        ("availability rows with no match",
         "SELECT count(*) FROM match_availability a "
         "LEFT JOIN matches m USING (game_id) WHERE m.game_id IS NULL", True),
        ("players with no date of birth (placeholders)",
         "SELECT count(*) FROM players WHERE date_of_birth IS NULL", False),
    ]:
        n = con.execute(sql).fetchone()[0]
        print(f"  {label:44} {n:>8,}")
        if fatal and n:
            ok = False
    if not ok:
        print("\n  Orphan availability rows mean game_lineups references players")
        print("  that were never inserted. Re-run build.py: it now backfills")
        print("  placeholders rather than losing the rows.")
    else:
        print("\n  Placeholder players carry a name and nothing else. They are kept")
        print("  on purpose -- excluding them would bias against exactly the")
        print("  low-profile players this project targets -- but treat their")
        print("  age-based analysis as unavailable, not as zero.")
    return ok


CHECKS = [
    ("season volume", check_season_volume),
    ("availability statuses", check_availability_statuses),
    ("invisible population", check_invisible_population),
    ("manager changes", check_manager_changes),
    ("referential integrity", check_orphans),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=Path("football.duckdb"))
    args = ap.parse_args()

    if not args.db.exists():
        raise SystemExit(f"{args.db} does not exist. Run build.py first.")

    con = duckdb.connect(str(args.db))
    print("=" * 68)
    print(f"AUDIT -- {args.db}")
    print("=" * 68)

    results = []
    for name, fn in CHECKS:
        print(f"\n{name.upper()}")
        try:
            passed = fn(con)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {exc}")
            passed = False
        results.append((name, passed))
        _record(con, name, str(args.db), passed, "")

    print("\n" + "=" * 68)
    failed = [n for n, p in results if not p]
    if failed:
        print(f"FAILED CHECKS: {', '.join(failed)}")
        print("Resolve these before building anything on top.")
    else:
        print("All checks passed.")
    con.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())