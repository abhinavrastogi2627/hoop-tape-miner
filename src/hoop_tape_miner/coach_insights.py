"""Coaching insights: validate insights.json against the trips, the knowledge base and summary.json; build the blind
A/B rating sheet that compares them with the memo conclusions.

usage: hoop-tape-miner coach-insights check --review <run>/review_v1 [--kb prompts/coach_kb.md] [--insights FILE]
       hoop-tape-miner coach-insights ab --review <run>/review_v1 --out <review>/eval/ab_insights.md
                                       [--old-report README.md] [--seed N] [--cap 450]

check: reads insights.json, coach_part*.json (+ part*.json for missing trip times), summary.json and features.json
(if present); prints every error and exits 1 when there is one.
ab: writes the rating sheet with two sets labelled A and B (randomly assigned, equal item count, same bullet format and
length cap) and a sidecar <out stem>.key.json with the seed and which set is which. Give the owner only the sheet.

Number names in an insight's `numbers` are dotted paths into summary.json, e.g. `all.us.turnovers` or
`B.them.transition_scores` (list items by index); `features.<path>` resolves in features.json. A name that does not
resolve is not checked (it may come from official.json or plusminus.json).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

from .coach_eval import load_trips, memo_conclusions, trip_times

KB = Path(__file__).resolve().parents[2] / "prompts" / "coach_kb.md"
SLACK = 3.0
TEXT_FIELDS = ("claim", "why", "rule", "drill", "target_next_game")
VERDICTS = ("keep", "revise", "drop")
CONFIDENCE = ("high", "medium", "low")
_KB_HEAD = re.compile(r"^###\s+KB-([A-Za-z0-9_-]+)\s*$", re.M)
_MISSING = object()


def kb_slugs(path: Path) -> set[str]:
    """Slugs of every `### KB-<slug>` heading in the knowledge base file."""
    return set(_KB_HEAD.findall(Path(path).read_text(encoding="utf8")))


def resolve(data, name: str):
    """Value at a dotted path (`all.us.turnovers`, `features.12-1.off_spacing_m`) or _MISSING."""
    cur = data
    for part in name.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.lstrip("-").isdigit() and -len(cur) <= int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return _MISSING
    return cur


def _same(a, b) -> bool:
    num = (int, float)
    if isinstance(a, num) and isinstance(b, num) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) <= 1e-6 * max(1.0, abs(b))
    return a == b


def _in_trip(t: float, windows: list[tuple[float, float]]) -> bool:
    return any(a - SLACK <= t <= b + SLACK for a, b in windows)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_insights(insights: list[dict], trips: list[dict], kb_slugs: set[str] | None, summary: dict,
                      features=None) -> list[str]:
    """Errors in a final insights list (empty = valid): every insight has >= 2 distinct evidence times, every cited
    time (evidence and counter-examples) lies within some trip's [t0, t1] +- 3 s, every kb slug exists (kb_slugs None
    skips that check), every resolvable number equals summary.json (or features.json for `features.*`), the text
    fields are filled, and the critic kept or revised it (a `drop` must be moved to insights_dropped.json)."""
    if not isinstance(insights, list) or not insights:
        return ["insights.json must be a non-empty list of insights"]
    windows = [w for w in (trip_times(x) for x in trips) if _num(w[0]) and _num(w[1])]
    errs, ids = [], set()
    for i, it in enumerate(insights):
        if not isinstance(it, dict):
            errs.append(f"insight {i}: not an object")
            continue
        tag = f"insight {it.get('id') or i}"
        if it.get("id") in ids:
            errs.append(f"{tag}: duplicate id")
        ids.add(it.get("id"))
        for f in TEXT_FIELDS:
            if not str(it.get(f) or "").strip():
                errs.append(f"{tag}: `{f}` is empty")
        ev = it.get("evidence") if isinstance(it.get("evidence"), list) else []
        times = {round(e["t"], 1) for e in ev if isinstance(e, dict) and _num(e.get("t"))}
        if len(times) < 2:
            errs.append(f"{tag}: needs evidence at >= 2 different video times (has {len(times)})")
        cex = it.get("counter_examples") or []
        if not isinstance(cex, list):
            errs.append(f"{tag}: `counter_examples` must be a list")
            cex = []
        for kind, items in (("evidence", ev), ("counter-example", cex)):
            for e in items:
                t = e.get("t") if isinstance(e, dict) else None
                if not _num(t):
                    errs.append(f"{tag}: {kind} item without a numeric `t`: {e!r}")
                elif not _in_trip(t, windows):
                    errs.append(f"{tag}: {kind} time {t} lies in no trip (orphan; cite a time inside a trip)")
        kb = it.get("kb")
        if not isinstance(kb, list) or not kb:
            errs.append(f"{tag}: `kb` must list at least one knowledge-base slug")
        elif kb_slugs is not None:
            errs += [f"{tag}: unknown kb slug {s!r}" for s in kb if s not in kb_slugs]
        nums = it.get("numbers") or {}
        if not isinstance(nums, dict):
            errs.append(f"{tag}: `numbers` must be an object {{name: value}}")
            nums = {}
        for name, val in nums.items():
            src, path = (features, name[len("features."):]) if name.startswith("features.") else (summary, name)
            want = resolve(src, path) if src is not None else _MISSING
            if want is not _MISSING and not _same(val, want):
                errs.append(f"{tag}: number {name} = {val!r} but the source says {want!r}")
        if it.get("confidence") not in CONFIDENCE:
            errs.append(f"{tag}: `confidence` must be one of {', '.join(CONFIDENCE)}")
        critic = it.get("critic")
        verdict = critic.get("verdict") if isinstance(critic, dict) else None
        if verdict not in VERDICTS:
            errs.append(f"{tag}: no critic verdict (critic.verdict keep|revise)")
        elif verdict == "drop":
            errs.append(f"{tag}: critic verdict is drop; move it to insights_dropped.json")
    return errs


def _load(p: Path, default=None):
    return json.loads(p.read_text(encoding="utf8")) if p.exists() else default


def check_review(review: Path, kb: Path = KB, insights: Path | None = None) -> list[str]:
    """validate_insights over a review folder's files (the `check` subcommand and the run step use this)."""
    review = Path(review)
    ip = Path(insights) if insights else review / "insights.json"
    if not ip.exists():
        return [f"{ip} not found"]
    if not Path(kb).exists():
        return [f"knowledge base {kb} not found"]
    try:
        items = json.loads(ip.read_text(encoding="utf8"))
    except json.JSONDecodeError as e:
        return [f"{ip}: invalid JSON ({e})"]
    return validate_insights(items, load_trips(review), kb_slugs(kb), _load(review / "summary.json", {}),
                             _load(review / "features.json"))


