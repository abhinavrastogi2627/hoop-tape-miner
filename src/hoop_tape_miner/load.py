"""Physical load per stint on court: minutes, distance, sprints, top speed, high-speed distance, from the CV tracks.

usage: hoop-tape-miner load --run <run> [--lineup lineup.json ...] [--game game.json] [--out <run>/load.json]

Reads <run>/tracks.pkl (court positions in metres, jersey `number` per row after `analyze`) and the stints:
--lineup files map "team#number" -> [[t_in, t_out], ...] in video seconds (later files override earlier keys, as in
plusminus); default the review's lineup_intervals.json (coach-sheets), else intervals computed from the tracks.
Writes <run>/load.json: per player, one entry per stint and a total. The focus player's page shows a table.

Method (positions are noisy and a jersey's track can jump to another player):
- one sample per frame from the smoothed positions (cx_s, cy_s; a rolling median); frames where two tracklets carry
  the same jersey are dropped (ambiguous), never averaged;
- a step counts only when the samples are <= MAX_DT apart and its speed is <= SPEED_CAP (faster = identity switch
  or projection jump): the step is dropped and the series breaks there. Gaps are never bridged or filled, so
  distance is "distance seen"; coverage = tracked time / stint time, and stints under MIN_COVERAGE are flagged;
- speed = centred rolling mean of the step speeds over SMOOTH_S inside each unbroken run; top speed is its maximum;
- sprint: speed >= SPRINT_SPEED for >= SPRINT_MIN_S; high-speed distance: steps at speed >= HIGH_SPEED.
Unknown values (no samples) are null, never 0.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import media
from .timefmt import mmss

SPEED_CAP = 8.0       # m/s; faster steps are identity switches or projection jumps (adult rec players rarely pass 7)
MAX_DT = 0.25         # s; a longer gap between samples breaks the series
SMOOTH_S = 0.5        # s; speed window
HIGH_SPEED = 4.0      # m/s (14.4 km/h): high-speed running, a common basketball threshold
SPRINT_SPEED = 5.0    # m/s (18 km/h): sprint
SPRINT_MIN_S = 0.5    # s at or above SPRINT_SPEED for one sprint
MIN_COVERAGE = 0.5    # share of the stint tracked; below it the stint is flagged as low coverage


def player_series(tracks: pd.DataFrame, team: str, number: str) -> pd.DataFrame:
    """One row per frame (t, x, y, track) for a jersey; frames claimed by two tracklets are dropped."""
    d = tracks[(tracks.team == team) & (tracks.number.astype(str) == str(number))] if len(tracks) else tracks
    if d is None or d.empty:
        return pd.DataFrame(columns=["frame", "t", "x", "y", "track"])
    xs, ys = ("cx_s", "cy_s") if "cx_s" in d else ("cx", "cy")
    d = d.drop_duplicates(["frame", "track"])
    d = d[~d.duplicated("frame", keep=False)]
    out = pd.DataFrame({"frame": d.frame, "t": d.t, "x": d[xs], "y": d[ys], "track": d.track})
    return out.dropna(subset=["x", "y"]).sort_values("t").reset_index(drop=True)


def _speeds(s: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(step distance, step dt, smoothed speed) per valid step; invalid steps are removed."""
    if len(s) < 2:
        return np.array([]), np.array([]), np.array([])
    t, x, y = s.t.to_numpy(float), s.x.to_numpy(float), s.y.to_numpy(float)
    dt = np.diff(t)
    dist = np.hypot(np.diff(x), np.diff(y))
    with np.errstate(divide="ignore", invalid="ignore"):
        v = dist / dt
    ok = (dt > 0) & (dt <= MAX_DT) & (v <= SPEED_CAP)
    run = np.cumsum(~ok)  # a new run after every broken step
    step = float(np.median(dt[dt > 0])) if (dt > 0).any() else 0.1
    win = max(1, int(round(SMOOTH_S / step)))
    vs = pd.Series(v[ok]).groupby(run[ok]).transform(
        lambda r: r.rolling(win, center=True, min_periods=1).mean()).to_numpy()
    return dist[ok], dt[ok], vs if len(vs) else np.array([])


