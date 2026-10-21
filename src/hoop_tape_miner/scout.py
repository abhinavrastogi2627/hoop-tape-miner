"""Opponent rematch dossier: pool every past game against one opponent into scout.json + scout.md.

usage: hoop-tape-miner scout --opponent "Red Foxes" [--before 2026-11-01] [--out DIR]

Reads every game folder <workspace>/teams/<opponent-slug>/<date>[-x]/ (game.json result and halftime, official.json
box score and score flow, the review's summary.json `four_factors` / `ppp` and insights.json when present) and, to
check the targets of past insights, the next game against any opponent. Re-reviews of one game (same league game id
or the same run folder) count once; the folder with a review wins. Writes to the opponent folder (or --out):
  scout.json  record and scores, their top scorers by jersey (official box only), Four Factors and points per trip
              by trip type pooled over the reviewed games (us vs them), what decided each game (Four Factors line,
              longest scoring runs, halftime), our insights' targets with the next game's values
  scout.md    the same as a short markdown section for the dossier / pre-game brief
Missing data is "unclear", never a guess. --before skips games on or after that date (the game being prepared).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import workspace
from .coach_insights import _MISSING, resolve
from .official import recorded

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
FACTORS = (("efg_pct", "eFG%", "higher"), ("tov_pct", "TOV%", "lower"), ("orb_pct", "ORB%", "higher"),
           ("ft_rate_pct", "FT rate (FTM/FGA)", "higher"))
TRIP_TYPES = ("transition", "half_court", "second_chance", "unknown", "after_live_turnover")
TOP_SCORERS = 5
_SOURCE = re.compile(r"^(official|plusminus|pm_\d+)$")


# ---- game folders --------------------------------------------------------------------------------------------

def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf8")) if p.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None


def load_game(folder: Path) -> dict | None:
    """One game folder -> {folder, slug, date, game, run, review, official, summary, insights}; None without a dated
    folder name or game.json. official.json from run/ (where fetch writes it) else the game folder."""
    folder = Path(folder)
    game = _load(folder / "game.json")
    if not isinstance(game, dict) or not DATE.match(folder.name):
        return None
    run = Path(game["run"]).expanduser() if game.get("run") else folder / "run"
    review = Path(game["review_dir"]) if game.get("review_dir") else Path("review_v1")
    review = review if review.is_absolute() else run / review
    official = _load(run / "official.json") or _load(folder / "official.json")
    summary = _load(review / "summary.json")
    insights = _load(review / "insights.json")
    return dict(folder=folder, slug=folder.parent.name, date=folder.name[:10], game=game, run=run, review=review,
                official=official if isinstance(official, dict) else None,
                summary=summary if isinstance(summary, dict) else None,
                insights=insights if isinstance(insights, list) else None)


def _key(g: dict) -> str:
    gid = (g["game"].get("league") or {}).get("game_id") if isinstance(g["game"].get("league"), dict) else None
    if gid:
        return f"league:{gid}"
    if g["game"].get("run"):
        return f"run:{Path(g['run']).resolve()}"
    return f"folder:{Path(g['folder']).resolve()}"


def _richness(g: dict) -> tuple:
    return (g["insights"] is not None, g["summary"] is not None, g["official"] is not None, g["folder"].name)


def dedupe(games: list[dict]) -> list[dict]:
    """One entry per real game (league id / run folder), the folder with the most review data; sorted by date."""
    best: dict[str, dict] = {}
    for g in games:
        k = _key(g)
        if k not in best or _richness(g) > _richness(best[k]):
            best[k] = g
    return sorted(best.values(), key=lambda g: (g["date"], g["folder"].name))


def team_games(team_dir: Path) -> list[dict]:
    """Every game folder under one opponent folder, re-reviews merged."""
    team_dir = Path(team_dir)
    if not team_dir.is_dir():
        return []
    return dedupe([g for d in sorted(team_dir.iterdir()) if d.is_dir() and (g := load_game(d))])


def all_games(root: Path) -> list[dict]:
    """Every game in the workspace (<root>/teams/*/*/), re-reviews merged, oldest first."""
    teams = Path(root) / "teams"
    if not teams.is_dir():
        return []
    return dedupe([g for t in sorted(teams.iterdir()) if t.is_dir()
                   for d in sorted(t.iterdir()) if d.is_dir() and (g := load_game(d))])


def label(g: dict) -> str:
    return f"{g['slug']}/{g['folder'].name}"


# ---- one game ------------------------------------------------------------------------------------------------

def score(g: dict) -> dict:
    """Final score {us, them} from game.json result, else official.json final; None where unknown."""
    res = g["game"].get("result") or {}
    fin = (g["official"] or {}).get("final") or {}
    return {s: res.get(s) if isinstance(res.get(s), int) else (fin.get(s) or {}).get("pts") for s in ("us", "them")}


def outcome(sc: dict) -> str:
    if None in (sc.get("us"), sc.get("them")):
        return "unclear"
    return "W" if sc["us"] > sc["them"] else "L" if sc["us"] < sc["them"] else "T"


def runs(flow: list[dict]) -> dict:
    """Longest unanswered scoring run (points) per team from the official score flow; None without a flow."""
    if not flow:
        return {"us": None, "them": None}
    best, cur, who = {"us": 0, "them": 0}, 0, None
    for e in flow:
        t, p = e.get("team"), e.get("points") or 0
        cur = cur + p if t == who else p
        who = t
        if t in best:
            best[t] = max(best[t], cur)
    return best


def _ff(g: dict) -> dict | None:
    ff = ((g["summary"] or {}).get("all") or {}).get("four_factors")
    return ff if isinstance(ff, dict) and isinstance(ff.get("us"), dict) else None


def decided_text(g: dict) -> str:
    ff = _ff(g)
    if not ff:
        return "unclear (no reviewed Four Factors for this game)"
    d = ff.get("decided") or {}
    return d.get("text") if d.get("status") == "ok" and d.get("text") else f"unclear ({d.get('text') or 'no deciding factor'})"


def game_row(g: dict) -> dict:
    sc = score(g)
    half = (g["game"].get("result") or {}).get("halftime") or {}
    ff = _ff(g)
    return dict(folder=g["folder"].name, date=g["date"], score=sc, result=outcome(sc),
                halftime={"us": half.get("us"), "them": half.get("them")},
                runs=runs((g["official"] or {}).get("score_flow") or []),
                four_factors={s: {k: ff[s].get(k) for k, _, _ in FACTORS} | {"possessions": ff[s].get("possessions")}
                              for s in ("us", "them")} if ff else None,
                decided=decided_text(g), reviewed=g["summary"] is not None, insights=g["insights"] is not None)


# ---- pooled --------------------------------------------------------------------------------------------------

def _attempts_known(off: dict) -> bool:
    """The sheet records attempts (some attempt total above the makes, in totals or any player line)."""
    if recorded(off)["attempts"]:
        return True
    return any(isinstance(v, dict) and v.get("att", 0) > v.get("made", 0)
               for side in (off.get("players") or {}).values() for p in (side or {}).values()
               for v in (p or {}).values())


def their_scorers(games: list[dict], top: int = TOP_SCORERS) -> list[dict]:
    """Their jerseys by total points over the games with an official box score (jersey numbers only). fg_att /
    ft_att only when every one of those games records attempts, else None (unclear)."""
    acc: dict[str, dict] = {}
    boxes = [g["official"] for g in games if g["official"] and (g["official"].get("players") or {}).get("them")]
    all_att = bool(boxes) and all(_attempts_known(o) for o in boxes)
    for off in boxes:
        for j, p in off["players"]["them"].items():
            a = acc.setdefault(str(j), dict(jersey=str(j), games=0, pts=0, fgm2=0, fgm3=0, ftm=0, fouls=0,
                                            fg_att=0 if all_att else None, ft_att=0 if all_att else None))
            a["games"] += 1
            a["pts"] += p.get("PTS") or 0
            a["fgm2"] += (p.get("2PM-A") or {}).get("made", 0)
            a["fgm3"] += (p.get("3PM-A") or {}).get("made", 0)
            a["ftm"] += (p.get("FTM-A") or {}).get("made", 0)
            a["fouls"] += p.get("PF") or 0
            if all_att:
                a["fg_att"] += (p.get("2PM-A") or {}).get("att", 0) + (p.get("3PM-A") or {}).get("att", 0)
                a["ft_att"] += (p.get("FTM-A") or {}).get("att", 0)
    rows = sorted(acc.values(), key=lambda a: (-a["pts"], int(a["jersey"]) if a["jersey"].isdigit() else 999))
    for a in rows:
        a["ppg"] = round(a["pts"] / a["games"], 1)
    return [{k: a[k] for k in ("jersey", "games", "pts", "ppg", "fgm2", "fgm3", "ftm", "fouls", "fg_att", "ft_att")}
            for a in rows[:top]]


def _pct(a, b):
    return round(100 * a / b, 1) if a is not None and b else None


def _sum(sides: list[dict], key: str):
    vals = [s.get(key) for s in sides]
    return None if any(v is None for v in vals) else round(sum(vals), 1)


def pooled_factors(games: list[dict]) -> dict | None:
    """Four Factors recomputed from the summed counts of every reviewed game (a factor whose count is missing in
    any game is None); None when no game has them."""
    ffs = [ff for g in games if (ff := _ff(g))]
    if not ffs:
        return None
    out = {"games": len(ffs)}
    for s in ("us", "them"):
        c = {k: _sum([ff[s] for ff in ffs], k) for k in
             ("fgm", "fg3m", "fga", "ftm", "fta", "tov", "possessions", "orb", "orb_chances")}
        out[s] = dict(c, efg_pct=_pct(None if None in (c["fgm"], c["fg3m"]) else c["fgm"] + 0.5 * c["fg3m"], c["fga"]),
                      tov_pct=_pct(c["tov"], c["possessions"]), orb_pct=_pct(c["orb"], c["orb_chances"]),
                      ft_rate_pct=_pct(c["ftm"], c["fga"]))
    return out


def pooled_ppp(games: list[dict]) -> dict | None:
    """Points per trip by trip type, trips and points summed over the reviewed games; None when none has `ppp`."""
    pp = [p for g in games if isinstance(p := ((g["summary"] or {}).get("all") or {}).get("ppp"), dict)]
    if not pp:
        return None
    out = {"games": len(pp)}
    for s in ("us", "them"):
        out[s] = {}
        for k in TRIP_TYPES:
            t = sum(((p.get(s) or {}).get(k) or {}).get("trips", 0) for p in pp)
            pts = sum(((p.get(s) or {}).get(k) or {}).get("points", 0) for p in pp)
            out[s][k] = {"trips": t, "points": pts, "ppp": round(pts / t, 2) if t else None}
    return out


# ---- targets -------------------------------------------------------------------------------------------------

def _value(g: dict, name: str):
    """A number name (insights.json `numbers`) in another game's files, or 'not comparable' (per-trip features)
    / 'unclear' (missing there)."""
    head, _, rest = name.partition(".")
    if head == "features":
        return "not comparable"
    if _SOURCE.match(head) and rest:
        src = g["official"] if head == "official" else _load(g["review"] / f"{head}.json")
        path = rest
    else:
        src, path = g["summary"], name
    v = resolve(src, path) if src is not None else _MISSING
    return "unclear" if v is _MISSING else v


def check(target: dict | None, after) -> str:
    """met / missed for a structured target_check {number, max?|min?}; unclear otherwise."""
    if not isinstance(target, dict) or not isinstance(after, (int, float)) or isinstance(after, bool):
        return "unclear"
    if "max" in target and after > target["max"]:
        return "missed"
    if "min" in target and after < target["min"]:
        return "missed"
    return "met" if ("max" in target or "min" in target) else "unclear"


def targets(games: list[dict], every: list[dict]) -> list[dict]:
    """Each past insight with its target and the next game's (any opponent) values for the same number names.
    Status met / missed only for an insight with a structured `target_check`; free-text targets stay unclear."""
    out = []
    for g in games:
        later = [x for x in every if (x["date"], x["folder"].name) > (g["date"], g["folder"].name)
                 and _key(x) != _key(g)]
        nxt = later[0] if later else None
        for it in g["insights"] or []:
            nums = it.get("numbers") or {}
            tc = it.get("target_check")
            names = list(nums) + ([tc["number"]] if isinstance(tc, dict) and tc.get("number") not in nums else [])
            vals = {n: {"before": nums.get(n, "unclear"), "after": _value(nxt, n) if nxt else "unclear"}
                    for n in names if n}
            after = vals.get(tc.get("number"), {}).get("after") if isinstance(tc, dict) else None
            out.append(dict(game=g["date"], id=it.get("id"), player=it.get("player"), kb=it.get("kb") or [],
                            claim=it.get("claim"), target=it.get("target_next_game"), drill=it.get("drill"),
                            next_game=label(nxt) if nxt else None, values=vals,
                            status=check(tc, after) if nxt else "unclear"))
    return out


# ---- build / write -------------------------------------------------------------------------------------------

def build(team_dir: Path, root: Path, before: str | None = None) -> dict:
    """scout.json content for one opponent folder; `before` (YYYY-MM-DD) skips games on or after that date."""
    every = all_games(root)
    games = [g for g in team_games(team_dir) if not before or g["date"] < before]
    rows = [game_row(g) for g in games]
    rec = {"games": len(rows), **{k: sum(r["result"] == k.upper() for r in rows) for k in ("w", "l", "t")},
           "unclear": sum(r["result"] == "unclear" for r in rows)}
    name = next((g["game"].get("them", {}).get("team") for g in reversed(games) if g["game"].get("them")), None)
    return dict(opponent=Path(team_dir).name, team=name, before=before, record=rec, games=rows,
                their_scorers=their_scorers(games), four_factors=pooled_factors(games), ppp=pooled_ppp(games),
                targets=targets(games, every),
                method="Scorers from official box scores (jersey numbers only). Four Factors and points per trip "
                       "pooled from summed counts of reviewed games. Target status met / missed only where an "
                       "insight has a structured target_check; otherwise unclear (judge from the values).")


def _n(v, suffix=""):
    return "unclear" if v is None else f"{v}{suffix}"


def markdown(sc: dict) -> str:
    """The scout as a short markdown section (English; numbers only from scout.json)."""
    r = sc["record"]
    title = sc.get("team") or sc["opponent"]
    L = [f"## Rematch scouting: {title}", ""]
    if not r["games"]:
        return "\n".join(L + ["No past games against this opponent in the workspace: everything is unclear.", ""])
    L += [f"Record: {r['w']}-{r['l']}" + (f"-{r['t']}" if r["t"] else "") +
          (f" ({r['unclear']} unclear)" if r["unclear"] else "") + f" over {r['games']} game(s).", "",
          "| Date | Score (us-them) | Result | Half | Longest runs (us / them) |", "|---|---|---|---|---|"]
    for g in sc["games"]:
        s, h, ru = g["score"], g["halftime"], g["runs"]
        half = f"{h['us']}-{h['them']}" if None not in (h["us"], h["them"]) else "unclear"
        L.append(f"| {g['date']} | {_n(s['us'])}-{_n(s['them'])} | {g['result']} | {half} | "
                 f"{_n(ru['us'])} / {_n(ru['them'])} |")
    L += ["", "### What decided past games", ""] + [f"- {g['date']}: {g['decided']}" for g in sc["games"]]
    L += ["", "### Their top scorers (official box score)", ""]
    if sc["their_scorers"]:
        L += ["| # | Games | Pts | Per game | 2PM | 3PM | FTM | Fouls | FGA |", "|---|---|---|---|---|---|---|---|---|"]
        L += [f"| #{p['jersey']} | {p['games']} | {p['pts']} | {p['ppg']} | {p['fgm2']} | {p['fgm3']} | {p['ftm']} | "
              f"{p['fouls']} | {_n(p['fg_att'])} |" for p in sc["their_scorers"]]
    else:
        L.append("unclear: no official box score.")
    ff = sc["four_factors"]
    L += ["", "### Four Factors" + (f" (pooled over {ff['games']} reviewed game(s))" if ff else ""), ""]
    if ff:
        L += ["| Factor | Us | Them | Better |", "|---|---|---|---|"]
        L += [f"| {name} | {_n(ff['us'][k])} | {_n(ff['them'][k])} | {better} |" for k, name, better in FACTORS]
        L.append(f"| Possessions | {_n(ff['us']['possessions'])} | {_n(ff['them']['possessions'])} | |")
    else:
        L.append("unclear: no reviewed game against them.")
    pp = sc["ppp"]
    L += ["", "### Points per trip by trip type" + (f" (pooled over {pp['games']} reviewed game(s))" if pp else ""), ""]
    if pp:
        L += ["| Trip type | Us trips / pts / per trip | Them trips / pts / per trip |", "|---|---|---|"]
        L += [f"| {k.replace('_', ' ')} | {pp['us'][k]['trips']} / {pp['us'][k]['points']} / {_n(pp['us'][k]['ppp'])} | "
              f"{pp['them'][k]['trips']} / {pp['them'][k]['points']} / {_n(pp['them'][k]['ppp'])} |"
              for k in TRIP_TYPES if pp["us"][k]["trips"] or pp["them"][k]["trips"]]
    else:
        L.append("unclear: no reviewed trips against them.")
    L += ["", "### Our targets from these games", ""]
    if sc["targets"]:
        for t in sc["targets"]:
            who = f" #{t['player']}" if t.get("player") else ""
            vals = "; ".join(f"{n}: {v['before']} -> {v['after']}" for n, v in t["values"].items()) or "no numbers"
            nxt = f"next game {t['next_game']}" if t["next_game"] else "no later game yet"
            L.append(f"- {t['game']} {t['id']}{who}: {t['target'] or 'unclear'} ({nxt}; {vals}) -> {t['status']}")
    else:
        L.append("unclear: no insights.json in these games.")
    return "\n".join(L) + "\n"


def write(team_dir: Path, root: Path, before: str | None = None, out: Path | None = None) -> dict:
    """Build and write scout.json + scout.md into `out` (default the opponent folder); returns the scout."""
    sc = build(team_dir, root, before)
    out = Path(out or team_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "scout.json").write_text(json.dumps(sc, indent=1, ensure_ascii=False) + "\n", encoding="utf8")
    (out / "scout.md").write_text(markdown(sc), encoding="utf8")
    return sc


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner scout", description=__doc__.splitlines()[0])
    ap.add_argument("--opponent", required=True, help='opponent name or folder slug, e.g. "Red Foxes" or red-foxes')
    ap.add_argument("--before", help="only games before this date YYYY-MM-DD (the game being prepared)")
    ap.add_argument("--out", help="folder for scout.json / scout.md (default: the opponent folder)")
    a = ap.parse_args(argv)
    team_dir = workspace.team_dir(a.opponent)
    sc = write(team_dir, workspace.root(), a.before, Path(a.out) if a.out else None)
    r = sc["record"]
    print(f"[scout] {r['games']} past game(s): {r['w']}-{r['l']}" + (f"-{r['t']}" if r["t"] else "")
          + f"; wrote {Path(a.out or team_dir) / 'scout.json'} and scout.md")


if __name__ == "__main__":
    main()
