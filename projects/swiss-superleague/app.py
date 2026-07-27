"""Scouting tool for the Swiss Super League.

    streamlit run app.py

Reads football.duckdb directly. Build it first with build.py.

DESIGN INTENT
-------------
This is not a general dashboard. It inverts the default of every public
scouting tool: instead of filtering out players below the minutes threshold,
it puts them front and centre, because they are the only players a mid-budget
club can realistically sign.

The hero chart makes the argument in one image -- output per 90 against minutes
played, with a line at 900. Everything to the left of that line is invisible to
conventional analysis. That is the market.
"""

from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import queries

# Resolved relative to this file, not the working directory. Streamlit Cloud
# runs from the repo root even when the app lives in a subfolder, so a bare
# relative path silently fails to find the database in deployment.
DB_PATH = Path(__file__).parent / "football.duckdb"
THRESHOLD = 900

st.set_page_config(page_title="Super League Scouting", layout="wide")


@st.cache_resource
def get_connection(path: str):
    return queries.connect(Path(path))


@st.cache_data
def load_player_seasons(path: str, mtime: float) -> pd.DataFrame:
    """Cached on file mtime, so rebuilding the database refreshes the app."""
    return queries.player_seasons(get_connection(path))


@st.cache_data
def load_options(path: str, mtime: float) -> dict:
    return queries.filter_options(get_connection(path))


if not DB_PATH.exists():
    st.error(f"{DB_PATH} not found. Run build.py first.")
    st.stop()

mtime = DB_PATH.stat().st_mtime
con = get_connection(str(DB_PATH))
df = load_player_seasons(str(DB_PATH), mtime)
opts = load_options(str(DB_PATH), mtime)

# ---------------------------------------------------------------- sidebar
st.sidebar.title("Filters")

seasons = st.sidebar.multiselect(
    "Season", opts["seasons"], default=opts["seasons"][:1]
)
clubs = st.sidebar.multiselect("Club", opts["clubs"])
positions = st.sidebar.multiselect("Position", opts["positions"])

max_minutes = int(df["minutes"].max()) if len(df) else 3000
minutes_range = st.sidebar.slider(
    "Minutes played", 0, max_minutes, (0, max_minutes), step=30
)

age_range = st.sidebar.slider("Age", 15, 40, (15, 40))
keep_unknown_age = st.sidebar.checkbox(
    "Keep players with unknown age", value=True,
    help="Placeholder players have no date of birth. Excluding them biases "
         "against exactly the low-profile players this tool is for, so it has "
         "to be a deliberate choice.",
)

value_max = float(df["market_value_eur"].max() or 0)
max_value = st.sidebar.number_input(
    "Max market value (EUR)", min_value=0.0, value=value_max, step=100_000.0
)

min_in_squad = st.sidebar.slider(
    "Minimum matchday squads", 1, 40, 5,
    help="Filters out players who barely featured in the squad at all, where "
         "even the bench_rate is noise.",
)

filtered = queries.apply_filters(
    df,
    seasons=seasons or None,
    clubs=clubs or None,
    positions=positions or None,
    minutes_range=minutes_range,
    age_range=age_range,
    max_value_eur=max_value if max_value else None,
    min_in_squad=min_in_squad,
    keep_unknown_age=keep_unknown_age,
)

