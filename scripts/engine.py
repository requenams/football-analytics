#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scouting report engine (multi-club)
====================================
Builds a percentile pizza chart per player, against positional peers,
using FBref data via soccerdata + mplsoccer.

Fill in the TARGETS list (one player per line) and run:  python engine.py
Produces one PNG per target.

Runs LOCALLY (needs access to fbref.com). First run per league is slow;
soccerdata caches. If FBref blocks you, wait a few minutes and retry.

NOTE: FBref only exposes BASIC data for Swiss football (no xG / passing /
possession / defense detail). For Swiss forwards use forwards_report.py.
This engine is kept for leagues where advanced data IS available.
"""
import json
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mplsoccer import PyPizza

# ============================================================================
# 1) TARGETS  ->  one player per line
#    pos: "ATA" (winger/forward) | "MED" (midfielder) | "DEF" (centre-back) | "LAT" (full-back)
# ============================================================================
TARGETS = [
    dict(club="FC Winterthur", player="Elias Maluvunu", pos="ATA",
         league="SUI-Super League", season="2025-2026", out="01_maluvunu.png"),
    dict(club="FC Aarau", player="Sian Dzelili", pos="DEF",
         league="SUI-Challenge League", season="2025-2026", out="02_dzelili.png"),
    dict(club="FC Zurich", player="Cheveyo Tsawa", pos="MED",
         league="SUI-Super League", season="2025-2026", out="03_tsawa.png"),
    dict(club="FC St. Gallen", player="Malamine Efekele", pos="ATA",
         league="SUI-Super League", season="2025-2026", out="04_efekele.png"),
    dict(club="Grasshopper Club Zurich", player="Lovro Zvonarek", pos="ATA",
         league="SUI-Super League", season="2025-2026", out="05_zvonarek.png"),
]

MIN_MINUTES = 450   # minimum minutes for the peer group (lower to 300 if too few)

# ============================================================================
# 2) Swiss leagues (not built into soccerdata) -> register as custom leagues
# ============================================================================
CUSTOM_LEAGUES = {
    "SUI-Super League":     {"FBref": "Swiss Super League",     "season_start": "Jul", "season_end": "May"},
    "SUI-Challenge League": {"FBref": "Swiss Challenge League", "season_start": "Jul", "season_end": "May"},
}
CFG = Path.home() / "soccerdata" / "config"; CFG.mkdir(parents=True, exist_ok=True)
f = CFG / "league_dict.json"
cur = json.loads(f.read_text() or "{}") if f.exists() else {}
cur.update({k: v for k, v in CUSTOM_LEAGUES.items() if k not in cur})
f.write_text(json.dumps(cur, indent=2))

# ============================================================================
# 3) Position presets:  (label, table, keys, exclude)
#    Colours in blocks of 3. Tune after seeing real output.
# ============================================================================
def M(label, table, keys, exclude=()):
    return dict(label=label, table=table, keys=keys, exclude=exclude)

PRESETS = {
    "ATA": (["#d64550"]*3 + ["#3f88c5"]*3 + ["#43aa8b"]*3, [
        M("npxG",                "shooting",           ("npxG",)),
        M("Shots",               "shooting",           ("Standard", "Sh"), ("/90", "SoT", "%")),
        M("Touches in box",      "possession",         ("Att Pen",)),
        M("xAG",                 "passing",            ("xAG",)),
        M("Shot-creating actions","goal_shot_creation",("SCA", "SCA"), ("90", "Types", "GCA")),
        M("Passes into box",     "passing",            ("PPA",), ("CrsPA",)),
        M("Progressive carries", "possession",         ("PrgC",)),
        M("Progressive passes",  "passing",            ("PrgP",)),
        M("Successful take-ons", "possession",         ("Take-Ons", "Succ"), ("%", "Att", "Tkld")),
    ]),
    "MED": (["#3f88c5"]*3 + ["#d64550"]*3 + ["#43aa8b"]*3, [
        M("Progressive passes",  "passing",            ("PrgP",)),
        M("Progressive carries", "possession",         ("PrgC",)),
        M("Passes into final 3rd","passing",           ("1/3",)),
        M("Shot-creating actions","goal_shot_creation",("SCA", "SCA"), ("90", "Types", "GCA")),
        M("xAG",                 "passing",            ("xAG",)),
        M("Passes into box",     "passing",            ("PPA",), ("CrsPA",)),
        M("Tackles",             "defense",            ("Tackles", "Tkl"), ("%", "TklW")),
        M("Interceptions",       "defense",            ("Int",), ("Tkl+Int",)),
        M("Ball recoveries",     "misc",               ("Recov",)),
    ]),
    "DEF": (["#d64550"]*3 + ["#3f88c5"]*3 + ["#43aa8b"]*3, [
        M("Tackles",             "defense",            ("Tackles", "Tkl"), ("%", "TklW")),
        M("Interceptions",       "defense",            ("Int",), ("Tkl+Int",)),
        M("Clearances",          "defense",            ("Clr",)),
        M("Aerial duels won",    "misc",               ("Aerial", "Won"), ("%",)),
        M("Blocks",              "defense",            ("Blocks", "Blocks")),
        M("Aerial win %",        "misc",               ("Aerial", "Won%")),
        M("Progressive passes",  "passing",            ("PrgP",)),
        M("Pass completion %",   "passing",            ("Total", "Cmp%")),
        M("Progressive carries", "possession",         ("PrgC",)),
    ]),
    "LAT": (["#d64550"]*3 + ["#3f88c5"]*3 + ["#43aa8b"]*3, [
        M("Progressive carries", "possession",         ("PrgC",)),
        M("Touches in box",      "possession",         ("Att Pen",)),
        M("Crosses into box",    "passing",            ("CrsPA",)),
        M("Passes into box",     "passing",            ("PPA",), ("CrsPA",)),
        M("xAG",                 "passing",            ("xAG",)),
        M("Progressive passes",  "passing",            ("PrgP",)),
        M("Tackles",             "defense",            ("Tackles", "Tkl"), ("%", "TklW")),
        M("Interceptions",       "defense",            ("Int",), ("Tkl+Int",)),
        M("Ball recoveries",     "misc",               ("Recov",)),
    ]),
}
TABLES_NEEDED = ["standard", "shooting", "passing", "goal_shot_creation", "possession", "defense", "misc"]

# ============================================================================
# 4) Helpers
# ============================================================================
def flatten(df):
    df = df.copy()
    df.columns = ["__".join([str(c) for c in col if str(c) != ""]).strip("_")
                  if isinstance(col, tuple) else str(col) for col in df.columns]
    return df.reset_index()

def find_col(df, *keys, exclude=()):
    cands = [c for c in df.columns
             if all(k.lower() in c.lower() for k in keys)
             and not any(x.lower() in c.lower() for x in exclude)]
    return sorted(cands, key=len)[0] if cands else None

def make_reader(league, season):
    import soccerdata as sd
    return sd.FBref(leagues=league, seasons=season)

# ============================================================================
# 5) Core: build percentiles + pizza for one target
# ============================================================================
def build_one(t, reader_factory=make_reader):
    print(f"\n=== {t['club']} | {t['player']} ({t['pos']}) ===")
    fb = reader_factory(t["league"], t["season"])
    tables = {}
    for st in TABLES_NEEDED:
        try:
            tables[st] = flatten(fb.read_player_season_stats(stat_type=st))
        except Exception as e:
            print(f"[warn] table '{st}': {e}")
    std = tables.get("standard")
    if std is None or std.empty:
        print("[error] no standard data -> skip"); return

    col_player = "player" if "player" in std.columns else find_col(std, "player")
    col_team   = "team" if "team" in std.columns else find_col(std, "team")
    col_min    = find_col(std, "Min", exclude=("/90", "%", "90s"))
    col_pos    = find_col(std, "Pos")
    if not (col_player and col_min and col_pos):
        print("standard cols:", list(std.columns)); print("[error] missing player/Min/Pos"); return

    keyc = [c for c in (col_player, col_team) if c]
    def kidx(df): return df.set_index(keyc)

    base = kidx(std)[[col_pos, col_min]].copy(); base.columns = ["Pos", "Min"]
    base = base[pd.to_numeric(base["Min"], errors="coerce").notna()]; base["Min"] = base["Min"].astype(float)

    colors, specs = PRESETS[t["pos"]]
    per90 = pd.DataFrame(index=base.index); labels, cmap = [], {}
    for spec, color in zip(specs, colors):
        df = tables.get(spec["table"])
        if df is None or df.empty:
            print(f"[warn] table '{spec['table']}' empty -> skip '{spec['label']}'"); continue
        c = find_col(df, *spec["keys"], exclude=spec["exclude"])
        if not c:
            print(f"[warn] '{spec['label']}' not found in '{spec['table']}'"); continue
        s = pd.to_numeric(kidx(df)[c], errors="coerce")
        per90[spec["label"]] = (s / base["Min"]) * 90.0
        labels.append(spec["label"]); cmap[spec["label"]] = color

    pos_keys = {"ATA": ("FW",), "MED": ("MF",), "DEF": ("DF",), "LAT": ("DF", "MF")}[t["pos"]]
    mask = base["Pos"].fillna("").str.contains("|".join(pos_keys)) & (base["Min"] >= MIN_MINUTES)
    peers = per90[mask]
    print(f"[ok] peers: {len(peers)} players")

    names = per90.index.get_level_values(0) if per90.index.nlevels > 1 else per90.index
    hit = per90[[t["player"].lower() == str(n).lower() for n in names]]
    if hit.empty:
        hit = per90[[t["player"].split()[-1].lower() in str(n).lower() for n in names]]
    if hit.empty:
        print("player not found"); return
    tgt = hit.iloc[0]

    vals, used, cols = [], [], []
    print(f"{'Metric':22}{'per90':>9}{'pct':>5}")
    for lab in labels:
        peer = peers[lab].dropna(); v = tgt.get(lab)
        if pd.isna(v) or peer.empty: continue
        pct = round((peer < v).mean() * 100)
        vals.append(pct); used.append(lab); cols.append(cmap[lab])
        print(f"{lab:22}{v:9.2f}{pct:5d}")
    if not vals: print("[error] no valid metrics"); return

    baker = PyPizza(params=used, background_color="#FFFFFF",
                    straight_line_color="#EBEBE9", straight_line_lw=1,
                    last_circle_color="#EBEBE9", last_circle_lw=1, other_circle_lw=0,
                    inner_circle_size=11)
    fig, ax = baker.make_pizza(vals, figsize=(8, 8.6), color_blank_space="same",
                               slice_colors=cols, value_bck_colors=cols, blank_alpha=0.4,
                               kwargs_slices=dict(edgecolor="#F2F2F2", zorder=2, linewidth=1),
                               kwargs_params=dict(color="#000000", fontsize=11, va="center"),
                               kwargs_values=dict(color="#FFFFFF", fontsize=11, zorder=3,
                                                  bbox=dict(edgecolor="#000000", boxstyle="round,pad=0.2", lw=1)))
    fig.text(0.515, 0.965, t["player"], size=16, ha="center", weight="bold")
    fig.text(0.515, 0.938, f"{t['club']} | percentiles vs {'/'.join(pos_keys)} | {t['league']} {t['season']} | n={len(peers)}",
             size=9, ha="center", color="#444444")
    fig.text(0.99, 0.005, "Data: FBref/Opta via soccerdata", size=8, ha="right", color="#888888")
    fig.savefig(t["out"], dpi=200, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)
    print(f"[ok] saved: {t['out']}")


if __name__ == "__main__":
    for t in TARGETS:
        try:
            build_one(t)
        except Exception as e:
            print(f"[error] {t.get('player')}: {e}")