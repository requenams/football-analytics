"""
Shot map de un partido usando datos abiertos de StatsBomb.
Uso:  python src/shot_map.py
Cambia el MATCH_ID por cualquier partido (ver notebooks/explorar_datos).
"""
import warnings
warnings.filterwarnings("ignore")

import matplotlib.pyplot as plt
from mplsoccer import Pitch
from statsbombpy import sb

MATCH_ID = 3869685  # Final Mundial 2022: Argentina 3-3 Francia

def load_shots(match_id: int):
    events = sb.events(match_id=match_id)
    shots = events[events["type"] == "Shot"].copy()
    # location = [x, y] en un campo de 120x80
    shots[["x", "y"]] = shots["location"].apply(lambda loc: [loc[0], loc[1]]).tolist()
    shots["is_goal"] = shots["shot_outcome"] == "Goal"
    return shots

def plot_shot_map(shots, match_id):
    teams = shots["team"].unique()
    pitch = Pitch(pitch_type="statsbomb", half=False, line_color="#c7c7c7",
                  pitch_color="#22312b")
    fig, ax = pitch.draw(figsize=(11, 7))
    fig.set_facecolor("#22312b")

    colors = {teams[0]: "#ef4444", teams[1]: "#38bdf8"}
    for team in teams:
        t = shots[shots["team"] == team]
        # tiros que no son gol
        no_goal = t[~t["is_goal"]]
        pitch.scatter(no_goal["x"], no_goal["y"], s=no_goal["shot_statsbomb_xg"] * 900 + 40,
                      ax=ax, color=colors[team], edgecolors="black", alpha=0.55, label=f"{team} (tiro)")
        # goles: mismo color, borde grueso y estrella
        goals = t[t["is_goal"]]
        pitch.scatter(goals["x"], goals["y"], s=goals["shot_statsbomb_xg"] * 900 + 120,
                      ax=ax, color=colors[team], edgecolors="white", linewidths=2.2,
                      marker="*", label=f"{team} (GOL)")

    ax.legend(loc="upper center", ncol=2, facecolor="#22312b", edgecolor="none",
              labelcolor="white", fontsize=9, bbox_to_anchor=(0.5, 0.02))
    ax.set_title(f"Shot map — {teams[0]} vs {teams[1]}  ·  tamaño = xG",
                 color="white", fontsize=13, pad=12)
    out = f"figures/shot_map_{match_id}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Guardado: {out}")
    print(f"Tiros totales: {len(shots)} | xG {teams[0]}: "
          f"{shots[shots.team==teams[0]]['shot_statsbomb_xg'].sum():.2f} | "
          f"xG {teams[1]}: {shots[shots.team==teams[1]]['shot_statsbomb_xg'].sum():.2f}")

if __name__ == "__main__":
    shots = load_shots(MATCH_ID)
    plot_shot_map(shots, MATCH_ID)
