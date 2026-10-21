"""Ground truth from the league: box score, score flow and video alignment.

The league sheet records MADE shots only (attempts == makes) plus personal
fouls; rebounds, assists, steals and turnovers are not recorded. Only jersey
numbers are kept, never person names.

* `align_videos`  - map official-video time to our (edited) video time
* `load_glory`    - box score + point chart JSON -> official.json structure
* `map_time`      - apply the alignment segments to one timestamp
* `recorded`      - which counts an official.json really holds (attempts, turnovers, offensive rebounds)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

from .timefmt import seconds

W, H = 64, 36
NOTE = ("League stat sheet records MADE shots only (attempts = makes), plus personal fouls. "
        "Rebounds/assists/steals/turnovers are not recorded (all 0).")


def _ffmpeg() -> str:
    exe = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found: install it or set the FFMPEG env var")
    return exe


def _gray_frames(video, fps: float) -> np.ndarray:
    """Decode to z-normalised 64x36 gray frames at `fps`, shape (n, W*H) float32."""
    cmd = [_ffmpeg(), "-v", "error", "-i", str(video), "-vf", f"fps={fps},scale={W}:{H}",
           "-pix_fmt", "gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, check=True, stdout=subprocess.PIPE).stdout
    a = np.frombuffer(raw, np.uint8).reshape(-1, W * H).astype(np.float32)
    a -= a.mean(1, keepdims=True)
    a /= a.std(1, keepdims=True) + 1e-6
    return a


def _best_offsets(a: np.ndarray, b: np.ndarray, fps: float, window_s=30.0, seq=40,
                  max_offset_s=600.0):
    """For each window of `a`, the shift (seconds) into `b` with best sequence correlation."""
    sim = a @ b.T / a.shape[1]                      # (na, nb) frame correlations
    win = int(window_s * fps)
    shifts = np.arange(0, int(max_offset_s * fps) + 1)
    out = []
    for start in range(0, len(a) - win + 1, win):
        idx = np.linspace(start, start + win - 1, seq).astype(int)
        cols = idx[:, None] + shifts[None, :]
        ok = (cols < len(b)).all(0)
        score = np.full(len(shifts), -1.0)
        score[ok] = sim[idx[:, None], cols[:, ok]].mean(0)
        k = int(score.argmax())
        out.append((start / fps, (start + win) / fps, shifts[k] / fps, float(score[k])))
    return out


def align_videos(ours, official, fps: float = 2, min_corr: float = 0.5) -> list[dict]:
    """Piecewise segments {official_from, official_to, offset_s, corr}; our_t = official_t - offset_s."""
    a, b = _gray_frames(ours, fps), _gray_frames(official, fps)
    segs: list[dict] = []
    for t0, t1, off, corr in _best_offsets(a, b, fps):
        if corr < min_corr:
            continue
        seg = {"official_from": t0 + off, "official_to": t1 + off, "offset_s": off,
               "corr": round(corr, 3)}
        if segs and abs(segs[-1]["offset_s"] - off) <= 0.5 / fps:
            segs[-1]["official_to"] = seg["official_to"]
            segs[-1]["corr"] = min(segs[-1]["corr"], seg["corr"])
        else:
            segs.append(seg)
    return sorted(segs, key=lambda s: s["official_from"])


def map_time(official_t: float, segments: list[dict], video_len: float | None = None):
    """Official-video time -> our video time, or None if it falls outside our footage."""
    for i, s in enumerate(segments):
        last = i == len(segments) - 1
        if s["official_from"] <= official_t < s["official_to"] or (last and official_t == s["official_to"]):
            t = official_t - s["offset_s"]
            if t < 0 or (video_len is not None and t > video_len):
                return None
            return round(t, 2)
    return None


# optional sheet columns -> our key (kept only when the sheet has them)
_COUNTS = {"TO": "TOV", "TOV": "TOV", "OREB": "ORB", "OR": "ORB", "ORB": "ORB", "DREB": "DRB", "DR": "DRB",
           "DRB": "DRB"}


def _stats(stats: list[dict]) -> dict:
    out = {}
    for s in stats:
        n = s["shortName"]
        if n in ("PTS", "PF"):
            out[n] = int(s["value"])
        elif n in ("FGM-A", "2PM-A", "3PM-A", "FTM-A"):
            out[n] = {"made": int(s["made"]), "att": int(s["total"])}
        elif n in _COUNTS and s.get("value") not in (None, ""):
            out[_COUNTS[n]] = int(s["value"])
    return out


def recorded(off: dict) -> dict:
    """Which team counts official.json really holds. attempts: some FG/FT attempt total exceeds the makes (a sheet
    that records makes only has att == made everywhere); turnovers / rebounds: TOV / ORB present for both teams
    and not all zero (a sheet that does not record them shows zeros)."""
    tot = (off or {}).get("totals") or {}
    sides = [tot.get(s) or {} for s in ("us", "them")]
    att = any(isinstance(t.get(k), dict) and t[k].get("att", 0) > t[k].get("made", 0)
              for t in sides for k in ("FGM-A", "2PM-A", "3PM-A", "FTM-A"))

    def counted(key):
        return all(isinstance(t.get(key), int) for t in sides) and any(t[key] for t in sides)
    return {"attempts": att, "turnovers": counted("TOV"), "rebounds": counted("ORB")}


def _mmss(s: str) -> int:
    """League clock 'mm:ss' -> whole seconds."""
    return int(seconds(s))


def _bool(v) -> bool:
    return v if isinstance(v, bool) else str(v).lower() == "true"


def _load(x):
    return x if isinstance(x, dict) else json.loads(Path(x).read_text(encoding="utf-8"))


def load_glory(boxscore_json, pointchart_json, us_is_home: bool, segments=None,
               video_len: float | None = None) -> dict:
    """Build the official.json structure (jersey numbers only, no person names)."""
    game = _load(boxscore_json)["data"]["game"]
    side, team, players, totals = {}, {}, {}, {}
    for p in game["participations"]:
        who = "us" if _bool(p["isHomeTeam"]) == us_is_home else "them"
        side[who] = _bool(p["isHomeTeam"])
        team[who] = p["team"]["name"]
        players[who] = {str(g["playerNumber"]): _stats(g["boxScoreStats"]) for g in p["gamePlayers"]}
        totals[who] = _stats(p["boxScoreTotalStats"])
    final = {w: {"team": f"{team[w]} ({'home' if side[w] else 'away'})", "pts": totals[w]["PTS"]}
             for w in ("us", "them")}

    flow, prev = [], (0, 0)
    for e in _load(pointchart_json)["data"]["game"]["pointChart"]["entries"]:
        home, away, t = int(e["homeScore"]), int(e["awayScore"]), _mmss(e["timeString"])
        d = {"home": home - prev[0], "away": away - prev[1]}
        prev = (home, away)
        for k in ("home", "away"):
            if d[k] > 0:
                who = "us" if (k == "home") == us_is_home else "them"
                flow.append({"official_t": t,
                             "our_video_t": map_time(t, segments, video_len) if segments else None,
                             "team": who, "points": d[k],
                             "score_us": home if us_is_home else away,
                             "score_them": away if us_is_home else home})
    return {"source": "Glory League official stats", "note": NOTE, "final": final,
            "players": players, "totals": totals, "score_flow": flow,
            "video_alignment": {"segments": segments or []}}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner official", description=__doc__.splitlines()[0])
    ap.add_argument("--boxscore", required=True)
    ap.add_argument("--pointchart", required=True)
    ap.add_argument("--us-home", required=True, choices=["true", "false"])
    ap.add_argument("--video", help="our video (for alignment)")
    ap.add_argument("--official-video", help="official broadcast video (for alignment)")
    ap.add_argument("--fps", type=float, default=2)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    segs = None
    if a.video and a.official_video:
        segs = align_videos(a.video, a.official_video, a.fps)
        print("alignment:", json.dumps(segs))
    out = load_glory(a.boxscore, a.pointchart, a.us_home == "true", segs)
    if segs:
        out["video_alignment"]["desc"] = (
            f"our_video_t = official_video_t - offset_s; found by {a.fps:g} fps 64x36 gray frame "
            "correlation over 30 s windows; point-chart times have 10 s resolution")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", a.out)


if __name__ == "__main__":
    main()
