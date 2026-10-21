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
import sys
from pathlib import Path

from . import pipeline as P
from . import training as T
from . import workspace


class Session(P.Session):
    """A training session folder (session.json), driven by pipeline.drive with TRAIN_STEPS."""
    JSON = "session.json"
    VIDEO = "session.mp4"
    REVIEW = "train_review"
    LABEL = "train"
    PLAN = "next session's targets"

    def fill_values(self) -> dict:
        return dict(super().fill_values(), sj=self.gj)

    @classmethod
    def load(cls, folder: Path) -> "Session":
        if not T.is_session(folder):
            sys.exit(f"{folder / 'session.json'} not found: start with `hoop-tape-miner train <phone videos>`")
        return cls(Path(folder), T.load_session(folder), P.profile_langs())


def review_done(g: Session) -> bool:
    briefs = {p.stem.removeprefix("brief_") for p in g.review.glob("brief_part*.md")}
    done = {p.stem.removeprefix("review_") for p in g.review.glob("review_part*.json")}
    return bool(briefs) and briefs <= done


def summary_done(g: Session) -> bool:
    return P.newer(g.folder / "summary.json", *g.review.glob("review_part*.json"))


def report_done(g: Session) -> bool:
    return all((g.folder / n).exists() for n in (*(P.readme(l) for l in g.langs), "plan.json"))


TRAIN_STEPS = [
    P.Step("video", "agent", lambda g: bool(g.video and g.video.exists()),
           how="session.json `video` does not point to a file: start the session with `hoop-tape-miner train <phone "
               "videos>`, or point `video` in {sj} to the joined session video."),
    P.Step("scan", "cmd", lambda g: (g.run / "reps.json").exists(),
           lambda g: [["train-scan", str(g.folder)]], long=True,
           inputs=lambda g: [g.video], params=lambda g: {k: g.game.get(k) for k in ("seed", "follow")}),
    P.Step("rim-probe", "cmd", lambda g: (g.review / "rim_probe.jpg").exists() or g.game.get("rim_checked") is True,
           lambda g: [["train-sheets", str(g.folder), "--probe"]]),
    P.Step("rim", "agent", lambda g: g.game.get("rim_checked") is True,
           how="Rim boxes (playbook, training step 3): view {review}/rim_probe.jpg (four frames across the session, "
               "grid lines every 0.1 of the frame). In {sj} set `rim` to the rim's box as frame fractions, e.g. "
               '[{{"from": "00:00", "box": [0.47, 0.18, 0.06, 0.03]}}] (x, y = top-left, w, h; add an entry with a '
               "later `from` when the camera moved), or [] when no rim is in view; then set \"rim_checked\": true."),
    # not tracked: train-sheets refuses to rebuild once reviews exist (`train-sheets --force` is the user's call)
    P.Step("sheets", "cmd", lambda g: (g.review / "manifest.json").exists() and any(g.review.glob("brief_part*.md")),
           lambda g: [["train-sheets", str(g.folder)]], long=True),
    P.Step("film-review", "agent", review_done,
           how="Film review (playbook, training step 5): launch one subagent per {review}/brief_part<N>.md, at most 3 "
               "at once; each writes review_part<N>.json and memo_part<N>.md there and replies in a few lines. Do not "
               "read the sheets yourself. Re-run a part whose json does not parse or misses candidate ids."),
    P.Step("summary", "cmd", summary_done, lambda g: [["train-summary", str(g.folder)]],
           inputs=lambda g: [*sorted(g.review.glob("review_part*.json")),
                             *(g.run / f for f in ("reps.json", "activity.json", "dribble.json"))],
           params=lambda g: {"targets": g.game.get("targets")}),
    P.Step("report", "agent", report_done,
           how="Write the session report (playbook, training step 7, prompts/training_report.md): {readmes} "
               "in {folder}, from {folder}/facts.md, the memos in {review} and the figures, with clip "
               "markers on the key reps; and {folder}/plan.json, the next session's drills with checkable targets."),
    *P.tail_steps(
        lambda g: g.video,
        listen_how="Write the narration scripts {folder}/listen.<lang>.md for {langs} (prompts/narration.md; for a "
                   "training session: what went well, what did not, and next session's plan, 2-3 minutes).",
        qa_how="QA: have the browser-check subagent serve {folder} over http and check the page in both languages, "
               "the audio and every clip. Write the result to {folder}/qa.md, first word PASS when it passes.",
        film_script_how="Write the explained-video scripts {folder}/film.<lang>.md for {langs} from the finished "
                        "report (prompts/film.md, training notes in prompts/training_report.md); check them with "
                        "`hoop-tape-miner film {folder} --dry`."),
]
NAMES = [s.name for s in TRAIN_STEPS]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner train", description=__doc__.splitlines()[0])
    ap.add_argument("target", nargs="+", help="phone video file(s) of one workout, or a session folder")
    ap.add_argument("--player", help="new session: player number or slug (default team.json focus_player)")
    ap.add_argument("--date", help="new session: date YYYY-MM-DD (default: recording date)")
    ap.add_argument("--name", help="new session: player display name")
    ap.add_argument("--plan", default="", help="new session: what you meant to train")
    P.add_drive_args(ap, NAMES, pages="page")
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
        P.print_status(g, TRAIN_STEPS)
        return
    sys.exit(P.drive(g, TRAIN_STEPS, a.until, a.redo, a.publish, a.dry))


if __name__ == "__main__":
    main()
