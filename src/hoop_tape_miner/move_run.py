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
from . import run as R
from . import workspace


class Session(R.Game):
    """A movement session folder, driven by run.drive with MOVE_STEPS."""

    @property
    def gj(self) -> Path:
        return self.folder / "movement.json"

    @property
    def run(self) -> Path:
        return M.path(self.folder, self.game, "run", "run")

    @property
    def video(self) -> Path | None:
        return M.path(self.folder, self.game, "video", "reel.mp4")

    @property
    def overlay(self) -> Path:
        return M.path(self.folder, self.game, "video_overlay", "reel.overlay.mp4") if self.game.get("video_overlay") \
            else self.video.with_name("reel.overlay.mp4")

    @property
    def review(self) -> Path:
        return self.run / "move_review"

    def reports(self) -> list[Path]:
        return [self.folder]

    @classmethod
    def load(cls, folder: Path) -> "Session":
        if not M.is_movement(folder):
            sys.exit(f"{folder / 'movement.json'} not found: start with `hoop-tape-miner move --spec segments.json`")
        langs = tuple(workspace.profile().get("languages") or R.LANGS)
        return cls(Path(folder), M.load(folder), langs)

    def fill(self, how: str) -> str:
        return how.format(folder=self.folder, mj=self.gj, run=self.run, review=self.review, video=self.video,
                          overlay=self.overlay, langs=", ".join(self.langs), player=self.game.get("player"),
                          qa=R.qa_hash(self))

    def finished(self):
        print(f"[move] done. Page: {self.folder / 'index.html'}")
        print("[move] explained video (send it yourself, it is not published): "
              + ", ".join(str(self.folder / f"film.{l}.mp4") for l in self.langs))
        print(f"[move] drills, re-tests, fuel and recovery: {self.folder / 'plan.json'}")


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


def sheets_done(g: Session) -> bool:
    """Sheets, briefs and the overlay reel exist and none is older than a track move-scan picked again."""
    from . import move_sheets as MSh
    segs = MSh.seg_npzs(g.run, g.game)
    return (R._newer(g.review / "manifest.json", *segs) and R._newer(g.overlay, *segs)
            and any(g.review.glob("brief_*.md")))


def labels_done(g: Session) -> bool:
    return not side_segments(g) or (g.game.get("labels_checked") is True and (g.review / "labels.json").exists())


def review_done(g: Session) -> bool:
    briefs = {p.stem.removeprefix("brief_") for p in g.review.glob("brief_*.md")}
    done = {p.stem.removeprefix("review_") for p in g.review.glob("review_*.json")}
    return bool(briefs) and briefs <= done


def summary_done(g: Session) -> bool:
    return R._newer(g.folder / "summary.json", *g.review.glob("review_*.json"), g.review / "labels.json",
                    g.run / "gait.json")


def report_done(g: Session) -> bool:
    return all((g.folder / n).exists() for n in ("README.md", "README.en.md", "plan.json"))


