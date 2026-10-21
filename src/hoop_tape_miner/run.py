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
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from . import game_config, pipeline, workspace
from .pipeline import (LANGS, QA_STAMP, WAITING, Step, Unit, clips_done, film_done, html_done,  # noqa: F401
                       listen_done, localised, profile_langs, published, qa_done, qa_hash, readme, reports_done,
                       tail_steps)
from .pipeline import newer as _newer

KB = Path(__file__).resolve().parents[2] / "prompts" / "coach_kb.md"   # coaching knowledge base (insights step)


class Game(Unit):
    """A game folder: game.json, run/ (the CV pass and the review), the team page and the focus player's page."""

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

    def fill_values(self) -> dict:
        return dict(super().fill_values(), gj=self.gj, focus=self.focus or "<N>", times=calib_times(self),
                    us_label=game_config.team(self.game, "us").get("label", "?"),
                    them_label=game_config.team(self.game, "them").get("label", "?"))

    def note(self, step: str, errors: list[str]) -> str | None:
        """Finished games whose reports predate the stricter coach gates get the LEGACY note."""
        return LEGACY if errors and step in GATED and reports_done(self) else None

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


def _exists(*rel: str, base: str = "run") -> Callable[[Game], bool]:
    def check(g: Game) -> bool:
        root = g.run if base == "run" else g.folder
        return all((root / r).exists() for r in rel)
    return check


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


def _v(g: Game) -> str:
    return str(g.video)


def _ball_done(name: str) -> Callable[[Game], bool]:
    """A ball step is done once its RUN file exists, or when the sheets it would feed are already written."""
    return lambda g: (g.run / name).exists() or (g.review / "manifest.json").exists()


def _pages_built(g: Game) -> bool:
    """Every report page of the game exists (the html step ran at least once)."""
    return all((d / "index.html").exists() for d in g.reports())


