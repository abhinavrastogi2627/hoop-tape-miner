"""Fetch one Glory League game: official stats, the league video, a filled game.json and run/official.json.

usage: hoop-tape-miner fetch <glory game url> [--video OWN_VIDEO] [--us-team NAME] [--secrets FILE] [--no-video]
       [--force]
The url is the game page, e.g. https://my.gloryleague.basketball/game/<GAME_ID>/overview.
Credentials: env GLORY_EMAIL / GLORY_PASSWORD, else KEY=VALUE lines in --secrets or team.json league.secrets.
Raw league responses (they contain person names) stay in <media>/league/; game.json and official.json keep
jersey numbers only. The league video goes to <media>/video/league.mp4 (resumable). Without --video it is our
video too and the alignment is the identity; with --video it is used to align our own video. A re-fetch keeps
filled game.json fields and a non-identity alignment in run/official.json (own video, or fixed by hand); --force
replaces both.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
import zoneinfo
from pathlib import Path

from . import media, new_game, official, workspace

API = "https://api.gloryleague.com/onsen/graphql"
LOGIN = "mutation ($input: LoginInput!) { login(input: $input) { authToken } }"
OPS = ("GameOverviewPage", "BoxScore", "PointChart", "ShotChart")
HALF_GRACE_S = 30   # scorer lag: a basket logged up to this long after a period's finish still counts for it
UNKNOWN_LEN = 86400.0
CHUNK = 1 << 20


class GloryError(RuntimeError):
    pass


def game_id(url: str) -> str:
    m = re.search(r"/game/([^/?#]+)", url)
    if not m:
        raise SystemExit(f"not a Glory League game url (expected .../game/<id>/overview): {url!r}")
    return m.group(1)


def queries() -> dict:
    return json.loads(Path(__file__).with_name("glory_queries.json").read_text(encoding="utf8"))


def read_secrets(path) -> dict:
    out = {}
    for line in Path(path).expanduser().read_text(encoding="utf8").splitlines():
        m = re.match(r"\s*(?:export\s+)?(\w+)\s*=\s*(.*?)\s*$", line)
        if m and not line.lstrip().startswith("#"):
            out[m.group(1)] = m.group(2).strip("\"'")
    return out


def credentials(secrets=None) -> tuple[str, str]:
    email, pw = os.environ.get("GLORY_EMAIL"), os.environ.get("GLORY_PASSWORD")
    if email and pw:
        return email, pw
    if secrets and Path(secrets).expanduser().exists():
        env = read_secrets(secrets)
        email, pw = env.get("GLORY_EMAIL"), env.get("GLORY_PASSWORD")
        if email and pw:
            return email, pw
    raise SystemExit("Glory League login missing: set GLORY_EMAIL / GLORY_PASSWORD, or pass --secrets FILE "
                     "(or league.secrets in team.json) with those KEY=VALUE lines")


def _open(req, timeout=60):
    """The one network call (tests replace it)."""
    return urllib.request.urlopen(req, timeout=timeout)


def post(body: dict) -> dict:
    req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", "user-agent": "hoop-tape-miner"})
    try:
        with _open(req) as r:
            return json.loads(r.read().decode("utf8"))
    except urllib.error.HTTPError as e:
        raise GloryError(f"Glory League API HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise GloryError(f"Glory League API unreachable: {e.reason}") from None


def _errors(resp: dict) -> str | None:
    errs = resp.get("errors") if isinstance(resp, dict) else ["no JSON object"]
    return "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errs) if errs else None


def login(email: str, password: str) -> str:
    resp = post({"query": LOGIN, "variables": {"input": {"email": email, "password": password}}})
    err = _errors(resp)
    token = ((resp.get("data") or {}).get("login") or {}).get("authToken")
    if err or not token:
        raise GloryError(f"Glory League login failed: {err or 'no token returned'}")
    return token


def gql(op: str, query: str, variables: dict, token: str) -> dict:
    """One authenticated query; HTTP 200 with errors (e.g. "Access Denied for field ...") raises."""
    resp = post({"operationName": op, "query": query, "variables": variables, "extensions": {"authToken": token}})
    err = _errors(resp)
    if err or not (resp.get("data") or {}).get("game"):
        raise GloryError(f"Glory League {op} failed: {err or 'game not found'}")
    return resp


def fetch_all(gid: str, token: str) -> dict:
    q = queries()
    return {op: gql(op, q[op], {"gameId": gid}, token) for op in OPS}


# ---- league data -> game facts -------------------------------------------------------------------------

def pick_side(overview: dict, us_team: str | None) -> str:
    """'home' or 'away' for our team (case-insensitive name match)."""
    g = overview["data"]["game"]
    names = {s: (g.get(s) or {}).get("name") or "" for s in ("home", "away")}
    want = (us_team or "").strip().casefold()
    for s, n in names.items():
        if want and n.strip().casefold() == want:
            return s
    raise SystemExit(f"our team {us_team!r} is neither home {names['home']!r} nor away {names['away']!r}: "
                     "pass --us-team with one of them (or set team in team.json)")


def game_date(played_at: str, tz_name: str | None = None) -> str:
    """playedAt in the org's time zone when known, else in playedAt's own offset."""
    t = dt.datetime.fromisoformat(played_at)
    if tz_name:
        try:
            t = t.astimezone(zoneinfo.ZoneInfo(tz_name))
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            pass
    return t.date().isoformat()


def periods(pointchart: dict) -> list[list[int]]:
    """League-video seconds per period, from PointChart start/finish mm:ss."""
    ps = pointchart["data"]["game"]["pointChart"].get("periods") or []
    return [[official._mmss(p["startTimeString"]), official._mmss(p["finishTimeString"])] for p in ps]


def score_at(pointchart: dict, t: float) -> tuple[int, int]:
    """(home, away) of the last entry at or before t seconds."""
    home = away = 0
    for e in pointchart["data"]["game"]["pointChart"]["entries"]:
        if official._mmss(e["timeString"]) > t:
            break
        home, away = int(e["homeScore"]), int(e["awayScore"])
    return home, away


def halftime(pointchart: dict, us_is_home: bool) -> dict:
    """Score at the end of the first half: end of period 2 with 4 periods, else period 1 (+HALF_GRACE_S)."""
    ps = periods(pointchart)
    if len(ps) < 2:
        return {"us": None, "them": None}
    home, away = score_at(pointchart, ps[1 if len(ps) == 4 else 0][1] + HALF_GRACE_S)
    return {"us": home, "them": away} if us_is_home else {"us": away, "them": home}


def rosters(boxscore: dict, us_is_home: bool) -> dict:
    out = {"us": [], "them": []}
    for p in boxscore["data"]["game"]["participations"]:
        who = "us" if official._bool(p["isHomeTeam"]) == us_is_home else "them"
        out[who] = [str(g["playerNumber"]) for g in p["gamePlayers"]]
    return out


def league_facts(data: dict, us_team: str | None) -> dict:
    """Everything fetch needs from the four responses (team names, never person names)."""
    g = data["GameOverviewPage"]["data"]["game"]
    us_side = pick_side(data["GameOverviewPage"], us_team)
    them_side = "away" if us_side == "home" else "home"
    us_home = us_side == "home"
    return {"us_side": us_side, "them_side": them_side, "us_is_home": us_home,
            "us": g[us_side]["name"], "them": g[them_side]["name"],
            "date": game_date(g["playedAt"], (g.get("org") or {}).get("timeZoneName")),
            "score": {"us": g[f"{us_side}Score"], "them": g[f"{them_side}Score"]},
            "halftime": halftime(data["PointChart"], us_home),
            "periods": periods(data["PointChart"]),
            "rosters": rosters(data["BoxScore"], us_home)}


def video_check(overview: dict) -> str:
    g = overview["data"]["game"]
    ok = (g.get("gameVideoStatus") == "available" and not g.get("videoProcessing") and not g.get("videoArchived")
          and g.get("videoDownloadUrl"))
    if not ok:
        raise SystemExit(f"league video not available (status={g.get('gameVideoStatus')!r}, processing="
                         f"{g.get('videoProcessing')}, archived={g.get('videoArchived')}): retry later, or use "
                         "--no-video / --video OWN_VIDEO")
    return g["videoDownloadUrl"]


# ---- video ---------------------------------------------------------------------------------------------

def remote_size(url: str) -> int | None:
    try:
        with _open(urllib.request.Request(url, method="HEAD")) as r:
            n = r.headers.get("Content-Length")
            return int(n) if n else None
    except (urllib.error.URLError, ValueError):
        return None


def download(url: str, dest, max_bytes: int | None = None, log=print) -> Path:
    """Resumable download: <dest>.part with Range requests, renamed when complete; skipped when dest already has
    the remote size. max_bytes stops early (leaves the .part; for checks)."""
    dest = Path(dest)
    size = remote_size(url)
    if dest.exists() and size is not None and dest.stat().st_size == size:
        log(f"video: kept {dest.name} ({size / 1e6:.0f} MB, complete)")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    if size is not None and have > size:
        have = 0
    if size is not None and have == size:
        part.replace(dest)
        return dest
    req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
    with _open(req, timeout=120) as r:
        if have and getattr(r, "status", 200) != 206:
            have = 0                                  # server ignored the Range: start over
        if size is None:
            n = r.headers.get("Content-Length")
            size = have + int(n) if n else None
        log(f"video: {'resuming at ' + format(have / 1e6, '.0f') + ' MB of ' if have else 'downloading '}"
            f"{(size or 0) / 1e6:.0f} MB -> {dest}")
        got, step = have, 10
        next_pct = (have * 100 // size // step + 1) * step if size else None
        with open(part, "ab" if have else "wb") as f:
            while True:
                if max_bytes is not None and got - have >= max_bytes:
                    log(f"video: stopped at {got / 1e6:.1f} MB (max_bytes)")
                    return part
                buf = r.read(CHUNK if max_bytes is None else min(CHUNK, max_bytes - (got - have)))
                if not buf:
                    break
                f.write(buf)
                got += len(buf)
                if size and got * 100 >= next_pct * size:
                    log(f"video: {got * 100 // size:3d}% {got / 1e6:.0f}/{size / 1e6:.0f} MB")
                    next_pct = (got * 100 // size // step + 1) * step
    if size is not None and got != size:
        raise SystemExit(f"video download incomplete ({got} of {size} bytes): run fetch again to resume")
    part.replace(dest)
    return dest


def video_length(path) -> float | None:
    """Seconds of the video, or None when it is missing or ffprobe is absent or fails."""
    if not Path(path).exists():
        return None
    try:
        return media.duration_s(Path(path))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def identity_alignment(length: float | None) -> list[dict]:
    return [{"official_from": 0, "official_to": round(length, 2) if length else UNKNOWN_LEN, "offset_s": 0,
             "corr": 1.0}]


def kept_alignment(official_json: Path) -> dict | None:
    """The video_alignment of an existing official.json when it is worth keeping (not the identity): an
    alignment to our own video, or one fixed by hand. None when there is none or it is the identity."""
    if not official_json.exists():
        return None
    try:
        va = json.loads(official_json.read_text(encoding="utf8")).get("video_alignment") or {}
    except (OSError, ValueError):
        return None
    segs = va.get("segments") or []
    if not segs or all(not s.get("offset_s") for s in segs):
        return None
    return va


# ---- game.json -----------------------------------------------------------------------------------------

def _empty(v, default) -> bool:
    return v is None or v == "" or v == [] or v == {} or v == default


def fill(game: dict, new: dict, default: dict | None = None, force: bool = False) -> dict:
    """Copy `new` into `game` where game's value is empty or still the template default (all with force)."""
    default = default or {}
    for k, v in new.items():
        cur, d = game.get(k), default.get(k)
        if isinstance(v, dict) and isinstance(cur, dict):
            fill(cur, v, d if isinstance(d, dict) else {}, force)
        elif force or _empty(cur, d):
            game[k] = v
    return game