# ---------------------------------------------------------------- columns
COLUMN_CONFIG = {
    "name": st.column_config.TextColumn("Player", width="medium"),
    "club": st.column_config.TextColumn("Club"),
    "position": st.column_config.TextColumn("Pos"),
    "age": st.column_config.NumberColumn("Age", format="%d"),
    "minutes": st.column_config.NumberColumn("Min", format="%d"),
    "in_squad": st.column_config.NumberColumn("Squads", format="%d"),
    "starts": st.column_config.NumberColumn("Starts", format="%d"),
    "sub_apps": st.column_config.NumberColumn("Sub", format="%d"),
    "benched": st.column_config.NumberColumn("Benched", format="%d"),
    "bench_rate": st.column_config.ProgressColumn(
        "Bench rate", min_value=0.0, max_value=1.0, format="%.2f",
        help="Share of matchday squads spent watching. The manager's opinion.",
    ),
    "avg_on_minute": st.column_config.NumberColumn(
        "Avg on", format="%.0f'",
        help="When he comes on. 55' is trust; 85' is garbage time.",
    ),
    "goals": st.column_config.NumberColumn("G", format="%d"),
    "assists": st.column_config.NumberColumn("A", format="%d"),
    "ga_per_90": st.column_config.NumberColumn(
        "G+A/90", format="%.2f",
        help="Unreliable at low minutes by construction. Orders the list; "
             "does not rank the players.",
    ),
    "market_value_eur": st.column_config.NumberColumn("Value", format="€%d"),
}

DISPLAY_COLS = [
    "name", "club", "position", "age", "minutes", "in_squad", "starts",
    "sub_apps", "benched", "bench_rate", "avg_on_minute", "goals", "assists",
    "ga_per_90", "market_value_eur",
]


def show_table(frame: pd.DataFrame, key: str) -> None:
    st.dataframe(
        frame[DISPLAY_COLS],
        column_config=COLUMN_CONFIG,
        hide_index=True,
        width="stretch",
        height=520,
        key=key,
    )
    st.caption(f"{len(frame)} player-seasons. Click any column header to sort.")


# ---------------------------------------------------------------- header
st.title("Super League Scouting")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Player-seasons", f"{len(filtered):,}")
c2.metric(
    "Below threshold",
    f"{int((filtered['minutes'] < THRESHOLD).sum()):,}",
    help=f"Fewer than {THRESHOLD} minutes: excluded by conventional analysis.",
)
c3.metric(
    "In the 270-899 band",
    f"{int(filtered['minutes'].between(270, 899).sum()):,}",
    help="Enough minutes to show something, too few to rank conventionally.",
)
c4.metric("Never played", f"{int((filtered['minutes'] == 0).sum()):,}")

tab_short, tab_browse, tab_never, tab_player, tab_mgr = st.tabs(
    ["Shortlist", "Browse", "Never played", "Player detail", "Managers"]
)

# ---------------------------------------------------------------- shortlist
with tab_short:
    st.subheader("The invisible market")
    st.markdown(
        "Players with enough minutes to show something and too few to appear "
        "on any public radar. This tool's reason to exist."
    )
    lo, hi = st.slider("Minute band", 0, THRESHOLD, (270, 899), step=30)
    sl = queries.shortlist(filtered, lo=lo, hi=hi, min_in_squad=min_in_squad)
    show_table(sl, "shortlist")
    st.info(
        "**G+A/90 is not a ranking.** At 400 minutes the confidence interval is "
        "enormous, which is the entire premise of this project. Read it "
        "alongside bench rate and average entry minute: a player the manager "
        "keeps introducing at 55 minutes is a different prospect from one who "
        "only appears at 85, whatever their per-90 says."
    )

# ---------------------------------------------------------------- browse
with tab_browse:
    st.subheader("All players")
    if len(filtered):
        chart_data = filtered.dropna(subset=["minutes", "ga_per_90"])
        base = alt.Chart(chart_data).encode(
            x=alt.X("minutes:Q", title="Minutes played"),
            y=alt.Y("ga_per_90:Q", title="Goals + assists per 90"),
        )
        points = base.mark_circle(size=90, opacity=0.65).encode(
            color=alt.Color("position:N", title="Position"),
            tooltip=["name", "club", "position", "age", "minutes",
                     "ga_per_90", "bench_rate", "avg_on_minute"],
        )
        rule = (
            alt.Chart(pd.DataFrame({"x": [THRESHOLD]}))
            .mark_rule(strokeDash=[6, 4], color="#c0392b", size=2)
            .encode(x="x:Q")
        )
        st.altair_chart(
            (points + rule).properties(height=380).interactive(),
            width="stretch",
        )
        st.caption(
            f"The dashed line is the conventional {THRESHOLD}-minute cutoff. "
            "Everything to its left is discarded by standard analysis. Note how "
            "the vertical spread widens as minutes fall -- that is sampling "
            "noise, not talent, and it is what the threshold exists to hide."
        )
    show_table(filtered, "browse")

