"""Plus-minus and stints per player from lineup intervals + the official score flow.

    hoop-tape-miner plusminus --lineup review_v1/lineup_intervals.json --official official.json \
        --out plusminus.json [--player 17] [--team us] [--lineup film_stints.json] \
        [--event-times play_times.json] [--merge-gap 0] [--windows 450-1272,1272-1810]

Lineup files map "team#number" -> [[t_in, t_out], ...] in our-video seconds (coach-sheets
writes the CV version; a hand-checked file with the same layout can be passed as a second
--lineup and overrides those keys). An event counts for a stint when t_in <= t < t_out.
Event time = `play_t` if the score_flow entry has one, else `--event-times[our_video_t]`
(film-verified basket times; the scorer feed lags), else `our_video_t`. Events without a
video time (off-video) are ignored.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .timefmt import mmss


def score_events(official: dict, times: dict | None = None) -> list[tuple[float, str, int]]:
    """[(t, team, points)] sorted by time, from official.json score_flow."""
    times = {float(k): float(v) for k, v in (times or {}).items()}
    ev = []
    for e in official["score_flow"]:
        t = e.get("play_t")
        if t is None and e.get("our_video_t") is not None:
            t = times.get(float(e["our_video_t"]), e["our_video_t"])
        if t is not None:
            ev.append((float(t), e["team"], int(e["points"])))
    return sorted(ev, key=lambda x: x[0])


def merge(segs, gap: float = 0.0) -> list[list[float]]:
    out = []
    for a, b in sorted(segs):
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _score_before(events, t):
    us = sum(p for x, team, p in events if x < t and team == "us")
    them = sum(p for x, team, p in events if x < t and team == "them")
    return [us, them]


def _tally(events, inside):
    f = [0, 0]
    for t, team, p in events:
        if inside(t):
            f[0 if team == "us" else 1] += p
    return f


def player_plusminus(stints, events, team="us", windows=()) -> dict:
    """+/- seen from the player's team; `for`/`against` are that team's / the other team's points."""
    flip = (lambda x: x) if team == "us" else (lambda x: x[::-1])

    def on(t):
        return any(a <= t < b for a, b in stints)

    rows = []
    for a, b in stints:
        pts = flip(_tally(events, lambda t: a <= t < b))
        rows.append({"in": a, "out": b, "seconds": round(b - a, 1), "entry_score": _score_before(events, a),
                     "exit_score": _score_before(events, b), "for": pts[0], "against": pts[1], "net": pts[0] - pts[1]})
    on_pts = flip(_tally(events, on))
    off_pts = flip(_tally(events, lambda t: not on(t)))
    res = {"stints": rows,
           "on": {"seconds": round(sum(b - a for a, b in stints), 1), "for": on_pts[0], "against": on_pts[1],
                  "net": on_pts[0] - on_pts[1]},
           "off": {"for": off_pts[0], "against": off_pts[1], "net": off_pts[0] - off_pts[1]}}
    if windows:
        res["windows"] = []
        for w0, w1 in windows:
            i = flip(_tally(events, lambda t: w0 <= t < w1 and on(t)))
            o = flip(_tally(events, lambda t: w0 <= t < w1 and not on(t)))
            res["windows"].append({"t0": w0, "t1": w1, "on": i, "off": o})
    return res


def compute(lineup: dict, events, players=None, merge_gap=0.0, windows=()) -> dict:
    keys = players or sorted(lineup, key=lambda k: (k.split("#")[0], int(k.split("#")[1]) if k.split("#")[1].isdigit() else 999))
    return {k: player_plusminus(merge(lineup.get(k, []), merge_gap), events, k.split("#")[0], windows) for k in keys}


def markdown(result: dict, detail: bool) -> str:
    out = ["| Player | On (min) | For | Against | On +/- | Off +/- | Stints |", "|---|---|---|---|---|---|---|"]
    for k, r in result.items():
        out.append(f"| {k} | {r['on']['seconds'] / 60:.1f} | {r['on']['for']} | {r['on']['against']} | "
                   f"{r['on']['net']:+d} | {r['off']['net']:+d} | {len(r['stints'])} |")
    if detail:
        for k, r in result.items():
            out += ["", f"**{k} stints** (score is us-them)", "",
                    "| # | In -> Out | Dur | Entry -> exit | For-Against | +/- |", "|---|---|---|---|---|---|"]
            for i, s in enumerate(r["stints"], 1):
                out.append(f"| S{i} | {mmss(s['in'])} -> {mmss(s['out'])} | {mmss(s['seconds'])} | "
                           f"{'-'.join(map(str, s['entry_score']))} -> {'-'.join(map(str, s['exit_score']))} | "
                           f"{s['for']}-{s['against']} | {s['net']:+d} |")
            for w in r.get("windows", []):
                out.append(f"\nwindow {mmss(w['t0'])}-{mmss(w['t1'])}: on {w['on'][0]}-{w['on'][1]}, "
                           f"off {w['off'][0]}-{w['off'][1]}")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner plusminus", description=__doc__.splitlines()[0])
    ap.add_argument("--lineup", action="append", required=True, help="lineup json; repeat to override keys")
    ap.add_argument("--official", required=True)
    ap.add_argument("--out", required=True, help="output json")
    ap.add_argument("--player", help="jersey number (default: all players)")
    ap.add_argument("--team", default="us", choices=["us", "them"])
    ap.add_argument("--event-times", help='json {"<our_video_t>": play_t} with film-verified basket times')
    ap.add_argument("--merge-gap", type=float, default=0.0, help="merge stints separated by <= this many s")
    ap.add_argument("--windows", default="", help="t0-t1,... (s): on/off split per game stretch")
    a = ap.parse_args(argv)
    lineup = {}
    for f in a.lineup:
        lineup.update(json.loads(Path(f).read_text(encoding="utf-8")))
    official = json.loads(Path(a.official).read_text(encoding="utf-8"))
    times = json.loads(Path(a.event_times).read_text(encoding="utf-8")) if a.event_times else None
    events = score_events(official, times)
    windows = [tuple(float(x) for x in w.split("-")) for w in a.windows.split(",") if w]
    players = [f"{a.team}#{a.player}"] if a.player else None
    if players and players[0] not in lineup:
        raise SystemExit(f"{players[0]} not in lineup files")
    result = compute(lineup, events, players, a.merge_gap, windows)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(markdown(result, detail=bool(a.player)))
    print("\nwrote", a.out)


if __name__ == "__main__":
    main()
