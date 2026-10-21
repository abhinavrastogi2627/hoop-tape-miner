"""Film-review trip schema v2: validation, migration from v1 free text, and the `coach-check` stage.

usage: hoop-tape-miner coach-check --review <run>/review_v1 [--migrate <run>/review_v2m]
Validates every coach_part*.json in --review and exits 1 with the error list when a trip is invalid. With --migrate,
writes v1 parts as v2 into the new folder (part*.json, manifest.json, lineup_intervals.json, briefs, memos and notes
are copied along; trip times missing in v1 are taken from part*.json), then validates the new folder.

v2 trip = the v1 checklist fields, plus `schema: 2`, `t0`/`t1`, `result` from RESULTS, and
  shot:  null | {t, shooter, made: bool|null, points: 2|3|null, zone, type, contested}
  fts:   null | {shooter, made, att}
  foul:  null | {t, by_team, by, on, type, cause, led_to}
  evidence: {field: [video seconds]} for result, shot, foul (and optionally fts, coach_note).
Optional (older reviews without them stay valid): `transition`: true | false | null (the trip attacked before the
defence was set), `turnover_kind`: "live" | "dead" | null (only with result turnover: live = the defence gained the
ball in play, e.g. a steal; dead = the ball went dead, e.g. out of bounds, travel, offensive foul).
Jerseys are strings of digits or null; anything uncertain goes into a *_note field, never into the jersey.
Migration never drops information: the original text stays in result_v1 / shooter_note / by_note / *_v1.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import sys
from pathlib import Path

from .coach_eval import foul_side, jersey, trip_times

RESULTS = ("made2", "made3", "missed", "turnover", "foul_ft", "foul_side", "dead_ball", "end_period", "unclear")
OFFENCE = ("us", "them", "none")
TEAMS = ("us", "them")
CONFIDENCE = ("high", "medium", "low")
SHOT_TYPES = ("layup", "floater", "pullup_mid", "catch_shoot_mid", "three_catch", "three_pullup", "post", "putback")
ZONES = ("rim", "paint_non_rim", "midrange", "three")
CONTESTED = ("open", "contested", "heavily_contested")
FOUL_TYPES = ("reach_in", "shooting_on_drive", "shooting_on_jumper", "block_charge", "over_the_back", "loose_ball",
              "off_ball", "unclear")
LED_TO = ("1 FT", "2 FT", "3 FT", "side-out", "unclear")
TURNOVER_KINDS = ("live", "dead")
EVIDENCE_FIELDS = ("result", "shot", "fts", "foul", "coach_note")
COPY = ("part*.json", "manifest.json", "lineup_intervals.json", "brief_part*.md", "memo_part*.md", "notes_part*.txt")
_JERSEY = re.compile(r"^\d{1,2}$")


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _enum(errs: list, where: str, v, allowed, nullable=True):
    if v is None and nullable:
        return
    if v not in allowed:
        errs.append(f"{where} {v!r} not in {'|'.join(map(str, allowed))}" + ("|null" if nullable else ""))


def _jersey_ok(errs: list, where: str, v):
    if v is not None and not (isinstance(v, str) and _JERSEY.match(v)):
        errs.append(f"{where} {v!r} must be a jersey string like \"13\" or null (put doubts in a *_note field)")


def validate_trip(trip: dict) -> list[str]:
    """Errors for one v2 trip; [] when valid. An unclear trip with no shot, fts or foul is valid."""
    if not isinstance(trip, dict):
        return ["trip is not an object"]
    e: list[str] = []
    if trip.get("schema") != 2:
        e.append("schema must be 2 (v1 parts: run coach-check --migrate)")
    if "pid" not in trip:
        e.append("pid missing")
    t0, t1 = trip.get("t0"), trip.get("t1")
    for k, v in (("t0", t0), ("t1", t1)):
        if v is not None and not _num(v):
            e.append(f"{k} {v!r} must be seconds or null")
    if _num(t0) and _num(t1) and t0 > t1:
        e.append(f"t0 {t0} after t1 {t1}")
    _enum(e, "offence", trip.get("offence"), OFFENCE, nullable=False)
    res = trip.get("result")
    _enum(e, "result", res, RESULTS, nullable=False)
    _enum(e, "confidence", trip.get("confidence"), CONFIDENCE, nullable=False)
    if trip.get("transition") is not None and not isinstance(trip.get("transition"), bool):
        e.append(f"transition {trip.get('transition')!r} must be true, false or null")
    _enum(e, "turnover_kind", trip.get("turnover_kind"), TURNOVER_KINDS)
    if trip.get("turnover_kind") is not None and res != "turnover":
        e.append(f"turnover_kind only goes with result turnover, not {res}")

    shot, fts, foul = trip.get("shot"), trip.get("fts"), trip.get("foul")
    if shot is not None:
        if not isinstance(shot, dict):
            e.append("shot must be an object or null")
            shot = None
        else:
            if shot.get("t") is not None and not _num(shot.get("t")):
                e.append("shot.t must be seconds or null")
            _jersey_ok(e, "shot.shooter", shot.get("shooter"))
            _enum(e, "shot.made", shot.get("made"), (True, False))
            _enum(e, "shot.points", shot.get("points"), (2, 3))
            _enum(e, "shot.zone", shot.get("zone"), ZONES)
            _enum(e, "shot.type", shot.get("type"), SHOT_TYPES)
            _enum(e, "shot.contested", shot.get("contested"), CONTESTED)
    if fts is not None:
        if not isinstance(fts, dict):
            e.append("fts must be an object or null")
            fts = None
        else:
            _jersey_ok(e, "fts.shooter", fts.get("shooter"))
            m, a = fts.get("made"), fts.get("att")
            if not (isinstance(m, int) and isinstance(a, int) and 0 <= m <= a and 1 <= a <= 3):
                e.append(f"fts made/att {m!r}/{a!r} must be integers with 0 <= made <= att <= 3")
    if foul is not None:
        if not isinstance(foul, dict):
            e.append("foul must be an object or null")
            foul = None
        else:
            if foul.get("t") is not None and not _num(foul.get("t")):
                e.append("foul.t must be seconds or null")
            _enum(e, "foul.by_team", foul.get("by_team"), TEAMS)
            _jersey_ok(e, "foul.by", foul.get("by"))
            _jersey_ok(e, "foul.on", foul.get("on"))
            _enum(e, "foul.type", foul.get("type"), FOUL_TYPES, nullable=False)
            _enum(e, "foul.led_to", foul.get("led_to"), LED_TO)

    # consistency between result and the objects
    if res in ("made2", "made3"):
        if not shot or shot.get("made") is not True or shot.get("points") != int(res[-1]):
            e.append(f"result {res} needs shot.made true and shot.points {res[-1]}")
    elif shot and shot.get("made") is True:
        e.append(f"shot.made true but result is {res}")
    if res == "missed" and not shot:
        e.append("result missed needs a shot object (made false)")
    if res == "foul_ft" and not fts:
        e.append("result foul_ft needs fts {shooter, made, att}")
    if fts and res not in ("made2", "made3", "foul_ft"):
        e.append(f"fts only go with made2/made3 (and-one) or foul_ft, not {res}")
    if res == "foul_side" and not foul:
        e.append("result foul_side needs a foul object")
    if trip.get("offence") == "none" and res not in ("dead_ball", "end_period", "unclear"):
        e.append(f"offence none (dead ball) cannot have result {res}")

    ev = trip.get("evidence", {})
    if not isinstance(ev, dict):
        e.append("evidence must be an object {field: [video seconds]}")
        ev = {}
    for k, v in ev.items():
        if k not in EVIDENCE_FIELDS:
            e.append(f"evidence key {k!r} not in {'|'.join(EVIDENCE_FIELDS)}")
        elif not (isinstance(v, list) and all(_num(s) and s >= 0 for s in v)):
            e.append(f"evidence.{k} must be a list of video seconds")
    if "result_v1" not in trip:  # migrated v1 trips carry no evidence; new reviews must cite times
        need = [k for k, on in (("result", res not in ("unclear", None)), ("shot", bool(shot)), ("foul", bool(foul)))
                if on and not ev.get(k)]
        e += [f"evidence.{k} needs at least one video time" for k in need]
    return e


def validate_part(path: Path) -> list[str]:
    """Errors for one coach_part*.json, each prefixed with the file name and trip."""
    name = Path(path).name
    try:
        trips = json.loads(Path(path).read_text(encoding="utf8"))
    except (OSError, ValueError) as ex:
        return [f"{name}: not valid JSON ({ex})"]
    if not isinstance(trips, list) or not trips:
        return [f"{name}: must be a non-empty array of trips"]
    out = []
    for i, t in enumerate(trips):
        pid = t.get("pid") if isinstance(t, dict) else None
        out += [f"{name} trip {i} (pid {pid}): {err}" for err in validate_trip(t)]
    return out


# ---- migration -------------------------------------------------------------------------------------------------

def _points_from_zone(zone) -> int | None:
    return 3 if zone == "three" else 2 if zone in ("rim", "paint_non_rim", "midrange") else None


def _led_to(v) -> tuple[str | None, bool]:
    """(v2 value, changed)."""
    if v is None or v in LED_TO:
        return v, False
    s = str(v)
    m = re.match(r"\s*(\d)\s*FT", s, re.I)
    if m and m.group(1) in "123":
        return f"{m.group(1)} FT", True
    return ("side-out" if "side" in s.lower() else "unclear"), True


def _foul(trip_v1: dict, f) -> dict | None:
    if f is None or (isinstance(f, str) and f.strip().lower() in ("", "none", "null", "n/a")):
        return None
    if not isinstance(f, dict):
        return {"t": None, "by_team": None, "by": None, "on": None, "type": "unclear", "cause": None,
                "led_to": None, "by_note": str(f)}
    team, by = foul_side(dict(trip_v1, foul=f))
    out = {k: v for k, v in f.items() if k not in ("who",)}
    who = f.get("who", f.get("by"))
    out.update({"t": f.get("t") if _num(f.get("t")) else None, "by_team": team, "by": by,
                "on": jersey(f.get("on")), "cause": f.get("cause")})
    if who is not None and str(who) != str(by):
        out["by_note"] = str(who)
    if f.get("on") is not None and str(f.get("on")) != str(out["on"]):
        out["on_note"] = str(f.get("on"))
    if f.get("t") is not None and out["t"] is None:
        out["t_v1"] = f.get("t")
    typ = f.get("type")
    out["type"] = typ if typ in FOUL_TYPES else "unclear"
    if typ is not None and typ not in FOUL_TYPES:
        out["type_v1"] = typ
    out["led_to"], changed = _led_to(f.get("led_to"))
    if changed:
        out["led_to_v1"] = f.get("led_to")
    return out


def migrate_v1(trip: dict) -> dict:
    """v1 trip -> v2 trip. Free text is parsed into result/shot/fts/foul; every original text is kept alongside."""
    if trip.get("schema") == 2:
        return copy.deepcopy(trip)
    v1 = copy.deepcopy(trip)
    x = copy.deepcopy(trip)
    d = x.pop("defence", None)  # some reviewers nested the defence block; flatten it
    if isinstance(d, dict):
        if any(k in x and x[k] != v for k, v in d.items()):
            x["defence_v1"] = d
        for k, v in d.items():
            x.setdefault(k, v)
        v1.setdefault("foul", d.get("foul"))
    elif d is not None:
        x["defence_v1"] = d

    t0, t1 = trip_times(x)
    for k in ("start", "end", "t_start", "t_end"):
        x.pop(k, None)
    x["t0"], x["t1"] = t0, t1

    off = str(x.get("offence")).strip()
    low_off = off.lower()
    norm = "us" if low_off == "us" else "them" if low_off == "them" else \
        "us" if low_off.startswith("us ") else "them" if low_off.startswith("them ") else "none"
    if norm != off:
        x["offence_v1"] = x.get("offence")
    x["offence"] = norm

    raw = trip.get("result")
    s = "" if raw is None else str(raw).strip()
    low = s.lower()
    head = re.match(r"[a-z0-9_]+", low)
    head = head.group(0) if head else ""
    ft = re.search(r"FT\s*\(?\s*(\d)\s*/\s*(\d)", s, re.I)
    note = s[len(head):].strip()
    shooter_raw = x.get("scorer_or_shooter")
    shooter = jersey(shooter_raw)
    zone, styp, cont = x.get("shot_zone"), x.get("shot_type"), x.get("contested")

    def shot(made, points):
        return {"t": None, "shooter": shooter, "made": made, "points": points,
                "zone": zone if zone in ZONES else None, "type": styp if styp in SHOT_TYPES else None,
                "contested": cont if cont in CONTESTED else None}

    fts = {"shooter": shooter, "made": int(ft.group(1)), "att": int(ft.group(2))} if ft else None
    if fts and not (0 <= fts["made"] <= fts["att"] <= 3 and fts["att"] >= 1):
        fts = None
    x["shot"], x["fts"] = None, None
    if head in ("made2", "made3"):
        res = head
        x["shot"] = shot(True, int(head[-1]))
        x["fts"] = fts
        if ft and not fts:
            res = "unclear"
    elif head == "ft" or (head == "missed" and ft):
        res = "foul_ft" if fts else "unclear"
        x["fts"] = fts
        if head == "missed":
            x["shot"] = shot(False, _points_from_zone(zone))
    elif ft:  # free throws next to a result that cannot carry them: keep the text, do not guess
        res = "unclear"
    elif head == "missed":
        res = "missed"
        x["shot"] = shot(False, _points_from_zone(zone))
    elif head in ("turnover", "end_period"):
        res = head
    elif head in ("foul_no_ft", "foul_side"):
        res = "foul_side"
    elif head.startswith("dead_ball") or head == "timeout":
        res = "dead_ball"
    else:
        res = "unclear"
    if x["offence"] == "none" and res not in ("dead_ball", "end_period", "unclear"):
        res = "unclear"
    x["result"] = res
    x["result_v1"] = raw
    known = head in ("made2", "made3", "missed", "ft", "unclear", "turnover", "end_period", "foul_no_ft",
                     "foul_side", "timeout") or head.startswith("dead_ball")
    if (note if known else s):
        x["result_note"] = note if known else s
    if shooter_raw is not None and str(shooter_raw) != str(shooter):
        x["shooter_note"] = str(shooter_raw)

    x["foul"] = _foul(v1, v1.get("foul"))
    if res == "foul_side" and x["foul"] is None:
        x["foul"] = {"t": None, "by_team": None, "by": None, "on": None, "type": "unclear", "cause": None,
                     "led_to": "side-out"}
    conf = x.get("confidence")
    if conf not in CONFIDENCE:
        x["confidence"] = "low"
        if conf is not None:
            x["confidence_v1"] = conf
    ev = x.get("evidence")
    x["evidence"] = ev if isinstance(ev, dict) else {}
    if ev is not None and not isinstance(ev, dict):
        x["evidence_v1"] = ev
    x["schema"] = 2
    return x


# ---- CLI -------------------------------------------------------------------------------------------------------

def _possession_times(review: Path) -> dict:
    poss = {}
    for p in sorted(review.glob("part*.json")):
        d = json.loads(p.read_text(encoding="utf8"))
        for x in d if isinstance(d, list) else d.get("possessions", []):
            poss[x["pid"]] = (x["start"], x["end"])
    return poss


def migrate_dir(src: Path, out: Path) -> list[str]:
    """Write v2 coach_part*.json (and the files next to them) from src into out; returns read errors."""
    out.mkdir(parents=True, exist_ok=True)
    for pat in COPY:
        for p in src.glob(pat):
            shutil.copy2(p, out / p.name)
    poss = _possession_times(src)
    errs = []
    for p in sorted(src.glob("coach_part*.json")):
        try:
            trips = json.loads(p.read_text(encoding="utf8"))
        except ValueError as ex:
            errs.append(f"{p.name}: not valid JSON ({ex}); not migrated")
            continue
        new = []
        for t in trips:
            m = migrate_v1(t)
            if m.get("t0") is None and m.get("pid") in poss:
                m["t0"], m["t1"] = poss[m["pid"]]
                m["times_from"] = "part"
            new.append(m)
        (out / p.name).write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf8")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner coach-check")
    ap.add_argument("--review", required=True, help="folder with coach_part*.json")
    ap.add_argument("--migrate", metavar="OUTDIR", help="write v1 parts as v2 into OUTDIR, then validate OUTDIR")
    a = ap.parse_args(argv)
    folder = Path(a.review)
    errs = []
    if a.migrate:
        errs += migrate_dir(folder, Path(a.migrate))
        folder = Path(a.migrate)
    parts = sorted(folder.glob("coach_part*.json"))
    if not parts:
        errs.append(f"no coach_part*.json in {folder}")
    n = 0
    for p in parts:
        errs += validate_part(p)
        try:
            n += len(json.loads(p.read_text(encoding="utf8")))
        except (ValueError, TypeError):
            pass
    if errs:
        print(f"coach-check: {len(errs)} error(s) in {folder}")
        print("\n".join(f"- {e}" for e in errs))
        sys.exit(1)
    print(f"coach-check ok: {len(parts)} part(s), {n} trips valid (schema 2) in {folder}")


if __name__ == "__main__":
    main()
