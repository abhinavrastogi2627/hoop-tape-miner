"""One personal training session end to end: phone videos -> session page, explained video, next-session plan.

usage: hoop-tape-miner train <phone video> [<phone video> ...] [--player 17] [--date D] [--name N] [--plan TEXT]
       hoop-tape-miner train <session folder> [--status] [--dry] [--until STEP] [--redo STEP] [--publish]

Videos start a new session (`train-new`), a session folder resumes one. Like `run` for games: done steps are
skipped, command steps run (long ones log to <workspace>/logs/), and the run stops with exit 3 at the first agent
step whose output is missing, printing what to do. Deliverables: <session>/index.html (bilingual, narration,
clips; published as a private link with --publish, never on the team hub), film.<lang>.mp4 (send it yourself)
and plan.json, whose targets the next session checks.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import run as R
from . import training as T
from . import workspace


class Session(R.Game):
    """A training session folder, driven by run.drive with TRAIN_STEPS."""

    @property
    def gj(self) -> Path:
        return self.folder / "session.json"

    @property
    def run(self) -> Path:
        return T.session_path(self.folder, self.game, "run", "run")

    @property
    def video(self) -> Path | None:
        return T.session_path(self.folder, self.game, "video", "session.mp4")

    @property
    def review(self) -> Path:
        return self.run / "train_review"

    def reports(self) -> list[Path]:
        return [self.folder]

    @classmethod
    def load(cls, folder: Path) -> "Session":
        if not T.is_session(folder):
            sys.exit(f"{folder / 'session.json'} not found: start with `hoop-tape-miner train <phone videos>`")
        langs = tuple(workspace.profile().get("languages") or R.LANGS)
        return cls(Path(folder), T.load_session(folder), langs)

    def fill(self, how: str) -> str:
        return how.format(folder=self.folder, sj=self.gj, run=self.run, review=self.review, video=self.video,
                          langs=", ".join(self.langs), player=self.game.get("player"))

    def finished(self):
        print(f"[train] done. Page: {self.folder / 'index.html'}")
        print("[train] explained video (send it yourself, it is not published): "
              + ", ".join(str(self.folder / f"film.{l}.mp4") for l in self.langs))
        print(f"[train] next session's targets: {self.folder / 'plan.json'}")


def review_done(g: Session) -> bool:
    briefs = {p.stem.removeprefix("brief_") for p in g.review.glob("brief_part*.md")}
    done = {p.stem.removeprefix("review_") for p in g.review.glob("review_part*.json")}
    return bool(briefs) and briefs <= done


def summary_done(g: Session) -> bool:
    return R._newer(g.folder / "summary.json", *g.review.glob("review_part*.json"))


def report_done(g: Session) -> bool:
    return all((g.folder / n).exists() for n in ("README.md", "README.en.md", "plan.json"))


TRAIN_STEPS = [
    R.Step("video", "agent", lambda g: bool(g.video and g.video.exists()),
           how="session.json `video` does not point to a file: start the session with `hoop-tape-miner train <phone "
               "videos>`, or point `video` in {sj} to the joined session video."),
    R.Step("scan", "cmd", lambda g: (g.run / "reps.json").exists(),
           lambda g: [["train-scan", str(g.folder)]], long=True),
    R.Step("rim-probe", "cmd", lambda g: (g.review / "rim_probe.jpg").exists() or g.game.get("rim_checked") is True,
           lambda g: [["train-sheets", str(g.folder), "--probe"]]),
    R.Step("rim", "agent", lambda g: g.game.get("rim_checked") is True,
           how="Rim boxes (playbook, training step 3): view {review}/rim_probe.jpg (four frames across the session, "
               "grid lines every 0.1 of the frame). In {sj} set `rim` to the rim's box as frame fractions, e.g. "
               '[{{"from": "00:00", "box": [0.47, 0.18, 0.06, 0.03]}}] (x, y = top-left, w, h; add an entry with a '
               "later `from` when the camera moved), or [] when no rim is in view; then set \"rim_checked\": true."),
    R.Step("sheets", "cmd", lambda g: (g.review / "manifest.json").exists() and any(g.review.glob("brief_part*.md")),
           lambda g: [["train-sheets", str(g.folder)]], long=True),
    R.Step("film-review", "agent", review_done,
           how="Film review (playbook, training step 5): launch one subagent per {review}/brief_part<N>.md, at most 3 "
               "at once; each writes review_part<N>.json and memo_part<N>.md there and replies in a few lines. Do not "
               "read the sheets yourself. Re-run a part whose json does not parse or misses candidate ids."),
    R.Step("summary", "cmd", summary_done, lambda g: [["train-summary", str(g.folder)]]),
    R.Step("report", "agent", report_done,
           how="Write the session report (playbook, training step 7, prompts/training_report.md): {folder}/README.md "
               "(Chinese) and README.en.md from {folder}/facts.md, the memos in {review} and the figures, with clip "
               "markers on the key reps; and {folder}/plan.json, the next session's drills with checkable targets."),
    R.Step("clips", "cmd", R.clips_done, lambda g: [["clips", str(g.folder), "--video", str(g.video)]]),
    R.Step("listen-script", "agent", lambda g: all((g.folder / f"listen.{l}.md").exists() for l in g.langs),
           how="Write the narration scripts {folder}/listen.<lang>.md for {langs} (prompts/narration.md; for a "
               "training session: what went well, what did not, and next session's plan, 2-3 minutes)."),
    R.Step("narrate", "cmd", R.listen_done, lambda g: [["narrate", str(g.folder)]]),
    R.Step("html", "cmd", R.html_done, lambda g: [["html", str(g.folder)]]),
    R.Step("qa", "agent", R.qa_done,
           how="QA: have the browser-check subagent serve {folder} over http and check the page in both languages, "
               "the audio and every clip. Write the result to {folder}/qa.md, first word PASS when it passes."),
    R.Step("publish", "cmd", R.published, lambda g: [["publish", str(g.folder), "--deploy"]]),
    R.Step("film-script", "agent", lambda g: all((g.folder / f"film.{l}.md").exists() for l in g.langs),
           how="Write the explained-video scripts {folder}/film.<lang>.md for {langs} from the finished report "
               "(prompts/film.md, training notes in prompts/training_report.md); check them with "
               "`hoop-tape-miner film {folder} --dry`."),
    R.Step("film", "cmd", R.film_done, lambda g: [["film", str(g.folder), "--video", str(g.video)]], long=True),
]
NAMES = [s.name for s in TRAIN_STEPS]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner train", description=__doc__.splitlines()[0])
    ap.add_argument("target", nargs="+", help="phone video file(s) of one workout, or a session folder")
    ap.add_argument("--player", help="new session: player number or slug (default team.json focus_player)")
    ap.add_argument("--date", help="new session: date YYYY-MM-DD (default: recording date)")
    ap.add_argument("--name", help="new session: player display name")
    ap.add_argument("--plan", default="", help="new session: what you meant to train")
    ap.add_argument("--status", action="store_true", help="list every step and whether it is done")
    ap.add_argument("--dry", action="store_true", help="print the next command instead of running it")
    ap.add_argument("--until", choices=NAMES, help="stop after this step")
    ap.add_argument("--redo", choices=NAMES, help="run this step again even if its output exists")
    ap.add_argument("--publish", action="store_true", help="also deploy the page (publish --deploy) at the end")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles: never die on a non-ASCII path or name
        sys.stdout.reconfigure(errors="replace")
    first = Path(a.target[0])
    if len(a.target) == 1 and first.is_dir():
        folder = first
    else:
        from . import train_new
        player = a.player or workspace.profile().get("focus_player")
        if not player:
            ap.error("--player is required when team.json has no focus_player")
        folder = train_new.create([Path(v) for v in a.target], str(player), a.date, a.name, a.plan)
    g = Session.load(folder)
    if a.status:
        for s in TRAIN_STEPS:
            print(f"  {'done' if s.done(g) else '----'}  {s.name:13s} {s.kind}")
        return
    sys.exit(R.drive(g, a.until, a.redo, a.publish, a.dry, steps=TRAIN_STEPS))


if __name__ == "__main__":
    main()