def game_fields(facts: dict, prof: dict, url: str, gid: str, video: Path | None, run: Path) -> dict:
    us = {"team": facts["us"]}
    for k in ("label", "hex", "focus_player"):
        if prof.get(k) not in (None, ""):
            us[k] = str(prof[k]) if k == "focus_player" else prof[k]
    return {"name": f"{facts['date']} vs {facts['them']}",
            "video": str(video.resolve()) if video else "",
            "run": str(run.resolve()),
            "us": us, "them": {"team": facts["them"]},
            "periods": facts["periods"], "periods_checked": False, "rosters": facts["rosters"],
            "result": {**facts["score"], "us_side": facts["us_side"], "them_side": facts["them_side"],
                       "halftime": facts["halftime"]},
            "league": {"kind": "glory", "game_id": gid, "url": url}}


def main(argv=None) -> Path:
    ap = argparse.ArgumentParser(prog="hoop-tape-miner fetch", description=__doc__.splitlines()[0])
    ap.add_argument("url", help="Glory League game page url (.../game/<id>/overview)")
    ap.add_argument("--video", help="our own video; the league video is then only used to align it")
    ap.add_argument("--us-team", help="our team name as in the league (default: team in team.json)")
    ap.add_argument("--secrets", help="KEY=VALUE file with GLORY_EMAIL / GLORY_PASSWORD "
                                      "(default: league.secrets in team.json)")
    ap.add_argument("--no-video", action="store_true", help="do not download the league video")
    ap.add_argument("--force", action="store_true", help="overwrite filled game.json fields with league data and recompute the "
                                                          "video alignment")
    a = ap.parse_args(argv)

    gid = game_id(a.url)
    prof = workspace.profile()
    secrets = a.secrets or (prof.get("league") or {}).get("secrets")
    try:
        token = login(*credentials(secrets))
        data = fetch_all(gid, token)
    except GloryError as e:
        raise SystemExit(str(e))
    del token
    facts = league_facts(data, a.us_team or prof.get("team"))
    media = workspace.media_dir(facts["them"], facts["date"], prof)
    run = media / "run"
    league = media / "league"
    league.mkdir(parents=True, exist_ok=True)
    for op, resp in data.items():
        (league / f"{op}.json").write_text(json.dumps(resp, indent=1, ensure_ascii=False), encoding="utf8")

    league_video = media / "video" / "league.mp4"
    if not a.no_video:
        download(video_check(data["GameOverviewPage"]), league_video)
    have_league = league_video.exists()
    own = Path(a.video).expanduser() if a.video else None
    if own and not own.exists():
        raise SystemExit(f"--video {own} not found")
    ours = own or (league_video if have_league else None)

    folder = new_game.scaffold(facts["them"], facts["date"], str(ours) if ours else None, facts["us"],
                               force=False, run=run)
    gj = folder / "game.json"
    game = json.loads(gj.read_text(encoding="utf8"))
    default = json.loads(new_game.template("game.example.json").read_text(encoding="utf8"))
    fill(game, game_fields(facts, prof, a.url, gid, ours, run), default, a.force)
    gj.write_text(json.dumps(game, indent=2, ensure_ascii=False) + "\n", encoding="utf8")

    kept = None if a.force else kept_alignment(run / "official.json")
    if kept:
        segs = kept["segments"]
        gv = Path(game["video"]).expanduser() if game.get("video") else None
        length = video_length(gv) if gv and gv.exists() else None
        print(f"kept the video alignment in {run / 'official.json'} (it is not the identity; --force recomputes it)")
    elif own:
        segs = official.align_videos(own, league_video) if have_league else None
        if not have_league:
            print("note: no league video, so official.json has no alignment (our_video_t is empty)")
        length = video_length(own)
    else:
        length = video_length(league_video) if have_league else None
        segs = identity_alignment(length)
    off = official.load_glory(data["BoxScore"], data["PointChart"], facts["us_is_home"], segs, length)
    if kept:
        off["video_alignment"] = kept
    elif own and segs:
        off["video_alignment"]["desc"] = "our_video_t = official_video_t - offset_s (fetch: frame correlation)"
    elif not own:
        off["video_alignment"]["desc"] = "our video is the league video: identity alignment"
    run.mkdir(parents=True, exist_ok=True)
    (run / "official.json").write_text(json.dumps(off, indent=1, ensure_ascii=False), encoding="utf8")

    s, h = facts["score"], facts["halftime"]
    print(f"""fetched {facts['us']} ({facts['us_side']}) vs {facts['them']} on {facts['date']}: \
{s['us']}-{s['them']} (half {h['us']}-{h['them']}), {len(facts['periods'])} periods
  game.json     {gj}
  official.json {run / 'official.json'}
  league data   {league}
  video         {game.get('video') or ours or 'none (use --video or drop --no-video)'}
{folder}""")
    return folder


if __name__ == "__main__":
    main()
