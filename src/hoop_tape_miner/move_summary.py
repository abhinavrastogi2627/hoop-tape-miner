"""Turn a reviewed movement session into gated numbers, merged film findings, figures and a fact sheet.

usage: hoop-tape-miner move-summary <movement folder>

Reads <run>/gait.json (move-scan), <run>/move_review/review_*.json (the film review), <run>/move_review/labels.json
(hand-labelled foot contacts on the label strips) and every earlier movement session's summary.json. Writes to the
session folder:
  summary.json   headline, validation per labelled segment, metrics per kind/view/reference key (shown only when
                 the label check passes), faults merged across review groups, progress, metrics_version
  facts.md       the same as tables: the only numbers the report may use (missing = unknown, never 0)
  metrics.png, faults.png (+ .en.png twins); metrics.png only when a metric is shown
Only side-view segments are measured. Running faults found on a non-side camera are hypotheses to test on the
re-shoot, never "seen".
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import gait as G
from . import movement as M

LABELS = {
    "zh": dict(metrics="侧面测量值 vs 参考范围", band="参考范围", faults="录像复盘：每个问题出现在几段里",
               seen="看到", hypothesis="待侧拍验证", not_seen="没看到", not_visible="这个角度看不到",
               segments="段数"),
    "en": dict(metrics="Side-view measurements vs reference bands", band="reference band",
               faults="Film review: segments per finding", seen="seen", hypothesis="to test on the side re-shoot",
               not_seen="not seen", not_visible="not visible from this angle", segments="segments"),
}
STATUSES = ("seen", "hypothesis", "not_seen", "not_visible")


def load_reviews(review_dir: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf8")) for p in sorted(review_dir.glob("review_*.json"))]


# ---- validation ----------------------------------------------------------------------------------------------

def slowmo_of(g: dict) -> float:
    """How many times slower than real life a segment's source plays: gait.json "slowmo", else real_fps / scan_fps
    (gait.json from before "slowmo" was written), else 1."""
    if g.get("slowmo"):
        return float(g["slowmo"])
    r, s = g.get("real_fps"), g.get("scan_fps")
    return max(1.0, round(float(r) / float(s), 2)) if r and s else 1.0


def validate(gaits: dict[str, dict], labels: dict) -> dict:
    """Per labelled side segment: detected contacts inside the labelled window vs the hand labels (gait.compare_contacts
    with a tolerance of 3 frames, at least 0.05 s), take-off check for layups, and `pass` (gait.gate). Label and
    detection times are source seconds; they are compared in real seconds (divided by the segment's slowmo), so the
    tolerance, the MAE (mae_s, tol_s) and the gate are all in real time and frames at the real fps. `window` = the
    label strip span [lo, hi] in source seconds (default: the labelled contacts +- the tolerance)."""
    out = {}
    for sid, lab in labels.items():
        g = gaits.get(sid) or {}
        if not g.get("measurable"):
            continue
        fps = float(g.get("real_fps") or g.get("scan_fps") or 30)
        k = slowmo_of(g)
        tol = max(0.05, 3 / fps)
        cons = lab.get("contacts") or []
        lo, hi = lab.get("window") or ((min(c["on"] for c in cons) - tol * k, max(c["on"] for c in cons) + tol * k)
                                        if cons else (None, None))
        det = [c for c in g.get("contacts") or [] if lo is not None and lo <= c["on"] <= hi]
        real = lambda cs: [dict(c, on=c["on"] / k) for c in cs]
        chk = G.compare_contacts(real(det), real(cons), tol)
        ok = G.gate(chk, fps)
        to_lab, to_det = lab.get("takeoff"), (g.get("layup") or {}).get("takeoff_t")
        if to_lab is not None:
            err = None if to_det is None else abs(to_det - to_lab) / k
            chk["takeoff_err_s"] = None if err is None else round(err, 3)
            ok = ok and err is not None and err <= tol + 1e-9
        out[sid] = dict({k_: (round(v, 4) if isinstance(v, float) else v) for k_, v in chk.items()}, fps=fps,
                        slowmo=k, tol_s=tol, **{"pass": bool(ok)})
    return out


# ---- metrics -------------------------------------------------------------------------------------------------

def seg_value(g: dict, ref: dict) -> float | None:
    """One segment's value for a reference entry (None = unknown)."""
    k, ph = ref["metric"], ref["phase"]
    if ph == "layup":
        return (g.get("layup") or {}).get(k)
    if ph == "dribble":
        return (g.get("dribble") or {}).get(k)
    steps = g.get("steps") or []
    steps = steps[:ref.get("steps", 4)] if ph == "accel" else steps[M.MAXV_FROM_STEP:]
    if k == "cadence_spm":
        st = [s["step_time"] for s in steps if s.get("step_time")]
        return 60 / float(np.mean(st)) if len(st) >= 2 else None
    vals = [s[k] for s in steps if s.get(k) is not None]
    need = 2 if ph == "accel" else 3
    return float(np.mean(vals)) if len(vals) >= need else None


def check_group(g: dict) -> tuple:
    """Segments one hand-label check speaks for: same kind, view, source file and real frame rate."""
    return g.get("kind"), g.get("view"), str(g.get("source") or ""), round(float(g.get("real_fps") or 0))


def validated(gaits: dict[str, dict], validation: dict) -> dict[str, bool | None]:
    """Per measurable segment: True when its own label check passed, or it is unlabelled and every labelled segment
    of its check_group passed; False when its own check (or its group's) failed; None = unvalidated (no labelled
    segment in its group). A passing clip never validates a clip of another source, frame rate or view."""
    groups: dict[tuple, list[bool]] = {}
    for s, v in validation.items():
        if s in gaits:
            groups.setdefault(check_group(gaits[s]), []).append(bool(v["pass"]))
    out = {}
    for s, g in gaits.items():
        if s in validation:
            out[s] = bool(validation[s]["pass"])
        else:
            res = groups.get(check_group(g))
            out[s] = None if not res else all(res)
    return out


def metrics(gaits: dict[str, dict], validation: dict) -> dict:
    """{"<kind>/<view>/<reference key>": {mean, sd, n, values, unvalidated, band, kb, unit, shown, reason}}. Dribble
    metrics need no contact labels; every other metric uses only validated segments (validated()): `values` feed
    the mean, segments without a check of their own group are listed in `unvalidated` and never shown."""
    out = {}
    ok = validated(gaits, validation)
    for sid, g in gaits.items():
        if not g.get("measurable"):
            continue
        for key, ref in M.REFERENCE.items():
            if g["kind"] not in ref["kinds"]:
                continue
            v = seg_value(g, ref)
            if v is None:
                continue
            row = out.setdefault(f"{g['kind']}/{g['view']}/{key}", dict(values={}, band=ref["band"], kb=ref["kb"],
                                                                        unit=ref["unit"], metric=ref["metric"],
                                                                        phase=ref["phase"]))
            row["values"][sid] = round(float(v), 3)
    for name, row in out.items():
        allv, row["unvalidated"] = row["values"], {}
        if row["phase"] == "dribble":
            row["shown"], row["reason"] = True, ""
        else:
            failed = sorted(s for s in allv if ok.get(s) is False)
            row["unvalidated"] = {s: v for s, v in allv.items() if ok.get(s) is None}
            row["values"] = {s: v for s, v in allv.items() if ok.get(s)}
            row["shown"] = bool(row["values"])
            row["reason"] = "" if row["shown"] else \
                "label check failed: " + ", ".join(failed) if failed else "no hand-labelled check"
        vals = list(row["values"].values())
        row["n"] = len(vals)
        row["mean"] = round(float(np.mean(vals)), 3) if vals else None
        row["sd"] = round(float(np.std(vals, ddof=1)), 3) if len(vals) > 1 else None
        if not vals:
            row["shown"], row["reason"] = False, row["reason"] or "no value"
    return out


# ---- faults --------------------------------------------------------------------------------------------------

def wrong_spans(s: dict) -> list[tuple[float, float]]:
    """A reviewed segment's "wrong_person" stretches ("mm:ss.s-mm:ss.s") as (from, to) source seconds."""
    out = []
    for x in s.get("wrong_person") or []:
        a, _, b = str(x).partition("-")
        try:
            out.append((M.secs(a.strip()), M.secs((b or a).strip())))
        except (ValueError, TypeError):
            continue
    return out


def in_spans(t, spans: list[tuple[float, float]]) -> bool:
    """True when any of the finding's times (one or a list of mm:ss.s) falls inside a stretch."""
    ts = t if isinstance(t, list) else [t] if t else []
    for x in ts:
        try:
            v = M.secs(x)
        except (ValueError, TypeError):
            continue
        if any(a - 0.05 <= v <= b + 0.05 for a, b in spans):
            return True
    return False


def faults(reviews: list[dict], gaits: dict[str, dict]) -> list[dict]:
    """Findings merged over review groups: per KB slug the segments and times per status. Segments with
    identity_ok false are left out, and so are findings timed inside a segment's "wrong_person" stretches. A running
    fault (M.SPRINT_SLUGS) seen only on non-side cameras is a hypothesis."""
    by: dict[str, dict] = {}
    good: dict[str, dict] = {}
    for rv in reviews:
        for s in rv.get("segments") or []:
            if s.get("identity_ok") is False:
                continue
            side = (gaits.get(s["id"]) or {}).get("view") == "side"
            wrong = wrong_spans(s)
            for f in s.get("faults") or []:
                if not f.get("kb"):  # a reviewer item without a knowledge-base slug cannot be filed
                    continue
                if f.get("status") in ("seen", "hypothesis") and in_spans(f.get("t"), wrong):
                    continue
                st = f.get("status")
                if st == "seen" and f["kb"] in M.SPRINT_SLUGS and not side:
                    st = "hypothesis"
                if st not in STATUSES:
                    continue
                row = by.setdefault(f["kb"], {k: [] for k in STATUSES} | {"times": [], "notes": []})
                row[st].append(s["id"])
                if st in ("seen", "hypothesis"):
                    if f.get("t"):
                        row["times"] += f["t"] if isinstance(f["t"], list) else [f["t"]]
                    if f.get("note"):
                        row["notes"].append(f"{s['id']}: {f['note']} ({f.get('confidence', '?')})")
            for gd in s.get("good") or []:
                if not gd.get("kb") or in_spans(gd.get("t"), wrong):
                    continue
                row = good.setdefault(gd["kb"], {"segments": [], "times": [], "notes": []})
                row["segments"].append(s["id"])
                if gd.get("t"):
                    row["times"].append(gd["t"])
                if gd.get("note"):
                    row["notes"].append(f"{s['id']}: {gd['note']}")
    rows = [dict(kb=k, status="seen" if v["seen"] else "hypothesis" if v["hypothesis"] else
                 "not_seen" if v["not_seen"] else "not_visible", **v) for k, v in by.items()]
    rows.sort(key=lambda r: (-len(r["seen"]), -len(r["hypothesis"]), r["kb"]))
    return rows + [dict(kb=k, status="good", **v) for k, v in sorted(good.items(), key=lambda x: -len(x[1]["segments"]))]


# ---- progress ------------------------------------------------------------------------------------------------

def progress(folder: Path, mets: dict) -> list[dict]:
    """Shown metrics compared with earlier movement sessions: same kind/view/reference key and metrics_version."""
    rows = []
    for d in M.earlier(folder):
        p = d / "summary.json"
        if not p.exists():
            continue
        old = json.loads(p.read_text(encoding="utf8"))
        if old.get("metrics_version") != G.METRICS_VERSION:
            continue
        for name, row in mets.items():
            o = (old.get("metrics") or {}).get(name)
            if row["shown"] and o and o.get("shown") and o.get("mean") is not None:
                rows.append(dict(session=d.name, metric=name, before=o["mean"], now=row["mean"],
                                 delta=round(row["mean"] - o["mean"], 3)))
    return rows


def summarize(folder: Path, m: dict, run: Path) -> dict:
    gl = json.loads((run / "gait.json").read_text(encoding="utf8"))
    gaits = {g["id"]: g for g in gl}
    for seg in m.get("segments", []):  # gait.json from before "source" was written
        if seg["id"] in gaits and seg.get("source"):
            gaits[seg["id"]].setdefault("source", seg["source"])
    rdir = run / "move_review"
    labels_p = rdir / "labels.json"
    labels = json.loads(labels_p.read_text(encoding="utf8")) if labels_p.exists() else {}
    reviews = load_reviews(rdir) if rdir.exists() else []
    val = validate(gaits, labels)
    mets = metrics(gaits, val)
    flt = faults(reviews, gaits)
    reviewed = sorted({s["id"] for rv in reviews for s in rv.get("segments") or []})
    segs = m.get("segments", [])
    side = [s["id"] for s in segs if s["view"] == "side"]
    return dict(
        player=m.get("player"), name=m.get("name"), date=m.get("date"), session=Path(folder).name,
        metrics_version=G.METRICS_VERSION,
        headline=dict(segments=len(segs), side=len(side), reviewed=len(reviewed),
                      seen=sum(r["status"] == "seen" for r in flt),
                      hypotheses=sum(r["status"] == "hypothesis" for r in flt),
                      good=sum(r["status"] == "good" for r in flt),
                      validated=bool(val) and all(v["pass"] for v in val.values()),
                      shown_metrics=sum(r["shown"] for r in mets.values())),
        kinds={k: [s["id"] for s in segs if s["kind"] == k] for k in M.KINDS if any(s["kind"] == k for s in segs)},
        not_reviewed=[s["id"] for s in segs if s["id"] not in reviewed],
        not_measurable=[s["id"] for s in segs if s["view"] != "side"],
        validation=val, metrics=mets, faults=flt, progress=progress(folder, mets),
        notes=[rv["notes"] for rv in reviews if rv.get("notes")])


# ---- facts ---------------------------------------------------------------------------------------------------

def unk(v, nd=2):
    """'unknown' for a missing value, never 0."""
    if v is None:
        return "unknown"
    return f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def facts(sm: dict) -> str:
    h = sm["headline"]
    L = [f"# Movement facts · {sm.get('name') or ''} #{sm.get('player')} · {sm.get('date')}", "",
         "Only these numbers may appear in the report. 2D pose numbers are approximate (write 'about'); 'unknown' "
         "means not measured, never zero.", "",
         f"- segments: {h['segments']} (side view, measurable: {h['side']}; reviewed on film: {h['reviewed']})",
         f"- findings seen: {h['seen']}; hypotheses for the side re-shoot: {h['hypotheses']}; good habits: {h['good']}",
         f"- label check: {'passed' if h['validated'] else 'not passed or not done'}; metrics shown: "
         f"{h['shown_metrics']}",
         f"- not measurable (not a side view, film review only): {', '.join(sm['not_measurable']) or 'none'}",
         f"- not reviewed: {', '.join(sm['not_reviewed']) or 'none'}", ""]
    L += ["## Film findings", "", "| KB | status | seen in | hypothesis in | not seen in | not visible in | times |",
          "|---|---|---|---|---|---|---|"]
    for r in sm["faults"]:
        if r["status"] == "good":
            continue
        L.append(f"| {r['kb']} | {r['status']} | {', '.join(r['seen']) or '-'} | {', '.join(r['hypothesis']) or '-'} | "
                 f"{', '.join(r['not_seen']) or '-'} | {', '.join(r['not_visible']) or '-'} | "
                 f"{', '.join(map(str, r['times'])) or '-'} |")
    notes = [(r["kb"], n) for r in sm["faults"] if r["status"] != "good" for n in r["notes"]]
    if notes:
        L += ["", "Reviewer notes:"] + [f"- [{kb}] {n}" for kb, n in notes]
    good = [r for r in sm["faults"] if r["status"] == "good"]
    if good:
        L += ["", "## Good habits", ""] + [f"- [{r['kb']}] {', '.join(r['segments'])}: " + "; ".join(r["notes"][:4])
                                           for r in good]
    L += ["", "## Measurements (side view)", ""]
    shown = {k: v for k, v in sm["metrics"].items() if v["shown"]}
    if shown:
        L += ["| metric | about (mean) | sd | n | band | KB |", "|---|---|---|---|---|---|"]
        for k, v in shown.items():
            band = f"{v['band'][0]}-{v['band'][1]} {v['unit']}" if v["band"] else "no band"
            L.append(f"| {k} | {unk(v['mean'])} {v['unit']} | {unk(v['sd'])} | {v['n']} | {band} | {v['kb']} |")
    else:
        L.append("No measurement is shown: no side-view segment passed the hand-labelled check.")
    left = {k: v["unvalidated"] for k, v in sm["metrics"].items() if v.get("unvalidated")}
    if left:
        L += ["", "Segments left out as unvalidated (no label check for that clip's kind, view, source and frame "
              "rate; do not quote): " + "; ".join(f"{k}: {', '.join(v)}" for k, v in left.items())]
    hidden = {k: v for k, v in sm["metrics"].items() if not v["shown"]}
    if hidden:
        L += ["", "Not shown (do not quote): " + "; ".join(f"{k} ({v['reason']})" for k, v in hidden.items())]
    if sm["validation"]:
        L += ["", "## Label check", "", "| segment | matched | missed | extra | MAE s | pass |", "|---|---|---|---|---|---|"]
        for s, v in sm["validation"].items():
            L.append(f"| {s} | {v['matched']} | {v['missed']} | {v['extra']} | {unk(v.get('mae_s'), 3)} | {v['pass']} |")
    if sm["progress"]:
        L += ["", "## Progress", "", "| metric | session | before | now | change |", "|---|---|---|---|---|"]
        L += [f"| {r['metric']} | {r['session']} | {r['before']} | {r['now']} | {r['delta']:+} |" for r in sm["progress"]]
    if sm["notes"]:
        L += ["", "## Review notes", ""] + [f"- {n}" for n in sm["notes"]]
    return "\n".join(L) + "\n"


# ---- figures -------------------------------------------------------------------------------------------------

def figures(folder: Path, sm: dict, hexcol: str):
    from . import plots  # noqa: F401  (rcParams, CJK fonts)
    import matplotlib.pyplot as plt
    from .plots import GRID, INK2, MUTED
    col = hexcol or "#6250d6"
    cols = {"seen": col, "hypothesis": "#e0a030", "not_seen": "#9bbf8a", "not_visible": GRID}
    for lang in ("zh", "en"):
        L = LABELS[lang]
        suf = "" if lang == "zh" else ".en"
        shown = [(k, v) for k, v in sm["metrics"].items() if v["shown"] and v["values"]]
        if shown:
            fig, axes = plt.subplots(len(shown), 1, figsize=(7, 1.1 * len(shown) + 0.8), squeeze=False)
            for ax, (k, v) in zip(axes[:, 0], shown):
                vals = list(v["values"].values())
                if v["band"]:
                    ax.axvspan(*v["band"], color=GRID, alpha=0.8, label=L["band"])
                ax.scatter(vals, np.zeros(len(vals)), color=col, s=30, zorder=3)
                ax.set_yticks([])
                ax.set_title(f"{k}  ({v['unit']})", loc="left", fontsize=9, color=INK2)
                lo = min(vals + list(v["band"] or vals))
                hi = max(vals + list(v["band"] or vals))
                pad = (hi - lo) * 0.15 or 1
                ax.set_xlim(lo - pad, hi + pad)
            fig.suptitle(L["metrics"], x=0.02, ha="left")
            save(fig, folder / f"metrics{suf}.png")
        rows = [r for r in sm["faults"] if r["status"] != "good"]
        if rows:
            fig, ax = plt.subplots(figsize=(7, 0.42 * len(rows) + 1.3))
            y = np.arange(len(rows))
            left = np.zeros(len(rows))
            for st in STATUSES:
                n = np.array([len(r[st]) for r in rows])
                ax.barh(y, n, left=left, color=cols[st], height=0.6, label=L[st])
                left += n
            ax.set_yticks(y, [r["kb"].removeprefix("MV-") for r in rows])
            ax.invert_yaxis()
            ax.set_xlabel(L["segments"], color=MUTED)
            ax.legend(frameon=False, fontsize=8, ncol=2, loc="lower right")
            ax.set_title(L["faults"], loc="left")
            save(fig, folder / f"faults{suf}.png")


def save(fig, path: Path):
    import matplotlib.pyplot as plt
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner move-summary", description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", help="movement session folder (with movement.json)")
    a = ap.parse_args(argv)
    folder = Path(a.folder)
    if not M.is_movement(folder):
        sys.exit(f"no movement.json in {folder}")
    m = M.load(folder)
    run = M.path(folder, m, "run", "run")
    if not (run / "gait.json").exists():
        sys.exit(f"[move-summary] no {run / 'gait.json'}: run move-scan first")
    sm = summarize(folder, m, run)
    (folder / "summary.json").write_text(json.dumps(sm, indent=1, ensure_ascii=False) + "\n", encoding="utf8")
    (folder / "facts.md").write_text(facts(sm), encoding="utf8")
    figures(folder, sm, m.get("hex") or "")
    h = sm["headline"]
    print(f"[move-summary] {h['segments']} segments, {h['reviewed']} reviewed, {h['seen']} findings seen, "
          f"{h['hypotheses']} hypotheses, {h['shown_metrics']} metrics shown; wrote {folder / 'summary.json'}, "
          "facts.md and figures")
    if sm["not_reviewed"]:
        print(f"[move-summary] warning: segments missing from the review: {', '.join(sm['not_reviewed'])}")


if __name__ == "__main__":
    main()
