"""Defender distance at each shot and who guarded whom, from the court tracks.

usage: hoop-tape-miner matchups --run <run> --review <run>/review_v1 [--out <run>/matchups.json]

Reads <run>/tracks.pkl (court metres, jersey `number` after `analyze`), <run>/possessions.pkl, the review's
coach_part*.json trips (shots with a time, via film_index.events) and <run>/shot_proposals.json if present.
Writes <run>/matchups.json:
- shots: per reviewed shot the nearest opponent's distance to the shooter at the shot time (smoothed positions,
  the frame nearest to shot.t within TOL_S) and its bin: tight < TIGHT_M, contested < OPEN_M, open beyond. Unknown
  (null) when the shooter is unclear or not tracked then, when two tracklets carry the shooter's jersey, or when
  fewer than MIN_OPP opponents are tracked (the nearest one may be off camera). Shot proposals more than MATCH_S
  from every reviewed shot of that team are listed as source "proposal" (no shooter, so unknown). The reviewer's
  own `contested` label is kept next to it, and `agreement` counts reviewer label vs bin.
- bins: per team, reviewed shots per bin (att, made, known = make/miss seen).
- matchups: per team on offence, per attacker with a jersey: seconds on offence, seconds with no defender assigned,
  and the defenders assigned most (time-weighted over the tracked frames of their possessions with >= MIN_OPP
  defenders). Each frame assigns at most one defender per attacker, by least total distance to a guarding spot
  between the attacker and the basket (frame_pairs); a defender without a jersey read is null.
The team page shows both tables; a player page shows that player's rows.
"""
from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from . import media

TIGHT_M = 1.2    # under 4 ft: tight (NBA tracking "very tight" + "tight")
OPEN_M = 1.8     # 6 ft and more: open (NBA "wide open"); between: contested
TOL_S = 0.3      # nearest frame to the shot time within this window
MIN_OPP = 3      # tracked opponents needed in that frame
MATCH_S = 2.5    # a shot proposal this close to a reviewed shot of the same team is that shot
GUARD_M = 3.0    # assigned defender further than this from the guarding spot: nobody is guarding the attacker
HOOP_W = 0.27    # guarding spot: this share of the way from the attacker to the basket (Franks et al. 2015)
TOP = 3          # defenders listed per attacker
BINS = ("tight", "contested", "open")


def bin_of(d: float | None) -> str | None:
    if d is None:
        return None
    return "tight" if d < TIGHT_M else "contested" if d < OPEN_M else "open"


def _xy(df: pd.DataFrame) -> np.ndarray:
    cols = ["cx_s", "cy_s"] if "cx_s" in df else ["cx", "cy"]
    return df[cols].to_numpy(float)


def _num(v) -> str | None:
    return None if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v) else str(v)


def defender_distance(tracks: pd.DataFrame, team: str, number: str | None, t: float) -> dict:
    """{"dist_m", "bin", "defender", "opp_tracked"} for the shooter `team#number` at video time t."""
    out = dict(dist_m=None, bin=None, defender=None, opp_tracked=None)
    if number is None or t is None:
        return out
    near = tracks[(tracks.t - t).abs() <= TOL_S]
    me = near[(near.team == team) & (near.number.astype(str) == str(number))]
    if me.empty:
        return out
    frame = me.frame.iloc[int((me.t - t).abs().to_numpy().argmin())]
    me = me[me.frame == frame].drop_duplicates("track")
    if len(me) != 1:
        return out  # two tracklets read as the shooter: which one is unknown
    opp = near[(near.frame == frame) & (near.team == ("them" if team == "us" else "us"))].drop_duplicates("track")
    out["opp_tracked"] = int(len(opp))
    if len(opp) < MIN_OPP:
        return out
    d = np.linalg.norm(_xy(opp) - _xy(me)[0], axis=1)
    i = int(d.argmin())
    out.update(dist_m=round(float(d[i]), 1), defender=_num(opp.number.iloc[i]))
    out["bin"] = bin_of(out["dist_m"])
    return out


