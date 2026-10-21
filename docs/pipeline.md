# Pipeline

Local pipeline that turns one amateur basketball game into a coach's team page, a focus-player page and an explained video. Developed on a single 8 GB NVIDIA GPU. All stages run through `uv run hoop-tape-miner <stage> ...`. Per-game data lives in the workspace (`$HOOP_WORKSPACE`, default `./workspace`, gitignored): `workspace/teams/<opponent-slug>/<date>/` (slug: lowercase letters and digits joined by `-`, safe on Windows) holds `game.json` and the finished reports; the heavy `run/` folder sits there too, or under `media_root` from `workspace/team.json` (game.json `run`). `run` drives every stage below in order and stops where the agent must judge. The step-by-step procedure is `docs/playbook.md`.

## Why a custom pipeline

No single open-source basketball repo was enough (details and sources in `docs/research.md`):

- `roboflow/sports` (feat/basketball) and the Roboflow basketball notebooks are the closest, but rely on hosted Roboflow models plus SAM2 at 1-2 fps, which is too slow and cloud-bound for a full game.
- `abdullahtarek/basketball_analysis` (MIT per its README) is a useful reference implementation; no code is copied from it.
- NBA-trained court keypoint models failed on amateur gyms (different floors, lighting, markings).

So we reuse the good parts (SigLIP+UMAP+KMeans team recipe, ByteTrack, RF-DETR) and build court registration, jersey reading and possession logic ourselves.

## Stack

| Concern | Choice |
|---|---|
| Person detection | RF-DETR-L (COCO, class person) |
| Ball detection | HF `koppolusameer/rfdetr-medium-basketball-playerexpanded-referee-detection` |
| Court registration | FIBA court model + line-mask (top-hat) alignment + optical-flow propagation + SIFT keyframe relocalisation (`court.py`, `camera.py`) |
| Team classification | SigLIP embeddings + UMAP + KMeans, one-time cluster naming (roboflow/sports `TeamClassifier` recipe) |
| Tracking | ByteTrack (roboflow/trackers) in court space |
| Jersey numbers | Qwen3-VL-4B (4-bit) OCR, per-tracklet voting, roster-gated |
| Possessions | half-court occupancy + "offence stands further from the basket" signal |
| Film review | frame sheets reviewed by vision-LLM subagents against a coach checklist (`prompts/film_review_brief.md`) |
| Output | metrics, matplotlib figures, agent-written reports, edge-tts narration, explained video (ffmpeg + libass subtitles), single-file HTML |

## Stages (in order)

