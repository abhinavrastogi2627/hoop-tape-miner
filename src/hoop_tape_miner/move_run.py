"""One movement session end to end: clips of running, layups and stops -> movement page, explained video, plan.

usage: hoop-tape-miner move <movement folder> [--status] [--dry] [--until STEP] [--redo STEP] [--publish]
       hoop-tape-miner move --spec segments.json [--player 17] [--date D] [--name N] [--plan TEXT] [--look TEXT]

A spec starts a new session (`move-new`), a folder resumes one. Like `train`: done steps are skipped, command steps
run (long ones log to <workspace>/logs/), and the run stops with exit 3 at the first agent step whose output is
missing, printing what to do. Deliverables: <session>/index.html (bilingual, narration, clips from the skeleton
overlay reel; a private link with --publish, never on the team hub), film.<lang>.mp4 (send it yourself) and
plan.json (drills, re-tests, fuel and recovery).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import movement as M
from . import pipeline as P
from . import workspace

SCAN_KEYS = ("id", "source", "from", "to", "kind", "view", "crop", "follow")   # segment fields move-scan reads


class Session(P.Session):
    """A movement session folder (movement.json), driven by pipeline.drive with MOVE_STEPS."""
    JSON = "movement.json"
    VIDEO = "reel.mp4"
    REVIEW = "move_review"
    LABEL = "move"
    PLAN = "drills, re-tests, fuel and recovery"

    @property
    def overlay(self) -> Path:
        return self.path("video_overlay", "reel.overlay.mp4") if self.game.get("video_overlay") \
            else self.video.with_name("reel.overlay.mp4")

    def fill_values(self) -> dict:
        return dict(super().fill_values(), mj=self.gj, overlay=self.overlay)

    @classmethod
    def load(cls, folder: Path) -> "Session":
        if not M.is_movement(folder):
            sys.exit(f"{folder / 'movement.json'} not found: start with `hoop-tape-miner move --spec segments.json`")
        return cls(Path(folder), M.load(folder), P.profile_langs())


def side_segments(g: Session) -> list[str]:
    return [s["id"] for s in g.game.get("segments", []) if s["view"] == "side"]


def scan_done(g: Session) -> bool:
    return (g.run / "gait.json").exists() and all((g.run / "gait" / f"{s['id']}.json").exists()
                                                  for s in g.game.get("segments", []))


def crowded_segments(g: Session) -> list[str]:
    """Segments where move-scan saw more than one person (gait/<id>.json "crowded")."""
    out = []
    for s in g.game.get("segments", []):
        p = g.run / "gait" / f"{s['id']}.json"
        if p.exists() and json.loads(p.read_text(encoding="utf8")).get("crowded"):
            out.append(s["id"])
    return out


def who_done(g: Session) -> bool:
    picked = {s["id"] for s in g.game.get("segments", []) if (s.get("who") or {}).get("box") is not None}
    from . import move_scan as MS
    if any(s["id"] in picked and not MS.pick_fresh(g.run, s, g.game) for s in g.game.get("segments", [])):
        return False  # picks in movement.json the track was not chosen with: move-scan has to run again
    return g.game.get("who_checked") is True or set(crowded_segments(g)) <= picked


def seg_npzs(g: Session) -> list[Path]:
    from . import move_sheets as MSh
    return MSh.seg_npzs(g.run, g.game)


def sheets_done(g: Session) -> bool:
    """Sheets, briefs and the overlay reel exist and none is older than a track move-scan picked again."""
    segs = seg_npzs(g)
    return (P.newer(g.review / "manifest.json", *segs) and P.newer(g.overlay, *segs)
            and any(g.review.glob("brief_*.md")))


def labels_done(g: Session) -> bool:
    return not side_segments(g) or (g.game.get("labels_checked") is True and (g.review / "labels.json").exists())


def review_done(g: Session) -> bool:
    briefs = {p.stem.removeprefix("brief_") for p in g.review.glob("brief_*.md")}
    done = {p.stem.removeprefix("review_") for p in g.review.glob("review_*.json")}
    return bool(briefs) and briefs <= done


def summary_inputs(g: Session) -> list[Path]:
    return [*sorted(g.review.glob("review_*.json")), g.review / "labels.json", g.run / "gait.json"]


def summary_done(g: Session) -> bool:
    return P.newer(g.folder / "summary.json", *summary_inputs(g))


def report_done(g: Session) -> bool:
    return all((g.folder / n).exists() for n in (*(P.readme(l) for l in g.langs), "plan.json"))


MOVE_STEPS = [
    P.Step("video", "agent", lambda g: bool(g.video and g.video.exists()),
           how="movement.json `video` does not point to a file: start the session with `hoop-tape-miner move-new "
               "--spec segments.json` (playbook, movement sessions), or rebuild the reel with `move-new --into {folder}`."),
    # params: the segment fields move-scan reads (not `who` / `more`: the who step's --repick handles those)
    P.Step("scan", "cmd", scan_done, lambda g: [["move-scan", str(g.folder)]], long=True,
           inputs=lambda g: [g.video],
           params=lambda g: {"segments": [{k: s.get(k) for k in SCAN_KEYS} for s in g.game.get("segments", [])]},
           again=("--force",)),        # its pose cache is kept per segment id: a changed segment needs --force
    P.Step("who", "agent", who_done,
           how="Identity check (playbook, movement step 2): launch one subagent with movement.json `look` to open every "
               "{run}/move_review/who_<id>.jpg (each person boxed and numbered, three frames captioned with source "
               "time) and fill {run}/move_review/who.json: per segment \"t\" = the caption time of the clearest frame "
               "and \"box\" = the player's number in that frame (null when the player is in no frame). Then run "
               "`hoop-tape-miner move-scan {folder} --repick` and `move-sheets {folder} --force`. When the rest "
               "cannot be identified, set \"who_checked\": true in {mj}."),
    P.Step("sheets", "cmd", sheets_done, lambda g: [["move-sheets", str(g.folder)]], long=True,
           inputs=lambda g: [*seg_npzs(g), g.run / "gait.json"], again=("--force",)),
    P.Step("labels", "agent", labels_done,
           how="Label check (playbook, movement step 4): launch one subagent to open every {review}/strip_<id>.jpg "
               "(frames numbered by source time) and write {review}/labels.json = "
               '{{"<id>": {{"window": [first tile time, last tile time], "contacts": [{{"foot": "L", "on": 12.345}}], '
               '"takeoff": 12.9 or null}}}} with every frame where a foot first touches the floor; at least 10 '
               "segments when there are that many. Then set \"labels_checked\": true in {mj}. Metrics whose check "
               "fails are not shown."),
    P.Step("review", "agent", review_done,
           how="Film review (playbook, movement step 5): launch one subagent per {review}/brief_<g>.md, at most 3 at "
               "once; each writes review_<g>.json and memo_<g>.md there and replies in a few lines. Do not read the "
               "sheets yourself. Re-run a group whose json does not parse or misses segment ids. Where a reviewer "
               "lists `wrong_person` stretches or sets identity_ok false, add {{\"t\": \"mm:ss.s\", \"box\": null}} "
               "items at those times to the segment's \"more\" list in {run}/move_review/who.json, run `move-scan "
               "{folder} --repick` (writes who_<id>.more.jpg), have a subagent fill each box (-1 when the player has no box of his own in that tile), run `move-scan --repick` "
               "and `move-sheets --force` again and review that group again."),
    P.Step("summary", "cmd", summary_done, lambda g: [["move-summary", str(g.folder)]], inputs=summary_inputs),
    P.Step("report", "agent", report_done,
           how="Write the movement report (playbook, movement step 7, prompts/movement_report.md): {readmes} "
               "in {folder}, from {folder}/facts.md, the memos in {review}, the figures and "
               "prompts/movement_kb.md + prompts/fuel_recovery_kb.md, with clip markers on the overlay reel; and "
               "{folder}/plan.json (focus, drills, tests, nutrition, recovery)."),
    *P.tail_steps(
        lambda g: g.overlay,
        listen_how="Write the narration scripts {folder}/listen.<lang>.md for {langs} (prompts/narration.md; for a "
                   "movement session: the verdict, the two or three changes that matter most, how to train, eat and "
                   "recover, 3-4 minutes).",
        qa_how="QA: have the browser-check subagent serve {folder} over http and check the page in both languages, "
               "the audio and every clip. Write the result to {folder}/qa.md, first word PASS when it passes.",
        film_script_how="Write the explained-video scripts {folder}/film.<lang>.md for {langs} from the finished "
                        "report (prompts/film.md, movement notes in prompts/movement_report.md; times are on the "
                        "overlay reel {overlay}); check them with `hoop-tape-miner film {folder} --dry --video "
                        "{overlay}`."),
]
NAMES = [s.name for s in MOVE_STEPS]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner move", description=__doc__.splitlines()[0])
    ap.add_argument("folder", nargs="?", help="movement session folder (with movement.json)")
    ap.add_argument("--spec", help="new session: JSON segments file (see move-new)")
    ap.add_argument("--player", help="new session: player number or slug (default team.json focus_player)")
    ap.add_argument("--date", help="new session: date YYYY-MM-DD")
    ap.add_argument("--name", help="new session: player display name")
    ap.add_argument("--plan", default="", help="new session: what the session is for")
    ap.add_argument("--look", default="", help="new session: what the player wears")
    P.add_drive_args(ap, NAMES, pages="page")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles: never die on a non-ASCII path or name
        sys.stdout.reconfigure(errors="replace")
    if a.spec:
        from . import move_new
        segs, extra = move_new.read_spec(Path(a.spec))
        player = a.player or extra.get("player") or workspace.profile().get("focus_player")
        if not player:
            ap.error("--player is required when team.json has no focus_player")
        folder = move_new.create(segs, str(player), a.date or extra.get("date"), a.name or extra.get("name"),
                                 a.plan or extra.get("plan", ""), a.look or extra.get("look", ""))
    elif a.folder:
        folder = Path(a.folder)
    else:
        ap.error("give a movement folder or --spec")
    g = Session.load(folder)
    if a.status:
        P.print_status(g, MOVE_STEPS)
        return
    sys.exit(P.drive(g, MOVE_STEPS, a.until, a.redo, a.publish, a.dry))


if __name__ == "__main__":
    main()
