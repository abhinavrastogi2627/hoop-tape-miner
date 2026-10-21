"""Coaching insights: validate insights.json against the trips, the knowledge base and the number sources; check and
sign the critic's own record (critic.json); build the blind A/B rating sheet that compares them with the memo
conclusions.

usage: hoop-tape-miner coach-insights check --review <run>/review_v1 [--kb prompts/coach_kb.md] [--insights FILE]
                                          [--official FILE] [--no-critic]
       hoop-tape-miner coach-insights critic --review <run>/review_v1 [--kb ...] [--insights FILE]
       hoop-tape-miner coach-insights ab --review <run>/review_v1 --out <review>/eval/ab_insights.md
                                       [--old-report README.md] [--seed N] [--cap 450]

check: reads insights.json, coach_part*.json (+ part*.json for missing trip times), summary.json, features.json,
official.json, plusminus.json / pm_<N>.json (if present) and critic.json; prints every error and exits 1 when there
is one. --no-critic is the writer's check (critic.json not required yet).
critic: the critic's last step: the same checks plus critic.json (every insight has a verdict that lists the sheets
the critic re-opened, covering every evidence time), then writes the hash of insights.json into critic.json. Any later
edit of insights.json breaks the signature and sends the file back to the critic.
ab: writes the rating sheet with two sets labelled A and B (randomly assigned, equal item count, same bullet format and
length cap) and a sidecar <out stem>.key.json with the seed and which set is which. Give the owner only the sheet.

Number names in an insight's `numbers` are dotted paths into summary.json, e.g. `all.us.turnovers` or
`B.them.transition_scores` (list items by index); the prefixes `features.`, `official.`, `plusminus.` and `pm_<N>.`
resolve in those files. A name that does not resolve is an error; the value "unknown" marks a number the writer
could not get (it is not checked).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

from .coach_eval import load_trips, memo_conclusions, trip_times
from .timefmt import mmss as _mmss

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


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _cite_error(e: dict, t: float, by_pid: dict) -> str | None:
    """Why an evidence item does not point at a real trip that contains its time (None = fine)."""
    pid = e.get("pid")
    if pid is None:
        return f"time {t} cites no pid (name the trip: pid and trip)"
    cands = by_pid.get(str(pid), [])
    if not cands:
        return f"time {t}: pid {pid} is not a trip in coach_part*.json (no trip by that pid; orphan)"
    trip = e.get("trip")
    if trip is not None:
        cands = [x for x in cands if str(x.get("trip", 1)) == str(trip)]
        if not cands:
            return f"pid {pid} trip {trip} does not exist (orphan)"
    elif len(cands) > 1:
        return f"pid {pid} has {len(cands)} trips; name the trip"
    wins = [w for w in (trip_times(x) for x in cands) if _num(w[0]) and _num(w[1])]
    if not wins:
        return None  # the trip has no times (old review); the pid itself exists
    if not any(a - SLACK <= t <= b + SLACK for a, b in wins):
        span = ", ".join(f"{a}-{b}" for a, b in wins)
        return f"time {t} lies outside the cited pid {pid}{f' trip {trip}' if trip is not None else ''} ({span})"
    return None


_SOURCE = re.compile(r"^(features|official|plusminus|pm_\d+)$")
UNKNOWN = "unknown"


def validate_insights(insights: list[dict], trips: list[dict], kb_slugs: set[str] | None, summary: dict,
                      features=None, *, sources: dict | None = None, roster: set[str] | None = None) -> list[str]:
    """Errors in an insights list (empty = valid): every insight has >= 2 distinct evidence times; every cited item
    (evidence and counter-examples) names an existing trip (`pid`, plus `trip` when the pid has several) and its time
    lies inside that trip's [t0, t1] +- 3 s; every kb slug exists (kb_slugs None skips that check); every number
    resolves and equals its source (summary.json, or features / official / plusminus / pm_<N> by prefix; the value
    "unknown" marks a number the writer could not get); `player` is on our roster when one is known; the text fields
    are filled; no insight carries a `drop` verdict. The critic's own verdicts are checked by check_critic."""
    if not isinstance(insights, list) or not insights:
        return ["insights.json must be a non-empty list of insights"]
    by_pid: dict[str, list[dict]] = {}
    for x in trips:
        if isinstance(x, dict):
            by_pid.setdefault(str(x.get("pid")), []).append(x)
    srcs = {"features": features, **(sources or {})}
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
                elif (why := _cite_error(e, t, by_pid)):
                    errs.append(f"{tag}: {kind} {why}")
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
            if val == UNKNOWN:
                continue
            head, _, rest = str(name).partition(".")
            if _SOURCE.match(head) and rest:
                src, path, file = srcs.get(head), rest, f"{head}.json"
            else:
                src, path, file = summary, name, "summary.json"
            if src is None:
                errs.append(f"{tag}: number {name}: {file} not found, so it cannot be checked "
                            f"(cite another source, or set the value to \"unknown\")")
                continue
            want = resolve(src, path)
            if want is _MISSING:
                errs.append(f"{tag}: number {name} not found in {file} (fix the name, or set the value to \"unknown\")")
            elif not _same(val, want):
                errs.append(f"{tag}: number {name} = {val!r} but {file} says {want!r}")
        player = it.get("player")
        if player not in (None, "") and roster and str(player) not in roster:
            errs.append(f"{tag}: player #{player} is not on our roster (official.json box score)")
        if it.get("confidence") not in CONFIDENCE:
            errs.append(f"{tag}: `confidence` must be one of {', '.join(CONFIDENCE)}")
        critic = it.get("critic")
        if isinstance(critic, dict) and critic.get("verdict") == "drop":
            errs.append(f"{tag}: critic verdict is drop; move it to insights_dropped.json")
    return errs


