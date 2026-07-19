#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Forwards scouting report (basic-data version - Swiss football)
==============================================================
FBref only exposes BASIC data for Swiss football (goals, shots, fouls...),
with no xG or creation/dribbling data. This script builds an honest pizza
chart from what IS available, for the three Super League forwards.

Run:  python forwards_report.py
Produces one PNG per player.
"""
import json
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mplsoccer import PyPizza

# --- The three forwards ---
TARGETS = [
    dict(player="Elias Maluvunu",   out="01_maluvunu.png"),
    dict(player="Malamine Efekele",  out="04_efekele.png"),
    dict(player="Lovro Zvonarek",    out="05_zvonarek.png"),
]
LEAGUE, SEASON = "SUI-Super League", "2025-2026"
MIN_MINUTES = 450

# --- Register the Swiss league in soccerdata (just in case) ---
CFG = Path.home() / "soccerdata" / "config"; CFG.mkdir(parents=True, exist_ok=True)
f = CFG / "league_dict.json"
cur = json.loads(f.read_text() or "{}") if f.exists() else {}
if LEAGUE not in cur:
    cur[LEAGUE] = {"FBref": "Swiss Super League", "season_start": "Jul", "season_end": "May"}
    f.write_text(json.dumps(cur, indent=2))

# --- Metrics: (label, table, keys, exclude, is_rate) ---
#     is_rate=True -> value used as-is (%, ratio); NOT divided by minutes
METRICS = [
    ("Goals",            "standard", ("Performance", "Gls"), (), False),
    ("Assists",          "standard", ("Performance", "Ast"), (), False),
    ("Goals + Assists",  "standard", ("Performance", "G+A"), (), False),
    ("Shots",            "shooting", ("Standard", "Sh"), ("/90", "SoT", "%"), False),
    ("Shots on target",  "shooting", ("Standard", "SoT"), ("/90", "%"), False),
    ("Shot accuracy %",  "shooting", ("SoT%",), (), True),
    ("Goals per shot",   "shooting", ("G/Sh",), (), True),
    ("Fouls drawn",      "misc",     ("Fld",), (), False),
    ("Aerial duels won", "misc",     ("Aerial", "Won"), ("%",), False),
]
COLORS = ["#d64550"]*3 + ["#3f88c5"]*3 + ["#43aa8b"]*3

# --- Helpers ---
def flatten(df):
    df = df.copy()
    df.columns = ["__".join(str(c) for c in col if str(c) != "").strip("_")
                  if isinstance(col, tuple) else str(col) for col in df.columns]
    return df.reset_index()

def find_col(df, *keys, exclude=()):
    c = [x for x in df.columns
         if all(k.lower() in x.lower() for k in keys)
         and not any(e.lower() in x.lower() for e in exclude)]
    return sorted(c, key=len)[0] if c else None

def make_reader():
    import soccerdata as sd
    return sd.FBref(leagues=LEAGUE, seasons=SEASON)

# --- Load the tables Switzerland actually has ---
def load_all(reader_factory=make_reader):
    fb = reader_factory()
    tabs = {}
    for st in ["standard", "shooting", "misc"]:
        try:
            tabs[st] = flatten(fb.read_player_season_stats(stat_type=st))
        except Exception as e:
            print(f"[warn] table '{st}': {e}")
    return tabs

# --- Build per-90 / rate matrix for all players ---
def build_matrix(tabs):
    std = tabs.get("standard")
    if std is None or std.empty:
        return None, None, None
    col_player = "player" if "player" in std.columns else find_col(std, "player")
    col_team   = "team" if "team" in std.columns else find_col(std, "team")
    col_min    = find_col(std, "Min", exclude=("/90", "%", "90s"))
    col_pos    = find_col(std, "Pos")
    keyc = [c for c in (col_player, col_team) if c]
    kidx = lambda d: d.set_index(keyc)

    base = kidx(std)[[col_pos, col_min]].copy(); base.columns = ["Pos", "Min"]
    base = base[pd.to_numeric(base["Min"], errors="coerce").notna()]
    base["Min"] = base["Min"].astype(float)

    mat = pd.DataFrame(index=base.index); labels, cmap = [], {}
    for (label, table, keys, excl, is_rate), color in zip(METRICS, COLORS):
        df = tabs.get(table)
        if df is None or df.empty:
            print(f"[warn] no table '{table}' -> skip '{label}'"); continue
        c = find_col(df, *keys, exclude=excl)
        if not c:
            print(f"[warn] column for '{label}' not found -> skip"); continue
        s = pd.to_numeric(kidx(df)[c], errors="coerce")
        mat[label] = s if is_rate else (s / base["Min"]) * 90.0
        labels.append(label); cmap[label] = color
    return base, mat, (labels, cmap)

# --- Pizza for one player ---
def pizza(name, out, base, mat, labels, cmap):
    peers_mask = base["Pos"].fillna("").str.contains("FW") & (base["Min"] >= MIN_MINUTES)
    peers = mat[peers_mask]

    names = mat.index.get_level_values(0) if mat.index.nlevels > 1 else mat.index
    idx = [n for n in names if name.lower() == str(n).lower()]
    if not idx:  # fallback by surname
        idx = [n for n in names if name.split()[-1].lower() in str(n).lower()]
    if not idx:
        print(f"[error] player '{name}' not found"); return
    tgt = mat[[str(n) == str(idx[0]) for n in names]].iloc[0]

    vals, used, cols = [], [], []
    print(f"\n--- {name} (forward peers n={len(peers)}) ---")
    print(f"{'Metric':20}{'value':>8}{'pct':>5}")
    for lab in labels:
        col = peers[lab].dropna(); v = tgt.get(lab)
        if pd.isna(v) or col.empty: continue
        pct = round((col < v).mean() * 100)
        vals.append(pct); used.append(lab); cols.append(cmap[lab])
        print(f"{lab:20}{v:8.2f}{pct:5d}")
    if len(vals) < 3:
        print(f"[error] only {len(vals)} metrics -> pizza not useful for {name}"); return

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
    fig.text(0.515, 0.965, name, size=16, ha="center", weight="bold")
    fig.text(0.515, 0.938, f"Percentiles vs forwards | Swiss Super League {SEASON} | n={len(peers)}",
             size=9, ha="center", color="#444444")
    fig.text(0.99, 0.005, "Basic data: FBref via soccerdata", size=8, ha="right", color="#888888")
    fig.savefig(out, dpi=200, bbox_inches="tight", facecolor="#FFFFFF"); plt.close(fig)
    print(f"[ok] saved: {out}")

if __name__ == "__main__":
    tabs = load_all()
    base, mat, meta = build_matrix(tabs)
    if base is None:
        print("[error] no standard data. Check your connection.")
    else:
        labels, cmap = meta
        for t in TARGETS:
            pizza(t["player"], t["out"], base, mat, labels, cmap)