MOVE_STEPS = [
    R.Step("video", "agent", lambda g: bool(g.video and g.video.exists()),
           how="movement.json `video` does not point to a file: start the session with `hoop-tape-miner move-new "
               "--spec segments.json` (playbook, movement sessions), or rebuild the reel with `move-new --into {folder}`."),
    R.Step("scan", "cmd", scan_done, lambda g: [["move-scan", str(g.folder)]], long=True),
    R.Step("who", "agent", who_done,
           how="Identity check (playbook, movement step 2): launch one subagent with movement.json `look` to open every "
               "{run}/move_review/who_<id>.jpg (each person boxed and numbered, three frames captioned with source "
               "time) and fill {run}/move_review/who.json: per segment \"t\" = the caption time of the clearest frame "
               "and \"box\" = the player's number in that frame (null when the player is in no frame). Then run "
               "`hoop-tape-miner move-scan {folder} --repick` and `move-sheets {folder} --force`. When the rest "
               "cannot be identified, set \"who_checked\": true in {mj}."),
    R.Step("sheets", "cmd", sheets_done, lambda g: [["move-sheets", str(g.folder)]], long=True),
    R.Step("labels", "agent", labels_done,
           how="Label check (playbook, movement step 4): launch one subagent to open every {review}/strip_<id>.jpg "
               "(frames numbered by source time) and write {review}/labels.json = "
               '{{"<id>": {{"window": [first tile time, last tile time], "contacts": [{{"foot": "L", "on": 12.345}}], '
               '"takeoff": 12.9 or null}}}} with every frame where a foot first touches the floor; at least 10 '
               "segments when there are that many. Then set \"labels_checked\": true in {mj}. Metrics whose check "
               "fails are not shown."),
    R.Step("review", "agent", review_done,
           how="Film review (playbook, movement step 5): launch one subagent per {review}/brief_<g>.md, at most 3 at "
               "once; each writes review_<g>.json and memo_<g>.md there and replies in a few lines. Do not read the "
               "sheets yourself. Re-run a group whose json does not parse or misses segment ids. Where a reviewer "
               "lists `wrong_person` stretches or sets identity_ok false, add {{\"t\": \"mm:ss.s\", \"box\": null}} "
               "items at those times to the segment's \"more\" list in {run}/move_review/who.json, run `move-scan "
               "{folder} --repick` (writes who_<id>.more.jpg), have a subagent fill each box (-1 when the player has no box of his own in that tile), run `move-scan --repick` "
               "and `move-sheets --force` again and review that group again."),
    R.Step("summary", "cmd", summary_done, lambda g: [["move-summary", str(g.folder)]]),
    R.Step("report", "agent", report_done,
           how="Write the movement report (playbook, movement step 7, prompts/movement_report.md): {folder}/README.md "
               "(Chinese) and README.en.md from {folder}/facts.md, the memos in {review}, the figures and "
               "prompts/movement_kb.md + prompts/fuel_recovery_kb.md, with clip markers on the overlay reel; and "
               "{folder}/plan.json (focus, drills, tests, nutrition, recovery)."),
    R.Step("clips", "cmd", R.clips_done, lambda g: [["clips", str(g.folder), "--video", str(g.overlay)]]),
    R.Step("listen-script", "agent", lambda g: all((g.folder / f"listen.{l}.md").exists() for l in g.langs),
           how="Write the narration scripts {folder}/listen.<lang>.md for {langs} (prompts/narration.md; for a "
               "movement session: the verdict, the two or three changes that matter most, how to train, eat and "
               "recover, 3-4 minutes)."),
    R.Step("narrate", "cmd", R.listen_done, lambda g: [["narrate", str(g.folder)]]),
    R.Step("html", "cmd", R.html_done, lambda g: [["html", str(g.folder)]]),
    R.Step("qa", "agent", R.qa_done,
           how="QA: have the browser-check subagent serve {folder} over http and check the page in both languages, "
               "the audio and every clip. Write the result to {folder}/qa.md, first word PASS when it passes."
               + R.QA_STAMP),
    R.Step("publish", "cmd", R.published, lambda g: [["publish", str(g.folder), "--deploy"]]),
    R.Step("film-script", "agent", lambda g: all((g.folder / f"film.{l}.md").exists() for l in g.langs),
           how="Write the explained-video scripts {folder}/film.<lang>.md for {langs} from the finished report "
               "(prompts/film.md, movement notes in prompts/movement_report.md; times are on the overlay reel "
               "{overlay}); check them with `hoop-tape-miner film {folder} --dry --video {overlay}`."),
    R.Step("film", "cmd", R.film_done, lambda g: [["film", str(g.folder), "--video", str(g.overlay)]], long=True),
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
    ap.add_argument("--status", action="store_true", help="list every step and whether it is done")
    ap.add_argument("--dry", action="store_true", help="print the next command instead of running it")
    ap.add_argument("--until", choices=NAMES, help="stop after this step")
    ap.add_argument("--redo", choices=NAMES, help="run this step again even if its output exists")
    ap.add_argument("--publish", action="store_true", help="also deploy the page (publish --deploy) at the end")
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
        for s in MOVE_STEPS:
            print(f"  {'done' if s.done(g) else '----'}  {s.name:13s} {s.kind}")
        return
    sys.exit(R.drive(g, a.until, a.redo, a.publish, a.dry, steps=MOVE_STEPS))


if __name__ == "__main__":
    main()
