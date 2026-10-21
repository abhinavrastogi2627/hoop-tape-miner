"""The step-table driver shared by `run` (games), `train` (training sessions) and `move` (movement sessions).

A driver is a list of Steps. A "cmd" step runs a hoop-tape-miner stage; an "agent" step stops the run (exit 3)
and prints what the agent has to do. `drive` walks the list: done steps are skipped, the next command steps run
(long ones log to <workspace>/logs/), a failed command stops the run with exit 1 and its log tail, and exit 0
means everything is done. `--until` stops after a step (done or not), `--redo` runs a done step again, and
publish runs only with `--publish`.

Freshness (make-style, as in Snakemake / DVC / doit): a cmd step that declares `inputs` is done when its own
check passes AND its provenance record still matches: a signature of each input file (content hash for files
under 1 MB, else size + mtime), the step's `params`, and the run stamp of the steps named in `after` (for
inputs a later stage rewrites, such as tracks.pkl). Records live in <folder>/.hoop-steps.json. A change to any
of them makes the step stale, so `--redo X` (or a new input) re-runs the steps that depend on X. Folders from
before provenance have no records: their steps count as done by their own check, and `drive` writes the records
on its first walk (`--status` and `--dry` never write). Agent steps keep their own checks.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import clips, media, workspace

WAITING = 3
LANGS = ("zh", "en")
STORE = ".hoop-steps.json"
SMALL = 1 << 20      # files below this size are signed by content, larger ones by size + mtime


def profile_langs() -> tuple:
    """Report languages from team.json `languages` (default zh + en); the page, voices and charts know zh and en."""
    langs = tuple(dict.fromkeys(workspace.profile().get("languages") or LANGS))
    bad = [language for language in langs if language not in LANGS]
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


# ---- what a driver walks over ------------------------------------------------------------------------------

@dataclass
class Unit:
    """One folder a driver works on (a game or a session): its json, run folder, video, review folder, pages."""
    folder: Path
    game: dict
    langs: tuple = LANGS

    JSON = "game.json"

    @property
    def gj(self) -> Path:
        return self.folder / self.JSON

    @property
    def run(self) -> Path:
        return self.folder / "run"

    @property
    def video(self) -> Path | None:
        return None

    @property
    def review(self) -> Path:
        return self.run / "review"

    def reports(self) -> list[Path]:
        """Report folders (each gets an index.html)."""
        return [self.folder]

    def fill_values(self) -> dict:
        """Placeholders for agent instructions ({folder}, {run}, {qa}, ...)."""
        return dict(folder=self.folder, run=self.run, review=self.review, video=self.video,
                    langs=", ".join(self.langs), readmes=" + ".join(readme(language) for language in self.langs), qa=qa_hash(self))

    def fill(self, how: str) -> str:
        return how.format(**self.fill_values())

    def note(self, step: str, errors: list[str]) -> str | None:
        """An extra line printed when an agent step waits (e.g. why an old game now fails a stricter check)."""
        return None

    def finished(self):
        print(f"[run] done: {self.folder}")

    @classmethod
    def load(cls, folder: Path) -> "Unit":
        raise NotImplementedError


class Session(Unit):
    """A personal session folder (training or movement): <JSON>, run/<REVIEW>, one page in the folder itself."""
    REVIEW = "review"
    VIDEO = "video.mp4"
    LABEL = "session"
    PLAN = "plan"         # what plan.json holds, for the closing line

    def path(self, key: str, default: str) -> Path:
        """A path value of the session json (absolute, or relative to the session folder), else folder/default."""
        v = self.game.get(key)
        p = Path(v).expanduser() if v else Path(default)
        return p if p.is_absolute() else Path(self.folder) / p

    @property
    def run(self) -> Path:
        return self.path("run", "run")

    @property
    def video(self) -> Path | None:
        return self.path("video", self.VIDEO)

    @property
    def review(self) -> Path:
        return self.run / self.REVIEW

    def fill_values(self) -> dict:
        return dict(super().fill_values(), player=self.game.get("player"))

    def finished(self):
        print(f"[{self.LABEL}] done. Page: {self.folder / 'index.html'}")
        print(f"[{self.LABEL}] explained video (send it yourself, it is not published): "
              + ", ".join(str(self.folder / f"film.{language}.mp4") for language in self.langs))
        print(f"[{self.LABEL}] {self.PLAN}: {self.folder / 'plan.json'}")


@dataclass
class Step:
    name: str
    kind: str                                   # "cmd": run it; "agent": stop and say what to do
    done: Callable[[Unit], bool]                # the step's own check (outputs exist / pass)
    args: Callable[[Unit], list[list[str]]] = field(default=lambda g: [])   # cmd: one or more stage argv
    how: str = ""                               # agent: instructions ({run}, {folder}, ... filled in)
    long: bool = False                          # cmd: log to a file instead of the terminal
    expect_exit: bool = False                   # cmd: a non-zero exit is the expected stop (tracks pass 1)
    errors: Callable[[Unit], list[str]] | None = None   # agent: why its output does not pass yet (printed when waiting)
    inputs: Callable[[Unit], list[Path] | None] | None = None   # cmd: files it reads (None = nothing to track now)
    params: Callable[[Unit], dict] | None = None                # cmd: settings that shape its output
    after: tuple = ()                           # cmd: steps whose re-run makes this one stale
    again: tuple = ()                           # cmd: extra argv when it re-runs over existing outputs


def newer(out: Path, *inputs: Path, slack: float = 2.0) -> bool:
    """out exists and no input changed after it (slack: files copied together differ by milliseconds)."""
    if not out.exists():
        return False
    t = out.stat().st_mtime + slack
    return all(not i.exists() or i.stat().st_mtime <= t for i in inputs)


# ---- provenance ----------------------------------------------------------------------------------------------

def signature(p: Path) -> str:
    """'sha1:<hash>' for a small file, '<size>:<mtime_ns>' for a large one, 'missing' when absent."""
    try:
        st = p.stat()
    except OSError:
        return "missing"
    if p.is_dir():
        return "dir"
    if st.st_size < SMALL:
        return "sha1:" + hashlib.sha1(p.read_bytes()).hexdigest()[:16]
    return f"{st.st_size}:{st.st_mtime_ns}"


def input_key(g: Unit, p: Path) -> str:
    """An input's name in the record: relative to the folder, else run/<rel>, else ext/<file name> (so moving the
    folder or the run does not make steps stale)."""
    for base, prefix in ((g.folder, ""), (g.run, "run/")):
        try:
            return prefix + Path(p).relative_to(base).as_posix()
        except ValueError:
            pass
    return "ext/" + Path(p).name


class Store:
    """<folder>/.hoop-steps.json: {"version": 1, "steps": {name: record}}; an unreadable file counts as empty."""

    def __init__(self, folder: Path):
        self.path = Path(folder) / STORE
        try:
            self.steps = json.loads(self.path.read_text(encoding="utf8")).get("steps") or {}
        except (OSError, ValueError, AttributeError):
            self.steps = {}

    def get(self, name: str) -> dict | None:
        return self.steps.get(name)

    def save(self):
        media.write_json_atomic(self.path, {"version": 1, "steps": self.steps}, indent=1)


def current(step: Step, g: Unit, store: Store) -> dict | None:
    """What the step's record would hold now (None: the step tracks nothing at the moment)."""
    files = step.inputs(g) if step.inputs else None
    if files is None:
        return None
    params = json.loads(json.dumps(step.params(g) if step.params else {}, default=str))
    return dict(inputs={input_key(g, p): signature(Path(p)) for p in files if p is not None}, params=params,
                after={d: (store.get(d) or {}).get("run") for d in step.after})