# ---------- blind A/B sheet ----------

_REPORT_SECTION = re.compile(r"结论|要点|问题|练|计划|conclusion|takeaway|went wrong|practi[cs]e|priorit|game plan", re.I)


def report_items(text: str) -> list[str]:
    """Numbered/bulleted items and numbered table rows under the H2 sections of a report that hold its conclusions,
    rules and practice priorities."""
    out = []
    for sec in re.split(r"^## ", text, flags=re.M)[1:]:
        if not _REPORT_SECTION.search(sec.splitlines()[0]):
            continue
        for line in sec.splitlines()[1:]:
            m = re.match(r"^\s*(?:\d+[.)]|[-*])\s+(.+)$", line)
            row = re.match(r"^\|\s*\d+\s*\|(.+)\|\s*$", line)
            if m:
                out.append(m.group(1))
            elif row:
                out.append(" · ".join(c.strip() for c in row.group(1).split("|") if c.strip()))
    return out


def _mmss(t: float) -> str:
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


def render_insight(it: dict) -> str:
    times = ", ".join(_mmss(e["t"]) for e in it.get("evidence", []) if isinstance(e, dict) and _num(e.get("t")))
    who = f"#{it['player']}: " if it.get("player") else ""
    return (f"{who}{it.get('claim', '')} Why: {it.get('why', '')} Rule: {it.get('rule', '')} "
            f"Drill: {it.get('drill', '')} Target: {it.get('target_next_game', '')} ({times})")


