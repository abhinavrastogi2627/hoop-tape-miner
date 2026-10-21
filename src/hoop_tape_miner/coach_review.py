"""Coach film-review sheets: 2x2 annotated frame grids per possession with the official
score flow in the header, CV lineups per possession, and the game split into N parts
(one reviewer each) with a filled-in brief per part.

    hoop-tape-miner coach-sheets --run RUN --game game.json --official official.json \
        --out RUN/review_v1 [--parts 6] [--video V] [--brief prompts/film_review_brief.md] [--skip-sheets]
    hoop-tape-miner coach-sheets zoom SHEET TILE X Y W H OUT [--scale 3]   # close-up crop of one tile
    hoop-tape-miner coach-sheets event --run RUN --video V --review R --official O --out DIR [--fps 4]
    hoop-tape-miner coach-sheets event-merge --review R --events DIR --out NEW_R [--official O]   # merge answers

Reads RUN/tracks.pkl, possessions.pkl, player_numbers.json; when present also RUN/ball_track.pkl (ball trail on
the sheets) and RUN/shot_proposals.json (CV shot-attempt markers + cv_attempts per possession in the manifest and
part files). Writes to --out: p<pid>_<k>.jpg,
manifest.json, part<N>.json, lineup_intervals.json, brief_part<N>.md (if the brief template
exists). Sheet paths in the json files are relative to --out. Optional game.json "review"
block overrides the layout: every, pre, post, tile [w, h], grid [cols, rows], header,
lineup_gap, lineup_min. Brief placeholders ({us_team}, {review_dir}, {official_totals}, {part},
{t0}, ...; see brief_values) come from game.json + official.json; a game.json "brief" block
overrides any of them (e.g. "watch_notes", "competition", "memo_language").
Official stats are optional: without --official (and no official.json next to game.json or in RUN) the
sheets carry no score flow and reviewers work from the recording alone.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from .ball import RIM_Z, cameras, facing_points
from .review import annotate, draw_attempt, draw_ball_trail, use_game
from .timefmt import mmss

LAYOUT = dict(every=1.0, pre=1.0, post=3.0, tile=[800, 450], grid=[2, 2], header=28, quality=82,
              lineup_gap=25.0, lineup_min=8.0, window_pad=8.0, trail=0.6, attempt_win=1.0)
BRIEF = Path(__file__).resolve().parents[2] / "prompts" / "film_review_brief.md"


def _num_key(n: str):
    return int(n) if str(n).isdigit() else 999


def intervals(ts, gap=25.0, min_len=8.0) -> list[tuple[float, float]]:
    """Sighting times -> on-court intervals: fill gaps <= `gap` s, drop intervals < `min_len` s."""
    ts = np.sort(np.asarray(ts, float))
    if not len(ts):
        return []
    segs, s, p = [], ts[0], ts[0]
    for t in ts[1:]:
        if t - p > gap:
            segs.append((s, p))
            s = t
        p = t
    segs.append((s, p))
    return [(float(a), float(b)) for a, b in segs if b - a >= min_len]


def lineup_intervals(tracks: pd.DataFrame, periods=None, rosters=None, gap=25.0, min_len=8.0) -> dict:
    """{"team#number": [(t0, t1), ...]} from jersey-identified track rows, per period, roster-gated."""
    d = tracks[tracks.number.notna() & tracks.team.isin(["us", "them"])]
    periods = periods or [(float(d.t.min()), float(d.t.max()))]
    out = {}
    for (team, n), g in d.groupby(["team", "number"]):
        n = str(n)
        if rosters and team in rosters and n not in {str(x) for x in rosters[team]}:
            continue
        segs = []
        for a, b in periods:
            segs += intervals(g.t[(g.t >= a) & (g.t <= b)].to_numpy(), gap, min_len)
        if segs:
            out[f"{team}#{n}"] = segs
    return out


def on_court(lineup: dict, t0: float, t1: float, min_overlap=0.3) -> dict:
    """Numbers whose interval covers > min_overlap of [t0, t1]."""
    res = {"us": [], "them": []}
    for k, segs in lineup.items():
        team, n = k.split("#")
        if any(a <= t1 and b >= t0 and min(b, t1) - max(a, t0) > min_overlap * (t1 - t0) for a, b in segs):
            res[team].append(n)
    return {k: sorted(v, key=_num_key) for k, v in res.items()}


def window_events(flow: list[dict], t0: float, t1: float) -> list[dict]:
    keys = ("our_video_t", "team", "points", "score_us", "score_them")
    return [{k: e[k] for k in keys} for e in flow
            if e.get("our_video_t") is not None and t0 <= e["our_video_t"] <= t1]


def events_text(ev: list[dict]) -> str:
    return "; ".join(f'{e["team"]} +{e["points"]} @~{mmss(e["our_video_t"])} ({e["score_us"]}-{e["score_them"]})'
                     for e in ev) or "no official scoring in window"


def split_parts(manifest: list[dict], n: int) -> list[list[dict]]:
    """Contiguous parts with roughly equal sheet counts."""
    tot = sum(len(m["sheets"]) for m in manifest) or 1
    parts, acc = [[] for _ in range(n)], 0
    for m in manifest:
        parts[min(n - 1, int(acc / (tot / n)))].append(m)
        acc += len(m["sheets"])
    return [p for p in parts if p]


def fill_brief(template: str, values: dict, part: int | None = None) -> str:
    """str.replace each {key} (JSON braces stay intact); drop a leading <!-- --> template note;
    with `part`, the generic file names partN.json / memo_partN.md become part<part>..."""
    template = re.sub(r"<!--.*?-->\n*", "", template, count=1, flags=re.S)
    for k, v in values.items():
        template = template.replace("{" + k + "}", str(v))
    return template.replace("partN", f"part{part}") if part else template


def official_summary(official: dict, game: dict) -> str:
    """One-line official totals + scorers per team for the brief."""
    fin, tot = official.get("final", {}), official.get("totals", {})
    ht = game.get("result", {}).get("halftime")
    s = [f"Final {fin.get('us', {}).get('pts', '?')}-{fin.get('them', {}).get('pts', '?')} (us-them)"
         + (f", halftime {ht['us']}-{ht['them']}" if ht else "")]
    for side in ("us", "them"):
        t = tot.get(side)
        if not t:
            continue
        made = lambda k: t.get(k, {}).get("made", 0)  # noqa: E731
        scorers = sorted(((n, p.get("PTS", 0)) for n, p in official.get("players", {}).get(side, {}).items()
                          if p.get("PTS")), key=lambda x: -x[1])
        s.append(f"{side}: made FG {made('FGM-A')} ({made('2PM-A')} twos, {made('3PM-A')} threes), FT {made('FTM-A')}, "
                 f"fouls {t.get('PF', '?')}; scorers " + ", ".join(f"#{n} {p}" for n, p in scorers))
    return ". ".join(s)


def load_official(path: str | None, game_path: Path, run: Path | None = None) -> dict:
    """official.json if there is one; otherwise an empty score flow, so the review runs from the recording alone."""
    if path:
        if not Path(path).is_file():
            raise SystemExit(f"official stats not found: {path}")
        return json.loads(Path(path).read_text(encoding="utf-8"))
    for p in [game_path.parent / "official.json"] + ([run / "official.json"] if run else []):
        if p.is_file():
            print("official stats:", p)
            return json.loads(p.read_text(encoding="utf-8"))
    print("note: no official stats (no official.json next to game.json or in the run dir); sheets will have no score flow "
          "and the review works from the recording alone. Add one later with `hoop-tape-miner official`.")
    return {"score_flow": []}


def brief_values(game: dict, official: dict, out: Path) -> dict:
    """Placeholder values from game.json / official.json; optional game.json "brief" block overrides."""
    m = re.match(r"\d{4}-\d{2}-\d{2}", game.get("name", ""))
    focus = game["us"].get("focus_players") or game["us"].get("focus_player")
    vals = dict(us_team=game["us"].get("team", "us"), them_team=game["them"].get("team", "them"),
                us_colour=game["us"].get("colour", ""), them_colour=game["them"].get("colour", ""),
                us_box="PURPLE", them_box="GREEN", game_date=game.get("date") or (m.group(0) if m else ""),
                competition=game.get("competition", "amateur league game"),
                official_totals=official_summary(official, game) if official.get("totals") else "not available",
                watch_notes=game.get("watch_notes", ""), memo_language=game.get("memo_language", "English"),
                focus_players=", ".join(f"#{x}" for x in ([focus] if isinstance(focus, str) else focus or [])) or "none",
                review_dir=out.resolve().as_posix(), out_dir=out.resolve().as_posix())
    return {**vals, **game.get("brief", {})}


def compose(tiles: list[np.ndarray], header: str, lay: dict) -> np.ndarray:
    cols, rows = lay["grid"]
    blank = np.zeros_like(tiles[0])
    tiles = tiles + [blank] * (cols * rows - len(tiles))
    sheet = np.vstack([np.hstack(tiles[r * cols:(r + 1) * cols]) for r in range(rows)])
    hdr = np.zeros((lay["header"], sheet.shape[1], 3), np.uint8)
    cv2.putText(hdr, header[:150], (4, lay["header"] - 8), 0, 0.55, (255, 255, 255), 1)
    return np.vstack([hdr, sheet])


def attempt_text(a: dict) -> str:
    """Short sheet label of a CV shot-attempt proposal."""
    lab = a.get("label") or "unlabelled"
    pts = f" +{a['points']}" if a.get("label") == "made" and a.get("points") else ""
    return f"CV attempt? {lab}{pts}"


def draw_ball_layers(img, t: float, fi: int, ball: pd.DataFrame | None, attempts: list[dict] | None,
                     cams: dict | None, lay: dict) -> np.ndarray:
    """Ball trail (ball_track.pkl sx, sy over the last lay['trail'] s) and CV attempt markers (shot_proposals.json,
    within lay['attempt_win'] s of t) drawn on a full-size frame, in place."""
    if ball is not None and len(ball):
        tr = ball[(ball.t > t - lay["trail"]) & (ball.t <= t + 0.05)]
        if len(tr) and t - tr.t.max() <= 0.3:
            draw_ball_trail(img, tr[["sx", "sy"]].to_numpy(float))
    if attempts and cams:
        frames = cams["frames"]
        P = cams["P"].get(int(frames[np.abs(frames - fi).argmin()])) if len(frames) else None
        for a in attempts:
            if P is None or abs(a["t"] - t) > lay["attempt_win"]:
                continue
            arc = np.array(a.get("arc") or [], float).reshape(-1, 3)
            arc_px = facing_points(P, a["side"], arc[:, 1], arc[:, 2]) if len(arc) else []
            rim = facing_points(P, a["side"], [0.0], [RIM_Z])[0]
            draw_attempt(img, arc_px, rim, attempt_text(a))
    return img


def load_ball_layers(run: Path, size=(1280, 720)) -> tuple[pd.DataFrame | None, list[dict] | None, dict | None]:
    """Optional sheet layers from RUN: ball_track.pkl (ball-track), shot_proposals.json "proposals" (shot-proposals)
    and the cameras from camera.npz (needed to draw attempt markers). Missing files give None."""
    ball = pd.read_pickle(run / "ball_track.pkl") if (run / "ball_track.pkl").is_file() else None
    attempts = cams = None
    if (run / "shot_proposals.json").is_file():
        attempts = json.loads((run / "shot_proposals.json").read_text(encoding="utf-8")).get("proposals", [])
    if attempts and (run / "camera.npz").is_file():
        P = cameras(dict(np.load(run / "camera.npz")), size)
        cams = {"frames": np.array(sorted(P), int), "P": P}
    return ball, attempts, cams


def build_sheets(cap, tracks, poss, numbers, flow, lineup, out: Path, lay: dict, ball: pd.DataFrame | None = None,
                 attempts: list[dict] | None = None, cams: dict | None = None) -> list[dict]:
    """Sheets per possession (see module doc). Optional layers: ball (ball_track.pkl) draws the ball trail;
    attempts (shot_proposals.json "proposals") with cams ({"frames": array, "P": {frame: 3x4}}) draws CV shot
    attempt markers and lists them per possession as cv_attempts in the manifest."""
    lay = {**LAYOUT, **lay}
    fps = cap.get(cv2.CAP_PROP_FPS)
    by_frame = {f: g for f, g in tracks.groupby("frame")}
    analysed = np.array(sorted(by_frame))
    per_sheet = lay["grid"][0] * lay["grid"][1]
    manifest = []
    for pid, p in poss.iterrows():
        t0, t1 = p.start - lay["pre"], p.end + lay["post"]
        ev = window_events(flow, t0 - lay["window_pad"], t1 + lay["window_pad"])
        cv_att = [dict(t=a["t"], side=a["side"], team=a.get("team"), label=a.get("label"), points=a.get("points"))
                  for a in attempts or [] if t0 <= a["t"] <= t1]
        tiles = []
        for t in np.arange(max(t0, 0.0), t1, lay["every"]):
            fi = int(round(t * fps))
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ok, f = cap.read()
            if not ok:
                continue
            near = analysed[np.abs(analysed - fi).argmin()]
            img = annotate(f, by_frame[near], numbers) if abs(near - fi) <= 6 else f
            if ball is not None or attempts:
                draw_ball_layers(img, float(t), fi, ball, attempts, cams, lay)
            img = cv2.resize(img, tuple(lay["tile"]))
            cv2.rectangle(img, (0, 0), (120, 24), (0, 0, 0), -1)
            m, s = divmod(t, 60)
            cv2.putText(img, f"{int(m):02d}:{s:04.1f}", (4, 18), 0, 0.6, (0, 255, 255), 2)
            tiles.append(img)
        head = f"P{pid:03d} {p.side} half, CV offence={p.offence} | OFFICIAL: {events_text(ev)}"
        if cv_att:
            head = f"P{pid:03d} {p.side} half, CV offence={p.offence}, CV attempts {len(cv_att)} | OFFICIAL: " \
                   f"{events_text(ev)}"
        sheets = []
        for k in range(0, len(tiles), per_sheet):
            name = f"p{pid:03d}_{k // per_sheet}.jpg"
            cv2.imwrite(str(out / name), compose(tiles[k:k + per_sheet], head, lay),
                        [cv2.IMWRITE_JPEG_QUALITY, lay["quality"]])
            sheets.append(name)
        manifest.append(dict(pid=int(pid), start=round(float(p.start), 1), end=round(float(p.end), 1),
                             side=p.side, cv_offence=p.offence, period=int(p.period), official_events=ev,
                             on_court=on_court(lineup, p.start, p.end), sheets=sheets,
                             **({"cv_attempts": cv_att} if attempts is not None else {})))
    return manifest


def zoom(sheet, tile, x, y, w, h, out, grid=(2, 2), header=28, scale=3):
    """Crop (x, y, w, h) inside tile `tile` (row-major) of a sheet and upscale it (Lanczos)."""
    img = cv2.imread(str(sheet))
    tw, th = img.shape[1] // grid[0], (img.shape[0] - header) // grid[1]
    tx, ty = (tile % grid[0]) * tw, header + (tile // grid[0]) * th
    crop = img[ty + y:ty + y + h, tx + x:tx + x + w]
    cv2.imwrite(str(out), cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4))


def _foul_time(trip: dict) -> float | None:
    """v2 foul.t when it is a number, else the trip end (t1)."""
    f = trip.get("foul") if isinstance(trip.get("foul"), dict) else {}
    t = f.get("t")
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        return float(t)
    t1 = trip.get("t1", trip.get("end"))
    return float(t1) if isinstance(t1, (int, float)) and not isinstance(t1, bool) else None


def event_windows(official: dict, trips: list[dict], pre: float = 35.0, post: float = 6.0) -> list[dict]:
    """Video windows to fact-check: [t - pre, t + post] around every official score_flow event with an
    `our_video_t` (the scorer logs 10-30 s after the play, so `pre` covers the lag) and around every reviewed
    foul (foul.t, else the trip end). Overlapping windows merge; each keeps the events it covers, sorted by time.
    Returns [{"t0", "t1", "events": [{"kind": "score"|"foul", "t", ...}]}] sorted by t0 (deterministic)."""
    evs = []
    for e in official.get("score_flow", []):
        t = e.get("our_video_t")
        if t is None:
            continue
        evs.append(dict(kind="score", t=float(t), team=e.get("team"), points=e.get("points"),
                        official_t=e.get("official_t"), score=f'{e.get("score_us")}-{e.get("score_them")}'))
    for x in trips:
        f = x.get("foul")
        if not f:
            continue
        t = _foul_time(x)
        if t is None:
            continue
        f = f if isinstance(f, dict) else {}
        ft = f.get("t")
        evs.append(dict(kind="foul", t=t, pid=x.get("pid"), trip=x.get("trip"), by_team=f.get("by_team"),
                        by=f.get("by"), on=f.get("on"), type=f.get("type"),
                        t_known=isinstance(ft, (int, float)) and not isinstance(ft, bool)))
    evs.sort(key=lambda e: (e["t"], e["kind"], str(e.get("team") or e.get("by_team"))))
    wins: list[dict] = []
    for e in evs:
        a, b = max(0.0, e["t"] - pre), e["t"] + post
        if wins and a <= wins[-1]["t1"]:
            wins[-1]["t1"] = max(wins[-1]["t1"], b)
            wins[-1]["events"].append(e)
        else:
            wins.append(dict(t0=a, t1=b, events=[e]))
    for w in wins:
        w["t0"], w["t1"] = round(w["t0"], 1), round(w["t1"], 1)
    return wins


def candidate_tracks(dets: pd.DataFrame, teams, max_dist: float = 3.0) -> set:
    """Heuristic candidate shooter/fouler in one frame (no ball track exists): for each team in `teams`, the
    tracked player of that team whose smoothed court position (cx_s, cy_s) is closest to either rim, if within
    `max_dist` metres. Returns the track ids to draw thicker."""
    from .court import hoop_xy
    hoops = np.array([hoop_xy("left"), hoop_xy("right")])
    out = set()
    if dets is None or not len(dets) or "cx_s" not in dets:
        return out
    for team in teams:
        d = dets[(dets.team == team) & dets.cx_s.notna()]
        if not len(d):
            continue
        xy = d[["cx_s", "cy_s"]].to_numpy(float)
        dist = np.min(np.linalg.norm(xy[:, None, :] - hoops[None], axis=2), axis=1)
        i = int(dist.argmin())
        if dist[i] <= max_dist:
            out.add(int(d.track.iloc[i]))
    return out


def window_teams(w: dict) -> list[str]:
    """Teams whose candidate players get boxed: scoring teams, foul teams (both if a fouler team is unknown)."""
    ts = set()
    for e in w["events"]:
        if e["kind"] == "score" and e.get("team") in ("us", "them"):
            ts.add(e["team"])
        elif e["kind"] == "foul":
            ts |= {e["by_team"]} if e.get("by_team") in ("us", "them") else {"us", "them"}
    return sorted(ts)


def event_questions(i: int, w: dict, sheets: list[str], fps: float) -> str:
    """Markdown question file for one window: the official facts and reviewed fouls, sheets, narrow questions."""
    lines = [f"# Event window {i:02d}: {mmss(w['t0'])}-{mmss(w['t1'])} (video {w['t0']}-{w['t1']} s)", "",
             f"Sheets at {fps:g} fps, 2x2 tiles, time stamp top-left of each tile. A thicker box = candidate "
             "shooter/fouler (the team's player nearest a rim; a guess, not a fact).", "",
             "## Official facts in this window (the league feed logs 10-30 s after the play; it has no scorer)", ""]
    sc = [e for e in w["events"] if e["kind"] == "score"]
    lines += [f"- S{k}: {e['team']} +{e['points']} logged @~{mmss(e['t'])} (official clock {e['official_t']}, "
              f"score {e['score']} us-them)" for k, e in enumerate(sc, 1)] or ["- none"]
    fo = [e for e in w["events"] if e["kind"] == "foul"]
    lines += ["", "## Fouls the film review reported here (to confirm or correct)", ""]
    lines += [f"- F{k}: trip pid {e['pid']} #{e['trip']}, @~{mmss(e['t'])}{'' if e['t_known'] else ' (trip end)'}: "
              f"by {e['by_team'] or '?'} {e['by'] or '?'} on {e['on'] or '?'}, type {e['type'] or '?'}"
              for k, e in enumerate(fo, 1)] or ["- none"]
    lines += ["", "## Sheets", ""] + [f"- {s}" for s in sheets]
    lines += ["", "## Questions (answer from the frames only; unsure = \"unclear\", never guess)", "",
              "For each S event: 1. who shot (team + jersey)? 2. made? 3. points: 2, 3 or FT? 4. video time of the shot.",
              "For each F event, and any other foul you see: 5. foul by team + jersey, on whom (jersey), type "
              "(shooting / non-shooting / offensive / unclear), video time.", "",
              "Answer as JSON in `event_%02d.answer.json` (jerseys are digit strings or null, doubts go in note; "
              "fouls you see that are not listed get ids Fx1, Fx2, ...):" % i, "",
              '```json\n{"window": "%02d", "events": [{"id": "S1", "team": "us", "kind": "shot|ft|and_one", '
              '"shot_t": 61.0, "shooter": "17", "made": true, "points": 2, "evidence_t": [60.5, 61.0], '
              '"confidence": "high|medium|low", "not_shooter": ["13"], "note": ""}], "fouls": [{"id": "F1", '
              '"t": 58.5, "by_team": "them", "by": "2", "on": "17", "type": "shooting_on_drive", "real": true, '
              '"evidence_t": [58.5], "confidence": "medium", "not_by": [], "note": ""}]}\n```' % i,
              "`not_shooter` / `not_by`: jerseys the frames rule out (e.g. the earlier review's guess stands "
              "elsewhere at the release), even when you cannot read the real one.", ""]
    return "\n".join(lines)


def build_event_sheets(cap, tracks, numbers, windows: list[dict], out: Path, fps_out: float = 4.0,
                       lay: dict | None = None) -> list[dict]:
    """Reads the video sequentially inside each window (one seek per window) at `fps_out` frames per second,
    annotates tracks (candidate players boxed thick + "?" label), writes ev<NN>_<k>.jpg and event_NN.md to `out`."""
    lay = {**LAYOUT, **(lay or {})}
    vfps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    by_frame = {f: g for f, g in tracks.groupby("frame")}
    analysed = np.array(sorted(by_frame))
    per_sheet = lay["grid"][0] * lay["grid"][1]
    res = []
    for i, w in enumerate(windows, 1):
        teams = window_teams(w)
        targets = [int(round(t * vfps)) for t in np.arange(w["t0"], w["t1"], 1.0 / fps_out)]
        tiles, fi = [], targets[0] if targets else 0
        if targets:
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        for tgt in targets:
            ok, f = True, None
            while fi <= tgt:
                ok, f = cap.read()
                fi += 1
                if not ok:
                    break
            if not ok or f is None:
                break
            near = analysed[np.abs(analysed - tgt).argmin()] if len(analysed) else None
            img = f
            if near is not None and abs(near - tgt) <= 6:
                dets = by_frame[near]
                img = annotate(f, dets, numbers)
                for _, r in dets[dets.track.isin(candidate_tracks(dets, teams))].iterrows():
                    cv2.rectangle(img, (int(r.x1), int(r.y1)), (int(r.x2), int(r.y2)), (0, 255, 255), 6)
                    cv2.putText(img, "?", (int(r.x2) + 2, int(r.y1) + 18), 0, 0.8, (0, 255, 255), 2)
            img = cv2.resize(img, tuple(lay["tile"]))
            cv2.rectangle(img, (0, 0), (120, 24), (0, 0, 0), -1)
            t = tgt / vfps
            cv2.putText(img, f"{int(t // 60):02d}:{t % 60:04.1f}", (4, 18), 0, 0.6, (0, 255, 255), 2)
            tiles.append(img)
        sc = "; ".join(f"{e['team']} +{e['points']} @~{mmss(e['t'])}" for e in w["events"] if e["kind"] == "score")
        nf = sum(e["kind"] == "foul" for e in w["events"])
        head = f"EV{i:02d} {mmss(w['t0'])}-{mmss(w['t1'])} | OFFICIAL: {sc or 'none'} | review fouls: {nf}"
        sheets = []
        for k in range(0, len(tiles), per_sheet):
            name = f"ev{i:02d}_{k // per_sheet:02d}.jpg"
            cv2.imwrite(str(out / name), compose(tiles[k:k + per_sheet], head, lay),
                        [cv2.IMWRITE_JPEG_QUALITY, lay["quality"]])
            sheets.append(name)
        (out / f"event_{i:02d}.md").write_text(event_questions(i, w, sheets, fps_out), encoding="utf-8")
        res.append({**w, "window": i, "teams": teams, "sheets": sheets, "questions": f"event_{i:02d}.md"})
    return res


def _trip_key(x: dict) -> tuple:
    return x.get("pid"), x.get("trip", 1)


def _num_t(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _find_trip(trips: list[dict], t: float, team: str | None = None, slack: float = 3.0) -> dict | None:
    """The trip (of `team` on offence, if given) whose [t0 - slack, t1 + slack] holds t; nearest centre wins."""
    best = None
    for x in trips:
        t0, t1 = x.get("t0"), x.get("t1")
        if not (_num_t(t0) and _num_t(t1)) or (team and x.get("offence") != team):
            continue
        if t0 - slack <= t <= t1 + slack:
            d = abs((t0 + t1) / 2 - t)
            if best is None or d < best[0]:
                best = (d, x)
    return best[1] if best else None


def _add_evidence(x: dict, field: str, ts) -> None:
    ev = x.setdefault("evidence", {})
    ev[field] = sorted(set(ev.get(field) or []) | set(ts))


def _credited(trips: list[dict], team: str, j: str, skip: dict | None = None) -> int:
    """Points the trips credit to jersey j of team (made shots + made FTs), leaving out trip `skip`."""
    n = 0
    for x in trips:
        if x is skip or x.get("offence") != team:
            continue
        s, f = x.get("shot") or {}, x.get("fts") or {}
        n += (s.get("points") or 0) if s.get("made") and s.get("shooter") == j else 0
        n += (f.get("made") or 0) if f.get("shooter") == j else 0
    return n


def merge_event_answers(trips: list[dict], windows: list[dict], answers: dict, box: dict | None = None) -> list[str]:
    """Merge fact-check answers (`answers[window_no]` = parsed event_NN.answer.json) into v2 `trips` in place and
    return a change log. An answer counts only with confidence high/medium and at least one evidence time (the
    brief's rule: it overrides the part reviewer only when it cites frames). A made shot goes to that team's trip
    holding shot_t; FT answers raise fts.made to the number of made FTs found for the trip; a listed foul F<k> goes
    back to the trip it came from (events.json), a new foul Fx<k> to the trip holding its time; `real: false`
    removes a reviewed foul; `not_shooter` / `not_by` (jerseys the frames rule out) clear a matching earlier jersey
    when no new one is read. Earlier values stay in `*_v2m` fields; no trip is created (unmatched answers are logged).
    With `box` ({team: {jersey: PTS}} from the official box score) a new shooter is not taken when it would credit
    that player with more points than the box score gives him (logged as "exceeds box score")."""
    log = []

    def fits(team, j, pts, x, tag, aid):
        if box is None or j is None:
            return True
        have, cap = _credited(trips, team, j, skip=x), (box.get(team) or {}).get(j, 0)
        if have + pts <= cap:
            return True
        log.append(f"{tag} {aid}: #{j} not taken, exceeds box score ({have} + {pts} > {cap})")
        return False

    ok = lambda a: a.get("confidence") in ("high", "medium") and a.get("evidence_t")
    by_key = {_trip_key(x): x for x in trips}
    for w in windows:
        ans = answers.get(int(w["window"]))
        if not ans:
            continue
        tag = f"EV{int(w['window']):02d}"
        ft_count: dict = {}
        for a in ans.get("events", []):
            t = a.get("shot_t")
            if not ok(a) or not _num_t(t) or a.get("made") is False:
                continue
            x = _find_trip(trips, t, a.get("team"))
            if x is None:
                log.append(f"{tag} {a.get('id')}: no {a.get('team')} trip at {mmss(t)}, unmatched")
                continue
            if a.get("kind") == "ft":
                f = dict(x.get("fts") or {"shooter": None, "made": 0, "att": 0})
                n = ft_count[_trip_key(x)] = ft_count.get(_trip_key(x), 0) + 1
                j = a.get("shooter")
                if j and j != f.get("shooter") and not fits(a.get("team"), j, max(f.get("made") or 0, n), x, tag,
                                                            a.get("id")):
                    j = None
                new = dict(f, shooter=j or f.get("shooter"), made=max(f.get("made") or 0, n))
                new["att"] = max(new.get("att") or 0, new["made"])
                if new != f:
                    x.setdefault("fts_v2m", x.get("fts"))
                    x["fts"] = new
                    if x.get("result") in ("unclear", "foul_side", "missed", None):
                        x.setdefault("result_v2m", x.get("result"))
                        x["result"] = "foul_ft"
                    _add_evidence(x, "fts", a["evidence_t"])
                    log.append(f"{tag} {a['id']}: pid {x.get('pid')} fts {f} -> {new}")
                continue
            old = x.get("shot") if isinstance(x.get("shot"), dict) else {}
            pts = a.get("points") if a.get("points") in (2, 3) else old.get("points")
            keep = old.get("shooter") if old.get("shooter") not in (a.get("not_shooter") or []) else None
            j = a.get("shooter")
            if j and j != old.get("shooter") and not fits(a.get("team"), j, pts or 0, x, tag, a.get("id")):
                j = None
            shot = dict(old, t=t, made=True, points=pts, shooter=j or keep)
            res = {2: "made2", 3: "made3"}.get(pts, x.get("result"))
            if shot != old or res != x.get("result"):
                x.setdefault("shot_v2m", x.get("shot"))
                x.setdefault("result_v2m", x.get("result"))
                if old.get("shooter") != shot["shooter"] or res != x.get("result"):
                    log.append(f"{tag} {a['id']}: pid {x.get('pid')} shooter {old.get('shooter')} -> "
                               f"{shot['shooter']}, result {x.get('result')} -> {res}")
                x["shot"], x["result"] = shot, res
                _add_evidence(x, "shot", a["evidence_t"])
                _add_evidence(x, "result", a["evidence_t"])
            if a.get("kind") == "and_one":
                f = dict(x.get("fts") or {}, shooter=shot["shooter"], made=1, att=1)
                if f != x.get("fts"):
                    x.setdefault("fts_v2m", x.get("fts"))
                    x["fts"] = f
                    _add_evidence(x, "fts", a["evidence_t"])
        listed = [e for e in w["events"] if e["kind"] == "foul"]
        for a in ans.get("fouls", []):
            if not ok(a):
                continue
            fid = str(a.get("id", ""))
            x = None
            if fid[:1] == "F" and fid[1:].isdigit() and 1 <= int(fid[1:]) <= len(listed):
                e = listed[int(fid[1:]) - 1]
                x = by_key.get((e.get("pid"), e.get("trip") or 1))
            elif _num_t(a.get("t")):
                x = _find_trip(trips, a["t"])
            if x is None:
                log.append(f"{tag} {fid}: no trip found, unmatched")
                continue
            old = x.get("foul") if isinstance(x.get("foul"), dict) else None
            if a.get("real") is False:
                if old:
                    x.setdefault("foul_v2m", old)
                    x["foul"] = None
                    log.append(f"{tag} {fid}: pid {x.get('pid')} foul removed (not on film)")
                continue
            new = dict(old or {"cause": None, "led_to": None})
            from .coach_schema import FOUL_TYPES
            for k in ("t", "by_team", "by", "on", "type"):
                if a.get(k) is not None and (k != "type" or a[k] in FOUL_TYPES):
                    new[k] = a[k]
            if a.get("by") is None and new.get("by") in (a.get("not_by") or []):
                new["by"] = None
            if new != old:
                x.setdefault("foul_v2m", old)
                x["foul"] = new
                _add_evidence(x, "foul", a["evidence_t"])
                o = old or {}
                if any(o.get(k) != new.get(k) for k in ("by_team", "by", "on", "type")):
                    log.append(f"{tag} {fid}: pid {x.get('pid')} foul {o.get('by_team')} {o.get('by')} on "
                               f"{o.get('on')} ({o.get('type')}) -> {new.get('by_team')} {new.get('by')} on "
                               f"{new.get('on')} ({new.get('type')})")
    return log


def event_merge_main(argv):
    """coach-sheets event-merge: copy --review into a new --out folder with the fact-check answers merged."""
    import shutil
    ap = argparse.ArgumentParser(prog="hoop-tape-miner coach-sheets event-merge", description=event_merge_main.__doc__)
    ap.add_argument("--review", required=True, help="review dir with coach_part*.json (v2 trips)")
    ap.add_argument("--events", required=True, help="event sheets dir with events.json and event_NN.answer.json")
    ap.add_argument("--out", required=True, help="new review dir (not --review)")
    ap.add_argument("--official", help="official.json: a new shooter is not taken beyond his box-score points")
    a = ap.parse_args(argv)
    src, ev_dir, out = Path(a.review), Path(a.events), Path(a.out)
    if out.resolve() == src.resolve():
        raise SystemExit("--out must be a new folder")
    out.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, out / f.name)
    windows = json.loads((ev_dir / "events.json").read_text(encoding="utf-8"))["windows"]
    answers = {}
    for p in sorted(ev_dir.glob("event_*.answer.json")):
        answers[int(p.name.split("_")[1].split(".")[0])] = json.loads(p.read_text(encoding="utf-8"))
    parts = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("coach_part*.json"))}
    box = None
    if a.official:
        players = json.loads(Path(a.official).read_text(encoding="utf-8")).get("players") or {}
        box = {t: {str(k): int(v.get("PTS") or 0) for k, v in (players.get(t) or {}).items()} for t in ("us", "them")}
    log = merge_event_answers([x for v in parts.values() for x in v], windows, answers, box)
    for name, v in parts.items():
        (out / name).write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "event_merge.md").write_text(f"# Event fact-check merge ({len(answers)} answer files)\n\n"
                                        + "".join(f"- {line}\n" for line in log), encoding="utf-8")
    print(f"{len(answers)} answer files, {len(log)} changes -> {out}")


def event_main(argv):
    """coach-sheets event: 4 fps sheets + question files around official score events and reviewed fouls."""
    import time
    from .coach_eval import load_trips
    ap = argparse.ArgumentParser(prog="hoop-tape-miner coach-sheets event", description=event_main.__doc__)
    ap.add_argument("--run", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--review", required=True, help="review dir with coach_part*.json (v2 trips)")
    ap.add_argument("--official", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--pre", type=float, default=35.0)
    ap.add_argument("--post", type=float, default=6.0)
    ap.add_argument("--game", help="game.json for team colours (default: next to --official, if any)")
    ap.add_argument("--limit", type=int, help="only the first N windows (smoke test)")
    a = ap.parse_args(argv)
    t_start = time.time()
    run, out = Path(a.run), Path(a.out)
    official = json.loads(Path(a.official).read_text(encoding="utf-8"))
    game_path = Path(a.game) if a.game else Path(a.official).parent / "game.json"
    if game_path.is_file():
        use_game(json.loads(game_path.read_text(encoding="utf-8")))
    if not Path(a.video).is_file():
        raise SystemExit(f"video not found: {a.video}")
    wins = event_windows(official, load_trips(Path(a.review)), a.pre, a.post)
    wins = wins[:a.limit] if a.limit else wins
    out.mkdir(parents=True, exist_ok=True)
    tracks = pd.read_pickle(run / "tracks.pkl")
    numbers = {int(k): v for k, v in json.loads((run / "player_numbers.json").read_text()).items()}
    res = build_event_sheets(cv2.VideoCapture(a.video), tracks, numbers, wins, out, a.fps)
    (out / "events.json").write_text(json.dumps(dict(fps=a.fps, pre=a.pre, post=a.post, windows=res), indent=1),
                                     encoding="utf-8")
    print(len(res), "windows", sum(len(w["sheets"]) for w in res), "sheets",
          sum(len(w["events"]) for w in res), "events", f"{time.time() - t_start:.0f}s ->", out)


def main(argv=None):
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["event"]:
        return event_main(argv[1:])
    if argv[:1] == ["event-merge"]:
        return event_merge_main(argv[1:])
    if argv[:1] == ["zoom"]:
        zp = argparse.ArgumentParser(prog="hoop-tape-miner coach-sheets zoom")
        for k in ("sheet", "tile", "x", "y", "w", "h", "out"):
            zp.add_argument(k, type=int if k in "tile x y w h".split() else str)
        zp.add_argument("--scale", type=float, default=3)
        z = zp.parse_args(argv[1:])
        Path(z.out).parent.mkdir(parents=True, exist_ok=True)
        zoom(z.sheet, z.tile, z.x, z.y, z.w, z.h, z.out, scale=z.scale)
        print("wrote", z.out)
        return
    ap = argparse.ArgumentParser(prog="hoop-tape-miner coach-sheets", description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--game", required=True)
    ap.add_argument("--official", help="league stats (default: official.json next to game.json or in --run, if any)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--parts", type=int, default=6)
    ap.add_argument("--video", help="default: game.json 'video', relative to game.json")
    ap.add_argument("--brief", default=str(BRIEF), help="brief template with {placeholders}")
    ap.add_argument("--skip-sheets", action="store_true", help="reuse --out/manifest.json; redo parts + briefs")
    a = ap.parse_args(argv)
    run, out, game_path = Path(a.run), Path(a.out), Path(a.game)
    game = json.loads(game_path.read_text(encoding="utf-8"))
    use_game(game)  # sheet outline colours from us.hex / them.hex
    lay = {**LAYOUT, **game.get("review", {})}
    official = load_official(a.official, game_path, run)
    out.mkdir(parents=True, exist_ok=True)

    if a.skip_sheets:
        manifest = json.loads((out / "manifest.json").read_text())
    else:
        video = Path(a.video or game.get("video", ""))
        if not video.is_absolute() and not a.video:
            video = game_path.parent / video
        if not video.is_file():
            raise SystemExit(f"video not found: {video} (pass --video)")
        tracks = pd.read_pickle(run / "tracks.pkl")
        poss = pd.read_pickle(run / "possessions.pkl")
        numbers = {int(k): v for k, v in json.loads((run / "player_numbers.json").read_text()).items()}
        lineup = lineup_intervals(tracks, game.get("periods"), game.get("rosters"), lay["lineup_gap"],
                                  lay["lineup_min"])
        cap = cv2.VideoCapture(str(video))
        size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280, int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720)
        ball, attempts, cams = load_ball_layers(run, size)
        layers = (["ball trail"] if ball is not None else []) + \
            ([f"{len(attempts)} CV shot attempts"] if attempts is not None else [])
        if layers:
            print("sheet layers:", ", ".join(layers))
        manifest = build_sheets(cap, tracks, poss, numbers, official["score_flow"], lineup, out, lay,
                                ball=ball, attempts=attempts, cams=cams)
        (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
        (out / "lineup_intervals.json").write_text(
            json.dumps({k: [[round(x) for x in s] for s in v] for k, v in lineup.items()}, indent=0))
    print(len(manifest), "possessions", sum(len(m["sheets"]) for m in manifest), "sheets")

    parts = split_parts(manifest, a.parts)
    template = Path(a.brief).read_text(encoding="utf-8") if Path(a.brief).is_file() else None
    base = brief_values(game, official, out) if template else {}
    for i, pt in enumerate(parts, 1):
        (out / f"part{i}.json").write_text(json.dumps(pt, indent=1))
        t0, t1 = pt[0]["start"], pt[-1]["end"]
        print(i, len(pt), "poss", sum(len(m["sheets"]) for m in pt), "sheets", f"{mmss(t0)}-{mmss(t1)}")
        if template:
            vals = {**base, "part": i, "n_parts": len(parts), "t0": mmss(t0), "t1": mmss(t1)}
            (out / f"brief_part{i}.md").write_text(fill_brief(template, vals, i), encoding="utf-8")
    if not template:
        print("no brief template at", a.brief, "- skipped brief_part*.md")


if __name__ == "__main__":
    main()