def _sprints(vs: np.ndarray, dt: np.ndarray) -> int:
    n, acc = 0, 0.0
    for v, d in zip(np.append(vs, 0.0), np.append(dt, 0.0)):
        if v >= SPRINT_SPEED:
            acc += d
            continue
        n += acc >= SPRINT_MIN_S - 1e-9
        acc = 0.0
    return int(n)


def _r(v, n=1):
    return None if v is None else round(float(v), n)


def stint_load(series: pd.DataFrame, t0: float, t1: float, frame_dt: float = 0.1) -> dict:
    """Load numbers of one stint [t0, t1) from a player_series."""
    s = series[(series.t >= t0) & (series.t < t1)] if len(series) else series
    length = max(float(t1) - float(t0), 1e-6)
    tracked = len(s) * frame_dt
    cov = min(1.0, tracked / length)
    dist, dt, vs = _speeds(s)
    seen = len(dist) > 0
    d = float(dist.sum()) if seen else None
    return dict(t0=round(float(t0), 1), t1=round(float(t1), 1), minutes=round(length / 60, 2),
                tracked_minutes=round(tracked / 60, 2), coverage=round(cov, 2), low_coverage=cov < MIN_COVERAGE,
                distance_m=_r(d), m_per_tracked_min=_r(d / (tracked / 60)) if seen and tracked else None,
                sprints=_sprints(vs, dt) if seen else None, top_speed=_r(vs.max(), 2) if seen else None,
                hsd_m=_r(dist[vs >= HIGH_SPEED].sum()) if seen else None)


def _total(stints: list[dict]) -> dict:
    def tot(k):
        vals = [s[k] for s in stints if s[k] is not None]
        return sum(vals) if vals else None
    mins = sum(s["minutes"] for s in stints)
    tracked = sum(s["tracked_minutes"] for s in stints)
    d = tot("distance_m")
    tops = [s["top_speed"] for s in stints if s["top_speed"] is not None]
    return dict(stints=len(stints), minutes=round(mins, 2), tracked_minutes=round(tracked, 2),
                coverage=round(tracked / mins, 2) if mins else 0.0, distance_m=_r(d),
                m_per_tracked_min=_r(d / tracked) if d is not None and tracked else None,
                sprints=tot("sprints"), top_speed=max(tops) if tops else None, hsd_m=_r(tot("hsd_m")))


def game_load(tracks: pd.DataFrame, lineup: dict, frame_dt: float | None = None) -> dict:
    """{"params", "players": {"team#number": {team, number, stints: [...], total}}} for every lineup key."""
    if frame_dt is None:
        ft = tracks.groupby("frame").t.first().sort_values().diff() if len(tracks) else pd.Series(dtype=float)
        frame_dt = float(ft.median()) if ft.notna().any() else 0.1
    players = {}
    for key, segs in lineup.items():
        team, _, num = key.partition("#")
        s = player_series(tracks, team, num)
        stints = [stint_load(s, a, b, frame_dt) for a, b in sorted(segs) if b > a]
        players[key] = dict(team=team, number=num, stints=stints, total=_total(stints))
    params = dict(speed_cap=SPEED_CAP, max_dt=MAX_DT, smooth_s=SMOOTH_S, high_speed=HIGH_SPEED,
                  sprint_speed=SPRINT_SPEED, sprint_min_s=SPRINT_MIN_S, min_coverage=MIN_COVERAGE,
                  frame_dt=round(frame_dt, 3))
    return {"params": params, "players": players}


# ---- page table -------------------------------------------------------------------------------------------------

