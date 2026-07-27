"""Query layer for the scouting tool.

    python queries.py --self-test

All SQL lives here, separated from the Streamlit UI, for one practical reason:
the queries are where the bugs are, and the UI is not testable without a
browser. Keeping them apart means the risky half has a self-test.

THE DERIVED COLUMNS THAT MATTER
-------------------------------
Any dataset gives you minutes and goals. What this database can produce and
others cannot comes from the reconstruction:

  bench_rate     of the matchday squads he was named in, the share he spent
                 watching. The manager's revealed opinion, quantified.
  avg_on_minute  when he does come on, how early. A substitute who enters in
                 the 55th minute is trusted; one who enters in the 85th is
                 getting minutes, not opportunities.
  start_rate     share of squads where he was in the eleven.

Those three separate two players with identical minutes into very different
prospects, which is the whole point.

KNOWN CAVEATS, CARRIED THROUGH DELIBERATELY
-------------------------------------------
1. `in_squad` counts only players named in a matchday squad. Anyone at the club
   all season who never made a bench is absent entirely, so the invisible
   population is a floor, not a total.
2. Market values come from `squad_memberships`, which was populated from
   valuation dates by calendar year. Treat them as approximate, not as the value
   on a given matchday.
3. Placeholder players have no date of birth. Their age is NULL, not zero, and
   filters must not silently drop them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd

# Aggregates one row per player-season, with the trust columns.
# Reused by both the browser and the shortlist so the numbers can never diverge
# between the two views.
_PLAYER_SEASON_CTE = """
WITH per_match AS (
    SELECT a.player_id,
           m.season,
           a.club_id,
           a.status,
           a.minutes,
           a.on_minute,
           a.goals,
           a.assists
    FROM match_availability a
    JOIN matches m USING (game_id)
),
agg AS (
    SELECT player_id,
           season,
           count(*)                                              AS in_squad,
           count(*) FILTER (WHERE status = 'started')             AS starts,
           count(*) FILTER (WHERE status = 'substitute_on')       AS sub_apps,
           count(*) FILTER (WHERE status = 'unused_sub')          AS benched,
           sum(minutes)                                           AS minutes,
           sum(goals)                                             AS goals,
           sum(assists)                                           AS assists,
           avg(on_minute) FILTER (WHERE status = 'substitute_on') AS avg_on_minute
    FROM per_match
    GROUP BY player_id, season
),
main_club AS (
    -- A transferred player appears for two clubs in one season. We report the
    -- club he was named for most often, not an arbitrary one.
    SELECT player_id, season, club_id
    FROM (
        SELECT player_id, season, club_id, count(*) AS n,
               row_number() OVER (
                   PARTITION BY player_id, season ORDER BY count(*) DESC
               ) AS rn
        FROM per_match
        GROUP BY player_id, season, club_id
    )
    WHERE rn = 1
),
value AS (
    SELECT player_id, season, market_value_eur
    FROM (
        SELECT player_id, season, market_value_eur,
               row_number() OVER (
                   PARTITION BY player_id, season
                   ORDER BY market_value_eur DESC NULLS LAST
               ) AS rn
        FROM squad_memberships
    )
    WHERE rn = 1
)
SELECT p.player_id,
       p.name,
       c.name                                        AS club,
       p.position,
       p.sub_position,
       p.foot,
       CASE WHEN p.date_of_birth IS NULL THEN NULL
            ELSE agg.season - year(p.date_of_birth) END AS age,
       agg.season,
       agg.in_squad,
       agg.starts,
       agg.sub_apps,
       agg.benched,
       agg.minutes,
       round(agg.benched * 1.0 / nullif(agg.in_squad, 0), 3)  AS bench_rate,
       round(agg.starts  * 1.0 / nullif(agg.in_squad, 0), 3)  AS start_rate,
       round(agg.avg_on_minute, 1)                            AS avg_on_minute,
       agg.goals,
       agg.assists,
       round((agg.goals + agg.assists) * 90.0 / nullif(agg.minutes, 0), 3)
                                                             AS ga_per_90,
       value.market_value_eur
