"""Run one game end to end: every deterministic stage in order, stopping where the agent has to judge.

usage: hoop-tape-miner run <game folder | league game url> [--status] [--dry] [--until STEP] [--redo STEP] [--publish]

Each step knows the file it produces, so a run resumes where it stopped: done steps are skipped, the next command
steps run (long ones log to <workspace>/logs/<game>-<step>.log), and the run stops at the first agent step whose
output is missing, printing what to do. Exit codes: 0 everything done, 3 waiting for the agent, 1 a command failed.
Deliverables: the team page and the focus-player page (index.html with narration audio and clips, published as
links with --publish) and the explained video film.<lang>.mp4 (a file to send yourself; never published).
A league url is fetched first (`fetch`), then the run continues in that game folder; a url whose game folder
already exists (game.json league.game_id) reuses it without fetching again (--refetch to force a fetch).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import clips, game_config, workspace

WAITING = 3
LANGS = ("zh", "en")
KB = Path(__file__).resolve().parents[2] / "prompts" / "coach_kb.md"   # coaching knowledge base (insights step)


def profile_langs() -> tuple:
    """Report languages from team.json `languages` (default zh + en); the page, voices and charts know zh and en."""
    langs = tuple(dict.fromkeys(workspace.profile().get("languages") or LANGS))
    bad = [l for l in langs if l not in LANGS]
    if bad:
        sys.exit(f"team.json languages {list(langs)}: {bad} not supported (choose from {list(LANGS)})")
    return langs


def readme(lang: str) -> str:
    """README.md is the Chinese report, README.<lang>.md any other language (same rule as render_html)."""
    return "README.md" if lang == "zh" else f"README.{lang}.md"


def localised(name: str, lang: str) -> str:
    """momentum.png for zh, momentum.<lang>.png otherwise."""
    stem, dot, ext = name.rpartition(".")
    return name if lang == "zh" else f"{stem}.{lang}{dot}{ext}"


@dataclass
class Game:
    folder: Path
    game: dict
    langs: tuple = LANGS

    @property
    def gj(self) -> Path:
        return self.folder / "game.json"

    @property
    def run(self) -> Path:
        r = self.game.get("run")
        return Path(r) if r else self.folder / "run"

    @property
    def video(self) -> Path | None:
        v = self.game.get("video")
        if not v:
            return None
        p = Path(v).expanduser()
        return p if p.is_absolute() else self.folder / p

    @property
    def focus(self) -> str | None:
        f = game_config.team(self.game, "us").get("focus_player")
        return str(f) if f not in (None, "") else None

    @property
    def review(self) -> Path:
        """run/review_v1, or game.json "review_dir" (a re-review of the same run, absolute or relative to run)."""
        r = self.game.get("review_dir")
        return self.run / r if r else self.run / "review_v1"

    @property
    def official(self) -> Path:
        """official.json in run/ (where fetch writes it), else next to game.json."""
        p = self.run / "official.json"
        return p if p.exists() or not (self.folder / "official.json").exists() else self.folder / "official.json"

    @property
    def lineup(self) -> Path:
        """lineup_intervals.json in the review folder, else in run/ (older runs wrote it there)."""
        p = self.review / "lineup_intervals.json"
        return p if p.exists() or not (self.run / "lineup_intervals.json").exists() else self.run / "lineup_intervals.json"

    def no_score_flow(self) -> bool:
        if not self.official.exists():
            return True
        return not json.loads(self.official.read_text(encoding="utf8")).get("score_flow")

    def reports(self) -> list[Path]:
        """Report folders: the team page, plus the focus player's page."""
        return [self.folder] + ([self.folder / f"player-{self.focus}"] if self.focus else [])

    def fill(self, how: str) -> str:
        return fill(how, self)

    def finished(self):
        print("[run] done. Pages: " + ", ".join(str(d / "index.html") for d in self.reports()))
        print("[run] explained video (send it yourself, it is not published): "
              + ", ".join(str(self.folder / f"film.{l}.mp4") for l in self.langs))

    @classmethod
    def load(cls, folder: Path) -> "Game":
        gj = folder / "game.json"
        if not gj.exists():
            sys.exit(f"{gj} not found: start with `hoop-tape-miner fetch <league game url>` or `new-game`")
        langs = profile_langs()
        return cls(folder, json.loads(gj.read_text(encoding="utf8")), langs)