# ---------- the critic's own file (critic.json) ----------

PAD = 5.0   # a sheet shows its possession from about 1 s before the start to 3 s after the end


def insights_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sheet_windows(review: Path) -> dict[str, tuple[float, float]]:
    """Sheet file name -> (start, end) of the possession it shows, from manifest.json."""
    m = _load(review / "manifest.json", [])
    out = {}
    for x in m if isinstance(m, list) else []:
        if isinstance(x, dict) and _num(x.get("start")) and _num(x.get("end")):
            for s in x.get("sheets") or []:
                out[str(s)] = (x["start"], x["end"])
    return out


def _inside(review: Path, rel: str) -> Path | None:
    p = (review / str(rel)).resolve()
    try:
        p.relative_to(review.resolve())
    except ValueError:
        return None
    return p if p.is_file() else None


def check_critic(review: Path, insights: Path | None = None, sign: bool = False) -> list[str]:
    """Errors in <review>/critic.json, the critic's own record (empty = valid). It must give every insight in
    insights.json a keep|revise verdict and every insight in insights_dropped.json a drop verdict; each verdict lists
    the files it `reopened` (paths inside the review folder that exist; at least one), and the re-opened sheets
    (manifest.json) must cover every evidence time of a kept or revised insight. A `critic` field left in
    insights.json must agree with critic.json. Unless `sign` (the checks run before signing), `insights_sha256` must
    equal the hash of insights.json: an edit after the critic signed sends it back to the critic."""
    review = Path(review)
    ip = Path(insights) if insights else review / "insights.json"
    cp = review / "critic.json"
    if not cp.exists():
        return [f"{cp.name} not found: the critic subagent writes it (prompts/coach_critic.md) and signs it with "
                f"`coach-insights critic --review <review>`; a verdict inside insights.json alone no longer counts"]
    try:
        crit = json.loads(cp.read_text(encoding="utf8"))
        items = json.loads(ip.read_text(encoding="utf8"))
        dropped = _load(review / "insights_dropped.json", [])
    except (OSError, ValueError) as ex:
        return [f"critic check: cannot read the files ({ex})"]
    verdicts = crit.get("verdicts") if isinstance(crit, dict) else None
    if not isinstance(verdicts, list):
        return [f"{cp.name}: needs {{\"verdicts\": [{{id, verdict, note, reopened}}, ...]}}"]
    errs, by_id = [], {}
    for v in verdicts:
        if not isinstance(v, dict) or not v.get("id"):
            errs.append(f"{cp.name}: verdict without an id: {v!r}")
            continue
        if v["id"] in by_id:
            errs.append(f"{cp.name}: two verdicts for {v['id']}")
        by_id[v["id"]] = v
        if v.get("verdict") not in VERDICTS:
            errs.append(f"{cp.name} {v['id']}: verdict must be keep|revise|drop")
        if not str(v.get("note") or "").strip():
            errs.append(f"{cp.name} {v['id']}: `note` (what was checked) is empty")
        reo = v.get("reopened")
        if not isinstance(reo, list) or not reo:
            errs.append(f"{cp.name} {v['id']}: `reopened` must list the sheets the critic re-opened; a verdict "
                        f"without re-opened evidence does not count")
            v["reopened"] = []
        for r in v["reopened"]:
            if _inside(review, r) is None:
                errs.append(f"{cp.name} {v['id']}: reopened {r!r} is not a file inside the review folder")
    windows = _sheet_windows(review)
    items = items if isinstance(items, list) else []
    for it in items:
        if not isinstance(it, dict):
            continue
        iid, v = it.get("id"), by_id.get(it.get("id"))
        if v is None:
            errs.append(f"{iid}: no verdict in {cp.name}")
            continue
        if v.get("verdict") == "drop":
            errs.append(f"{iid}: {cp.name} says drop; move it to insights_dropped.json")
            continue
        own = it.get("critic")
        if isinstance(own, dict) and own.get("verdict") not in (None, v.get("verdict")):
            errs.append(f"{iid}: insights.json says critic.verdict {own.get('verdict')} but {cp.name} says "
                        f"{v.get('verdict')}")
        seen = [windows[str(r)] for r in v["reopened"] if str(r) in windows]
        for e in it.get("evidence") or []:
            t = e.get("t") if isinstance(e, dict) else None
            if _num(t) and not any(a - PAD <= t <= b + PAD for a, b in seen):
                errs.append(f"{iid}: evidence time {t} is on no sheet the critic re-opened (add the sheet to "
                            f"`reopened` after checking it)")
    for it in dropped if isinstance(dropped, list) else []:
        iid = it.get("id") if isinstance(it, dict) else None
        if by_id.get(iid, {}).get("verdict") != "drop":
            errs.append(f"insights_dropped.json {iid}: no drop verdict in {cp.name}")
    dropped_ids = {it.get("id") for it in dropped if isinstance(it, dict)} if isinstance(dropped, list) else set()
    kept_ids = {it.get("id") for it in items if isinstance(it, dict)}
    for iid, v in by_id.items():
        if v.get("verdict") == "drop" and iid not in dropped_ids and iid not in kept_ids:
            errs.append(f"{cp.name} {iid}: dropped but not in insights_dropped.json")
    if not sign and not errs and crit.get("insights_sha256") != insights_hash(ip):
        errs.append("insights.json changed after the critic signed it, or critic.json is not signed: the critic "
                    "re-checks and runs `coach-insights critic --review <review>`")
    return errs


