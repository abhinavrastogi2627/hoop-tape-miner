"""Turn a reviewed training session into numbers, figures and a fact sheet for the report writer.

usage: hoop-tape-miner train-summary <session folder>

Reads <run>/train_review/review_part<N>.json (the film review), <run>/reps.json (pose metrics), dribble.json and
activity.json, session.json targets and every earlier session's summary.json of the same player, and our games up
to the session date for the player's jersey (game_link: insights to train for, game vs practice make rates). Writes
to the session folder:
  summary.json   totals, per zone / spot / type / hand, misses, streak, thirds, form, dribbling, targets,
                 previous session and progress over all sessions (the html band reads `totals`)
  facts.md       the same as tables with video times: the only numbers the report may use
  zones.png, timeline.png, form.png, progress.png (+ .en.png twins)
Every percentage counts decided attempts only (make / miss); `unclear` attempts are listed apart.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import game_link, workspace
from . import training as T

LABELS = {
    "zh": dict(zones="各区域命中率", zone=dict(ft="罚球", rim="篮下", paint="禁区", mid="中距离", three="三分"),
               finish="终结", timeline="训练时间线", minute="训练时间（分钟）", make="进", miss="不进", unclear="看不清",
               dribble="运球", form="出手姿态：进球 vs 不进", progress="每次训练的命中率", session="训练",
               all="全部", shot="投篮", ft="罚球",
               metric=dict(lift="出手高度（躯干长）", knee_bend="屈膝（度）", dip_to_release="下蹲到出手（秒）",
                           elbow_set="举球时肘角（度）", elbow_release="出手时肘角（度）", jump="起跳（躯干长）"),
               block=dict(shooting="投篮", finishing="终结", dribbling="运球", rest="休息")),
    "en": dict(zones="Make % by zone", zone=dict(ft="Free throw", rim="At the rim", paint="Paint", mid="Mid-range", three="Three"),
               finish="Finish", timeline="Session timeline", minute="Session time (min)", make="make", miss="miss",
               unclear="unclear", dribble="Dribbling", form="Shooting form: makes vs misses", progress="Make % per session",
               session="Session", all="All", shot="Shots", ft="Free throws",
               metric=dict(lift="Release height (torso lengths)", knee_bend="Knee bend (deg)", dip_to_release="Dip to release (s)",
                           elbow_set="Elbow at set point (deg)", elbow_release="Elbow at release (deg)", jump="Jump (torso lengths)"),
               block=dict(shooting="shooting", finishing="finishing", dribbling="dribbling", rest="rest")),
}


def load_reviews(review_dir: Path) -> list[dict]:
    """review_part<N>.json files in part order; other names (review_part2.old.json, a backup) are skipped."""
    parts = []
    for p in review_dir.glob("review_part*.json"):
        n = p.stem.removeprefix("review_part")
        if not n.isdigit():
            print(f"[train-summary] skipping {p.name}: not review_part<N>.json")
            continue
        parts.append((int(n), p))
    return [json.loads(p.read_text(encoding="utf8")) for _, p in sorted(parts)]


def merge_metrics(reps: list[dict], candidates: list[dict]) -> list[dict]:
    """Reviewed reps get the pose metrics of their candidate (same id)."""
    by_id = {c["id"]: c for c in candidates}
    out = []
    for r in reps:
        c = by_id.get(r.get("id"), {})
        out.append({**{k: c.get(k) for k in (*T.FORM_KEYS, "travel", "hint", "two_hands")}, "pose_hand": c.get("hand"), **r})
    return out


def dribble_summary(reviews: list[dict], detected: list[dict]) -> dict:
    """Confirmed dribble drills from the review (bounce counts from the overlapping detected segments)."""
    drills = [d for part in reviews for d in part.get("dribble", [])]
    confirmed = bool(drills)
    if not drills:
        drills = [{"from": T.mmss(d["from"]), "to": T.mmss(d["to"]), "drill": None, "hand": None, "losses": None}
                  for d in detected]
    windows = merge_windows([(T.seconds(d["from"]), T.seconds(d["to"])) for d in drills])
    secs = sum(b - a for a, b in windows)
    share = {"R": 0.0, "L": 0.0}
    counted = 0.0  # counted: seconds of drill time the scan has bounces for (the rate)
    for seg in detected:  # each detected segment once, its bounces clipped to the drill windows by time share
        f, t = float(seg["from"]), float(seg["to"])
        inside = sum(max(0.0, min(t, b) - max(f, a)) for a, b in windows)
        if inside <= 0:
            continue
        counted += inside
        frac = inside / (t - f) if t > f else 1.0
        for h in share:
            share[h] += seg["bounces"][h] * frac
    bounces = {h: int(round(v)) for h, v in share.items()}
    total = sum(bounces.values())
    return dict(confirmed=confirmed, seconds=round(secs, 1), drills=drills, bounces=bounces,
                left_share=round(bounces["L"] / total, 2) if total else None,
                rate=round(total / counted, 2) if counted else None,
                losses=sum(d.get("losses") or 0 for d in drills) if confirmed else None)


def merge_windows(ws: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Overlapping or touching (from, to) windows joined, empty ones dropped, in time order."""
    out: list[list[float]] = []
    for a, b in sorted(w for w in ws if w[1] > w[0]):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def progress_rows(folder: Path, current: dict) -> list[dict]:
    rows = []
    for d in T.earlier_sessions(folder):
        p = d / "summary.json"
        if p.exists():
            rows.append(row(json.loads(p.read_text(encoding="utf8"))))
    return rows + [row(current)]