@dataclass
class Step:
    name: str
    kind: str                                   # "cmd": run it; "agent": stop and say what to do
    done: Callable[[Game], bool]
    args: Callable[[Game], list[list[str]]] = field(default=lambda g: [])   # cmd: one or more stage argv
    how: str = ""                               # agent: instructions ({run}, {folder}, ... filled in)
    long: bool = False                          # cmd: log to a file instead of the terminal
    expect_exit: bool = False                   # cmd: a non-zero exit is the expected stop (tracks pass 1)
    errors: Callable[[Game], list[str]] | None = None   # agent: why its output does not pass yet (printed when waiting)


def _exists(*rel: str, base: str = "run") -> Callable[[Game], bool]:
    def check(g: Game) -> bool:
        root = g.run if base == "run" else g.folder
        return all((root / r).exists() for r in rel)
    return check


def _newer(out: Path, *inputs: Path, slack: float = 2.0) -> bool:
    """out exists and no input changed after it (slack: files copied together differ by milliseconds)."""
    if not out.exists():
        return False
    t = out.stat().st_mtime + slack
    return all(not i.exists() or i.stat().st_mtime <= t for i in inputs)


def extracted(g: Game) -> bool:
    return _exists("detections.pkl", "camera.npz")(g)


def calib_times(g: Game) -> str:
    """Four frames spread over the playing time (both halves, so the camera's zoom range is covered)."""
    periods = g.game.get("periods") or []
    if periods:
        ts = [a + (b - a) * f for a, b in (periods[0], periods[-1]) for f in (0.25, 0.75)]
    else:
        ts = [300, 900, 1500, 2100]
    return ",".join(f"{t:.0f}" for t in ts)


def parts_errors(g: Game) -> list[str]:
    """Why the film review is not done: parts without a valid (schema v2, see coach_schema) coach_part<N>.json,
    then part coverage (coach_eval.part_coverage: every pid has a trip, no gap over MAX_GAP, jerseys resolved)."""
    from .coach_eval import part_coverage
    from .coach_schema import validate_part
    parts = {p.stem.removeprefix("brief_") for p in g.review.glob("brief_part*.md")}
    parts |= {p.stem for p in g.review.glob("part*.json")}
    files = sorted(g.review.glob("coach_part*.json"))
    if not files:
        return ["no coach_part*.json yet"]
    errs = [f"{p.name}: {e}" for p in files for e in validate_part(p)]
    have = {p.stem.removeprefix("coach_") for p in files}
    errs += [f"coach_{p}.json: missing" for p in sorted(parts - have)]
    return errs or part_coverage(g.review)


def parts_done(g: Game) -> bool:
    """A valid coach_part<N>.json for every part coach-sheets wrote (part<N>.json / brief_part<N>.md), covering
    its part (see parts_errors)."""
    return not parts_errors(g)


def parts_listed(g: Game) -> bool:
    return any(g.review.glob("brief_part*.md")) or any(g.review.glob("coach_part*.json"))


def _official(g: Game) -> Path | None:
    return g.official if g.official.exists() else None


def insights_errors(g: Game) -> list[str]:
    """The writer's check of review/insights.json (`coach-insights check --no-critic`: cited trips, KB slugs,
    numbers that resolve in their source files, roster)."""
    from .coach_insights import check_review
    return check_review(g.review, KB, critic=False, official=_official(g))


def critic_errors(g: Game) -> list[str]:
    """The full check, including the critic's own signed critic.json (`coach-insights check`)."""
    from .coach_insights import check_review
    return check_review(g.review, KB, official=_official(g))