# ---------------------------------------------------------------- never played
with tab_never:
    st.subheader("Named but never used")
    st.markdown(
        "Zero minutes across every squad they were named in. The strongest "
        "rejection signal available in public data -- the manager had them "
        "available, repeatedly, and never used them."
    )
    nv = queries.never_played(filtered, min_in_squad=min_in_squad)
    show_table(nv, "never")
    st.warning(
        "Incomplete by construction: this only covers players who made at "
        "least one matchday squad. Anyone at the club all season who never "
        "made a bench is absent from the source data entirely."
    )

# ---------------------------------------------------------------- player
with tab_player:
    st.subheader("Player detail")
    if not len(filtered):
        st.info("No players match the current filters.")
    else:
        labels = (
            filtered.assign(
                label=filtered["name"] + "  (" + filtered["season"].astype(str)
                + ", " + filtered["minutes"].astype(int).astype(str) + " min)"
            )
            .sort_values("name")
        )
        choice = st.selectbox("Player", labels["label"].tolist())
        row = labels[labels["label"] == choice].iloc[0]

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Minutes", int(row["minutes"]))
        m2.metric("Squads", int(row["in_squad"]))
        m3.metric("Bench rate", f"{row['bench_rate']:.0%}"
                  if pd.notna(row["bench_rate"]) else "n/a")
        m4.metric("Avg entry", f"{row['avg_on_minute']:.0f}'"
                  if pd.notna(row["avg_on_minute"]) else "never")
        m5.metric("Age", int(row["age"]) if pd.notna(row["age"]) else "unknown")

        log = queries.match_log(con, int(row["player_id"]), int(row["season"]))
        if len(log):
            log["match_date"] = pd.to_datetime(log["match_date"])
            timeline = (
                alt.Chart(log)
                .mark_bar()
                .encode(
                    x=alt.X("match_date:T", title="Match date"),
                    y=alt.Y("minutes:Q", title="Minutes", scale=alt.Scale(domain=[0, 90])),
                    color=alt.Color(
                        "status:N",
                        scale=alt.Scale(
                            domain=["started", "substitute_on", "unused_sub"],
                            range=["#2c7fb8", "#7fcdbb", "#d9d9d9"],
                        ),
                        title="Status",
                    ),
                    tooltip=["match_date:T", "home", "away", "status",
                             "on_minute", "off_minute", "minutes", "manager"],
                )
                .properties(height=260)
            )
            st.altair_chart(timeline, width="stretch")
            st.caption(
                "Grey bars are matchdays he was named and not used. Read them "
                "against the manager column below: a run of grey that ends when "
                "the manager changes says something a season total cannot."
            )
            st.dataframe(
                log[["match_date", "home", "away", "status", "on_minute",
                     "off_minute", "minutes", "goals", "assists", "manager"]],
                hide_index=True, width="stretch", height=300,
            )
        else:
            st.info("No match records for this player-season.")

# ---------------------------------------------------------------- managers
with tab_mgr:
    st.subheader("Managerial spells")
    st.markdown(
        "Context for reading a player's usage. A change of manager reshuffles "
        "minutes for reasons partly unrelated to any individual's quality, "
        "which is what makes these dates useful."
    )
    season_pick = st.selectbox("Season", opts["seasons"], key="mgr_season")
    spells = queries.manager_spells(con, season=int(season_pick))
    st.dataframe(spells, hide_index=True, width="stretch")