def row(s: dict) -> dict:
    tot = s.get("totals", {})
    return dict(session=s.get("session"), date=s.get("date"), all=tot.get("all"), shot=tot.get("shot"),
                finish=tot.get("finish"), ft=(s.get("zones") or {}).get("ft"),
                active_min=round((s.get("active_s") or 0) / 60, 1), dribble_s=(s.get("dribble") or {}).get("seconds"),
                targets_met=sum(t["status"] == "met" for t in s.get("targets", [])), targets=len(s.get("targets", [])))


def summarize(folder: Path, s: dict, run: Path) -> dict:
    review_dir = run / "train_review"
    reviews = load_reviews(review_dir)
    if not reviews:
        sys.exit(f"no review_part<N>.json in {review_dir}: run the film review first")
    candidates = json.loads((run / "reps.json").read_text(encoding="utf8"))
    detected = json.loads((run / "dribble.json").read_text(encoding="utf8"))
    act = json.loads((run / "activity.json").read_text(encoding="utf8"))
    reps = merge_metrics(T.reviewed_reps(reviews), candidates)
    shots = [r for r in reps if r["category"] == "shot"]
    fins = [r for r in reps if r["category"] == "finish"]
    reviewed_ids = {r.get("id") for p in reviews for r in p.get("reps", [])}
    missing = [c["id"] for c in candidates if c["id"] not in reviewed_ids]
    active_min = (act.get("active_s") or 0) / 60
    out = dict(
        session=folder.name, player=s.get("player"), name=s.get("name"), date=s.get("date"),
        duration_s=act.get("duration_s"), active_s=act.get("active_s"), visible_s=act.get("visible_s"),
        totals=dict(all=T.tally(reps), shot=T.tally(shots), finish=T.tally(fins)),
        reps_per_active_min=round(len(reps) / active_min, 1) if active_min > 0 else None,  # None: no active time
        zones=T.by(shots, "zone", T.ZONES), spots=T.by(shots, "spot"), types=T.by(reps, "type"),
        finish_hands=T.by(fins, "hand", ("R", "L")),
        left_finish_share=round(sum(r.get("hand") == "L" for r in fins) / len(fins), 2) if fins else None,
        misses={k: sum(r.get("miss") == k for r in reps if r.get("result") == "miss")
                for k in ("short", "long", "left", "right", "rim-out", "airball", "blocked")},
        streak=T.longest_streak(reps),
        thirds=T.thirds(reps, 0, act.get("duration_s") or (reps[-1]["t_s"] if reps else 0)),
        form=T.form_stats(shots), form_finish=T.form_stats(fins),
        blocks=[b for p in reviews for b in p.get("blocks", [])],
        dribble=dribble_summary(reviews, detected),
        targets=T.check_targets(s.get("targets") or [], reps), targets_from=s.get("targets_from"),
        review=dict(candidates=len(candidates), confirmed=sum(1 for r in reps if not r.get("added")),
                    added=sum(1 for r in reps if r.get("added")), not_reviewed=missing,
                    notes=[p.get("notes") for p in reviews if p.get("notes")]),
        reps=[{k: v for k, v in r.items() if k != "t_s"} for r in reps],
    )
    out.update(game_loop(folder, s, out))
    out["progress"] = progress_rows(folder, out)
    prev = out["progress"][-2] if len(out["progress"]) > 1 else None
    if prev:
        def d(key):
            a, b = (out["totals"].get(key) or {}).get("pct"), (prev.get(key) or {}).get("pct")
            return round(a - b, 3) if a is not None and b is not None else None
        out["previous"] = dict(session=prev["session"], delta_pct=d("all"), delta_shot=d("shot"), delta_finish=d("finish"))
    return out