def _load(p: Path, default=None):
    return json.loads(p.read_text(encoding="utf8")) if p.exists() else default


def number_sources(review: Path, official: Path | None = None) -> dict:
    """Files an insight's numbers may cite by prefix: official (official.json in the review folder or the run
    folder above it, or `official`), plusminus and pm_<N> (in the review folder). Missing files map to None."""
    review = Path(review)
    if official is None:
        official = next((p for p in (review / "official.json", review.parent / "official.json") if p.exists()), None)
    out = {"official": _load(Path(official)) if official else None,
           "plusminus": _load(review / "plusminus.json")}
    out.update({p.stem: _load(p) for p in review.glob("pm_*.json")})
    return out


def roster(official: dict | None) -> set[str]:
    """Our jerseys in the official box score (empty when unknown)."""
    players = (official or {}).get("players", {})
    return {str(k) for k in (players.get("us") or {})} if isinstance(players, dict) else set()


def check_review(review: Path, kb: Path = KB, insights: Path | None = None, critic: bool = True,
                 official: Path | None = None) -> list[str]:
    """validate_insights over a review folder's files, then (critic=True) check_critic: the `check` subcommand and
    the run steps `insights` (critic=False) and `critic` use this."""
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
    src = number_sources(review, official)
    errs = validate_insights(items, load_trips(review), kb_slugs(kb), _load(review / "summary.json", {}),
                             _load(review / "features.json"), sources=src, roster=roster(src["official"]))
    if critic and not errs:
        errs = check_critic(review, ip)
    return errs


