"""Season page: every game folder in the workspace -> one season folder with season.json, a bilingual page and,
with --brief, a pre-game listen script.

usage: hoop-tape-miner season [--season <id>] [--out <folder>] [--brief [--opponent <name>]] [--no-html]

Reads every <workspace>/teams/<opponent>/<date>/game.json and, per game, what exists of: the result (game.json,
else official.json `final`), official.json (run/ or the game folder), the review's summary.json (`all`, with
`four_factors`), insights.json (KB slugs, `target_next_game`), plusminus.json / pm_<N>.json and
lineup_intervals.json. A piece an older game does not have is listed as missing, never filled in.
A folder named `<date>-<suffix>` (e.g. `2026-10-14-v2`) is a redo of the same game: the last one by name counts.

Writes <workspace>/season/<season-id>/ (or --out): season.json, README.md / README.<lang>.md (languages from
team.json), small SVG charts and index.html (the `html` page; the band shows the record). The season id is
team.json `season`, else `<first date>_<last date>`. `publish <season folder>` gives it its own stable link and puts
it at the top of the team hub.

Small samples, our rule: a net rating per 10 minutes is pulled toward 0 by adding PRIOR_MIN minutes of 0 net,
rate = 10 * net / (minutes + PRIOR_MIN). Players and 5-man lineups below SMALL_MIN pooled minutes, or seen in
fewer than SMALL_GAMES games, are flagged as a small sample.

--brief writes brief.<lang>.md, a 5-minute spoken script (recurring themes, the targets for the next game and,
with --opponent, our past results against them) for `hoop-tape-miner narrate --script <folder>/brief.<lang>.md`.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

from . import game_config as gc
from . import media
from . import workspace as ws
from .plusminus import score_events

PRIOR_MIN = 20.0   # our rule: minutes of 0 net added to every pooled net rating (shrinkage toward 0)
SMALL_MIN = 20.0   # pooled minutes below this -> small sample
SMALL_GAMES = 3    # fewer games than this -> small sample
DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
FACTORS = (("efg", "efg_pct"), ("tov", "tov_pct"), ("orb", "orb_pct"), ("ft", "ft_rate_pct"))
LANG_ORDER = ("zh", "en")


# ---- reading the games ------------------------------------------------------------------------------------------
def _load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf8"))
    except (OSError, ValueError):
        return default


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def game_folders(root: Path) -> list[Path]:
    """Game folders under <root>/teams/*/*/ (with game.json), oldest first; of `<date>` and `<date>-<suffix>` folders
    of one opponent only the last by name is kept (a redo of the same game)."""
    best: dict[tuple[str, str], Path] = {}
    for gj in sorted((root / "teams").glob("*/*/game.json")):
        folder = gj.parent
        m = DATE.match(folder.name)
        key = (folder.parent.name, m.group(1) if m else folder.name)
        if key not in best or folder.name > best[key].name:
            best[key] = folder
    return sorted(best.values(), key=lambda f: (game_date(f), f.parent.name))


def game_date(folder: Path) -> str:
    m = DATE.match(folder.name)
    return m.group(1) if m else folder.name


def _run_dir(folder: Path, game: dict) -> Path:
    run = Path(game["run"]).expanduser() if game.get("run") else folder / "run"
    return run if run.is_absolute() else folder / run


def _first(*paths: Path) -> Path | None:
    return next((p for p in paths if p.exists()), None)


def plusminus_of(review: Path) -> dict:
    """plusminus.json merged over every pm_<N>.json in the review folder: {"us#17": {"on": ..., "off": ...}}."""
    out = {}
    for p in sorted(review.glob("pm_*.json")) + [review / "plusminus.json"]:
        d = _load(p, {})
        if isinstance(d, dict):
            out.update({k: v for k, v in d.items() if isinstance(v, dict) and isinstance(v.get("on"), dict)})
    return out


def lineup_units(lineup: dict, events, team: str = "us") -> dict:
    """Seconds and points per 5-player unit of `team`: {"4-7-9-10-13": {"seconds", "for", "against"}}. Time slices
    with more or fewer than 5 players on (tracking gaps) are left out."""
    segs = {k.split("#", 1)[1]: v for k, v in lineup.items() if k.startswith(team + "#") and isinstance(v, list)}
    cuts = sorted({float(t) for v in segs.values() for s in v for t in s[:2]})
    units: dict[str, dict] = {}
    for a, b in zip(cuts, cuts[1:]):
        mid = (a + b) / 2
        on = sorted((n for n, v in segs.items() if any(s[0] <= mid < s[1] for s in v)),
                    key=lambda n: (not n.isdigit(), int(n) if n.isdigit() else 0, n))
        if len(on) != 5:
            continue
        u = units.setdefault("-".join(on), {"seconds": 0.0, "for": 0, "against": 0})
        u["seconds"] += b - a
        for t, side, pts in events:
            if a <= t < b:
                u["for" if side == team else "against"] += pts
    for u in units.values():
        u["seconds"] = round(u["seconds"], 1)
    return units


def _halves(game: dict, official: dict | None, final: tuple) -> tuple[list | None, str | None]:
    """[[us, them] per period] and its source: game.json halftime, else official score_flow inside game.json periods."""
    ht = (game.get("result") or {}).get("halftime") or {}
    h1 = (_num(ht.get("us")), _num(ht.get("them")))
    if None not in h1 and None not in final:
        return [list(h1), [final[0] - h1[0], final[1] - h1[1]]], "game.json halftime"
    periods = game.get("periods") or []
    flow = (official or {}).get("score_flow") or []
    if periods and flow and all(e.get("our_video_t") is not None for e in flow):
        starts = sorted(p[0] for p in periods)
        out = [[0, 0] for _ in starts]
        for e in flow:  # a basket counts for the last period that started before it (feed lag can push it past the end)
            i = max([j for j, s in enumerate(starts) if s <= e["our_video_t"]], default=0)
            out[i][0 if e.get("team") == "us" else 1] += int(e.get("points") or 0)
        return out, "official score flow"
    return None, None


def load_game_data(folder: Path) -> dict:
    """One game as the season needs it. Missing pieces are named in `missing`; their values stay None."""
    game = _load(folder / "game.json", {}) or {}
    run = _run_dir(folder, game)
    review = run / game["review_dir"] if game.get("review_dir") else run / "review_v1"
    if not review.is_absolute():
        review = folder / review
    official_p = _first(run / "official.json", folder / "official.json")
    official = _load(official_p) if official_p else None
    res = game.get("result") or {}
    final = (_num(res.get("us")), _num(res.get("them")))
    result_src = "game.json" if None not in final else None
    if result_src is None and official:
        f = official.get("final") or {}
        final = (_num((f.get("us") or {}).get("pts")), _num((f.get("them") or {}).get("pts")))
        result_src = "official.json" if None not in final else None
    halves, halves_src = _halves(game, official, final)
    summary_p = _first(folder / "summary.json", review / "summary.json")
    summary = _load(summary_p, {}) if summary_p else None
    insights = _load(review / "insights.json") if (review / "insights.json").exists() else None
    pm = plusminus_of(review) if review.is_dir() else {}
    lineup_p = _first(review / "lineup_intervals.json", run / "lineup_intervals.json")
    lineup = _load(lineup_p, {}) if lineup_p else None
    periods = game.get("periods") or []
    length = sum(b - a for a, b in periods) if periods else None
    ff = ((summary or {}).get("all") or {}).get("four_factors") if summary else None
    units = None
    if lineup and official and official.get("score_flow"):
        units = lineup_units(lineup, score_events(official))
    d = {
        "key": f"{folder.parent.name}/{folder.name}",
        "date": game_date(folder), "opponent": gc.team_name(game, "them"), "opponent_slug": folder.parent.name,
        "us": gc.team_name(game, "us"), "hex": {s: gc.team_hex(game, s) for s in gc.SIDES},
        "result": {"us": final[0], "them": final[1], "source": result_src,
                   "outcome": None if result_src is None else
                   ("W" if final[0] > final[1] else "L" if final[0] < final[1] else "T")},
        "periods": halves, "periods_source": halves_src, "game_seconds": length,
        "four_factors": _ff_row(ff) if isinstance(ff, dict) else None,
        "insights": [{"id": it.get("id"), "kb": [s for s in it.get("kb") or [] if isinstance(s, str)],
                      "player": it.get("player"), "rule": it.get("rule"),
                      "target_next_game": it.get("target_next_game"), "target": it.get("target")}
                     for it in insights if isinstance(it, dict)] if isinstance(insights, list) else None,
        "plusminus": {k: {"on": v["on"], "off": v.get("off")} for k, v in pm.items()} or None,
        "lineups": units or None,
    }
    d["missing"] = [k for k, have in (("result", result_src), ("periods", halves), ("official", official),
                                       ("four_factors", d["four_factors"]), ("insights", d["insights"]),
                                       ("plusminus", d["plusminus"]), ("lineups", d["lineups"])) if not have]
    d["_summary"], d["_official"], d["_plusminus"] = summary or None, official, pm or None
    return d


def _ff_row(ff: dict) -> dict:
    out = {}
    for side in ("us", "them"):
        s = ff.get(side) or {}
        out[side] = {**{f: _num(s.get(k)) for f, k in FACTORS}, "poss": _num(s.get("possessions")),
                     "ppp": _num(s.get("ppp"))}
    out["decided"] = (ff.get("decided") or {}).get("factor")
    return out


# ---- targets from game N checked in game N+1 --------------------------------------------------------------------
OPS = [("at most", "<="), ("no more than", "<="), ("at least", ">="), ("no fewer than", ">="),
       ("fewer than", "<"), ("less than", "<"), ("below", "<"), ("under", "<"),
       ("more than", ">"), ("above", ">"), ("over", ">"), ("<=", "<="), (">=", ">="), ("<", "<"), (">", ">")]
OP_RE = re.compile(r"(" + "|".join(re.escape(w) for w, _ in OPS) + r")\s*(-?\d+(?:\.\d+)?)", re.I)
METRIC_RE = re.compile(r"\b(summary|official|plusminus)\s+([A-Za-z_][\w:]*(?:[. ][A-Za-z_#][\w:#]*)*)")


def resolve(game: dict, metric: str):
    """A number named by `metric` in a game: `summary.<path>` (tried as given and under `all`), `official.<path>`,
    `plusminus.<path>`; path parts split on '.' or spaces. None when it does not resolve to a number."""
    src, _, path = metric.partition(".") if "." in metric.split(" ")[0] else metric.partition(" ")
    data = {"summary": game.get("_summary"), "official": game.get("_official"),
            "plusminus": game.get("_plusminus")}.get(src)
    parts = [p for p in re.split(r"[.\s]+", path) if p]
    for base in ([data, (data or {}).get("all")] if src == "summary" else [data]):
        v = base
        for p in parts:
            if isinstance(v, dict) and p in v:
                v = v[p]
            elif isinstance(v, list) and p.isdigit() and int(p) < len(v):
                v = v[int(p)]
            else:
                v = None
                break
        if _num(v) is not None:
            return v
    return None


def _compare(actual, op, value) -> bool:
    return {"<=": actual <= value, ">=": actual >= value, "<": actual < value, ">": actual > value}[op]


def target_clauses(item: dict) -> list[dict]:
    """The measurable parts of an insight's target: structured `target` ({metric, op, value} or a list of them)
    first, else every `;`-separated clause of `target_next_game` that names `summary <path>` (or official /
    plusminus) followed by "at most N", "at least N", "below N" ... Other clauses are kept as not measurable.
    `target_check` ({number, max and/or min}, the insights.json field shared with scout) wins over both."""
    tc = item.get("target_check")
    if isinstance(tc, dict) and tc.get("number"):
        head = str(tc["number"]).partition(".")[0]
        metric = tc["number"] if head in ("official", "plusminus") else f"summary.{tc['number']}"
        text = item.get("target_next_game") or tc["number"]
        return [{"text": text, "metric": metric, "op": op, "value": _num(tc[k])}
                for k, op in (("min", ">="), ("max", "<=")) if k in tc]
    t = item.get("target")
    if isinstance(t, dict):
        t = [t]
    if isinstance(t, list) and t:
        return [{"text": c.get("text") or f"{c.get('metric')} {c.get('op')} {c.get('value')}",
                 "metric": c.get("metric"), "op": c.get("op"), "value": _num(c.get("value"))}
                for c in t if isinstance(c, dict)]
    out = []
    for clause in filter(None, (c.strip() for c in str(item.get("target_next_game") or "").split(";"))):
        m = METRIC_RE.search(clause)
        op = OP_RE.search(clause, m.end()) if m else None
        if m and op:
            word = op.group(1).lower()
            out.append({"text": clause, "metric": f"{m.group(1)}.{m.group(2).strip()}",
                        "op": next(o for w, o in OPS if w == word), "value": float(op.group(2))})
        else:
            out.append({"text": clause, "metric": None, "op": None, "value": None})
    return out


def check_targets(prev: dict, nxt: dict) -> list[dict]:
    """Each insight of game `prev` with a target, checked against game `nxt`: per clause met / missed / not
    measurable (no number named, or the number is missing in the next game)."""
    out = []
    for it in prev.get("insights") or []:
        if not (it.get("target_next_game") or it.get("target") or it.get("target_check")):
            continue
        clauses = []
        for c in target_clauses(it):
            actual = resolve(nxt, c["metric"]) if c["metric"] and c["op"] in ("<=", ">=", "<", ">") \
                and c["value"] is not None else None
            status = ("not_measurable" if actual is None else
                      "met" if _compare(actual, c["op"], c["value"]) else "missed")
            clauses.append({**c, "actual": actual, "status": status})
        st = [c["status"] for c in clauses if c["status"] != "not_measurable"]
        status = ("not_measurable" if not st else "met" if all(s == "met" for s in st)
                  else "missed" if all(s == "missed" for s in st) else "partly")
        out.append({"insight": it.get("id"), "kb": it.get("kb"), "target": it.get("target_next_game"),
                    "status": status, "clauses": clauses})
    return out


# ---- pooling with shrinkage -------------------------------------------------------------------------------------
def shrunk_per10(net, seconds) -> float | None:
    """Our rule: 10 * net / (minutes + PRIOR_MIN), a net rating per 10 minutes pulled toward 0."""
    if seconds is None:
        return None
    return round(10 * net / (seconds / 60 + PRIOR_MIN), 2)


def raw_per10(net, seconds) -> float | None:
    return round(10 * net / (seconds / 60), 2) if seconds else None


def small(minutes: float, games: int) -> bool:
    return minutes < SMALL_MIN or games < SMALL_GAMES


def pool_players(games: list[dict], team: str = "us") -> list[dict]:
    """Per player of `team`: games, on minutes, on / off points pooled over every game with plus-minus; off minutes
    only from games whose length is known (game.json periods)."""
    acc: dict[str, dict] = {}
    for g in games:
        for k, v in (g.get("plusminus") or {}).items():
            if not k.startswith(team + "#"):
                continue
            a = acc.setdefault(k.split("#", 1)[1], {"games": 0, "on_s": 0.0, "on_for": 0, "on_against": 0,
                                                    "off_s": 0.0, "off_for": 0, "off_against": 0, "off_games": 0})
            on, off = v["on"], v.get("off") or {}
            a["games"] += 1
            a["on_s"] += on.get("seconds") or 0
            a["on_for"] += on.get("for") or 0
            a["on_against"] += on.get("against") or 0
            if g.get("game_seconds") and off:
                a["off_s"] += max(0.0, g["game_seconds"] - (on.get("seconds") or 0))
                a["off_for"] += off.get("for") or 0
                a["off_against"] += off.get("against") or 0
                a["off_games"] += 1
    rows = []
    for n, a in acc.items():
        on_net, off_net = a["on_for"] - a["on_against"], a["off_for"] - a["off_against"]
        on10 = shrunk_per10(on_net, a["on_s"])
        off10 = shrunk_per10(off_net, a["off_s"]) if a["off_games"] else None
        rows.append({"player": n, "games": a["games"], "minutes": round(a["on_s"] / 60, 1),
                     "on": {"for": a["on_for"], "against": a["on_against"], "net": on_net,
                            "per10_raw": raw_per10(on_net, a["on_s"]), "per10_shrunk": on10},
                     "off": None if not a["off_games"] else
                     {"minutes": round(a["off_s"] / 60, 1), "games": a["off_games"], "for": a["off_for"],
                      "against": a["off_against"], "net": off_net, "per10_raw": raw_per10(off_net, a["off_s"]),
                      "per10_shrunk": off10},
                     "on_off_shrunk": None if off10 is None else round(on10 - off10, 2),
                     "small_sample": small(a["on_s"] / 60, a["games"])})
    return sorted(rows, key=lambda r: -r["minutes"])


def pool_lineups(games: list[dict]) -> list[dict]:
    acc: dict[str, dict] = {}
    for g in games:
        for k, u in (g.get("lineups") or {}).items():
            a = acc.setdefault(k, {"games": 0, "seconds": 0.0, "for": 0, "against": 0})
            a["games"] += 1
            a["seconds"] += u["seconds"]
            a["for"] += u["for"]
            a["against"] += u["against"]
    rows = []
    for k, a in acc.items():
        net = a["for"] - a["against"]
        rows.append({"lineup": k.split("-"), "games": a["games"], "minutes": round(a["seconds"] / 60, 1),
                     "for": a["for"], "against": a["against"], "net": net,
                     "per10_raw": raw_per10(net, a["seconds"]), "per10_shrunk": shrunk_per10(net, a["seconds"]),
                     "small_sample": small(a["seconds"] / 60, a["games"])})
    return sorted(rows, key=lambda r: -r["minutes"])


def themes(games: list[dict]) -> list[dict]:
    """KB slugs counted across games: in how many games and how many insights each appears, newest game last."""
    n_games, n_items, dates = Counter(), Counter(), {}
    for g in games:
        slugs = [s for it in g.get("insights") or [] for s in it["kb"]]
        n_items.update(slugs)
        for s in dict.fromkeys(slugs):
            n_games[s] += 1
            dates.setdefault(s, []).append(g["date"])
    return [{"kb": s, "games": n_games[s], "insights": n_items[s], "dates": dates[s], "recurring": n_games[s] >= 2}
            for s in sorted(n_games, key=lambda s: (-n_games[s], -n_items[s], s))]


def period_totals(games: list[dict]) -> list[dict]:
    """Points for / against per period summed over the games where that period is known."""
    out = []
    for i in range(max((len(g["periods"]) for g in games if g.get("periods")), default=0)):
        have = [g["periods"][i] for g in games if g.get("periods") and len(g["periods"]) > i]
        out.append({"period": i + 1, "games": len(have), "for": sum(p[0] for p in have),
                    "against": sum(p[1] for p in have)})
    return out


def build(root: Path, season_id: str | None = None) -> tuple[dict, list[dict]]:
    """(season.json content, per-game records incl. the private `_summary` etc. used for target checks)."""
    games = [load_game_data(f) for f in game_folders(root)]
    if not games:
        sys.exit(f"no game folders with game.json under {root / 'teams'}")
    first, last = games[0]["date"], games[-1]["date"]
    sid = season_id or ws.profile().get("season") or (first if first == last else f"{first}_{last}")
    known = [g for g in games if g["result"]["source"]]
    rec = Counter(g["result"]["outcome"] for g in known)
    checks = [{"from": a["key"], "from_date": a["date"], "checked_in": b["key"], "checked_date": b["date"],
               "targets": check_targets(a, b)} for a, b in zip(games, games[1:])]
    season = {
        "season": sid, "team": games[-1]["us"], "games": len(games),
        "record": {"W": rec["W"], "L": rec["L"], "T": rec["T"], "unknown": len(games) - len(known),
                   "for": sum(g["result"]["us"] for g in known), "against": sum(g["result"]["them"] for g in known)},
        "rule": {"prior_minutes": PRIOR_MIN, "small_minutes": SMALL_MIN, "small_games": SMALL_GAMES,
                 "text": f"net per 10 min = 10 * net / (minutes + {PRIOR_MIN:g}): {PRIOR_MIN:g} minutes of 0 net "
                         "are added, which pulls small samples toward 0 (our rule, not a fitted prior)"},
        "results": [{k: g[k] for k in ("key", "date", "opponent", "opponent_slug", "result", "periods",
                                       "periods_source", "four_factors", "missing")} for g in games],
        "period_totals": period_totals(games),
        "targets_checked": checks,
        "next_targets": [{"insight": it.get("id"), "kb": it["kb"], "target": it.get("target_next_game")}
                         for it in games[-1].get("insights") or [] if it.get("target_next_game")],
        "themes": themes(games),
        "players": pool_players(games),
        "lineups": pool_lineups(games),
    }
    return season, games


# ---- page ---------------------------------------------------------------------------------------------------------
T = {
    "zh": dict(title="赛季总览 {sid}", lead="{n} 场比赛：{w} 胜 {l} 负{t}，总得分 {pf}–{pa}。样本很小：每个数字都要看场次。",
               results="比赛结果", date="日期", opp="对手", score="比分", res="结果", missing="缺少的数据",
               periods="分节得分", period="第 {i} 节", half=("上半场", "下半场"), games="场次", pf="得分", pa="失分",
               net="净胜", ff="四要素 每场趋势", ff_note="来自每场录像复盘的 summary.json；缺的场次留空，不补。",
               targets="上一场的目标 检查", t_from="{d1} 的目标，在 {d2} 检查：", met="达成", missed="没达成",
               partly="部分达成", not_measurable="无法测量", actual="实际", none_checked="还没有可以检查的下一场。",
               next="下一场的目标", themes="反复出现的教练主题", kb="主题（KB）", insights="条结论", recurring="反复出现",
               players="球员 上场时间和在场 / 不在场（全赛季合计）", player="球员", minutes="上场分钟",
               on="在场净胜", on10="在场 每10分钟（收缩后）", off10="不在场 每10分钟（收缩后）", onoff="差值",
               small="小样本", lineups="五人阵容 每10分钟净胜（收缩后）", lineup="阵容", raw="原始",
               rule="我们的规则：每 10 分钟净胜 = 10 × 净胜 ÷ (上场分钟 + {p})。相当于先加上 {p} 分钟 0 净胜，"
                    "上场越少，数字越被拉向 0。少于 {m} 分钟或少于 {g} 场标为小样本。",
               no_data="还没有数据。", efg="有效命中率 eFG%", tov="失误率 TOV%", orb="进攻篮板率 ORB%",
               ft="罚球率", us="我们", them="对手", tie="平"),
    "en": dict(title="Season {sid}", lead="Games played: {n}; {w} won, {l} lost{t}; points {pf}–{pa}. Small samples: read "
                                          "every number with its game count.",
               results="Results", date="Date", opp="Opponent", score="Score", res="Result", missing="Missing data",
               periods="Points by period", period="Period {i}", half=("1st half", "2nd half"), games="Games",
               pf="For", pa="Against", net="Net", ff="Four Factors per game",
               ff_note="From each game's film review (summary.json); a game without it stays empty, nothing is "
                       "filled in.",
               targets="Last game's targets checked", t_from="Targets set on {d1}, checked on {d2}:", met="met",
               missed="missed", partly="partly met", not_measurable="not measurable", actual="actual",
               none_checked="No later game to check against yet.", next="Targets for the next game",
               themes="Recurring coaching themes", kb="Theme (KB)", insights="insights", recurring="recurring",
               players="Players: minutes and on / off (pooled over the season)", player="Player", minutes="Minutes",
               on="On-court net", on10="On, per 10 min (shrunk)", off10="Off, per 10 min (shrunk)", onoff="On−off",
               small="small sample", lineups="5-player lineups: net per 10 min (shrunk)", lineup="Lineup",
               raw="raw",
               rule="Our rule: net per 10 min = 10 × net ÷ (minutes + {p}). That adds {p} minutes of 0 net, so the "
                    "fewer the minutes, the more the number is pulled toward 0. Under {m} minutes or under {g} "
                    "games is flagged as a small sample.",
               no_data="No data yet.", efg="Effective FG% (eFG%)", tov="Turnover rate (TOV%)",
               orb="Offensive rebounding (ORB%)", ft="Free-throw rate", us="Us", them="Them", tie="tied"),
}


def _fmt(v, nd=1) -> str:
    if v is None:
        return "–"
    return f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def _signed(v) -> str:
    return "–" if v is None else f"{v:+.1f}"


def svg_trend(games: list[dict], key: str, lang: str, colours: tuple[str, str]) -> str:
    """Small line chart of one factor per game, us vs them; a game without the number leaves a gap."""
    w, h, l, r, top, bot = 360, 150, 34, 10, 12, 30
    vals = [((g.get("four_factors") or {}).get(s) or {}).get(key) if g.get("four_factors") else None
            for g in games for s in ("us", "them")]
    nums = [v for v in vals if v is not None]
    hi = max(nums + [10.0])
    hi = (int(hi / 10) + 1) * 10
    n = len(games)
    xs = [l + (w - l - r) * (i + 0.5) / n for i in range(n)]

    def y(v):
        return top + (h - top - bot) * (1 - v / hi)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
             f'font-family="system-ui, sans-serif" font-size="10">',
             f'<rect width="{w}" height="{h}" fill="#ffffff"/>']
    for t in (0, hi / 2, hi):
        parts.append(f'<line x1="{l}" x2="{w - r}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="#e3e3ec"/>'
                     f'<text x="{l - 4}" y="{y(t) + 3:.1f}" text-anchor="end" fill="#6c6b84">{t:g}</text>')
    for i, g in enumerate(games):
        parts.append(f'<text x="{xs[i]:.1f}" y="{h - bot + 14}" text-anchor="middle" fill="#6c6b84">'
                     f'{html.escape(g["date"][5:])}</text>')
    for j, (side, col) in enumerate(zip(("us", "them"), colours)):
        pts = [(xs[i], ((g.get("four_factors") or {}).get(side) or {}).get(key)) for i, g in enumerate(games)]
        run: list[str] = []
        for x, v in pts + [(None, None)]:
            if v is None:
                if len(run) > 1:
                    parts.append(f'<polyline fill="none" stroke="{col}" stroke-width="2" points="{" ".join(run)}"/>')
                run = []
            else:
                run.append(f"{x:.1f},{y(v):.1f}")
                parts.append(f'<circle cx="{x:.1f}" cy="{y(v):.1f}" r="3" fill="{col}"/>')
        parts.append(f'<rect x="{l + 6 + j * 70}" y="{h - 12}" width="10" height="3" fill="{col}"/>'
                     f'<text x="{l + 20 + j * 70}" y="{h - 8}" fill="#221f45">{html.escape(T[lang][side])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def readme(season: dict, games: list[dict], lang: str, charts: dict[str, str]) -> str:
    L = T[lang]
    rec = season["record"]
    t = (f", {rec['T']} {L['tie']}" if rec["T"] else "")
    out = [f"# {L['title'].format(sid=season['season'])}", "",
           L["lead"].format(n=season["games"], w=rec["W"], l=rec["L"], t=t, pf=rec["for"], pa=rec["against"]), ""]
    out += [f"## {L['results']}", "", f"| {L['date']} | {L['opp']} | {L['score']} | {L['res']} | {L['missing']} |",
            "|---|---|---|---|---|"]
    for g in season["results"]:
        r = g["result"]
        score = f"{r['us']}–{r['them']}" if r["source"] else "–"
        out.append(f"| {g['date']} | {_cell(g['opponent'])} | {score} | {r['outcome'] or '–'} | "
                   f"{', '.join(g['missing']) or '–'} |")
    out += ["", f"## {L['periods']}", ""]
    if season["period_totals"]:
        out += [f"| | {L['games']} | {L['pf']} | {L['pa']} | {L['net']} |", "|---|---|---|---|---|"]
        for p in season["period_totals"]:
            name = L["half"][p["period"] - 1] if len(season["period_totals"]) == 2 else L["period"].format(i=p["period"])
            out.append(f"| {name} | {p['games']} | {p['for']} | {p['against']} | {p['for'] - p['against']:+d} |")
    else:
        out.append(L["no_data"])
    out += ["", f"## {L['ff']}", "", L["ff_note"], ""]
    if any(g["four_factors"] for g in season["results"]):
        out += [f"| {L['date']} | eFG% | TOV% | ORB% | FT | Poss | PPP |", "|---|---|---|---|---|---|---|"]
        for g in season["results"]:
            ff = g["four_factors"]
            if not ff:
                out.append(f"| {g['date']} | – | – | – | – | – | – |")
                continue
            cell = [f"{_fmt(ff['us'][k])} / {_fmt(ff['them'][k])}" for k in ("efg", "tov", "orb", "ft")]
            out.append(f"| {g['date']} | " + " | ".join(cell) + f" | {_fmt(ff['us']['poss'])} / {_fmt(ff['them']['poss'])}"
                       f" | {_fmt(ff['us']['ppp'], 2)} / {_fmt(ff['them']['ppp'], 2)} |")
        out.append("")
        for k, _ in FACTORS:
            if k in charts:
                out += [f"![{L[k]}]({charts[k]})", ""]
    else:
        out.append(L["no_data"])
    out += ["", f"## {L['targets']}", ""]
    checked = [c for c in season["targets_checked"] if c["targets"]]
    if not checked:
        out += [L["none_checked"], ""]
    for c in checked:
        out += [L["t_from"].format(d1=c["from_date"], d2=c["checked_date"]), ""]
        for t in c["targets"]:
            out.append(f"- **{L[t['status']]}** ({', '.join(t['kb'] or [])}): {_cell(t['target'])}")
            for cl in t["clauses"]:
                if cl["status"] != "not_measurable":
                    out.append(f"  - {L[cl['status']]}: {_cell(cl['metric'])} {cl['op']} {cl['value']:g}, "
                               f"{L['actual']} {cl['actual']:g}")
        out.append("")
    if season["next_targets"]:
        out += [f"**{L['next']}**", ""] + [f"- ({', '.join(t['kb'])}) {_cell(t['target'])}" for t in season["next_targets"]]
    out += ["", f"## {L['themes']}", ""]
    if season["themes"]:
        out += [f"| {L['kb']} | {L['games']} | {L['insights']} | {L['date']} |", "|---|---|---|---|"]
        for t in season["themes"]:
            mark = f" ({L['recurring']})" if t["recurring"] else ""
            out.append(f"| {t['kb']}{mark} | {t['games']} | {t['insights']} | {', '.join(t['dates'])} |")
    else:
        out.append(L["no_data"])
    rule = L["rule"].format(p=f"{PRIOR_MIN:g}", m=f"{SMALL_MIN:g}", g=SMALL_GAMES)
    out += ["", f"## {L['players']}", "", rule, ""]
    if season["players"]:
        out += [f"| {L['player']} | {L['games']} | {L['minutes']} | {L['on']} | {L['on10']} | {L['off10']} | "
                f"{L['onoff']} | |", "|---|---|---|---|---|---|---|---|"]
        for p in season["players"]:
            off = (p["off"] or {}).get("per10_shrunk")
            out.append(f"| #{p['player']} | {p['games']} | {p['minutes']} | {p['on']['net']:+d} | "
                       f"{_signed(p['on']['per10_shrunk'])} ({L['raw']} {_signed(p['on']['per10_raw'])}) | "
                       f"{_signed(off)} | {_signed(p['on_off_shrunk'])} | {L['small'] if p['small_sample'] else ''} |")
    else:
        out.append(L["no_data"])
    out += ["", f"## {L['lineups']}", "", rule, ""]
    if season["lineups"]:
        out += [f"| {L['lineup']} | {L['games']} | {L['minutes']} | {L['net']} | {L['raw']} | {L['net']} / 10 | |",
                "|---|---|---|---|---|---|---|"]
        for u in season["lineups"]:
            out.append(f"| {' '.join('#' + n for n in u['lineup'])} | {u['games']} | {u['minutes']} | {u['net']:+d} | "
                       f"{_signed(u['per10_raw'])} | {_signed(u['per10_shrunk'])} | "
                       f"{L['small'] if u['small_sample'] else ''} |")
    else:
        out.append(L["no_data"])
    return "\n".join(out) + "\n"


def _cell(s) -> str:
    return str(s if s is not None else "–").replace("|", "/").replace("\n", " ")


# ---- pre-game brief ---------------------------------------------------------------------------------------------
B = {
    "zh": dict(intro="赛季简报。到现在我们打了 {n} 场，{w} 胜 {l} 负，总得分 {pf} 比 {pa}。",
               themes="反复出现的问题：{items}。", theme_item="{kb}，{g} 场都出现",
               no_themes="还没有反复出现的问题。", last_themes="上一场的主题：{items}。", targets="上一场定下的目标，这一场要做到：",
               no_targets="上一场没有写下一场的目标。",
               opp="对手 {o}：我们之前和他们打过 {k} 场。{items}。", opp_item="{d}，{us} 比 {them}，{res}",
               opp_none="对手 {o}：之前没有和他们比赛的记录。", win="我们赢", loss="我们输", tie="打平",
               unknown="比分不清楚", last="最后一句：先做好最常出现的那一个问题。"),
    "en": dict(intro="Season brief. Games played so far: {n}; {w} won, {l} lost, points {pf} to {pa}.",
               themes="Our recurring themes: {items}.", theme_item="{kb}, in {g} games",
               no_themes="No theme has come up in more than one game yet.", last_themes="Last game's themes: {items}.",
               targets="The targets we set after the last game, for this one:",
               no_targets="The last game set no targets for the next one.",
               opp="Today's opponent, {o}: games against them so far: {k}. {items}.",
               opp_item="On {d}, {us} to {them}, {res}", opp_none="Today's opponent, {o}: no earlier game against them.",
               win="a win", loss="a loss", tie="a tie", unknown="score unclear",
               last="One thing to take on court: fix the theme that keeps coming back first."),
}


def brief(season: dict, games: list[dict], lang: str, opponent: str | None = None) -> str:
    """Plain paragraphs for the ear (narrate reads every paragraph; lines starting with '#' are not read)."""
    L = B[lang]
    rec = season["record"]
    paras = [f"# Pre-game brief, season {season['season']} (generated by `season --brief`; edit before narrating)",
             L["intro"].format(n=season["games"], w=rec["W"], l=rec["L"], pf=rec["for"], pa=rec["against"])]
    rec_themes = [t for t in season["themes"] if t["recurring"]][:3]
    if rec_themes:
        paras.append(L["themes"].format(items="; ".join(
            L["theme_item"].format(kb=t["kb"].replace("-", " "), g=t["games"]) for t in rec_themes)))
    else:
        last = list(dict.fromkeys(s for it in games[-1].get("insights") or [] for s in it["kb"]))[:3]
        paras.append(L["no_themes"] + (" " + L["last_themes"].format(items=", ".join(s.replace("-", " ") for s in last))
                                       if last else ""))
        rec_themes = [t for t in season["themes"] if t["kb"] in last]
    if lang == "en":
        rules = {s: it["rule"] for g in games for it in g.get("insights") or [] for s in it["kb"] if it.get("rule")}
        paras += [f"{t['kb'].replace('-', ' ')}: {rules[t['kb']]}" for t in rec_themes if t["kb"] in rules]
    if season["next_targets"]:
        paras.append(L["targets"])
        paras += [t["target"] for t in season["next_targets"]]
    else:
        paras.append(L["no_targets"])
    if opponent:
        slug = ws.slug(opponent)
        past = [g for g in games if g["opponent_slug"] in (slug, ws._legacy_slug(opponent))
                or g["opponent"].lower() == opponent.lower()]
        if past:
            items = []
            for g in past:
                r = g["result"]
                res = {"W": L["win"], "L": L["loss"], "T": L["tie"]}.get(r["outcome"], L["unknown"])
                items.append(L["opp_item"].format(d=g["date"], us=r["us"] if r["source"] else "?",
                                                  them=r["them"] if r["source"] else "?", res=res))
            paras.append(L["opp"].format(o=past[-1]["opponent"], k=len(past), items="; ".join(items)))
        else:
            paras.append(L["opp_none"].format(o=opponent))
    paras.append(L["last"])
    return "\n\n".join(paras) + "\n"


# ---- writing ------------------------------------------------------------------------------------------------------
def write(season: dict, games: list[dict], out: Path, langs: tuple[str, ...], html_page: bool = True) -> list[Path]:
    """season.json (kind "season", read by `html` for the record band), README per language, SVG charts and
    index.html into `out`."""
    out.mkdir(parents=True, exist_ok=True)
    colours = (games[-1]["hex"]["us"], games[-1]["hex"]["them"])
    payload = {"kind": "season", "us": {"team": season["team"], "hex": colours[0]},
               "them": {"hex": colours[1]}, **season}
    written = [out / "season.json"]
    media.write_text_atomic(out / "season.json", json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    for lang in langs:
        charts = {}
        if any(g["four_factors"] for g in season["results"]):
            for k, _ in FACTORS:
                name = f"ff_{k}.{lang}.svg"
                (out / name).write_text(svg_trend(season["results"], k, lang, colours), encoding="utf8")
                charts[k] = name
        p = out / ("README.md" if lang == "zh" else f"README.{lang}.md")
        p.write_text(readme(season, games, lang, charts), encoding="utf8")
        written.append(p)
    if html_page:
        from . import render_html
        page = out / "index.html"
        page.write_text(render_html.page(out), encoding="utf8")
        written.append(page)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner season", description=__doc__.splitlines()[0])
    ap.add_argument("--season", help="season id (default: team.json `season`, else <first date>_<last date>)")
    ap.add_argument("--out", type=Path, help="season folder (default: <workspace>/season/<season id>)")
    ap.add_argument("--brief", action="store_true", help="also write brief.<lang>.md, the pre-game listen script")
    ap.add_argument("--opponent", help="next opponent's name: the brief adds our past results against them")
    ap.add_argument("--no-html", action="store_true", help="skip index.html")
    a = ap.parse_args(argv)
    root = ws.root()
    season, games = build(root, a.season)
    langs = tuple(l for l in (ws.profile().get("languages") or LANG_ORDER) if l in T) or LANG_ORDER
    out = a.out or root / "season" / season["season"]
    written = write(season, games, out, langs, not a.no_html)
    if a.brief:
        for lang in langs:
            p = out / f"brief.{lang}.md"
            p.write_text(brief(season, games, lang, a.opponent), encoding="utf8")
            written.append(p)
    rec = season["record"]
    print(f"[season] {season['season']}: {season['games']} games, {rec['W']}-{rec['L']}"
          + (f"-{rec['T']}" if rec["T"] else ""))
    for g in season["results"]:
        if g["missing"]:
            print(f"  {g['key']}: missing {', '.join(g['missing'])}")
    for p in written:
        print("wrote", p)


if __name__ == "__main__":
    main()