def game_loop(folder: Path, s: dict, sm: dict) -> dict:
    """game_focus (session.json, else the latest game now) and game_vs_practice for the player's jersey; both None
    when the session is outside a workspace or no jersey is known."""
    root, jersey = game_link.workspace_of(folder), game_link.jersey_for(s, workspace.profile())
    if not root or not jersey or not s.get("date"):
        return dict(game_focus=s.get("game_focus"), game_vs_practice=None)
    return dict(game_focus=s.get("game_focus") or game_link.focus(root, jersey, s["date"]),
                game_vs_practice=game_link.compare(root, jersey, s["date"], sm))


# ---- facts.md ----------------------------------------------------------------------------------------------

def _rate(t: dict | None) -> str:
    return pct(t) if t else "–"


def game_facts(sm: dict) -> list[str]:
    """facts.md lines: the latest game's insights to train for, and game vs practice make rates."""
    L = []
    gf = sm.get("game_focus")
    if gf:
        L += [f"## Game focus (from {gf['game']}, jersey #{gf['jersey']})", ""]
        L += [f"- {i['id']} ({i['scope']}): {i.get('claim') or ''} Drill: {i.get('drill') or 'unclear'}. "
              f"Game target: {i.get('target_next_game') or 'unclear'}" for i in gf["insights"]]
        L += ([gf["note"]] if gf.get("note") else []) + [""]
    gv = sm.get("game_vs_practice")
    if gv and gv["rows"]:
        L += [f"## Game vs practice (jersey #{gv['jersey']}, {gv['games']} game(s), last {gv['last_game']})", "",
              gv["note"] + f" Small sample = fewer than {gv['small_n']} attempts on a side.", "",
              "| category | practice (this session) | last game | all games | gap (games - practice) | sample |",
              "|---|---|---|---|---|---|"]
        for r in gv["rows"]:
            g = r["games"]
            L.append(f"| {r['category']} | {_rate(r['practice'])} | {_rate(r['last_game'])} | {_rate(g)} ({g['source']}) | "
                     f"{'+' if r['gap_pp'] >= 0 else ''}{r['gap_pp']} pp | {r['sample']}"
                     + (f"; {r['unattributed']} of our reviewed shots have no shooter, so his game attempts are "
                        "likely more" if r.get("unattributed") else "") + " |")
        L.append("")
    return L

def pct(t):
    return f"{t['made']}/{t['att']} ({round(100 * t['pct'])}%)" if t and t.get("att") else "–"


