"""Data pipeline for the Indian Super League 2021/22 left-back analysis.

Three responsibilities, all validated during exploration and moved here so the
notebook stays about analysis rather than plumbing:

    load_isl_events()      download once, cache locally, reload instantly after
    player_minutes()       total minutes per player, derived from substitutions
    build_left_back_pool() genuine left-backs only (modal position = LB/LWB),
                           above a minutes threshold, with a share_LB transparency
                           column for flagging hybrids

Design notes worth remembering:
  * `position` in StatsBomb is per-event, not per-player. Filtering on "played
    LB at least once" leaks wingers/forwards who briefly covered the flank, so
    we filter on each player's MODAL position instead.
  * Grouping team by mode consolidates players whose club appears under two
    names in the data (e.g. the ATK Mohun Bagan / Mohun Bagan Super Giant split).
"""
import os
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

ISL_COMPETITION_ID = 1238
ISL_SEASON_ID = 108
CACHE_PATH = "data/raw/isl_2122_events.pkl"
LEFT_BACK_POSITIONS = ["Left Back", "Left Wing Back"]


def load_isl_events(cache_path: str = CACHE_PATH) -> pd.DataFrame:
    """Return all ISL 2021/22 events, downloading match-by-match only once.

    Raw events carry nested columns (lists, freeze frames), so we cache with
    pickle rather than parquet, which chokes on them.
    """
    if os.path.exists(cache_path):
        return pd.read_pickle(cache_path)

    from statsbombpy import sb  # local import: cache hits need no network

    matches = sb.matches(competition_id=ISL_COMPETITION_ID, season_id=ISL_SEASON_ID)
    frames = []
    for i, match_id in enumerate(matches["match_id"], 1):
        frames.append(sb.events(match_id=match_id))
        print(f"  {i}/{len(matches)} matches", end="\r")

    events = pd.concat(frames, ignore_index=True)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    events.to_pickle(cache_path)
    print(f"\nSaved {len(events)} events to {cache_path}")
    return events


def _minutes_in_match(match: pd.DataFrame) -> pd.DataFrame:
    """Minutes played by each player in a single match, inferred from subs.

    A starter runs from minute 0 to the match end; a player subbed on/off starts
    or stops at the substitution minute. `.get(player, default)` supplies 0 for
    starters (absent from the "on" map) and the match end for anyone not subbed
    off.
    """
    end = int(match["minute"].max())
    subs = match[match["type"] == "Substitution"]
    off = dict(zip(subs["player"], subs["minute"]))
    on = dict(zip(subs["substitution_replacement"], subs["minute"]))
    players = set(match["player"].dropna()) | set(on) | set(off)
    rows = [(p, max(0, off.get(p, end) - on.get(p, 0))) for p in players]
    return pd.DataFrame(rows, columns=["player", "min"])


def player_minutes(events: pd.DataFrame) -> pd.Series:
    """Total minutes played per player across the whole season."""
    return (
        events.groupby("match_id", group_keys=False)
        .apply(_minutes_in_match)
        .groupby("player")["min"]
        .sum()
        .rename("minutes")
    )


def build_left_back_pool(events: pd.DataFrame, min_minutes: int = 900) -> pd.DataFrame:
    """Clean pool of genuine left-backs above a minutes threshold.

    Columns: minutes, modal_pos, share_LB (% of events played as LB/LWB), team.
    """
    minutes = player_minutes(events)

    pos = events.dropna(subset=["player", "position"])
    counts = pos.groupby(["player", "position"]).size().rename("n").reset_index()

    modal_pos = (
        counts.sort_values("n", ascending=False)
        .drop_duplicates("player")
        .set_index("player")["position"]
        .rename("modal_pos")
    )
    total_events = counts.groupby("player")["n"].sum()
    lb_events = (
        counts[counts["position"].isin(LEFT_BACK_POSITIONS)]
        .groupby("player")["n"]
        .sum()
    )
    share_lb = (lb_events / total_events).fillna(0).mul(100).round(0).rename("share_LB")
    team = (
        pos.groupby("player")["team"]
        .agg(lambda s: s.value_counts().index[0])
        .rename("team")
    )

    table = pd.concat([minutes, modal_pos, share_lb, team], axis=1)
    is_left_back = table["modal_pos"].isin(LEFT_BACK_POSITIONS)
    pool = (
        table[is_left_back & (table["minutes"] >= min_minutes)]
        .sort_values("minutes", ascending=False)
    )
    return pool