UI = {
    "zh": dict(title="跑动负荷（每段上场）", stint="上场段", min="分钟", tracked="追踪到", dist="跑动 (米)",
               per_min="米/分钟", sprints="冲刺", top="最高速度 (米/秒)", hsd="高速跑 (米)", total="合计",
               low="追踪不足", note="来自比赛录像的位置追踪。距离只算追踪到的时间，空档不补；追踪不到一半的上场段标为“追踪不足”，"
               "数字只作参考。冲刺 = 至少 {s} 秒达到 {v} 米/秒；高速跑 = {h} 米/秒以上。"),
    "en": dict(title="Running load per stint", stint="Stint", min="Min", tracked="Tracked", dist="Distance (m)",
               per_min="m/min", sprints="Sprints", top="Top speed (m/s)", hsd="High-speed (m)", total="Total",
               low="low coverage", note="From position tracking on the game video. Distance counts only tracked time; "
               "gaps are never filled. Stints tracked under half the time are marked low coverage: read them as rough. "
               "Sprint = at least {s} s at {v} m/s or faster; high-speed = above {h} m/s."),
}


def _cell(v, n=0):
    return "–" if v is None else f"{v:.{n}f}"


def table_html(doc: dict, number: str, lang: str) -> str:
    """Stint table for our player `number` from a load.json document; "" when the player has no stints."""
    p = (doc.get("players") or {}).get(f"us#{number}")
    if not p or not p.get("stints"):
        return ""
    u = UI[lang]

    def row(label, s, cls=""):
        tr = f"{round(100 * s['coverage'])}%" + (f' <span class="ld-low">{u["low"]}</span>' if s.get("low_coverage") else "")
        return (f'<tr{cls}><td>{label}</td><td>{_cell(s["minutes"], 1)}</td><td>{tr}</td><td>{_cell(s["distance_m"])}</td>'
                f'<td>{_cell(s["m_per_tracked_min"])}</td><td>{_cell(s["sprints"])}</td><td>{_cell(s["top_speed"], 1)}</td>'
                f'<td>{_cell(s["hsd_m"])}</td></tr>')
    rows = [row(f"{mmss(s['t0'])}–{mmss(s['t1'])}", s, ' class="ld-dim"' if s.get("low_coverage") else "")
            for s in p["stints"]]
    rows.append(row(f"<b>{u['total']}</b>", p["total"]))
    head = "".join(f"<th>{u[k]}</th>" for k in ("stint", "min", "tracked", "dist", "per_min", "sprints", "top", "hsd"))
    note = u["note"].format(s=SPRINT_MIN_S, v=SPRINT_SPEED, h=HIGH_SPEED)
    return (f'<div class="table-wrap ld"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
            f'<p class="fi-note">{html.escape(note)}</p>')


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner load", description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", required=True, help="run folder with tracks.pkl")
    ap.add_argument("--lineup", action="append", default=[],
                    help="stints json (team#number -> [[t_in, t_out]]); repeat to override keys (default: review "
                         "lineup_intervals.json)")
    ap.add_argument("--game", help="game.json (periods, rosters, review_dir) when stints come from the tracks")
    ap.add_argument("--out", help="default <run>/load.json")
    a = ap.parse_args(argv)
    run = Path(a.run)
    tracks = pd.read_pickle(run / "tracks.pkl")
    game = json.loads(Path(a.game).read_text(encoding="utf8")) if a.game else {}
    files = [Path(p) for p in a.lineup]
    if not files:
        review = run / (game.get("review_dir") or "review_v1")
        files = [p for p in (review / "lineup_intervals.json", run / "lineup_intervals.json") if p.exists()][:1]
    lineup = {}
    for p in files:
        lineup.update(json.loads(p.read_text(encoding="utf8")))
    if not lineup:
        from .coach_review import lineup_intervals  # loads OpenCV; only needed without a lineup file
        lineup = lineup_intervals(tracks, game.get("periods"), game.get("rosters"))
        print("stints from the tracks (no lineup file)")
    doc = game_load(tracks, lineup)
    out = Path(a.out) if a.out else run / "load.json"
    media.write_json_atomic(out, doc, indent=1)
    low = sum(s["low_coverage"] for p in doc["players"].values() for s in p["stints"])
    n = sum(len(p["stints"]) for p in doc["players"].values())
    print(f"load: {len(doc['players'])} players, {n} stints ({low} low coverage) -> {out}")


if __name__ == "__main__":
    main()
