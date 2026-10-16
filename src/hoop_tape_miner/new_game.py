"""Scaffold a new game in the workspace: game.json from templates/, run/ for heavy outputs, optional opponent dossier.

usage: hoop-tape-miner new-game --opponent "Red Foxes" --date 2026-10-14 [--video PATH] [--us-team NAME] [--dossier]
       [--force]
Creates <workspace>/teams/<opponent-slug>/<date>/{game.json, run/} (workspace = $HOOP_WORKSPACE or ./workspace);
with --dossier also <workspace>/teams/<opponent-slug>/README.md. An existing game.json / README.md is never
overwritten unless --force.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from . import workspace

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"


def template(name: str) -> Path:
    p = TEMPLATES / name
    if not p.exists():
        raise SystemExit(f"template {p} not found (run from a clone of the repo, installed with `uv pip install -e .`)")
    return p


def make_game(opponent: str, date: str, video: str | None = None, us_team: str | None = None,
              run: str | Path | None = None) -> dict:
    game = json.loads(template("game.example.json").read_text(encoding="utf8"))
    game["name"] = f"{date} vs {opponent}"
    game["them"]["team"] = opponent
    if us_team:
        game["us"]["team"] = us_team
    if video:
        game["video"] = str(Path(video).expanduser().resolve())
    if run:
        game["run"] = str(Path(run).expanduser().resolve())
    return game


def scaffold(opponent: str, date: str, video: str | None = None, us_team: str | None = None,
             force: bool = False, dossier: bool = False, run: str | Path | None = None) -> Path:
    """Game folder with game.json; run/ goes to `run` (stored in game.json) or <folder>/run."""
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        raise SystemExit(f"--date must be YYYY-MM-DD, got {date!r}")
    if not workspace.slug(opponent):
        raise SystemExit("--opponent must not be empty")
    folder = workspace.game_dir(opponent, date)
    folder.mkdir(parents=True, exist_ok=True)
    Path(run or folder / "run").expanduser().mkdir(parents=True, exist_ok=True)
    gj = folder / "game.json"
    if gj.exists() and not force:
        print("kept existing", gj)
    else:
        gj.write_text(json.dumps(make_game(opponent, date, video, us_team, run), indent=2, ensure_ascii=False) + "\n",
                      encoding="utf8")
        print("wrote", gj)
    if dossier:
        readme = folder.parent / "README.md"
        if readme.exists() and not force:
            print("kept existing", readme)
        else:
            text = template("team-readme.md").read_text(encoding="utf8")
            readme.write_text(text.replace("{opponent}", opponent).replace("{date}", date), encoding="utf8")
            print("wrote", readme)
    return folder


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner new-game", description=__doc__.splitlines()[0])
    ap.add_argument("--opponent", required=True, help='opponent team name, e.g. "Red Foxes"')
    ap.add_argument("--date", required=True, help="game date YYYY-MM-DD")
    ap.add_argument("--video", help="path to our game video (stored in game.json)")
    ap.add_argument("--us-team", help="our team's display name")
    ap.add_argument("--dossier", action="store_true",
                    help="also create the opponent dossier <workspace>/teams/<opponent-slug>/README.md")
    ap.add_argument("--force", action="store_true", help="overwrite an existing game.json / dossier README.md")
    a = ap.parse_args(argv)
    folder = scaffold(a.opponent, a.date, a.video, a.us_team, a.force, a.dossier)
    run = folder / "run"
    video = a.video or "<video>"
    print(f"""
Next steps:
  1. Edit {folder / 'game.json'}: team names, periods (seconds of our video), rosters, optional hex colours.
  2. Calibrate the court (keyframes.json), then run the CV passes into {run}:
       hoop-tape-miner extract --video {video} --out {run} --calib <keyframes.json>
       hoop-tape-miner embed   --run {run} --video {video}
       hoop-tape-miner tracks  --run {run} --video {video} --game {folder / 'game.json'}
       hoop-tape-miner jersey  --run {run} --video {video}
       hoop-tape-miner analyze --run {run} --game {folder / 'game.json'}
  3. Review, write README.md / README.en.md in {folder}, then:
       hoop-tape-miner html {folder}
  Run `hoop-tape-miner <stage> -h` for each stage's options.""")


if __name__ == "__main__":
    main()