def frame_pairs(att: np.ndarray, dfd: np.ndarray, hoop: tuple[float, float] | None) -> list[tuple[int, int | None]]:
    """(attacker index, defender index or None) for one frame: one defender per attacker at most, by minimum total
    distance from each defender to the attacker's guarding spot (HOOP_W of the way from the attacker toward the
    basket, after Franks et al. 2015; the ball is not tracked in court space, so its term is left out). A pair
    further apart than GUARD_M means nobody guards that attacker."""
    from scipy.optimize import linear_sum_assignment

    spot = att if hoop is None else att + HOOP_W * (np.asarray(hoop, float) - att)
    cost = np.linalg.norm(spot[:, None] - dfd[None], axis=2)
    rows, cols = linear_sum_assignment(cost)
    pair = {int(i): int(j) for i, j in zip(rows, cols) if cost[i, j] <= GUARD_M}
    return [(i, pair.get(i)) for i in range(len(att))]


def matchups(tracks: pd.DataFrame, poss: pd.DataFrame) -> dict:
    """{offence team: {attacker number: {total_s, unguarded_s, by: [{defender, s, share}]}}} over the possessions.

    Only frames with >= MIN_OPP tracked defenders count (with fewer, a missing defender would read as "unguarded").
    poss needs start, end, offence; with `side` (the basket attacked) the guarding spot leans toward that basket."""
    from .court import hoop_xy

    p = tracks[tracks.team.isin(["us", "them"])]
    fdt = p.groupby("frame").t.first().sort_values().diff().median() if len(p) else 0.1
    fdt = float(fdt) if fdt == fdt else 0.1
    acc = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))  # off -> attacker -> defender -> s
    unguarded = defaultdict(lambda: defaultdict(float))
    for r in poss.itertuples():
        off = r.offence
        if off not in ("us", "them"):
            continue
        dfn = "them" if off == "us" else "us"
        side = getattr(r, "side", None)
        hoop = hoop_xy(side) if side in ("left", "right") else None
        w = p[p.t.between(r.start, r.end)].drop_duplicates(["frame", "track"])
        for _, g in w.groupby("frame"):
            o = g[(g.team == off) & g.number.notna()]
            o = o[~o.number.duplicated(keep=False)]  # ambiguous jersey in this frame
            d = g[g.team == dfn]
            if o.empty or len(d) < MIN_OPP:
                continue
            nums = o.number.astype(str).tolist()
            for k, j in frame_pairs(_xy(o), _xy(d), hoop):
                if j is None:
                    unguarded[off][nums[k]] += fdt
                else:
                    acc[off][nums[k]][_num(d.number.iloc[j])] += fdt
    out = {}
    for off in ("us", "them"):
        players = set(acc[off]) | set(unguarded[off])
        if not players:
            continue
        out[off] = {}
        for n in sorted(players, key=lambda s: (not s.isdigit(), int(s) if s.isdigit() else 0, s)):
            guarded = acc[off][n]
            total = sum(guarded.values()) + unguarded[off][n]
            by = sorted(guarded.items(), key=lambda kv: -kv[1])[:TOP]
            out[off][n] = dict(total_s=round(total, 1), unguarded_s=round(unguarded[off][n], 1),
                               by=[dict(defender=k, s=round(v, 1), share=round(v / total, 2)) for k, v in by])
    return out


def shot_rows(tracks: pd.DataFrame, trips: list[dict], proposals: list[dict] | None = None,
              periods=None) -> list[dict]:
    """Reviewed shots (and unmatched proposals) with the defender distance at the shot."""
    from .film_index import events

    rows = []
    for e in events(trips, periods):
        if e.kind != "shot":
            continue
        dd = defender_distance(tracks, e.team, e.player, e.t)
        rows.append(dict(source="review", pid=e.pid, team=e.team, shooter=e.player,
                         t=None if e.t is None else round(e.t, 1), made=e.made, zone=e.zone,
                         reviewer=e.contested, **dd))
    for pr in proposals or []:
        t, team = pr.get("t"), pr.get("team")
        if t is None or team not in ("us", "them"):
            continue
        if any(r["team"] == team and r["t"] is not None and abs(r["t"] - t) <= MATCH_S
               for r in rows if r["source"] == "review"):
            continue
        rows.append(dict(source="proposal", pid=None, team=team, shooter=None, t=round(float(t), 1),
                         made=True if pr.get("label") == "made" else None, zone=None, reviewer=None,
                         dist_m=None, bin=None, defender=None, opp_tracked=None))
    return sorted(rows, key=lambda r: (r["t"] is None, r["t"] or 0))


