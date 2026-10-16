# hoop-tape-miner (agent instructions)

Turns one amateur basketball game into two deliverables: the team page and the focus player's page (bilingual HTML with narration audio and film clips, published as private links), and an explained video per language (a file the user sends themselves, never published).

- When the user gives a league game link or a game folder, drive `uv run hoop-tape-miner run <link|folder>` in a loop as `docs/playbook.md` "One-command run" describes (Claude Code: `/game <link>`). Exit 3 = do the agent step it names, then run again; exit 1 = fix and run again; publish only with `--publish` after QA passes.
- Procedure and each step: `docs/playbook.md`. Stage details: `docs/pipeline.md`.
- Team profile (our team, focus player, league secrets file, languages): `workspace/team.json`, from `templates/team.example.json`.
- Writing: use the guides in `prompts/` (film review brief, coach report, player deep dive, narration, explained video; opponent dossier and court cues are optional extras).
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