def _with_posters(tail: list[Step]) -> list[Step]:
    """The shared tail with a games-only `posters` step right after `clips` (marks need the run's tracks). Done
    when marked, or when the page was built after the current posters (an older game: no redraw after its QA)."""
    from . import posters

    def done(d: Path) -> bool:
        plain = [p for p in (d / "clips").glob("*.jpg") if not p.name.endswith(".mark.jpg")]
        return posters.done(d) or ((d / "index.html").exists() and _newer(d / "index.html", *plain))
    step = Step("posters", "cmd", lambda g: all(done(d) for d in g.reports()),
                lambda g: [["posters", str(d), "--video", _v(g)] for d in g.reports()])
    i = [s.name for s in tail].index("clips") + 1
    return [*tail[:i], step, *tail[i:]]


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
                     "--fps", "10"]], long=True,
         inputs=lambda g: [g.video], params=lambda g: {"fps": 10}),   # not keyframes.json: recalib refits instead
    Step("embed", "cmd", lambda g: _newer(g.run / "embeddings.npz", g.run / "detections.pkl"),  # new extract: re-embed
         lambda g: [["embed", "--run", str(g.run), "--video", _v(g)]], long=True,
         inputs=lambda g: [g.run / "detections.pkl"]),
    Step("montage", "cmd", lambda g: any(_exists(f)(g) for f in ("cluster_montage.jpg", "cluster_names.json", "tracks.pkl")),
         lambda g: [["tracks", "--run", str(g.run), "--video", _v(g), "--game", str(g.gj)]], long=True,
         expect_exit=True),
    Step("clusters", "agent", lambda g: _exists("cluster_names.json")(g) or _exists("tracks.pkl")(g),
         how="Name the team clusters (playbook step 5): view {run}/cluster_montage.jpg and write "
             '{run}/cluster_names.json, one label per cluster id: "us", "them", "ref" or "unk" '
             "(our jerseys: {us_label}; theirs: {them_label})."),
    # tracks.pkl is never an input: analyze rewrites it, so the steps after tracks follow its run stamp (`after`)
    Step("tracks", "cmd", _exists("tracks.pkl"),
         lambda g: [["tracks", "--run", str(g.run), "--video", _v(g), "--game", str(g.gj)]], long=True,
         inputs=lambda g: [g.run / f for f in ("detections.pkl", "embeddings.npz", "cluster_names.json")]),
    Step("jersey", "cmd", _exists("jersey.json"),
         lambda g: [["jersey", "--run", str(g.run), "--video", _v(g)]], long=True,
         inputs=lambda g: [g.run / "detections.pkl"], after=("tracks",)),
    Step("analyze", "cmd", _exists("possessions.pkl", "possession_metrics.pkl"),
         lambda g: [["analyze", "--run", str(g.run), "--game", str(g.gj)]], long=True,
         inputs=lambda g: [g.run / "jersey.json", g.run / "camera.npz"], after=("tracks",),
         params=lambda g: {k: g.game.get(k) for k in ("periods", "rosters")}),
    Step("official", "agent", lambda g: g.official.exists() or bool(g.game.get("no_league_data")),
         how="No {run}/official.json. `fetch` writes it for league games; for another league convert its data "
             '(playbook step 6), or set "no_league_data": true in {gj} to go on from the film alone.'),
    # ball layers for the sheets (ball trail, CV shot-attempt markers): optional for coach-sheets, so a game whose
    # sheets already exist skips them (re-run by hand to add the layers to an old review)
    Step("ball-track", "cmd", _ball_done("ball_track.pkl"),
         lambda g: [["ball-track", "--run", str(g.run), "--video", _v(g)]],
         inputs=lambda g: [g.run / "detections.pkl", g.run / "camera.npz"]),
    Step("rim-scan", "cmd", _ball_done("rim_scan.pkl"),
         lambda g: [["rim-scan", "--run", str(g.run), "--game", str(g.gj)]], long=True,
         inputs=lambda g: [g.video, g.run / "camera.npz"]),
    Step("shot-proposals", "cmd", _ball_done("shot_proposals.json"),
         lambda g: [["shot-proposals", "--run", str(g.run)]
                    + (["--official", str(g.official)] if g.official.exists() else [])],
         inputs=lambda g: [g.run / "rim_scan.pkl", *([g.official] if g.official.exists() else [])],
         after=("analyze",)),
    Step("coach-sheets", "cmd", lambda g: (g.review / "manifest.json").exists() and parts_listed(g),
         lambda g: [["coach-sheets", "--run", str(g.run), "--game", str(g.gj), "--out", str(g.review), "--parts", "6",
                     "--video", _v(g)]], long=True,
         inputs=lambda g: [g.run / "possessions.pkl", g.run / "possession_metrics.pkl"], after=("analyze",),
         params=lambda g: {"parts": 6}),
    Step("film-review", "agent", parts_done,
         how="Film review (playbook step 7): launch one subagent per {review}/brief_part<N>.md, at most 3 at once; "
             "each writes coach_part<N>.json, memo_part<N>.md and notes_part<N>.txt there. Do not read the sheets "
             "yourself. A part counts as done when `hoop-tape-miner coach-check --review {review}` passes for it "
             "(schema, every pid of the part covered without gaps over 20 s, scoring and foul jerseys written or "
             "marked unknown); send a part's errors back to its subagent.",
         errors=parts_errors),
    Step("features", "cmd", lambda g: (g.review / "features.json").exists(),
         lambda g: [["coach-features", "--run", str(g.run), "--review", str(g.review)]],
         inputs=lambda g: [g.review / "manifest.json", *sorted(g.review.glob("coach_part*.json"))], after=("analyze",)),
    Step("coach-eval", "cmd", eval_done,
         lambda g: [["coach-eval", "--review", str(g.review), "--official", str(g.official), "--label", "run",
                     "--gate"]],
         inputs=lambda g: [g.official, *sorted(g.review.glob("coach_part*.json"))] if g.official.exists() else None),
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
                    for l in g.langs],
         inputs=lambda g: None if g.no_score_flow() else [g.official, g.lineup, g.gj],
         params=lambda g: {"langs": list(g.langs)}),
    # tracking numbers for the pages (and the fact sheets): running load per stint, defender distance and matchups;
    # a game whose pages are already built skips them (run them by hand, then `--redo html`)
    Step("load", "cmd", lambda g: _exists("load.json")(g) or _pages_built(g),
         lambda g: [["load", "--run", str(g.run), "--game", str(g.gj),
                     *(["--lineup", str(g.lineup)] if g.lineup.exists() else [])]],
         inputs=lambda g: [g.gj, *([g.lineup] if g.lineup.exists() else [])], after=("analyze",)),
    Step("matchups", "cmd", lambda g: _exists("matchups.json")(g) or _pages_built(g),
         lambda g: [["matchups", "--run", str(g.run), "--review", str(g.review), "--game", str(g.gj)]],
         inputs=lambda g: [g.gj, *sorted(g.review.glob("coach_part*.json")),
                           *([g.run / "shot_proposals.json"] if (g.run / "shot_proposals.json").exists() else [])],
         after=("analyze",)),
    Step("facts", "agent",
         lambda g: (g.review / "players_facts.md").exists() and (not g.focus or (g.review / f"player{g.focus}_facts.md").exists()),
         how="Write the fact sheets (playbook step 9): {review}/players_facts.md and {review}/player{focus}_facts.md."),
    Step("reports", "agent", reports_done,
         how="Write the reports (playbook step 10): {readmes} in {folder} (prompts/coach_report.md) "
             "and in {folder}/player-{focus} (prompts/player_deep_dive.md), with clip markers on the key plays."),
    *_with_posters(tail_steps(
        lambda g: g.video,
        listen_how="Write the narration scripts listen.<lang>.md for {langs} in {folder} and {folder}/player-{focus} "
                   "(playbook step 11, prompts/narration.md).",
        qa_how="QA (playbook step 13): have the browser-check subagent serve {folder} over http and check both pages "
               "in both languages, the audio and every clip. Write the result to {folder}/qa.md, first "
               "word PASS when it passes.",
        film_script_how="Write the explained-video scripts {folder}/film.<lang>.md for {langs} from the finished team "
                        "report (playbook step 15, prompts/film.md); check them with `hoop-tape-miner film {folder} "
                        "--video {video} --dry`.",
        film_run=True)),
]
NAMES = [s.name for s in STEPS]
GATED = ("film-review", "insights", "critic")   # checks made stricter: finished games get the LEGACY note


def status(g: Game) -> list[tuple[str, str, bool]]:
    """(name, kind, done) per game step; read-only (see pipeline.rows for why a step is stale)."""
    return pipeline.status(g, STEPS)


def drive(g: Game, until: str | None = None, redo: str | None = None, publish: bool = False,
          dry: bool = False, runner=subprocess.run, steps: list[Step] | None = None) -> int:
    """Walk `steps` (default: the game STEPS) with pipeline.drive; `g` may be any pipeline.Unit."""
    return pipeline.drive(g, STEPS if steps is None else steps, until, redo, publish, dry, runner)


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
    pipeline.add_drive_args(ap, NAMES)
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
        pipeline.print_status(g, STEPS)
        line = eval_line(g)
        if line:
            print(f"  {line}")
        return
    sys.exit(drive(g, a.until, a.redo, a.publish, a.dry))


if __name__ == "__main__":
    main()