def bin_table(rows: list[dict]) -> dict:
    """{team: {bin|unknown: {att, made, known}}} over the reviewed shots."""
    out = {}
    for team in ("us", "them"):
        tab = {b: dict(att=0, made=0, known=0) for b in (*BINS, "unknown")}
        for r in rows:
            if r["source"] != "review" or r["team"] != team:
                continue
            c = tab[r["bin"] or "unknown"]
            c["att"] += 1
            c["made"] += r["made"] is True
            c["known"] += r["made"] in (True, False)
        out[team] = tab
    return out


def agreement(rows: list[dict]) -> dict:
    """{reviewer label: {bin: count}} for reviewed shots that have both."""
    out = defaultdict(lambda: defaultdict(int))
    for r in rows:
        if r["source"] == "review" and r["reviewer"] and r["bin"]:
            out[r["reviewer"]][r["bin"]] += 1
    return {k: dict(v) for k, v in out.items()}


# ---- page tables ------------------------------------------------------------------------------------------------

UI = {
    "zh": dict(title="对位与出手防守", shots="按最近防守人距离的出手", bin="距离", us="我们", them="对手",
               att="出手", made="命中 / 看清", tight=f"贴身（< {TIGHT_M} 米）", contested=f"有干扰（{TIGHT_M}–{OPEN_M} 米）",
               open=f"空位（≥ {OPEN_M} 米）", unknown="不明", match="对位（按时间）", player="球员",
               by="最常防他的人", guarded="他最常防的人", free="身边没人",
               note="出手瞬间离投篮人最近的对手的距离（位置追踪，误差约半米）；投篮人或防守人没追踪到就记为不明，不猜。"
                    "对位 = 每一帧离进攻球员最近的防守人，按时间累计；{g} 米内没人算身边没人。"),
    "en": dict(title="Matchups and shot defence", shots="Shots by nearest defender", bin="Distance", us="Us",
               them="Them", att="Att", made="Made / seen", tight=f"tight (< {TIGHT_M} m)",
               contested=f"contested ({TIGHT_M}–{OPEN_M} m)", open=f"open (≥ {OPEN_M} m)", unknown="unknown",
               match="Matchups (by time)", player="Player", by="Guarded most by", guarded="Guarded most",
               free="no one near",
               note="Distance from the shooter to the nearest opponent at the shot (position tracking, about half a "
                    "metre of error); unknown when the shooter or the defenders are not tracked, never guessed. "
                    "Matchup = the nearest defender in every frame, added up over time; nobody within {g} m counts as "
                    "no one near."),
}


def _who(entries: list[dict], u: dict) -> str:
    return ", ".join(f"{'#' + e['defender'] if e['defender'] else '?'} {round(100 * e['share'])}%" for e in entries) or "–"


def _guarded_most(m_them: dict, n: str) -> list[dict]:
    """Their attackers our #n was nearest to most (inverted matchups), share of our #n's guarding time."""
    got = {a: next((b["s"] for b in v["by"] if b["defender"] == n), 0.0) for a, v in m_them.items()}
    total = sum(got.values())
    top = sorted(((a, s) for a, s in got.items() if s > 0), key=lambda kv: -kv[1])[:TOP]
    return [dict(defender=a, s=s, share=s / total) for a, s in top]


