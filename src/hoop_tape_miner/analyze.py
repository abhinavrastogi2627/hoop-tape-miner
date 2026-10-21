"""CLI: tracks + jersey reads + game config -> player identities, possessions, metrics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .camera import sampled_fps
from .court import LENGTH
from .metrics import possession_metrics
from .possessions import frame_table, offence_by_distance, segment_possessions


def identities(tr: pd.DataFrame, jersey: dict, rosters: dict) -> dict[int, str]:
    """track -> jersey number, keeping only numbers on the team's roster (if given).

    A tracklet whose vote is "none" is still accepted when it has exactly one distinct non-none read
    that is on the team's roster (the vote needs 2 agreeing reads, which drops many one-read tracklets).
    Roster entries and reads are compared as strings, so a hand-written roster of ints works too.
    """
    team_of = tr.groupby("track").team.first()
    out = {}
    for tid, j in jersey.items():
        n = str(j["number"])
        tid = int(tid)
        if tid not in team_of.index:
            continue
        roster = {str(x) for x in rosters.get(team_of[tid]) or []}
        if n == "none":
            reads = {str(r) for r in j.get("reads", []) if str(r) != "none"}
            if len(reads) != 1 or not roster:
                continue
            n = reads.pop()
        if roster and n not in roster:
            continue
        out[tid] = n
    return out


def halves(n_periods: int) -> list[list[int]]:
    """Period numbers that share baskets: 1-2 and 3+ with four quarters (overtime keeps the 4th quarter's
    baskets), else period 1 and the rest (as fetch.halftime splits them)."""
    if n_periods <= 1:
        return [[1]] if n_periods == 1 else []
    k = 2 if n_periods >= 4 else 1
    return [list(range(1, k + 1)), list(range(k + 1, n_periods + 1))]


def _us_attacks_right(sig: dict) -> bool | None:
    """From the "offence stands further from the basket" signal per court half; None when there is none.
    sig[side] > 0: on that half, us stand further from its basket than them, so us attack it."""
    r, l = sig["right"], sig["left"]
    if np.isfinite(r) and np.isfinite(l):
        return bool(r - l > 0)
    if np.isfinite(r):
        return bool(r > 0)
    if np.isfinite(l):
        return not l > 0
    return None


def attack_directions(tr: pd.DataFrame, ft: pd.DataFrame, live: pd.Series, groups: list[list[int]]) -> dict:
    """{(period, team): side attacked}, one direction per half (`groups` of periods, signal pooled), since teams
    only switch baskets at half time. A half with no signal takes the nearest other half's direction (switched
    at each half time) with a warning; with no signal at all it fails instead of guessing."""
    us_right = {}
    for i, group in enumerate(groups):
        f = ft[ft.period.isin(group) & live]
        sig = {s: offence_by_distance(tr, f.index[(f.x_med > LENGTH / 2) == (s == "right")], s)
               for s in ("left", "right")}
        us_right[i] = _us_attacks_right(sig)
        if us_right[i] is not None:
            print(f"periods {'+'.join(map(str, group))}: us attack {'right' if us_right[i] else 'left'}  "
                  f"(signal R {sig['right']:+.2f}, L {sig['left']:+.2f})")
    known = {i: v for i, v in us_right.items() if v is not None}
    if not known:
        raise SystemExit("cannot tell the attack direction: no live frames with both teams in any half. Check "
                         "`periods` in game.json (seconds of our video) and the team labels (cluster_names.json).")
    attack = {}
    for i, group in enumerate(groups):
        v = us_right[i]
        if v is None:
            j = min(known, key=lambda k: abs(k - i))
            v = known[j] if (i - j) % 2 == 0 else not known[j]
            print(f"warning: periods {'+'.join(map(str, group))} give no attack-direction signal; assuming us "
                  f"attack {'right' if v else 'left'} (baskets switch at half time). Check `periods` in game.json.")
        for per in group:
            attack[(per, "us")] = "right" if v else "left"
            attack[(per, "them")] = "left" if v else "right"
    return attack


def stitched_tracks(run: Path, tr: pd.DataFrame, jersey: dict) -> tuple[pd.DataFrame, dict]:
    """With RUN/stitch.json from `stitch` for this tracks.pkl: tracks with track = player chain (the old id kept as
    `tracklet`) and the chains' pooled jersey numbers. Without it, or when it is stale, the inputs unchanged."""
    from .stitch import apply_stitch, base_tracks, stitched_jersey
    path = run / "stitch.json"
    if not path.exists():
        return tr, jersey
    st = json.loads(path.read_text())
    try:
        return apply_stitch(tr, st), stitched_jersey(st)
    except ValueError as e:
        print(f"{path}: ignored, {e}")
        return base_tracks(tr), jersey


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--game", required=True, help="game.json with periods / rosters")
    ap.add_argument("--fps", type=float, default=None, help="sampled frame rate (default: fps in camera.npz)")
    args = ap.parse_args(argv)
    run = Path(args.run)
    game = json.loads(Path(args.game).read_text(encoding="utf8"))
    tr = pd.read_pickle(run / "tracks.pkl")
    jersey = json.loads((run / "jersey.json").read_text()) if (run / "jersey.json").exists() else {}
    tr, jersey = stitched_tracks(run, tr, jersey)
    nums = identities(tr, jersey, game.get("rosters", {}))
    (run / "player_numbers.json").write_text(json.dumps(nums, indent=0))
    tr["number"] = tr.track.map(nums)

    ft = frame_table(tr)
    ft["period"] = 0
    for i, (a, b) in enumerate(game["periods"], 1):
        ft.loc[ft.t.between(a, b), "period"] = i
    live = (ft.period > 0) & (ft.n_us + ft.n_them >= 6)

    # attack direction per half from the "offence stands further from the basket" signal
    attack = attack_directions(tr, ft, live, halves(len(game["periods"])))
    poss = segment_possessions(tr, ft, live, args.fps or sampled_fps(run), attack)
    poss.to_pickle(run / "possessions.pkl")
    pm = possession_metrics(tr, poss)
    pm.to_pickle(run / "possession_metrics.pkl")
    tr.to_pickle(run / "tracks.pkl")
    print(f"{len(poss)} possessions; by offence:", poss.offence.value_counts().to_dict())
    print(pm.groupby("offence")[["dur", "spacing", "off_hull", "def_hull", "guard_gap", "paint_share",
                                  "three_share", "cross_time"]].mean().round(2).T)


if __name__ == "__main__":
    main()