def changes(step: Step, g: Unit, store: Store) -> list[str]:
    """What changed since the step's record; [] when fresh, untracked, or never recorded (older folders)."""
    rec = store.get(step.name)
    cur = current(step, g, store) if rec is not None else None
    if cur is None:
        return []
    old, new = rec.get("inputs") or {}, cur["inputs"]
    out = [k for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]
    if (rec.get("params") or {}) != cur["params"]:
        out.append("params")
    out += [f"{d} ran again" for d in step.after if (rec.get("after") or {}).get(d) != cur["after"][d]]
    return out


def record(step: Step, g: Unit, store: Store) -> bool:
    """Write the step's record as things are now (new run stamp); False when the step tracks nothing."""
    cur = current(step, g, store)
    if cur is None:
        return False
    store.steps[step.name] = dict(cur, run=uuid.uuid4().hex[:8], at=dt.datetime.now().isoformat(timespec="seconds"))
    return True


def adopt(steps: list[Step], g: Unit, store: Store) -> None:
    """Record every tracked step that passes its own check but has no record yet (a folder from before provenance),
    in order, so a later --redo makes its dependants stale. Saves the store when anything was added."""
    added = False
    for s in steps:
        if s.kind == "cmd" and s.inputs and store.get(s.name) is None and s.done(g):
            added = record(s, g, store) or added
    if added:
        store.save()