def eval_result(g: Game) -> dict | None:
    """review/eval/run.json written by the coach-eval step (None if missing or unreadable)."""
    try:
        return json.loads((g.review / "eval" / "run.json").read_text(encoding="utf8"))
    except (OSError, ValueError):
        return None


def eval_done(g: Game) -> bool:
    """coach-eval ran on the current trips and its gate passed (nothing to compare against without official.json)."""
    if not g.official.exists():
        return True
    res = eval_result(g)
    return bool(isinstance(res, dict) and (res.get("gate") or {}).get("pass")) and _newer(
        g.review / "eval" / "run.json", g.official, *g.review.glob("coach_part*.json"))


def eval_line(g: Game) -> str | None:
    """One `run --status` line from review/eval/run.json: recalls, gate, regressions."""
    res = eval_result(g)
    if not isinstance(res, dict) or not isinstance(res.get("facts"), dict):
        return None
    f, gt = res["facts"], res.get("gate") or {}
    sides = "; ".join(f"{s} pts recall {(f.get(s) or {}).get('pts_recall')} prec {(f.get(s) or {}).get('pts_precision')}"
                      for s in ("us", "them"))
    out = f"coach-eval {res.get('at', '?')}: {sides}; gate {'PASS' if gt.get('pass') else 'FAIL'}"
    if gt.get("skipped"):
        out += f" (not computed: {', '.join(gt['skipped'])})"
    if res.get("regressions"):
        out += f"; WARNING worse than {res.get('previous')}: {', '.join(res['regressions'])}"
    return out


LEGACY = ("this game's reports were written before the stricter coach gates. Newly required: every pid of each part "
          "covered by a trip without gaps over 20 s, scoring and foul jerseys written or marked unknown (film-review); "
          "insight evidence that names its pid and trip, numbers that resolve in their source file (insights); a "
          "critic.json signed by a separate critic (critic); the coach-eval gate (coach-eval). Fix these and re-run, "
          "or keep the pages already published.")


def reports_done(g: Game) -> bool:
    return all((d / readme(l)).exists() for d in g.reports() for l in g.langs)


def clips_done(g: Game) -> bool:
    return all(clips.clip_path(d, a, b).exists() for d in g.reports() for a, b in clips.find_clips(d))


def film_done(g: Game) -> bool:
    return all(_newer(g.folder / f"film.{l}.mp4", g.folder / f"film.{l}.md") for l in g.langs)


def listen_done(g: Game) -> bool:
    return all(_newer(d / f"listen.{l}.mp3", d / f"listen.{l}.md") for d in g.reports() for l in g.langs)


def html_done(g: Game) -> bool:
    def inputs(d: Path) -> list[Path]:
        return [*(d / readme(l) for l in g.langs), g.gj, *d.glob("listen.*.mp3"), *d.glob("clips/*.mp4")]
    return all(_newer(d / "index.html", *inputs(d)) for d in g.reports())


def published(g: Game) -> bool:
    """Every report page was uploaded by a successful `publish --deploy` after its index.html was last built
    (a failed deploy, or a publish without --deploy, does not count)."""
    from . import publish
    path = workspace.root() / "publish.json"
    if not path.exists():
        return False
    reg = publish.load_registry(path)
    root = workspace.root().resolve()
    for d in g.reports():
        try:
            key = d.resolve().relative_to(root).as_posix()
        except ValueError:
            return False
        if not publish.is_published(reg, key, d / "index.html"):
            return False
    return True


def qa_hash(g: Game) -> str:
    """Stamp of what QA checks: the text of each report's pages and READMEs, plus the name and size of its audio
    and clips. Any edit after QA changes it."""
    h = hashlib.sha256()
    for d in g.reports():
        for p in [d / n for n in ("index.html", "README.md", "README.en.md")]:
            h.update(f"{p.relative_to(g.folder).as_posix()}\0".encode())
            h.update(p.read_bytes() if p.exists() else b"-")
        for p in sorted([*d.glob("listen.*.mp3"), *d.glob("clips/*")]):
            h.update(f"{p.relative_to(g.folder).as_posix()}\0{p.stat().st_size}\0".encode())
    return h.hexdigest()[:16]


