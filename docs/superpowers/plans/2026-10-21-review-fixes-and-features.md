# Review fixes and features (2026-10-21)

Source: a deep code review and a web research pass (notes kept outside the repo, they cite real game data).
Each batch runs as up to 3 agents in separate git worktrees; the coordinator merges them into master, runs the
full test suite after each merge and updates `CHANGELOG.md` (*Unreleased*).

Rules for every task: TDD (failing test first), follow the surrounding code style, no real names, opponents,
local paths or game data in code, tests or docs; never re-run the full `extract` CV pass; long runs log to
a logs folder outside the repo.

## Batch 1: correctness and security fixes

- **1A run loop / CV numerics**: `run <url>` must not overwrite an existing `run/official.json` alignment
  (reuse the folder when the game already exists); one sampling rate recorded by `extract` and read downstream
  instead of hard-coded 10 fps; `--until` stops when the step is already done (game / train / move drivers);
  `analyze` normalises roster numbers to strings and fails loudly (or uses the official flow) when the
  attack direction is NaN, decided per half; embedding cache keyed by a detection fingerprint; slug-safe
  Windows paths from team names; `train-sheets --force`; `languages` from the team profile instead of
  hard-coded zh+en; stale homography when the camera tracker is lost.
- **1B publish / security**: registry written atomically and only after a successful deploy; QA PASS bound
  to a hash of the checked files; markdown rendered with raw HTML off or sanitised; referenced files must stay
  inside the report folder; security headers (CSP, nosniff, referrer, noindex) in the Worker; `PYTHONUTF8`
  for subprocesses.
- **1C movement / training validity**: slow-motion gate tolerances in source time; unlabelled clips do not
  inherit "validated"; `who` picks re-pick the track before later steps.

## Batch 2: report features

- **2A Four Factors + possession-type PPP** (eFG%, TOV% live/dead, ORB%, FT rate; transition / half-court /
  second chance / after live-ball TO) with the "factor that decided the game" line; schema fields
  `transition`, `turnover_kind`.
- **2B shot chart + playlists**: clickable zone shot chart from reviewed trips (filter by player / half,
  dot opens the clip); automatic per-player and per-theme playlists on the published pages.
- **2C honest coach gates**: pid coverage per part, unresolved numbers fail, real orphan check, critic not
  self-certified, `coach-eval` as a run step.

## Batch 3: shared pipeline core

- `pipeline.py` (step table, driver, exit 3 / exit 1 protocol), `media.py` (ffmpeg / probe / atomic writes),
  `timefmt.py`; provenance-based `fresh()` (inputs + params hash) replacing existence-only done checks in the
  game, train and move drivers.

## Batch 4: CV quality

- **4A identity**: tracking metric tooling (MOT-format labels for short clips, IDF1 / HOTA via a library) and
  proxy metrics on existing runs; joint tracking of both teams; GTA-style tracklet split / merge on
  `tracks.pkl`; at most 5 per team; jersey legibility gate, pose torso crop and confidence voting.
- **4B ball**: ball-track cleanup and shot-attempt proposals from the ball arc, labelled by the official
  point chart; ball trail and attempt markers on review sheets.

## Batch 5: season-level features

- **5A season hub**: per-season page (results, Four Factors trends, goals from the last game checked,
  pooled on/off with shrinkage, lineup net per 10 min with shrinkage); pre-game brief.
- **5B opponent scouting + game-to-training loop**: rematch dossier from past games and league data;
  next training targets seeded from the last game; game vs practice make rates.
- **5C load and matchups + sharing**: per-stint distance / sprints / top speed; defender distance at shot and
  matchup table; 9:16 per-player reels; telestration on clip posters.

## Not done now (with reason)

- Event-spotting model trained on our own games: needs about 10 reviewed games as labels.
- SAM 2 / SAM 3 masks: low value for the cost on this camera.
- Fine-tuned jersey classifier: needs labelled crops from more games; the gate / crop / voting comes first.