# ---- QA and publish (shared by every driver) ---------------------------------------------------------------

def qa_hash(g: Unit) -> str:
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


def qa_done(g: Unit) -> bool:
    """qa.md starts with PASS and carries the stamp of the files as they are now (`checked: <qa_hash>`)."""
    qa = g.folder / "qa.md"
    if not qa.exists():
        return False
    text = qa.read_text(encoding="utf8")
    stamp = re.search(r"checked:\s*([0-9a-f]{16})", text)
    return text.lstrip().upper().startswith("PASS") and bool(stamp) and stamp.group(1) == qa_hash(g)


QA_STAMP = (" Then add the line `checked: {qa}` to qa.md (the stamp of the files you checked; an edit after QA "
            "changes it and the run asks for QA again).")


def published(g: Unit) -> bool:
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


def reports_done(g: Unit) -> bool:
    return all((d / readme(language)).exists() for d in g.reports() for language in g.langs)


def clips_done(g: Unit) -> bool:
    return all(clips.clip_path(d, a, b).exists() for d in g.reports() for a, b in clips.find_clips(d))


def film_done(g: Unit) -> bool:
    return all(newer(g.folder / f"film.{language}.mp4", g.folder / f"film.{language}.md") for language in g.langs)


def listen_done(g: Unit) -> bool:
    return all(newer(d / f"listen.{language}.mp3", d / f"listen.{language}.md") for d in g.reports() for language in g.langs)


def html_inputs(g: Unit) -> list[Path]:
    return [x for d in g.reports() for x in (*(d / readme(language) for language in g.langs), g.gj, *sorted(d.glob("listen.*.mp3")),
                                             *sorted(d.glob("clips/*.mp4")))]


def html_done(g: Unit) -> bool:
    def inputs(d: Path) -> list[Path]:
        return [*(d / readme(language) for language in g.langs), g.gj, *d.glob("listen.*.mp3"), *d.glob("clips/*.mp4")]
    return all(newer(d / "index.html", *inputs(d)) for d in g.reports())


def tail_steps(video: Callable[[Unit], Path], listen_how: str, qa_how: str, film_script_how: str,
               film_run: bool = False) -> list[Step]:
    """The steps every driver ends with: clips -> narration -> page -> QA -> publish -> explained video.
    `video` is what clips and the film cut from; film_run passes --run (games: the film draws the tracks)."""
    def film_args(g):
        return [["film", str(g.folder), "--video", str(video(g)), *(["--run", str(g.run)] if film_run else [])]]
    return [
        Step("clips", "cmd", clips_done, lambda g: [["clips", str(d), "--video", str(video(g))] for d in g.reports()],
             inputs=lambda g: [video(g)], again=("--force",)),      # a new video re-cuts every clip
        Step("listen-script", "agent",
             lambda g: all((d / f"listen.{language}.md").exists() for d in g.reports() for language in g.langs), how=listen_how),
        Step("narrate", "cmd", listen_done, lambda g: [["narrate", str(d), "--lang", *g.langs] for d in g.reports()],
             inputs=lambda g: [d / f"listen.{language}.md" for d in g.reports() for language in g.langs]),
        Step("html", "cmd", html_done, lambda g: [["html", str(d)] for d in g.reports()], inputs=html_inputs),
        Step("qa", "agent", qa_done, how=qa_how + QA_STAMP),
        Step("publish", "cmd", published, lambda g: [["publish", *map(str, g.reports()), "--deploy"]]),
        Step("film-script", "agent", lambda g: all((g.folder / f"film.{language}.md").exists() for language in g.langs),
             how=film_script_how),
        Step("film", "cmd", film_done, film_args, long=True,
             inputs=lambda g: [*(g.folder / f"film.{language}.md" for language in g.langs), video(g)]),
    ]