def qa_done(g: Game) -> bool:
    """qa.md starts with PASS and carries the stamp of the files as they are now (`checked: <qa_hash>`)."""
    qa = g.folder / "qa.md"
    if not qa.exists():
        return False
    text = qa.read_text(encoding="utf8")
    stamp = re.search(r"checked:\s*([0-9a-f]{16})", text)
    return text.lstrip().upper().startswith("PASS") and bool(stamp) and stamp.group(1) == qa_hash(g)


QA_STAMP = (" Then add the line `checked: {qa}` to qa.md (the stamp of the files you checked; an edit after QA "
            "changes it and the run asks for QA again).")


def _v(g: Game) -> str:
    return str(g.video)


STEPS = [
    Step("video", "agent", lambda g: bool(g.video and g.video.exists()),
         how="game.json `video` does not point to a file. Run `hoop-tape-miner fetch <league game url>` "
             "(downloads the league video), or set `video` to our recording."),
    Step("teams", "agent",
         lambda g: all(game_config.team(g.game, s).get("team") not in (None, "", "Our Team", "Opponent")
                       for s in game_config.SIDES) and bool(g.game.get("periods")),
         how="Fill {gj}: us/them `team`, rosters, `periods` (seconds of our video) and `result`. `fetch` fills them "
             "from the league; without league data, read them from the video and ask the user what you cannot see."),
    Step("periods", "agent", lambda g: g.game.get("periods_checked") is not False,
         how="Periods (playbook step 2): the league's periods in {gj} split the whole league video (pre-game "
             "footage and the break included). Grab stills around each boundary (`ffmpeg -ss T -i {video} -frames:v 1 x.jpg`), set `periods` to the "
             "seconds of our video where play starts and ends in each period (with our own video, shift them by "
             "the alignment in {run}/official.json), then set \"periods_checked\": true."),
    Step("calib-grid", "cmd",
         lambda g: any((g.run / "calib").glob("grid_*.jpg")) or _exists("calib/keyframes.json")(g) or extracted(g),
         lambda g: [["calibrate", "--video", _v(g), "--times", calib_times(g), "--out", str(g.run / "calib"),
                     "--grid"]]),
    Step("calibrate", "agent", lambda g: _exists("calib/keyframes.json")(g) or extracted(g),
         how="Court calibration (playbook step 3): view {run}/calib/grid_*.jpg, write {run}/calib/points.json with "
             "4-6 landmarks per frame, then `hoop-tape-miner calibrate --video {video} --times {times} --out "
             "{run}/calib --points {run}/calib/points.json`. Fix the points it reports as WEAK and re-run until "
             "every frame says PASS; check the ov_*.jpg overlays (lines on the painted lines)."),
    Step("extract", "cmd", extracted,
         lambda g: [["extract", "--video", _v(g), "--out", str(g.run), "--calib", str(g.run / "calib/keyframes.json"),
                     "--fps", "10"]], long=True),
    Step("embed", "cmd", lambda g: _newer(g.run / "embeddings.npz", g.run / "detections.pkl"),  # new extract: re-embed
         lambda g: [["embed", "--run", str(g.run), "--video", _v(g)]], long=True),
    Step("montage", "cmd", lambda g: any(_exists(f)(g) for f in ("cluster_montage.jpg", "cluster_names.json", "tracks.pkl")),
         lambda g: [["tracks", "--run", str(g.run), "--video", _v(g), "--game", str(g.gj)]], long=True,
         expect_exit=True),
    Step("clusters", "agent", lambda g: _exists("cluster_names.json")(g) or _exists("tracks.pkl")(g),
         how="Name the team clusters (playbook step 5): view {run}/cluster_montage.jpg and write "
             '{run}/cluster_names.json, one label per cluster id: "us", "them", "ref" or "unk" '
             "(our jerseys: {us_label}; theirs: {them_label})."),
    Step("tracks", "cmd", _exists("tracks.pkl"),
         lambda g: [["tracks", "--run", str(g.run), "--video", _v(g), "--game", str(g.gj)]], long=True),
    Step("jersey", "cmd", _exists("jersey.json"),
         lambda g: [["jersey", "--run", str(g.run), "--video", _v(g)]], long=True),
    Step("analyze", "cmd", _exists("possessions.pkl", "possession_metrics.pkl"),
         lambda g: [["analyze", "--run", str(g.run), "--game", str(g.gj)]], long=True),
    Step("official", "agent", lambda g: g.official.exists() or bool(g.game.get("no_league_data")),
         how="No {run}/official.json. `fetch` writes it for league games; for another league convert its data "
             '(playbook step 6), or set "no_league_data": true in {gj} to go on from the film alone.'),
    Step("coach-sheets", "cmd", lambda g: (g.review / "manifest.json").exists() and parts_listed(g),
         lambda g: [["coach-sheets", "--run", str(g.run), "--game", str(g.gj), "--out", str(g.review), "--parts", "6",
                     "--video", _v(g)]], long=True),
    Step("film-review", "agent", parts_done,
         how="Film review (playbook step 7): launch one subagent per {review}/brief_part<N>.md, at most 3 at once; "
             "each writes coach_part<N>.json, memo_part<N>.md and notes_part<N>.txt there. Do not read the sheets "
             "yourself. A part counts as done when `hoop-tape-miner coach-check --review {review}` passes for it "
             "(schema, every pid of the part covered without gaps over 20 s, scoring and foul jerseys written or "
             "marked unknown); send a part's errors back to its subagent.",
         errors=parts_errors),
    Step("features", "cmd", lambda g: (g.review / "features.json").exists(),
         lambda g: [["coach-features", "--run", str(g.run), "--review", str(g.review)]]),
    Step("coach-eval", "cmd", eval_done,
         lambda g: [["coach-eval", "--review", str(g.review), "--official", str(g.official), "--label", "run",
                     "--gate"]]),
    Step("summary", "agent",
         lambda g: (g.review / "summary.json").exists(),
         how="Choose the game's stretches from the score flow, then run `coach-summary --official "
             "{run}/official.json` (with Four Factors) and `plusminus` into {review}/summary.json and "
             "{review}/plusminus.json (playbook step 7.4)."),
    Step("insights", "agent", lambda g: not insights_errors(g),
         how="Coaching insights (playbook step 7.5): launch the writer subagent with prompts/coach_insights.md "
             "(review folder {review}; it also uses {review}/features.json when present); it writes "
             "{review}/insights.json and is done when `hoop-tape-miner coach-insights check --review {review} "
             "--no-critic` passes. Send the errors back to the writer. The writer does not write critic.json.",
         errors=insights_errors),
    Step("critic", "agent", lambda g: not critic_errors(g),
         how="Critic (playbook step 7.5): launch a separate critic subagent with prompts/coach_critic.md (review "
             "folder {review}). It re-opens the cited sheets, writes {review}/critic.json (a verdict per insight "
             "with the sheets it re-opened), moves dropped insights to {review}/insights_dropped.json, and signs "
             "with `hoop-tape-miner coach-insights critic --review {review}`. Any later edit of insights.json "
             "needs the critic again.",
         errors=critic_errors),
    Step("momentum", "cmd",
         lambda g: g.no_score_flow() or all((g.folder / localised("momentum.png", l)).exists() for l in g.langs),
         lambda g: [["momentum", "--official", str(g.official), "--game", str(g.gj), "--lineup",
                     str(g.lineup), "--out", str(g.folder / localised("momentum.png", l)), "--lang", l]
                    for l in g.langs]),
    Step("facts", "agent",
         lambda g: (g.review / "players_facts.md").exists() and (not g.focus or (g.review / f"player{g.focus}_facts.md").exists()),
         how="Write the fact sheets (playbook step 9): {review}/players_facts.md and {review}/player{focus}_facts.md."),
    Step("reports", "agent", reports_done,
         how="Write the reports (playbook step 10): {readmes} in {folder} (prompts/coach_report.md) "
             "and in {folder}/player-{focus} (prompts/player_deep_dive.md), with clip markers on the key plays."),
    Step("clips", "cmd", clips_done, lambda g: [["clips", str(d), "--video", _v(g)] for d in g.reports()]),
    Step("listen-script", "agent",
         lambda g: all((d / f"listen.{l}.md").exists() for d in g.reports() for l in g.langs),
         how="Write the narration scripts listen.<lang>.md for {langs} in {folder} and {folder}/player-{focus} "
             "(playbook step 11, prompts/narration.md)."),
    Step("narrate", "cmd", listen_done, lambda g: [["narrate", str(d), "--lang", *g.langs] for d in g.reports()]),
    Step("html", "cmd", html_done, lambda g: [["html", str(d)] for d in g.reports()]),
    Step("qa", "agent", qa_done,
         how="QA (playbook step 13): have the browser-check subagent serve {folder} over http and check both pages "
             "in both languages, the audio and every clip. Write the result to {folder}/qa.md, first "
             "word PASS when it passes." + QA_STAMP),
    Step("publish", "cmd", published,
         lambda g: [["publish", *map(str, g.reports()), "--deploy"]]),
    Step("film-script", "agent", lambda g: all((g.folder / f"film.{l}.md").exists() for l in g.langs),
         how="Write the explained-video scripts {folder}/film.<lang>.md for {langs} from the finished team report "
             "(playbook step 15, prompts/film.md); check them with `hoop-tape-miner film {folder} --video {video} --dry`."),
    Step("film", "cmd", film_done,
         lambda g: [["film", str(g.folder), "--video", _v(g), "--run", str(g.run)]], long=True),
]
NAMES = [s.name for s in STEPS]
GATED = ("film-review", "insights", "critic")   # checks made stricter: finished games get the LEGACY note