def tables_html(doc: dict, focus: str | None, lang: str) -> str:
    """Shot-defence and matchup tables (all our players, or only `focus`); "" when there is nothing to show."""
    u = UI[lang]
    m = doc.get("matchups") or {}
    m_us, m_them = m.get("us") or {}, m.get("them") or {}
    parts = []
    if focus is None:
        bins = doc.get("bins") or {}
        if any(c["att"] for t in bins.values() for c in t.values()):
            rows = []
            for b in (*BINS, "unknown"):
                cells = ""
                for side in ("us", "them"):
                    c = (bins.get(side) or {}).get(b, dict(att=0, made=0, known=0))
                    cells += f"<td>{c['att']}</td><td>{c['made']}/{c['known']}</td>"
                rows.append(f"<tr><td>{u[b]}</td>{cells}</tr>")
            head = (f"<tr><th rowspan=2>{u['bin']}</th><th colspan=2>{u['us']}</th><th colspan=2>{u['them']}</th></tr>"
                    f"<tr><th>{u['att']}</th><th>{u['made']}</th><th>{u['att']}</th><th>{u['made']}</th></tr>")
            parts.append(f'<h3>{u["shots"]}</h3><div class="table-wrap"><table><thead>{head}</thead>'
                         f'<tbody>{"".join(rows)}</tbody></table></div>')
        players = sorted(m_us, key=lambda s: int(s) if s.isdigit() else 999)
    else:
        players = [focus] if focus in m_us else []
        mine = [r for r in doc.get("shots") or [] if r["source"] == "review" and r["team"] == "us" and r["shooter"] == focus]
        if mine:
            cnt = {b: sum((r["bin"] or "unknown") == b for r in mine) for b in (*BINS, "unknown")}
            parts.append(f"<h3>{u['shots']}</h3><p>" + " · ".join(f"{u[b]}: {n}" for b, n in cnt.items() if n) + "</p>")
    if players:
        rows = "".join(f"<tr><td>#{html.escape(n)}</td><td>{_who(m_us[n]['by'], u)}</td>"
                       f"<td>{_who(_guarded_most(m_them, n), u)}</td>"
                       f"<td>{round(100 * m_us[n]['unguarded_s'] / m_us[n]['total_s']) if m_us[n]['total_s'] else 0}%</td></tr>"
                       for n in players)
        parts.append(f'<h3>{u["match"]}</h3><div class="table-wrap"><table><thead><tr><th>{u["player"]}</th>'
                     f'<th>{u["by"]}</th><th>{u["guarded"]}</th><th>{u["free"]}</th></tr></thead><tbody>{rows}</tbody>'
                     f'</table></div>')
    if not parts:
        return ""
    return "".join(parts) + f'<p class="fi-note">{html.escape(u["note"].format(g=GUARD_M))}</p>'


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner matchups", description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", required=True, help="run folder with tracks.pkl and possessions.pkl")
    ap.add_argument("--review", required=True, help="review folder with coach_part*.json")
    ap.add_argument("--game", help="game.json (periods, for the half of each shot)")
    ap.add_argument("--out", help="default <run>/matchups.json")
    a = ap.parse_args(argv)
    from .coach_eval import load_trips

    run = Path(a.run)
    tracks = pd.read_pickle(run / "tracks.pkl")
    game = json.loads(Path(a.game).read_text(encoding="utf8")) if a.game else {}
    props = run / "shot_proposals.json"
    proposals = json.loads(props.read_text(encoding="utf8")).get("proposals", []) if props.exists() else []
    rows = shot_rows(tracks, load_trips(Path(a.review)), proposals, game.get("periods"))
    poss = pd.read_pickle(run / "possessions.pkl") if (run / "possessions.pkl").exists() else pd.DataFrame()
    doc = dict(params=dict(tight_m=TIGHT_M, open_m=OPEN_M, tol_s=TOL_S, min_opp=MIN_OPP, guard_m=GUARD_M),
               shots=rows, bins=bin_table(rows), agreement=agreement(rows),
               matchups=matchups(tracks, poss) if len(poss) else {})
    out = Path(a.out) if a.out else run / "matchups.json"
    media.write_json_atomic(out, doc, indent=1)
    rev = [r for r in rows if r["source"] == "review"]
    known = sum(r["bin"] is not None for r in rev)
    print(f"matchups: {len(rev)} reviewed shots ({known} with a defender distance), "
          f"{len(rows) - len(rev)} other proposals -> {out}")
    print("reviewer label vs distance bin:", json.dumps(doc["agreement"]))


if __name__ == "__main__":
    main()
