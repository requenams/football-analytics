"""Reconstruct per-player minutes from lineups and match events.

    python availability.py --self-test

`appearances.csv` does not cover every competition in the dataset -- the Swiss
Super League is one of the missing ones. But the ingredients are there: who
started is in `game_lineups`, and who came on or off and at what minute is in
`game_events`.

And the reconstruction comes out BETTER than the original: `appearances.csv`
only gives a minutes total, whereas here we recover the on and off minute. That
difference matters for the selection model: a player who always comes on in the
80th minute with the game already decided tells you something very different
about the manager's trust than one who comes on at half-time at 0-0.

RULES APPLIED
-------------
  starter, never substituted  -> 0 to REGULATION
  starter, substituted off    -> 0 to substitution minute
  starter, sent off           -> 0 to red card minute
  substitute who came on      -> substitution minute to REGULATION
  substitute on then off      -> on minute to off minute
  unused substitute           -> 0 minutes, status unused_sub

Stoppage time is ignored: everything is truncated at 90, the same way
`appearances.csv` does it, so the two sources stay comparable wherever both
exist.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

REGULATION = 90


def _resolve(df: pd.DataFrame, *candidates: str) -> str | None:
    """Find a column by exact name first, then by substring."""
    lowered = {c: str(c).lower() for c in df.columns}
    for cand in candidates:
        for c in df.columns:
            if lowered[c] == cand.lower():
                return c
    for cand in candidates:
        for c in df.columns:
            if cand.lower() in lowered[c]:
                return c
    return None


def detect_sub_direction(subs: pd.DataFrame, starters: set) -> bool:
    """Work out whether `player_id` is the player going OFF in a substitution.

    We do not assume this -- we check it against the data. The player going off
    should almost always be in the starting eleven, and the player coming on
    almost never. If the ratio comes out the other way round, the columns mean
    the opposite of what we expected and need swapping.

    Returns True if player_id is the outgoing player (the expected convention).
    """
    if subs.empty:
        return True
    pid_in_starters = subs["_off_candidate"].isin(starters).mean()
    inid_in_starters = subs["_on_candidate"].isin(starters).mean()
    return pid_in_starters >= inid_in_starters


def reconstruct(
    lineups: pd.DataFrame, events: pd.DataFrame, games: pd.DataFrame
) -> pd.DataFrame:
    """Return one row per player-match with status and minutes."""
    valid = set(games["game_id"])
    lu = lineups[lineups["game_id"].isin(valid)].copy()
    if lu.empty:
        return pd.DataFrame(
            columns=["game_id", "player_id", "club_id", "status",
                     "on_minute", "off_minute", "minutes", "goals", "assists"]
        )

    col_type = _resolve(lu, "type")
    lu["is_starter"] = (
        lu[col_type].astype(str).str.contains("start", case=False, na=False)
    )

    ev = events[events["game_id"].isin(valid)].copy()
    col_evtype = _resolve(ev, "type")
    col_minute = _resolve(ev, "minute")
    col_in = _resolve(ev, "player_in_id")
    col_desc = _resolve(ev, "description")
    ev[col_minute] = pd.to_numeric(ev[col_minute], errors="coerce")

    starters = set(
        map(tuple, lu.loc[lu["is_starter"], ["game_id", "player_id"]].values)
    )

    # --- Substitutions -------------------------------------------------
    subs = ev[ev[col_evtype].astype(str)
              .str.contains("substitut", case=False, na=False)].copy()
    on_map: dict[tuple, float] = {}
    off_map: dict[tuple, float] = {}

    if not subs.empty and col_in:
        subs["_off_candidate"] = list(
            map(tuple, subs[["game_id", "player_id"]].values)
        )
        subs["_on_candidate"] = list(map(tuple, subs[["game_id", col_in]].values))
        pid_is_off = detect_sub_direction(subs, starters)
        if not pid_is_off:
            print("  note: player_id/player_in_id were reversed; corrected.")
        off_col = "_off_candidate" if pid_is_off else "_on_candidate"
        on_col = "_on_candidate" if pid_is_off else "_off_candidate"
        for _, r in subs.iterrows():
            minute = r[col_minute]
            if pd.isna(minute):
                continue
            minute = float(min(max(minute, 0), REGULATION))
            off_map.setdefault(r[off_col], minute)
            on_map.setdefault(r[on_col], minute)
    elif not subs.empty:
        print("  note: no player_in_id column; cannot map players coming on.")

    # --- Red cards -----------------------------------------------------
    # A sending-off ends that player's match, so it shortens their minutes.
    # Without this, a player sent off in the 20th minute would count as 90.
    reds: dict[tuple, float] = {}
    cards = ev[ev[col_evtype].astype(str)
               .str.contains("card", case=False, na=False)]
    if col_desc and not cards.empty:
        is_red = cards[col_desc].astype(str).str.contains(
            "red", case=False, na=False
        )
        for _, r in cards[is_red].iterrows():
            minute = r[col_minute]
            if pd.isna(minute):
                continue
            key = (r["game_id"], r["player_id"])
            minute = float(min(max(minute, 0), REGULATION))
            reds[key] = min(reds.get(key, REGULATION), minute)

    # --- Assembly ------------------------------------------------------
    rows = []
    for r in lu.itertuples(index=False):
        key = (r.game_id, r.player_id)
        if r.is_starter:
            on = 0.0
            off = min(off_map.get(key, REGULATION), reds.get(key, REGULATION))
            status = "started"
        elif key in on_map:
            on = on_map[key]
            # A substitute can himself be substituted; only treat off_map as
            # his exit if it happened after he came on.
            candidate_off = off_map.get(key, REGULATION)
            off = candidate_off if candidate_off > on else REGULATION
            off = min(off, reds.get(key, REGULATION))
            status = "substitute_on"
        else:
            on, off, status = 0.0, 0.0, "unused_sub"

        rows.append({
            "game_id": r.game_id,
            "player_id": r.player_id,
            "club_id": getattr(r, "club_id", None),
            "status": status,
            "on_minute": on if status != "unused_sub" else None,
            "off_minute": off if status != "unused_sub" else None,
            "minutes": int(max(off - on, 0)),
        })

    out = pd.DataFrame(rows).drop_duplicates(subset=["game_id", "player_id"])

    # Goals and assists from the event stream.
    goals = ev[ev[col_evtype].astype(str)
               .str.contains("goal", case=False, na=False)]
    g_count = goals.groupby(["game_id", "player_id"]).size().rename("goals")
    out = out.merge(g_count, on=["game_id", "player_id"], how="left")
    out["goals"] = out["goals"].fillna(0).astype(int)

    col_assist = _resolve(ev, "player_assist_id")
    if col_assist is not None and not goals.empty:
        a = goals[goals[col_assist].notna()]
        a_count = (a.groupby(["game_id", col_assist]).size()
                   .rename("assists").reset_index()
                   .rename(columns={col_assist: "player_id"}))
        a_count["player_id"] = pd.to_numeric(a_count["player_id"], errors="coerce")
        out = out.merge(a_count, on=["game_id", "player_id"], how="left")
    if "assists" not in out.columns:
        out["assists"] = 0
    out["assists"] = out["assists"].fillna(0).astype(int)

    return out[["game_id", "player_id", "club_id", "status",
                "on_minute", "off_minute", "minutes", "goals", "assists"]]


# ---------------------------------------------------------------------------
def self_test() -> int:
    """One match containing the six cases the logic has to tell apart.

    Expected values are computed by hand on purpose. Deriving them from
    reconstruct() itself would make the test pass without checking anything.
    """
    print("SELF-TEST -- minutes reconstruction\n")

    games = pd.DataFrame({"game_id": [1]})
    lineups = pd.DataFrame({
        "game_id": [1] * 7,
        "club_id": [10] * 7,
        "player_id": [101, 102, 103, 201, 202, 203, 204],
        "type": ["starting_lineup"] * 3 + ["substitutes"] * 4,
    })
    # 101 played the full match      | 102 started, off in the 60th for 201
    # 103 started, sent off in 30th  | 202 on in the 75th, off in the 85th
    # 203 came on in the 85th        | 204 unused substitute
    events = pd.DataFrame({
        "game_id": [1, 1, 1, 1, 1],
        "minute": [60, 30, 75, 85, 55],
        "type": ["Substitutions", "Cards", "Substitutions", "Substitutions", "Goals"],
        "player_id": [102, 103, 999, 202, 101],
        "player_in_id": [201, None, 202, 203, None],
        "description": ["", "second yellow, Red card", "", "", "Header"],
        "player_assist_id": [None, None, None, None, 102],
    })

    out = reconstruct(lineups, events, games).set_index("player_id")
    print(out[["status", "on_minute", "off_minute", "minutes", "goals", "assists"]]
          .to_string())

    expected = {
        101: ("started", 0, 90, 90),
        102: ("started", 0, 60, 60),
        103: ("started", 0, 30, 30),
        201: ("substitute_on", 60, 90, 30),
        202: ("substitute_on", 75, 85, 10),
        203: ("substitute_on", 85, 90, 5),
        204: ("unused_sub", None, None, 0),
    }
    ok = True
    print()
    for pid, (status, on, off, mins) in expected.items():
        row = out.loc[pid]
        got = (row["status"], row["on_minute"], row["off_minute"], row["minutes"])
        match = (
            got[0] == status
            and (pd.isna(got[1]) if on is None else got[1] == on)
            and (pd.isna(got[2]) if off is None else got[2] == off)
            and got[3] == mins
        )
        if not match:
            print(f"  FAIL {pid}: expected {(status, on, off, mins)}, got {got}")
            ok = False
    if ok:
        print("  all six cases correct: full match, substituted off, sent off,")
        print("  came on, came on then off, and unused.")

    total = out["minutes"].sum()
    print(f"\n  total team minutes: {total} (expected 225)")
    if total != 225:
        print("  FAIL on the total.")
        ok = False

    if out.loc[101, "goals"] != 1 or out.loc[102, "assists"] != 1:
        print("  FAIL: goals or assists misattributed.")
        ok = False
    else:
        print("  goal credited to 101 and assist to 102: correct.")

    print("\n" + ("OK -- reconstruction is valid." if ok else "FAILURES PRESENT."))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    ap.error("use --self-test, or import reconstruct() from build.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())