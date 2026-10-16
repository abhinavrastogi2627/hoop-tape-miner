# Pipeline

Local pipeline that turns one amateur basketball game video into a tactical scouting report. Developed on a single 8 GB NVIDIA GPU. All stages run through `uv run hoop-tape-miner <stage> ...`. Per-game data lives in the workspace (`$HOOP_WORKSPACE`, default `./workspace`, gitignored): `workspace/teams/<opponent-slug>/<date>/` holds `game.json`, the heavy `run/` folder and the finished report. The step-by-step procedure is `docs/playbook.md`.

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
| Output | metrics, matplotlib figures, agent-written reports, edge-tts narration, single-file HTML |

## Stages (in order)

| Stage | Required args [optional] | Output |
|---|---|---|
| `new-game` | `--opponent --date` [`--video --us-team --force`] | `workspace/teams/<slug>/<date>/game.json` (from `templates/game.example.json`), `run/`, opponent dossier README |
| `calibrate` | `--video --times --out` [`--points --propagate --step`] | `<out>/keyframes.json` (hand-picked court landmarks), `points.json`, overlays |
| `extract` | `--video --out --calib` [`--fps 10 --start --end`] | per-frame detections (pickle), homographies (`camera.npz`) |
| `recalib` (optional) | `--run --video --calib` [`--start --end --dry`] | court homography re-run, court coordinates recomputed |
| `embed` | `--run --video` [`--batch`] | SigLIP embeddings of on-court person crops |
| `tracks` | `--run --video` [`--game --us --fps`] | pass 1: `cluster_montage.jpg`; pass 2 (after `cluster_names.json` with `us`/`them`/`ref`/`unk`): `tracks.pkl` |
| `jersey` | `--run --video` [`--min-len --limit`] | jersey number per tracklet (VLM, voting) |
| `analyze` | `--run --game` [`--fps`] | identities, possessions, tactical metrics |
| `official` (optional) | `--boxscore --pointchart --us-home --out` [`--video --official-video --fps`] | `official.json`: box score, score flow, video alignment (one league JSON format for now) |
| `review` (optional) | `--run --video` [`--every --pad --game`] | `run/review/`: 3x2 event sheets + manifest (`docs/review_protocol.md`) |
| `merge-reviews` (optional) | `--run` [`--review review`] | `events.json`, `review_coverage.json` from `events_part*/coverage_part*` |
| `coach-sheets` | `--run --game --out` [`--official` (auto-found, optional) `--parts --video --brief --skip-sheets`]; `coach-sheets zoom SHEET TILE X Y W H OUT` | 2x2 coach sheets, `manifest.json`, `part<N>.json`, `lineup_intervals.json`, `brief_part<N>.md` |
| `coach-summary` | `--review` [`--segments --out`] | per-stretch coach numbers from `coach_part*.json` (`summary.json`) |
| `plusminus` | `--lineup --official --out` [`--player --team --event-times --merge-gap --windows`] | per-player stints and on/off score (json + markdown table) |
| `report` | `--run --out` [`--game --focus --lang en|zh --events --coverage`] | figures + `stats.json` (English labels by default) |
| `momentum` | `--official --out` [`--game --lineup --players --lang en|zh --stretches --min-run --title`] | score-margin chart with detected scoring runs and on-court lanes |
| `replay` (optional) | `--run --out` [`--pid --t0 --t1 --fps --game`] | 2D tactics-board clips (mp4) |
| `narrate` | `FOLDER` or `--script FILE` [`--lang zh en --out --gap --chime --loud --rate`] | `listen.<lang>.mp3` per script, or one MP3 next to `--script` |
| `clips` | `FOLDER` [`--video --height --force`] | `clips/<from>-<to>.mp4` + poster for every `![caption](clip:mm:ss-mm:ss)` in the READMEs |
| `html` | `FOLDER` [`--out index.html --share`] | bilingual `index.html` with clip players (`--share`: self-contained copy with audio and clips embedded) |
| `publish` | `FOLDER...` [`--deploy --project --base-url --new-link`] | `<workspace>/site/<token>/` per report (web page + audio + clips), a hub of team reports, `<workspace>/publish.json`; `--deploy` uploads with `npx wrangler deploy` (static assets behind `publish_worker.js`, which serves Range requests for Safari) to `<project>.<subdomain>.workers.dev` |

`uv run hoop-tape-miner <stage> -h` is authoritative; `docs/playbook.md` shows each stage with real paths. Team names, colours (`us.hex` / `them.hex`), focus player, periods, rosters, result and narration voices come from `game.json`.

Current limits: the HTML page and narration handle exactly two languages, Chinese (`README.md`, `listen.zh.md`) and English (`README.en.md`, `listen.en.md`); `official` reads one league's box-score/point-chart JSON format; court dimensions are FIBA.

## Key design decisions

- **Court space first.** The camera pans and zooms, so everything is projected to metres on a FIBA court (x 0-28, y 0-15). The per-frame homography comes from optical flow (background only, players masked), snapped to painted lines to kill drift, with SIFT relocalisation against calibrated keyframes when tracking is lost.
- **Team clusters are named once.** KMeans on SigLIP embeddings is unsupervised; one look at the montage tells which cluster is us, them and the referees.
- **Possessions from positions, not the ball.** The camera follows the ball, so the half occupied by the ten players tells where play is; the offence is the side standing further from the basket.
- **Agents for meaning, CV for geometry.** CV gives positions, lineups and segment boundaries; actions, results, fouls and coaching judgement come from film review against a fixed checklist, checked against official totals when a league feed exists.
- **Reports from fact sheets.** Agents write prose only from structured facts (`players_facts.md`, `player<N>_facts.md`) built from the merged review, so every claim traces back to a video time.

## Interpreting outputs

The automatic "possessions" are half-court activity segments, not official ball possessions. Visual review regularly finds dead balls, timeouts, wrong offence assignments and multiple real possessions inside single segments; the coach review splits them into trips. Use their spatial aggregates as estimates. Position-share plots average each segment equally; they do not represent field-goal attempts or full-game player-time percentages.

Player tracking coverage counts the union of recognised frames. Simultaneous tracklets with the same jersey number are omitted from player movement and heatmaps. Coverage still includes possible OCR errors and dead-ball samples, so it is not minutes played; minutes in reports are lower-bound estimates from lineups and observed substitutions. Unknown shot outcomes remain null and are displayed separately; low-confidence outcomes never become confirmed makes or points.