FROM agg
JOIN players p USING (player_id)
LEFT JOIN main_club mc ON mc.player_id = agg.player_id AND mc.season = agg.season
LEFT JOIN clubs c ON c.club_id = mc.club_id
LEFT JOIN value ON value.player_id = agg.player_id AND value.season = agg.season
"""


def connect(db_path: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


def player_seasons(con) -> pd.DataFrame:
    """Every player-season with the derived trust columns."""
    return con.execute(_PLAYER_SEASON_CTE).df()


def filter_options(con) -> dict:
    """Distinct values for populating the filter widgets."""
    def col(sql: str) -> list:
        return [r[0] for r in con.execute(sql).fetchall() if r[0] is not None]

    return {
        "seasons": sorted(col("SELECT DISTINCT season FROM matches"), reverse=True),
        "clubs": sorted(col("SELECT DISTINCT name FROM clubs")),
        "positions": sorted(col("SELECT DISTINCT position FROM players")),
        "sub_positions": sorted(col("SELECT DISTINCT sub_position FROM players")),
    }


def apply_filters(
    df: pd.DataFrame,
    seasons: list | None = None,
    clubs: list | None = None,
    positions: list | None = None,
    minutes_range: tuple | None = None,
    age_range: tuple | None = None,
    max_value_eur: float | None = None,
    min_in_squad: int | None = None,
    keep_unknown_age: bool = True,
) -> pd.DataFrame:
    """Filter in pandas rather than SQL, so the widgets stay responsive.

    `keep_unknown_age` defaults to True on purpose. Placeholder players have a
    NULL age, and a naive numeric filter would drop them silently -- excluding
    low-profile players is the exact bias this project is about, so it has to be
    an explicit choice rather than a side effect.
    """
    out = df
    if seasons:
        out = out[out["season"].isin(seasons)]
    if clubs:
        out = out[out["club"].isin(clubs)]
    if positions:
        out = out[out["position"].isin(positions)]
    if minutes_range:
        lo, hi = minutes_range
        out = out[(out["minutes"] >= lo) & (out["minutes"] <= hi)]
    if age_range:
        lo, hi = age_range
        in_band = out["age"].between(lo, hi)
        if keep_unknown_age:
            in_band = in_band | out["age"].isna()
        out = out[in_band]
    if max_value_eur is not None:
        out = out[
            (out["market_value_eur"] <= max_value_eur)
            | out["market_value_eur"].isna()
        ]
    if min_in_squad is not None:
        out = out[out["in_squad"] >= min_in_squad]
    return out


def shortlist(
    df: pd.DataFrame,
    season: int | None = None,
    lo: int = 270,
    hi: int = 899,
    min_in_squad: int = 5,
) -> pd.DataFrame:
    """The invisible population: enough minutes to show something, too few to rank.

    This is the tool's reason to exist. Conventional analysis filters these
    players out; here they are the default view.

    Sorted by output per 90 but that column is deliberately unreliable at this
    sample size -- that is the entire premise. It orders the list; it does not
    rank the players.
    """
    out = df[(df["minutes"] >= lo) & (df["minutes"] <= hi)]
    if season is not None:
        out = out[out["season"] == season]
    out = out[out["in_squad"] >= min_in_squad]
    return out.sort_values("ga_per_90", ascending=False, na_position="last")


def never_played(df: pd.DataFrame, season: int | None = None,
                 min_in_squad: int = 5) -> pd.DataFrame:
    """Named in squads, never given a minute. The strongest rejection signal."""
    out = df[(df["minutes"] == 0) & (df["in_squad"] >= min_in_squad)]
    if season is not None:
        out = out[out["season"] == season]
    return out.sort_values("in_squad", ascending=False)


def match_log(con, player_id: int, season: int | None = None) -> pd.DataFrame:
    """Match-by-match log for one player, with the manager in charge.

    The manager column is what makes this more than a fixture list: it shows
    whether a player's usage changed when the manager did.
    """
    sql = """
        SELECT m.match_date,
               m.season,
               hc.name AS home,
               ac.name AS away,
               m.home_goals, m.away_goals,
               a.status, a.on_minute, a.off_minute, a.minutes,
               a.goals, a.assists,
               CASE WHEN a.club_id = m.home_club_id THEN m.home_manager
                    ELSE m.away_manager END AS manager
        FROM match_availability a
        JOIN matches m USING (game_id)
        LEFT JOIN clubs hc ON hc.club_id = m.home_club_id
        LEFT JOIN clubs ac ON ac.club_id = m.away_club_id
        WHERE a.player_id = ?
    """
    params: list = [player_id]
    if season is not None:
        sql += " AND m.season = ?"
        params.append(season)
    return con.execute(sql + " ORDER BY m.match_date", params).df()


def manager_spells(con, season: int | None = None) -> pd.DataFrame:
    """Managerial spells per club, for reading usage changes against."""
    sql = """
        WITH team_matches AS (
            SELECT home_club_id AS club_id, season, match_date,
                   home_manager AS manager
            FROM matches WHERE home_manager IS NOT NULL
            UNION ALL
            SELECT away_club_id, season, match_date, away_manager
            FROM matches WHERE away_manager IS NOT NULL
        )
        SELECT c.name AS club, t.season, t.manager,
               min(t.match_date) AS from_date,
               max(t.match_date) AS to_date,
               count(*)          AS matches
        FROM team_matches t
        LEFT JOIN clubs c ON c.club_id = t.club_id
        {where}
        GROUP BY c.name, t.season, t.manager
        ORDER BY club, from_date
    """
    where = "WHERE t.season = ?" if season is not None else ""
    params = [season] if season is not None else []
    return con.execute(sql.format(where=where), params).df()


# ---------------------------------------------------------------------------
def _fixture(path: Path) -> None:
    """Build a synthetic database rich enough to exercise every query."""
    import numpy as np

    rng = np.random.default_rng(0)
    con = duckdb.connect(str(path))
    con.execute((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))

    con.execute("INSERT INTO competitions VALUES ('C1','Super League','Switzerland',1,'test')")
    clubs = [(1, "FC Zurich"), (2, "FC Basel"), (3, "Young Boys")]
    for cid, cname in clubs:
        con.execute("INSERT INTO clubs VALUES (?,?,'C1')", [cid, cname])

    n_players = 60
    for pid in range(1, n_players + 1):
        # Every fifth player gets a NULL date of birth, mirroring the real
        # placeholder rows, so the age filter is tested against them.
        dob = None if pid % 5 == 0 else f"{int(rng.integers(1990, 2006))}-06-15"
        pos = ["Attack", "Midfield", "Defender", "Goalkeeper"][pid % 4]
        con.execute(
            "INSERT INTO players VALUES (?,?,?,?,?,NULL,'right',180,'CH')",
            [pid, f"Player {pid:03d}", f"player {pid:03d}", dob, pos],
        )

    game_id = 0
    for season in (2024, 2025):
        for md in range(1, 21):
            for home, away in [(1, 2), (2, 3), (3, 1)]:
                game_id += 1
                mgr_h = "Mgr A" if md <= 10 else "Mgr B"
                con.execute(
                    "INSERT INTO matches VALUES (?,'C1',?,?,?,?,?,?,?,?,?)",
                    [game_id, season, f"{season}-08-01", str(md), home, away,
                     1, 1, f"{mgr_h} {home}", f"Mgr {away}"],
                )
                for club in (home, away):
                    squad = [p for p in range(1, n_players + 1) if p % 3 == club % 3][:18]
                    for i, pid in enumerate(squad):
                        if i < 11:
                            status, on, off = "started", 0, 90
                        elif i < 14:
                            status = "substitute_on"
                            on = int(rng.integers(45, 88))
                            off = 90
                        else:
                            status, on, off = "unused_sub", None, None
                        mins = 0 if status == "unused_sub" else off - on
                        con.execute(
                            "INSERT INTO match_availability VALUES (?,?,?,?,?,?,?,?,?)",
                            [game_id, pid, club, status, on, off, mins,
                             int(rng.integers(0, 2)) if mins > 60 else 0, 0],
                        )
        for pid in range(1, n_players + 1):
            con.execute(
                "INSERT INTO squad_memberships VALUES (?,?,?,NULL,NULL,NULL,?,NULL)",
                [pid, 1 + (pid % 3), season, int(rng.integers(1, 40)) * 100_000],
            )
    con.close()


def self_test() -> int:
    import tempfile

    print("SELF-TEST -- query layer\n")
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "fixture.duckdb"
    _fixture(db)
    con = connect(db)
    ok = True

    df = player_seasons(con)
    print(f"player_seasons: {len(df)} rows, {df['season'].nunique()} seasons")
    required = {"name", "club", "age", "minutes", "bench_rate", "start_rate",
                "avg_on_minute", "ga_per_90", "market_value_eur", "in_squad"}
    if not required.issubset(df.columns):
        print(f"  FAIL: missing columns {required - set(df.columns)}")
        ok = False

    # Internal consistency: the three statuses must account for every squad row.
    bad = df[df["starts"] + df["sub_apps"] + df["benched"] != df["in_squad"]]
    print(f"status counts reconcile with in_squad: {len(bad)} mismatches")
    if len(bad):
        ok = False

    # Rates must be probabilities.
    for c in ("bench_rate", "start_rate"):
        v = df[c].dropna()
        if not ((v >= 0) & (v <= 1)).all():
            print(f"  FAIL: {c} outside [0,1]")
            ok = False
    print("bench_rate and start_rate within [0,1]: yes")

    # avg_on_minute must be NULL for players who never came off the bench.
    no_subs = df[df["sub_apps"] == 0]
    if len(no_subs) and no_subs["avg_on_minute"].notna().any():
        print("  FAIL: avg_on_minute set for players with no sub appearances")
        ok = False
    print("avg_on_minute NULL when sub_apps is 0: yes")

    # The age filter must not silently discard NULL-age placeholders.
    n_null_age = int(df["age"].isna().sum())
    kept = apply_filters(df, age_range=(20, 25), keep_unknown_age=True)
    dropped = apply_filters(df, age_range=(20, 25), keep_unknown_age=False)
    print(f"\nplaceholders with NULL age: {n_null_age}")
    print(f"  age filter keeping unknowns:   {len(kept)} rows")
    print(f"  age filter dropping unknowns:  {len(dropped)} rows")
    if n_null_age and len(kept) <= len(dropped):
        print("  FAIL: keep_unknown_age has no effect")
        ok = False
    if int(kept["age"].isna().sum()) != n_null_age:
        print("  FAIL: unknown ages were dropped despite keep_unknown_age")
        ok = False

    sl = shortlist(df, season=2025, min_in_squad=1)
    print(f"\nshortlist(2025): {len(sl)} rows")
    if len(sl):
        outside = sl[(sl["minutes"] < 270) | (sl["minutes"] > 899)]
        if len(outside):
            print("  FAIL: shortlist contains players outside the minute band")
            ok = False
        else:
            print("  all within the 270-899 band: yes")

    nv = never_played(df, min_in_squad=1)
    print(f"never_played: {len(nv)} rows")
    if len(nv) and (nv["minutes"] != 0).any():
        print("  FAIL: never_played contains players with minutes")
        ok = False

    pid = int(df.iloc[0]["player_id"])
    log = match_log(con, pid)
    print(f"match_log(player {pid}): {len(log)} rows, "
          f"{log['manager'].nunique()} managers")
    if len(log) and log["manager"].isna().all():
        print("  FAIL: manager never resolved")
        ok = False

    spells = manager_spells(con, season=2025)
    print(f"manager_spells(2025): {len(spells)} spells")
    if spells.empty:
        print("  FAIL: no spells found")
        ok = False

    opts = filter_options(con)
    print(f"filter_options: {[(k, len(v)) for k, v in opts.items()]}")
    if not opts["seasons"] or not opts["clubs"]:
        print("  FAIL: filter options empty")
        ok = False

    con.close()
    print("\n" + ("OK -- query layer is consistent."
                  if ok else "FAILURES PRESENT."))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--db", type=Path, default=Path("football.duckdb"))
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    con = connect(args.db)
    df = player_seasons(con)
    print(df.head(20).to_string(index=False))
    print(f"\n{len(df)} player-seasons")
    return 0


if __name__ == "__main__":
    sys.exit(main())