# ---- running -------------------------------------------------------------------------------------------------

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


def run_cmd(step: Step, g: Unit, runner=subprocess.run, argvs: list[list[str]] | None = None) -> bool:
    """Run a command step; long ones log to a file and only the tail is printed on failure."""
    env = child_env()
    for i, argv in enumerate(step.args(g) if argvs is None else argvs):
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


def rows(g: Unit, steps: list[Step]) -> list[tuple[str, str, bool, list[str]]]:
    """(name, kind, done, what changed) per step, read-only: a step whose own check passes but whose inputs
    changed since its record is not done, and the changes say why."""
    store = Store(g.folder)
    out = []
    for s in steps:
        ok = s.done(g)
        why = changes(s, g, store) if ok else []
        out.append((s.name, s.kind, ok and not why, why))
    return out


def status(g: Unit, steps: list[Step]) -> list[tuple[str, str, bool]]:
    return [(n, k, ok) for n, k, ok, _ in rows(g, steps)]


def print_status(g: Unit, steps: list[Step]) -> None:
    for name, kind, ok, why in rows(g, steps):
        stale = f"  (stale: {', '.join(why[:4])}{' ...' if len(why) > 4 else ''})" if why else ""
        print(f"  {'done' if ok else '----'}  {name:13s} {kind}{stale}")


def drive(g: Unit, steps: list[Step], until: str | None = None, redo: str | None = None, publish: bool = False,
          dry: bool = False, runner=subprocess.run) -> int:
    """Walk `steps` and return the exit code: 0 done (or stopped at --until), 3 waiting for the agent, 1 failed."""
    store = Store(g.folder)
    if not dry:
        adopt(steps, g, store)
    for s in steps:
        if s.name == "publish" and not publish:
            if not s.done(g):
                print("[run] publish skipped: re-run with --publish to deploy the pages as links")
            if s.name == until:
                print(f"[run] stopped after {until}")
                return 0
            continue
        own = s.done(g)
        why = changes(s, g, store) if own else []
        if own and not why and s.name != redo:
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
            note = g.note(s.name, errs)
            if note:
                print(f"[run] note: {note}")
            return WAITING
        argvs = [[*a, *s.again] for a in s.args(g)] if own else s.args(g)
        if why:
            print(f"[run] {s.name}: changed since its last run: {', '.join(why[:6])}{' ...' if len(why) > 6 else ''}")
        if dry:
            for argv in argvs:
                print(f"[dry] {s.name}: hoop-tape-miner {' '.join(argv)}")
            return 0
        if not run_cmd(s, g, runner, argvs):
            return 1
        g = type(g).load(g.folder)  # stages may have filled game.json
        if record(s, g, store):
            store.save()
        if s.expect_exit and not s.done(g):
            print(f"[run] {s.name} did not produce its output; see its log")
            return 1
        if s.name == until:
            print(f"[run] stopped after {until}")
            return 0
    g.finished()
    return 0


def add_drive_args(ap, names: list[str], pages: str = "pages") -> None:
    """The flags every driver takes."""
    ap.add_argument("--status", action="store_true", help="list every step and whether it is done")
    ap.add_argument("--dry", action="store_true", help="print the next command instead of running it")
    ap.add_argument("--until", choices=names, help="stop after this step")
    ap.add_argument("--redo", choices=names, help="run this step again even if its output exists (steps that "
                                                  "depend on it run again too)")
    ap.add_argument("--publish", action="store_true", help=f"also deploy the {pages} (publish --deploy) at the end")