def facts(sm: dict) -> str:
    L = [f"# Training facts: {sm.get('name') or '#' + str(sm.get('player'))}, {sm['date']}" + (f" ({sm['session']})" if sm['session'] != sm['date'] else ""), "",
         "Every number here comes from the film review (makes / misses) and the pose scan (form, time). "
         "Percentages count decided attempts only; `unclear` attempts are listed apart.", "",
         "## Volume", "",
         f"- session {(sm['duration_s'] or 0) / 60:.1f} min, active {(sm['active_s'] or 0) / 60:.1f} min, "
         f"{len(sm['reps'])} attempts ({dash(sm['reps_per_active_min'])} per active minute)",
         f"- all {pct(sm['totals']['all'])}, unclear {sm['totals']['all']['unclear']}; shots {pct(sm['totals']['shot'])}; "
         f"finishes {pct(sm['totals']['finish'])}",
         f"- longest make streak {sm['streak']}",
         "- by third of the session: " + ", ".join(pct(t) for t in sm["thirds"]),
         f"- scan: {sm['review']['candidates']} candidates, {sm['review']['confirmed']} reviewed as attempts, "
         f"{sm['review']['added']} added by the reviewer" + (f"; NOT REVIEWED: {', '.join(sm['review']['not_reviewed'])}"
                                                           if sm['review']['not_reviewed'] else ""), ""]
    if sm.get("previous"):
        p = sm["previous"]
        L += [f"- vs {p['session']}: all {fmt_delta(p['delta_pct'])}, shots {fmt_delta(p['delta_shot'])}, "
              f"finishes {fmt_delta(p['delta_finish'])}", ""]
    for title, key in (("Shots by zone", "zones"), ("Shots by spot", "spots"), ("All attempts by type", "types"),
                       ("Finishes by hand", "finish_hands")):
        if sm[key]:
            L += [f"## {title}", "", "| | made/att | unclear |", "|---|---|---|"]
            L += [f"| {k} | {pct(v)} | {v['unclear']} |" for k, v in sm[key].items()] + [""]
    if sm.get("left_finish_share") is not None:
        L += [f"Left-hand share of finishes: {round(100 * sm['left_finish_share'])}%", ""]
    L += ["## Misses", "", ", ".join(f"{k} {v}" for k, v in sm["misses"].items() if v) or "none recorded", ""]
    for title, key in (("Shooting form (pose, 2D, comparable only with the same camera spot)", "form"),
                       ("Finishing form", "form_finish")):
        if sm[key]:
            L += [f"## {title}", "", "| metric | mean | spread (sd) | n | makes | misses |", "|---|---|---|---|---|---|"]
            L += [f"| {k} | {v['mean']} | {dash(v['sd'])} | {v['n']} | {dash(v['make_mean'])} | {dash(v['miss_mean'])} |" for k, v in sm[key].items()]
            L += [""]
    dr = sm["dribble"]
    L += ["## Dribbling", "", f"- {dr['seconds'] / 60:.1f} min" + ("" if dr["confirmed"] else " (detected by pose, NOT confirmed by the review)")
          + f", bounces R {dr['bounces']['R']} / L {dr['bounces']['L']}, about {dr['rate']} per s, losses {dr['losses']}"]
    L += [f"- {d['from']}-{d['to']} {d.get('drill') or ''} hand {d.get('hand')} losses {d.get('losses')} {d.get('notes') or ''}".rstrip()
          for d in dr["drills"]] + [""]
    if sm["targets"]:
        L += ["## Targets" + (f" (from {sm['targets_from']})" if sm.get('targets_from') else ""), "", "| target | wanted | actual | status |", "|---|---|---|---|"]
        for t in sm["targets"]:
            want = f"{t.get('attempts') or '-'} att" + (f", {round(100 * t['pct'])}%" if t.get("pct") is not None else "")
            got = f"{t['actual_made']}/{t['actual_att']}" + (f" ({round(100 * t['actual_pct'])}%)" if t["actual_pct"] is not None else "")
            L.append(f"| {t['name']} | {want} | {got} | {t['status']} |")
        L += [""]
    L += game_facts(sm)
    if len(sm["progress"]) > 1:
        L += ["## Progress", "", "| session | all | shots | finishes | free throws | active min | dribble min |", "|---|---|---|---|---|---|---|"]
        L += [f"| {r['session']} | {pct(r['all'])} | {pct(r['shot'])} | {pct(r['finish'])} | {pct(r['ft'])} | {r['active_min']} | "
              f"{round((r['dribble_s'] or 0) / 60, 1)} |" for r in sm["progress"]] + [""]
    L += ["## Blocks", ""] + [f"- {b['from']}-{b['to']} {b.get('category')}: {b.get('drill') or ''}" for b in sm["blocks"]] + [""]
    if sm["review"]["notes"]:
        L += ["## Review notes", ""] + [f"- {n}" for n in sm["review"]["notes"]] + [""]
    L += ["## Every attempt", "", "| t | id | category | zone / type | hand | result | miss | form note |", "|---|---|---|---|---|---|---|---|"]
    L += [f"| {r['t']} | {r.get('id')} | {r['category']} | {r.get('zone') or ''} {r.get('type') or ''} | {r.get('hand') or ''} | "
          f"{r.get('result')} | {r.get('miss') or ''} | {r.get('form') or ''} |" for r in sm["reps"]]
    return "\n".join(L) + "\n"