| Stage | Required args [optional] | Output |
|---|---|---|
| `run` | `TARGET` (game folder or league game url) [`--status --dry --until --redo --publish --refetch`] | every stage below in order, resuming from existing outputs (a url of a game already fetched reuses its folder); exit 3 when an agent step is due, 1 on a failed stage; publishes only with `--publish` |
| `fetch` | `URL` [`--video --us-team --secrets --no-video --force`] | Glory League game: `game.json` (teams, rosters, result, periods, league id), `run/official.json`, the league video in `<media>/video/league.mp4` (resumable), raw responses in `<media>/league/` |
| `new-game` | `--opponent --date` [`--video --us-team --dossier --force`] | `workspace/teams/<slug>/<date>/game.json` (from `templates/game.example.json`), `run/`; `--dossier` also the opponent README |
| `calibrate` | `--video --times --out` [`--grid --points --propagate --step --detections --max-point-err`] | `--grid`: `grid_<t>.jpg` (pixel grid + numbered landmark map) to read without a GUI; `--points`: solve points.json, print PASS/WEAK per frame (exit 2 if weak); without either, click in a window. `<out>/keyframes.json`, overlays |
| `extract` | `--video --out --calib` [`--fps 10 --start --end`] | per-frame detections (pickle), homographies (`camera.npz`, with `fps`: the rate actually sampled, video fps / the whole-frame step closest to `--fps`; `tracks`, `analyze` and `report` read it, old runs fall back to 10) |
| `recalib` (optional) | `--run --video --calib` [`--start --end --dry`] | court homography re-run, court coordinates recomputed |
| `embed` | `--run --video` [`--batch`] | SigLIP embeddings of on-court person crops; incremental, and cached rows that no longer match detections.pkl (a new extract) are dropped and re-embedded (`tracks` refuses stale ones) |
| `tracks` | `--run --video` [`--game --us --fps`] | pass 1: `cluster_montage.jpg`; pass 2 (after `cluster_names.json` with `us`/`them`/`ref`/`unk`): `tracks.pkl` |
| `jersey` | `--run --video` [`--min-len --limit`] | jersey number per tracklet (VLM, voting) |
| `analyze` | `--run --game` [`--fps`] | identities (roster numbers compared as strings), possessions, tactical metrics; attack direction decided once per half (periods 1-2 / 3+ with quarters); a half with no signal takes the other half's switched with a warning, no signal at all stops with an error |
| `official` (optional; `fetch` does this for league links) | `--boxscore --pointchart --us-home --out` [`--video --official-video --fps`] | `official.json`: box score, score flow, video alignment (one league JSON format for now) |
| `review` (optional) | `--run --video` [`--every --pad --game`] | `run/review/`: 3x2 event sheets + manifest (`docs/review_protocol.md`) |
| `merge-reviews` (optional) | `--run` [`--review review`] | `events.json`, `review_coverage.json` from `events_part*/coverage_part*` |
| `coach-sheets` | `--run --game --out` [`--official` (auto-found, optional) `--parts --video --brief --skip-sheets`]; `coach-sheets zoom SHEET TILE X Y W H OUT` | 2x2 coach sheets, `manifest.json`, `part<N>.json`, `lineup_intervals.json`, `brief_part<N>.md` |
| `coach-sheets event` | `--run --video --review --official --out` [`--fps 4 --pre 35 --post 6 --game --limit`] | fact-check sheets at 4 fps around each official score event and reviewed foul (overlapping windows merged; candidate shooter/fouler boxed thick: that team's player nearest a rim), `ev<NN>_<k>.jpg`, `event_NN.md` (narrow questions), `events.json` |
| `coach-check` | `--review` [`--migrate OUTDIR`] | validates every `coach_part*.json` against trip schema v2 (result enum, `shot`/`fts`/`foul` objects, evidence times); exit 1 with the error list. `--migrate` writes v1 parts as v2 into OUTDIR (free text kept in `result_v1`, `shooter_note`, `by_note`) and validates them. `run` counts a review part as done only when it passes |
| `coach-features` | `--run --review` [`--out --back-offset`] | `<review>/features.json`: per trip, from the court tracks, `numbers_back_2s` (defenders on their own half 2 s after the trip starts, capped at 5), offensive spacing and hull area, paint crowd, standstill share, half-court crossing time (`null` = unknown); `<review>/ball_quality.json` (ball coverage and gaps, raw vs cleaned). Ball-based fields are not produced: on the reference game only ~0.3 of cleaned ball boxes were the game ball |
| `coach-sheets event-merge` | `--review --events --out` | new review folder: `--review` copied with each `event_NN.answer.json` merged into the v2 trips (answers need confidence high/medium and an evidence time; earlier values kept in `*_v2m`; unmatched answers logged, no trip created) and `event_merge.md` (change log) |
| `coach-summary` | `--review` [`--segments --out`] | per-stretch coach numbers from `coach_part*.json` (`summary.json`) |
| `coach-insights` | `check --review` [`--kb --insights`]; `ab --review --out` [`--old-report --insights --seed --cap`] | `check`: validates `insights.json` (each insight: >= 2 evidence times, every cited time inside a trip with 3 s slack, known `prompts/coach_kb.md` slugs, `numbers` equal to `summary.json` / `features.json` by dotted name, claim/why/rule/drill/target filled, critic verdict keep or revise); exit 1 with the error list. `run` counts the insights step done only when it passes. `ab`: blind rating sheet (memo conclusions vs insights, sets A/B at random, equal count and format) plus `<out>.key.json` |
| `coach-eval` | `--review --label` [`--official --insights`] | `<review>/eval/<label>.json` + a line in `eval/log.md`: points recall/precision vs the score flow, per-player PTS/PF error vs the box score, official events matched one-to-one (shots and free throws apart), invalid result share (v2 trips: any coach-check error); `--insights` lints conclusions (evidence times, why, drill, target) |
| `plusminus` | `--lineup --official --out` [`--player --team --event-times --merge-gap --windows`] | per-player stints and on/off score (json + markdown table) |
| `report` | `--run --out` [`--game --focus --lang en|zh --events --coverage`] | figures + `stats.json` (English labels by default) |
| `momentum` | `--official --out` [`--game --lineup --players --lang en|zh --stretches --min-run --title`] | score-margin chart with detected scoring runs and on-court lanes |
| `replay` (optional) | `--run --out` [`--pid --t0 --t1 --fps --game`] | 2D tactics-board clips (mp4) |
| `narrate` | `FOLDER` or `--script FILE` [`--lang` (default: every listen.<lang>.md present) `--out --gap --chime --loud --rate --tight`] | `listen.<lang>.mp3` per script, or one MP3 next to `--script`; `--tight` trims TTS silence around each paragraph so `--gap` is the real pause (cue loops) |
| `clips` | `FOLDER` [`--video --height --force`] | `clips/<from>-<to>.mp4` + poster for every `![caption](clip:mm:ss-mm:ss)` in the READMEs |
| `film` | `FOLDER` [`--lang zh en --video --run --height 720 --crf 23 --font --scenes A-B --dry`] | `film.<lang>.mp4`: narration from `film.<lang>.md` over chapter cards, figures, stat scenes, animated court diagrams (`plays/*.json`) and clips of our video, with freeze frames that ring players from `run/tracks.pkl` and burned-in subtitles; speech cached in `.film-cache/` |
| `html` | `FOLDER` [`--out index.html --share`] | `index.html` in the languages whose README is present (switch when both) with clip players (`--share`: self-contained copy with audio and clips embedded) |
| `train` | `TARGET...` (phone videos, or a session folder) [`--player --date --name --plan --status --dry --until --redo --publish`] | one personal training session end to end, like `run`: `train-new` on videos, then the training steps below, resuming; exit 3 when an agent step is due (rim boxes, film review, writing, QA) |
| `train-new` | `VIDEO...` [`--player --date --name --plan --height 1080`] | `<workspace>/players/<player>/training/<date>[-n]/session.json` (sources with start offsets, targets copied from the previous `plan.json`) and the joined `session.mp4` (rotation applied, 30 fps; under `media_root` when set) |
| `train-scan` | `FOLDER` [`--fps 15 --seed x,y --no-ball --force`] | `run/pose.npz` (yolo11s-pose keypoints of the main person, ball centre from yolo11s), `reps.json` (shot/finish candidates with knee bend, elbow angles, dip-to-release, jump, travel), `dribble.json` (bounce segments per hand), `activity.json` |
| `train-sheets` | `FOLDER` [`--probe --reps-per-part 50 --force`] | `--probe`: `run/train_review/rim_probe.jpg` (four frames with a 0.1 grid); then overview, rep (set / release / follow-through crops, rim filmstrip, wide frame) and dribble sheets, `manifest.json` and `brief_part<N>.md` from `prompts/training_review_brief.md` (needs `rim_checked`; refuses to rebuild over review_part*.json without `--force`) |
| `train-summary` | `FOLDER` | from `review_part<N>.json` + pose metrics: `summary.json`, `facts.md`, figures `zones` / `timeline` / `form` / `progress` (`.png` zh, `.en.png`), targets checked, progress over earlier sessions |
| `move` | `FOLDER` or `--spec segments.json` [`--player --date --name --plan --look --status --dry --until --redo --publish`] | one movement session end to end, like `train`; exit 3 when an agent step is due (identity, label check, review, writing, QA) |
| `move-new` | `--spec FILE` or `VIDEO... --kind --view` [`--player --date --name --plan --look --into FOLDER`] | `<workspace>/players/<player>/movement/<date>[-n]/movement.json` (segments: kind, view, source window, release, slowmo, seed, anchor, follow, who) and `reel.mp4` (every window letterboxed to 1280x720 at 30 fps, `reel_from` / `reel_to` per segment) |
| `move-scan` | `FOLDER` [`--force --repick --only S01,S03`] | per segment at native fps (cap 120 real fps): `run/seg/<id>.raw.npz` (every person and ball), `<id>.npz` (the player: the `who` pick followed both ways with clothing colour, else ball holder at the anchor, else seed / largest), `gait/<id>.json` (contacts, per-step trunk, shin, touchdown, contact time, cadence; layup and dribble metrics; `measurable` = side view; `crowded`), `gait.json`; `move_review/who_<id>.jpg` + `who.json` for crowded segments |
| `move-sheets` | `FOLDER` [`--group-size 8 --force`] | `reel.overlay.mp4` (skeleton on the reel), `move_review/keys_<id>.jpg`, `strip_<id>.jpg` (side view), `brief_<g>.md` from `prompts/movement_review_brief.md`, `manifest.json` |
| `move-summary` | `FOLDER` | label check against `labels.json`, findings merged from `review_<g>.json`, gated metrics against `movement.REFERENCE` bands, progress: `summary.json`, `facts.md`, figures `faults` / `metrics` (`.png` zh, `.en.png`) |
| `publish` | `FOLDER...` [`--deploy --project --base-url --new-link`] | `<workspace>/site/<token>/` per report (web page + audio + clips), a hub of team reports, `<workspace>/publish.json`; `--deploy` uploads with `npx wrangler deploy` (static assets behind `publish_worker.js`, which serves Range requests for Safari) to `<project>.<subdomain>.workers.dev` |

`uv run hoop-tape-miner <stage> -h` is authoritative; `docs/playbook.md` shows each stage with real paths. Team names, colours (`us.hex` / `them.hex`), focus player, periods, rosters, result and narration voices come from `game.json`.

Current limits: the HTML page and narration know two languages, Chinese (`README.md`, `listen.zh.md`) and English (`README.en.md`, `listen.en.md`); team.json `languages` picks both (default) or one, and the drivers, `narrate` (default: the scripts present) and `html` (only the READMEs present, no switch for one) follow it; `official` reads one league's box-score/point-chart JSON format; court dimensions are FIBA.

## Key design decisions

- **Court space first.** The camera pans and zooms, so everything is projected to metres on a FIBA court (x 0-28, y 0-15). The per-frame homography comes from optical flow (background only, players masked), snapped to painted lines to kill drift, with SIFT relocalisation against calibrated keyframes when tracking is lost; a frame with no pose stores a NaN homography (its detections get no court position) rather than the last pose.
- **Team clusters are named once.** KMeans on SigLIP embeddings is unsupervised; one look at the montage tells which cluster is us, them and the referees.
- **Possessions from positions, not the ball.** The camera follows the ball, so the half occupied by the ten players tells where play is; the offence is the side standing further from the basket.
- **Agents for meaning, CV for geometry.** CV gives positions, lineups and segment boundaries; actions, results, fouls and coaching judgement come from film review against a fixed checklist, checked against official totals when a league feed exists.
- **Reports from fact sheets.** Agents write prose only from structured facts (`players_facts.md`, `player<N>_facts.md`) built from the merged review, so every claim traces back to a video time.

## Interpreting outputs

The automatic "possessions" are half-court activity segments, not official ball possessions. Visual review regularly finds dead balls, timeouts, wrong offence assignments and multiple real possessions inside single segments; the coach review splits them into trips. Use their spatial aggregates as estimates. Position-share plots average each segment equally; they do not represent field-goal attempts or full-game player-time percentages.

Player tracking coverage counts the union of recognised frames. Simultaneous tracklets with the same jersey number are omitted from player movement and heatmaps. Coverage still includes possible OCR errors and dead-ball samples, so it is not minutes played; minutes in reports are lower-bound estimates from lineups and observed substitutions. Unknown shot outcomes remain null and are displayed separately; low-confidence outcomes never become confirmed makes or points.
