# hoop-tape-miner (agent instructions)

Turns one amateur basketball game video into a coach report: CV pipeline, agent film review, written reports, narration and a single-page HTML.

- Procedure: follow `docs/playbook.md` step by step (video -> report). Stage details: `docs/pipeline.md`.
- Sharing: publish a stable link per report (`publish --deploy`, playbook step 14); a `--share` file is the fallback.
- Writing: use the guides in `prompts/` (film review brief, coach report, player deep dive, opponent dossier, narration, explained video, court cues).
- Personal data lives in `$HOOP_WORKSPACE` (default `./workspace`, gitignored); one game = `workspace/teams/<opponent-slug>/<date>/`.

## Working rules

- One game per session. Read `git status` and the game's `game.json` first; reuse an existing `run/`, do not re-run the CV pass.
- Long runs: redirect output to `workspace/logs/*.log` and read only the tail.
- Parallel helpers (if your tool has them): at most 3 at once, one review part each; they write files and reply in a few lines.
- Browser checks and screenshots: delegate to a separate helper if available; keep images out of the main context.
- Never invent a game result; write "unclear" or "likely" instead.

## Changing the code

- Setup and tests: `uv sync`, then `uv run pytest -q` (fast, no GPU or video). Without CUDA, see the CPU install in `CONTRIBUTING.md`.
- One module per CLI stage in `src/hoop_tape_miner/`; register new stages in `cli.py`.
- Add or update tests for behaviour changes, update docs and `CHANGELOG.md` (*Unreleased*) when users would notice.
- Follow `CONTRIBUTING.md` for branches and pull requests; it wins over this file on conflict.

## Privacy (see `docs/privacy.md`)

- Never commit or push `workspace/`, videos, frames, audio, rosters, names or official stats. Check `git status` before any commit.
- Never print or commit credentials; read them from a secrets file outside the repo.
- Players may be minors: frames of players are shared only with the team, with consent.