def fill(how: str, g: Game) -> str:
    vals = dict(run=g.run, folder=g.folder, gj=g.gj, video=g.video, review=g.review, focus=g.focus or "<N>",
                times=calib_times(g), langs=", ".join(g.langs), readmes=" + ".join(readme(l) for l in g.langs),
                qa=qa_hash(g),
                us_label=game_config.team(g.game, "us").get("label", "?"),
                them_label=game_config.team(g.game, "them").get("label", "?"))
    return how.format(**vals)


def logs_dir() -> Path:
    d = workspace.root() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def stage_cmd(argv: list[str]) -> list[str]:
    return [sys.executable, "-m", "hoop_tape_miner.cli", *argv]


def tail(path: Path, n: int = 15) -> str:
    lines = path.read_text(encoding="utf8", errors="replace").splitlines()
    return "\n".join(lines[-n:])


def child_env() -> dict:
    """The environment for stage subprocesses: UTF-8 stdio, so Chinese text in a log file or on a cp1252 / GBK
    Windows console never raises UnicodeEncodeError."""
    return {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def run_cmd(step: Step, g: Game, runner=subprocess.run) -> bool:
    """Run a command step; long ones log to a file and only the tail is printed on failure."""
    env = child_env()
    for i, argv in enumerate(step.args(g)):
        print(f"[run] {step.name}: hoop-tape-miner {' '.join(argv)}", flush=True)
        if step.long:
            log = logs_dir() / f"{g.folder.parent.name}-{g.folder.name}-{step.name}{i or ''}.log"
            print(f"[run]   log: {log}", flush=True)
            with open(log, "w", encoding="utf8") as fh:
                rc = runner(stage_cmd(argv), stdout=fh, stderr=subprocess.STDOUT, env=env).returncode
        else:
            log, rc = None, runner(stage_cmd(argv), env=env).returncode
        if rc != 0 and not step.expect_exit:
            print(f"[run] {step.name} failed (exit {rc})" + (f"; last lines of {log}:\n{tail(log)}" if log else ""))
            return False
    return True


def status(g: Game) -> list[tuple[str, str, bool]]:
    return [(s.name, s.kind, s.done(g)) for s in STEPS]


def drive(g: Game, until: str | None = None, redo: str | None = None, publish: bool = False,
          dry: bool = False, runner=subprocess.run, steps: list[Step] | None = None) -> int:
    """Walk `steps` (default: the game STEPS); `g` may be a Game subclass (train-run uses a Session)."""
    for s in STEPS if steps is None else steps:
        if s.name == "publish" and not publish:
            if not s.done(g):
                print("[run] publish skipped: re-run with --publish to deploy the pages as links")
            if s.name == until:
                print(f"[run] stopped after {until}")
                return 0
            continue
        if s.done(g) and s.name != redo:
            if s.name == until:
                print(f"[run] stopped after {until} (already done)")
                return 0
            continue
        if s.kind == "agent":
            print(f"[run] waiting for the agent: {s.name}\n{g.fill(s.how)}")
            errs = s.errors(g) if s.errors else []
            for e in errs[:12]:
                print(f"[run]   {e}")
            if len(errs) > 12:
                print(f"[run]   ... {len(errs) - 12} more")
            if errs and s.name in GATED and reports_done(g):
                print(f"[run] note: {LEGACY}")
            return WAITING
        if dry:
            for argv in s.args(g):
                print(f"[dry] {s.name}: hoop-tape-miner {' '.join(argv)}")
            return 0
        if not run_cmd(s, g, runner):
            return 1
        g = type(g).load(g.folder)  # stages may have filled game.json
        if s.expect_exit and not s.done(g):
            print(f"[run] {s.name} did not produce its output; see its log")
            return 1
        if s.name == until:
            print(f"[run] stopped after {until}")
            return 0
    g.finished()
    return 0


def game_for_url(url: str, game_id: Callable[[str], str]) -> Path | None:
    """The workspace game folder already fetched from this league url (game.json league.game_id), else None."""
    gid = game_id(url)
    for gj in sorted((workspace.root() / "teams").glob("*/*/game.json")):
        try:
            league = json.loads(gj.read_text(encoding="utf8")).get("league") or {}
        except (OSError, ValueError):
            continue
        if league.get("game_id") == gid:
            return gj.parent
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner run", description=__doc__.splitlines()[0])
    ap.add_argument("target", help="game folder (with game.json), or a league game url to fetch first")
    ap.add_argument("--status", action="store_true", help="list every step and whether it is done")
    ap.add_argument("--dry", action="store_true", help="print the next command instead of running it")
    ap.add_argument("--until", choices=NAMES, help="stop after this step")
    ap.add_argument("--redo", choices=NAMES, help="run this step again even if its output exists")
    ap.add_argument("--publish", action="store_true", help="also deploy the pages (publish --deploy) at the end")
    ap.add_argument("--refetch", action="store_true",
                    help="url target: fetch again even when the game folder exists (keeps an own-video alignment)")
    a = ap.parse_args(argv)
    target = a.target
    if target.startswith(("http://", "https://")):
        from . import fetch
        found = None if a.refetch else game_for_url(target, fetch.game_id)
        if found:
            print(f"[run] already fetched: {found} (use --refetch to fetch the league data again)")
            target = str(found)
        else:
            target = str(fetch.main([target]))
    g = Game.load(Path(target))
    if a.status:
        for name, kind, ok in status(g):
            print(f"  {'done' if ok else '----'}  {name:13s} {kind}")
        line = eval_line(g)
        if line:
            print(f"  {line}")
        return
    sys.exit(drive(g, a.until, a.redo, a.publish, a.dry))


if __name__ == "__main__":
    main()