def dash(v):
    return "–" if v is None else v


def fmt_delta(d):
    return "–" if d is None else f"{'+' if d >= 0 else '-'}{abs(round(100 * d))} pp"


# ---- figures -----------------------------------------------------------------------------------------------

def figures(folder: Path, sm: dict, hexcol: str):
    from . import plots  # noqa: F401  (rcParams, CJK fonts)
    import matplotlib.pyplot as plt
    from .plots import GRID, INK2, MUTED
    col = hexcol or "#6250d6"
    for lang in ("zh", "en"):
        L = LABELS[lang]
        suf = "" if lang == "zh" else ".en"

        # zones + finish types
        rows = [(L["zone"].get(k, k), v) for k, v in sm["zones"].items() if v["att"]]
        rows += [(f"{L['finish']} · {k}", v) for k, v in sm["types"].items()
                 if v["att"] and any(r.get("type") == k and r["category"] == "finish" for r in sm["reps"])]
        if rows:
            fig, ax = plt.subplots(figsize=(7, 0.5 * len(rows) + 1.2))
            y = np.arange(len(rows))
            ax.barh(y, [100 for _ in rows], color=GRID, height=0.6)
            ax.barh(y, [100 * v["pct"] for _, v in rows], color=col, height=0.6)
            for yi, (_, v) in zip(y, rows):
                ax.text(101, yi, f" {round(100 * v['pct'])}%  {v['made']}/{v['att']}", va="center", color=INK2, fontsize=9)
            ax.set_yticks(y, [n for n, _ in rows])
            ax.invert_yaxis()
            ax.set_xlim(0, 135)
            ax.set_xticks([0, 50, 100])
            ax.set_title(L["zones"], loc="left")
            save(fig, folder / f"zones{suf}.png")

        # timeline
        fig, ax = plt.subplots(figsize=(9, 2.8))
        cats = [L["zone"].get(z, z) for z in T.ZONES] + [L["finish"], L["dribble"]]
        for b in sm["blocks"]:
            if b.get("category") in ("shooting", "finishing", "dribbling"):
                ax.axvspan(T.seconds(b["from"]) / 60, T.seconds(b["to"]) / 60, color=GRID, alpha=0.5, lw=0)
        for r in sm["reps"]:
            yv = cats.index(L["finish"]) if r["category"] == "finish" else cats.index(L["zone"].get(r.get("zone"), L["zone"]["mid"])) \
                if r.get("zone") in T.ZONES else cats.index(L["zone"]["mid"])
            x = T.seconds(r["t"]) / 60
            if r.get("result") == "make":
                ax.plot(x, yv, "o", color=col, ms=6)
            elif r.get("result") == "miss":
                ax.plot(x, yv, "o", mfc="none", mec=INK2, ms=6)
            else:
                ax.plot(x, yv, "x", color=MUTED, ms=5)
        for d in sm["dribble"]["drills"]:
            ax.plot([T.seconds(d["from"]) / 60, T.seconds(d["to"]) / 60], [len(cats) - 1] * 2, color=col, lw=5, solid_capstyle="butt")
        ax.set_yticks(range(len(cats)), cats)
        ax.invert_yaxis()
        ax.set_xlabel(L["minute"])
        ax.set_xlim(0, max((sm.get("duration_s") or 60) / 60, 0.5))
        ax.plot([], [], "o", color=col, label=L["make"])
        ax.plot([], [], "o", mfc="none", mec=INK2, label=L["miss"])
        ax.plot([], [], "x", color=MUTED, label=L["unclear"])
        ax.legend(frameon=False, loc="upper right", ncol=3, bbox_to_anchor=(1, 1.22))
        ax.set_title(L["timeline"], loc="left")
        save(fig, folder / f"timeline{suf}.png")

        # form: makes vs misses per metric
        keys = [k for k in ("lift", "knee_bend", "elbow_release", "dip_to_release") if k in sm["form"]]
        shots = [r for r in sm["reps"] if r["category"] == "shot" and r.get("result") in ("make", "miss")]
        if keys and shots:
            fig, axes = plt.subplots(1, len(keys), figsize=(2.6 * len(keys), 2.8))
            axes = np.atleast_1d(axes)
            for ax, k in zip(axes, keys):
                for xi, res in enumerate(("make", "miss")):
                    v = [r[k] for r in shots if r.get("result") == res and isinstance(r.get(k), (int, float))]
                    jit = (np.random.default_rng(0).random(len(v)) - 0.5) * 0.3
                    ax.plot(xi + jit, v, "o", ms=4, **({"color": col} if res == "make" else {"mfc": "none", "mec": INK2}))
                    if v:
                        ax.plot([xi - 0.25, xi + 0.25], [np.mean(v)] * 2, color="#0b0b0b", lw=1.5)
                ax.set_xticks([0, 1], [L["make"], L["miss"]])
                ax.set_xlim(-0.6, 1.6)
                ax.set_title(L["metric"][k], fontsize=9, loc="left")
            fig.suptitle(L["form"], x=0.02, ha="left", fontweight="bold")
            save(fig, folder / f"form{suf}.png")

        # progress over sessions
        prog = sm["progress"]
        if len(prog) > 1:
            fig, ax = plt.subplots(figsize=(7, 2.8))
            x = np.arange(len(prog))
            for key, style in (("all", dict(color=col, lw=2.2)), ("shot", dict(color=INK2, lw=1.2, ls="--")),
                               ("finish", dict(color=MUTED, lw=1.2, ls=":")), ("ft", dict(color="#c9343f", lw=1.2))):
                vals = [100 * r[key]["pct"] if r.get(key) and r[key].get("pct") is not None else np.nan for r in prog]
                if np.isfinite(vals).any():
                    ax.plot(x, vals, marker="o", label=L[key] if key != "ft" else L["ft"], **style)
            ax.set_xticks(x, [r["date"] or r["session"] for r in prog], rotation=0, fontsize=8)
            ax.set_ylim(0, 100)
            ax.yaxis.grid(True, color=GRID)
            ax.legend(frameon=False, fontsize=8, ncol=4, loc="lower left")
            ax.set_title(L["progress"], loc="left")
            save(fig, folder / f"progress{suf}.png")


def save(fig, path: Path):
    import matplotlib.pyplot as plt
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner train-summary", description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", help="session folder (with session.json)")
    a = ap.parse_args(argv)
    folder = Path(a.folder)
    s = T.load_session(folder)
    run = T.session_path(folder, s, "run", "run")
    sm = summarize(folder, s, run)
    (folder / "summary.json").write_text(json.dumps(sm, indent=1, ensure_ascii=False) + "\n", encoding="utf8")
    (folder / "facts.md").write_text(facts(sm), encoding="utf8")
    figures(folder, sm, s.get("hex") or "")
    tot = sm["totals"]["all"]
    print(f"[train-summary] {pct(tot) if tot.get('att') else 'no decided attempts'} over {len(sm['reps'])} attempts ({tot['unclear']} unclear); wrote "
          f"{folder / 'summary.json'}, facts.md and figures")
    if sm["review"]["not_reviewed"]:
        print(f"[train-summary] warning: candidates missing from the review: {', '.join(sm['review']['not_reviewed'])}")


if __name__ == "__main__":
    main()