def plain(text: str, cap: int) -> str:
    """One line of plain text: markdown emphasis, links and clip markers removed, capped at `cap` characters."""
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", str(text))
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[*_`#>]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= cap else s[:cap - 1].rstrip() + "…"


SHEET = """# Rating sheet: two sets of coaching points

Two sets, A and B, written from the same game film. Rate every item on its own; do not try to guess where a set
came from. Fill the table below each set.

- truth 1-5: matches what happened on film (5 = certainly true).
- why 1-5: explains why it happened, in basketball terms.
- act 1-5: the team can act on it (a clear rule, drill or target).
- fact error: yes/no; yes when any fact (time, jersey, count, outcome) is wrong. Note which.

At the end: which set would you rather give the team, A or B, and why (one line).
"""


def build_ab(review: Path, out: Path, old_report: Path | None = None, seed: int | None = None, cap: int = 450,
             insights: Path | None = None) -> dict:
    """Write the blind sheet to `out` and `<out stem>.key.json`; return the key."""
    review, out = Path(review), Path(out)
    old = [c for p in sorted(review.glob("memo_part*.md")) for c in memo_conclusions(p.read_text(encoding="utf8"))]
    if old_report:
        old += report_items(Path(old_report).read_text(encoding="utf8"))
    ins = json.loads((Path(insights) if insights else review / "insights.json").read_text(encoding="utf8"))
    new = [render_insight(it) for it in ins]
    if seed is None:
        seed = random.SystemRandom().randrange(1 << 30)
    rng = random.Random(seed)
    n = min(len(old), len(new))
    sets = {"memos": rng.sample(old, n), "insights": rng.sample(new, n)}
    order = ["memos", "insights"]
    rng.shuffle(order)
    key = {"seed": seed, "sets": {"A": order[0], "B": order[1]}, "items_per_set": n,
           "available": {"memos": len(old), "insights": len(new)}}
    lines = [SHEET]
    for label in ("A", "B"):
        lines.append(f"## Set {label}\n")
        lines += [f"- {label}{i}. {plain(x, cap)}" for i, x in enumerate(sets[key["sets"][label]], 1)]
        lines.append("\n| item | truth 1-5 | why 1-5 | act 1-5 | fact error (yes/no, which) |\n|---|---|---|---|---|")
        lines += [f"| {label}{i} |  |  |  |  |" for i in range(1, n + 1)]
        lines.append("")
    lines.append("Preferred set (A/B) and why:\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf8")
    out.with_name(out.stem + ".key.json").write_text(json.dumps(key, indent=1), encoding="utf8")
    return key


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hoop-tape-miner coach-insights")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate <review>/insights.json; exit 1 with the error list")
    c.add_argument("--review", required=True)
    c.add_argument("--kb", default=str(KB))
    c.add_argument("--insights", help="default: <review>/insights.json")
    b = sub.add_parser("ab", help="blind A/B rating sheet: memo conclusions vs insights.json")
    b.add_argument("--review", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--old-report", help="a finished README.md whose conclusion/practice sections join the memo set")
    b.add_argument("--insights", help="default: <review>/insights.json")
    b.add_argument("--seed", type=int)
    b.add_argument("--cap", type=int, default=450, help="max characters per item (both sets)")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        errs = check_review(Path(a.review), Path(a.kb), a.insights)
        for e in errs:
            print(e)
        if errs:
            sys.exit(f"coach-insights check: {len(errs)} error(s)")
        print("coach-insights check: PASS")
        return 0
    key = build_ab(Path(a.review), Path(a.out), a.old_report, a.seed, a.cap, a.insights)
    print(f"wrote {a.out} ({key['items_per_set']} items per set); key in "
          f"{Path(a.out).with_name(Path(a.out).stem + '.key.json')} (do not show it to the rater)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