def sign_critic(review: Path, kb: Path = KB, insights: Path | None = None) -> list[str]:
    """Check insights.json and critic.json (all but the signature); when clean, write the insights hash into
    critic.json. Returns the errors (empty = signed)."""
    review = Path(review)
    ip = Path(insights) if insights else review / "insights.json"
    errs = check_review(review, kb, insights, critic=False) or check_critic(review, ip, sign=True)
    if not errs:
        cp = review / "critic.json"
        crit = json.loads(cp.read_text(encoding="utf8"))
        crit["insights_sha256"] = insights_hash(ip)
        cp.write_text(json.dumps(crit, ensure_ascii=False, indent=1), encoding="utf8")
    return errs


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
    c = sub.add_parser("check", help="validate <review>/insights.json and the signed critic.json; exit 1 with the "
                                     "error list")
    c.add_argument("--review", required=True)
    c.add_argument("--kb", default=str(KB))
    c.add_argument("--insights", help="default: <review>/insights.json")
    c.add_argument("--official", help="official.json (default: in the review folder or the run folder above it)")
    c.add_argument("--no-critic", action="store_true", help="the writer's check: skip critic.json")
    s = sub.add_parser("critic", help="the critic's step: check insights.json + critic.json, then sign critic.json")
    s.add_argument("--review", required=True)
    s.add_argument("--kb", default=str(KB))
    s.add_argument("--insights", help="default: <review>/insights.json")
    b = sub.add_parser("ab", help="blind A/B rating sheet: memo conclusions vs insights.json")
    b.add_argument("--review", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--old-report", help="a finished README.md whose conclusion/practice sections join the memo set")
    b.add_argument("--insights", help="default: <review>/insights.json")
    b.add_argument("--seed", type=int)
    b.add_argument("--cap", type=int, default=450, help="max characters per item (both sets)")
    a = ap.parse_args(argv)
    if a.cmd in ("check", "critic"):
        if a.cmd == "check":
            errs = check_review(Path(a.review), Path(a.kb), a.insights, critic=not a.no_critic,
                                official=Path(a.official) if a.official else None)
        else:
            errs = sign_critic(Path(a.review), Path(a.kb), a.insights)
        for e in errs:
            print(e)
        if errs:
            sys.exit(f"coach-insights {a.cmd}: {len(errs)} error(s)")
        print(f"coach-insights {a.cmd}: PASS" + (" (critic.json signed)" if a.cmd == "critic" else ""))
        return 0
    key = build_ab(Path(a.review), Path(a.out), a.old_report, a.seed, a.cap, a.insights)
    print(f"wrote {a.out} ({key['items_per_set']} items per set); key in "
          f"{Path(a.out).with_name(Path(a.out).stem + '.key.json')} (do not show it to the rater)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
