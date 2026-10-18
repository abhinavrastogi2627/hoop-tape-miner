# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Personal training sessions: `train <phone videos>` (Claude Code: `/train`) turns one player's solo workout into a session page, an explained video and `plan.json` for next time. New stages `train-new` (joins the phone files), `train-scan` (YOLO pose and ball: shot and finish candidates with knee bend, elbow angles, dip-to-release and jump; dribble segments), `train-sheets` (rim probe, rep sheets with a rim filmstrip, briefs) and `train-summary` (percentages by zone, spot, type and hand, miss directions, form for makes vs misses, dribbling, last session's targets checked, progress over sessions, figures). Agents judge make or miss and write the report with `prompts/training_review_brief.md` and `prompts/training_report.md`. `html` shows a training band instead of the score, `film` a training title card, and `publish` gives a session its own link without listing it on the team hub.
- `coach-features` stage (run step `features`, after the film review): per-trip numbers measured from the court tracks (players back on defence 2 s into the opponent's trip, offensive spacing, paint crowd, standing still, time to cross half court) in `features.json`, and a ball-track quality report. The insights writer quotes these numbers and `coach-insights check` verifies them.
- `coach-sheets event`: fact-check sheets at 4 fps around each official score event (reaching back over the league feed's 10-30 s lag) and each reviewed foul, with the likely shooter or fouler boxed thicker and a short question file per window (who shot, made, 2/3/FT, foul by/on/type), so a reviewer can confirm the facts on just the frames that matter. `coach-sheets event-merge` writes a new review folder with those answers merged into the trips (earlier values kept) and a change log.
- Coaching insights step with a critic: after the summary, `run` waits for `insights.json`, written by a writer subagent (`prompts/coach_insights.md`: patterns seen on at least two trips, the mechanism from the coaching knowledge base, one rule, one drill, a measurable next-game target) and checked by a critic subagent (`prompts/coach_critic.md`) that re-opens the cited sheets and drops what the film does not show. The new `coach-insights check` rejects evidence times outside any trip, unknown knowledge-base entries, numbers that differ from `summary.json` and insights without a critic verdict; `coach-insights ab` builds a blind A/B rating sheet against the memo conclusions. The coach report's conclusions and practice plan now come from `insights.json`. Optional team-profile key `coach_library` points the writer to a local folder of coaching texts.
- `coach-eval` stage: scores a film review against the league feed (points recall and precision against the score flow, per-player points and fouls against the box score, result values outside the brief) and lints coaching conclusions for evidence times, reasons, drills and targets. Results go to `<review>/eval/<label>.json` and a running `eval/log.md`, so each change to the coach review can be compared with the last.
- `coach-check` stage and trip schema v2: film-review trips use a fixed `result` list plus `shot`, `fts` and `foul` objects with jersey fields and evidence times; `coach-check` lists every invalid trip, and `--migrate` converts v1 reviews without losing their free text. `run` treats a review part as done only when it passes, the brief asks reviewers to run the check before replying, and `coach-eval` / `coach-summary` read v2 (`coach-eval` also reports official shot and free-throw events matched one-to-one).
- One-command run: `run <league game url | game folder>` drives every stage in order, resumes from the outputs that exist, stops with exit 3 where the agent must judge (calibration points, cluster names, film review, writing, QA) and publishes only with `--publish`. Claude Code users type `/game <url>`.
- `fetch` stage: reads a Glory League game (teams, rosters, final and halftime score, periods, box score, score flow) over its API, downloads the league video (resumable) and writes `game.json` and `official.json`. Our team, focus player, colours, languages and the league secrets file come from a team profile `workspace/team.json` (`templates/team.example.json`); heavy files can live under its `media_root`.
- Calibration without a GUI: `calibrate --grid` writes frames with a pixel grid and a numbered landmark map for an agent to read; `calibrate --points` solves them and prints PASS/WEAK per frame with the worst points (exit 2 while any frame is weak).
- `film --crf` (default 23) and a poster `film.<lang>.jpg` next to each explained video.
- Film clips in reports: mark a play with `![caption](clip:mm:ss-mm:ss)`, cut it with the new `clips` stage, and the HTML page shows a numbered player with a slow-motion button next to the analysis (embedded in `--share` files). Writing guides say which plays deserve a clip.
- Explained video: the new `film` stage turns `film.<lang>.md` into one MP4 where the narration plays over chapter cards, charts and the report's clips, with burned-in subtitles; clips replay at half speed when the explanation is longer than the play. Writing guide: `prompts/film.md`. The film can freeze a clip and draw on it: `> 07:28 我#17 对#25 "label"` dims the frame, rings the players (found in the CV tracks, or placed by hand) and adds arrows. It also has animated court diagrams (`![caption](court:plays/x.json)`), big-number stat scenes (`stat:`) and chapter cards over blurred game footage (` · ` splits a title into lines). A `>` line on its own resumes the clip while the narration goes on. Speech has its trailing silence trimmed, so scene changes no longer pause.
- `publish` stage: builds a private-link website from report folders (audio and clips as files, no local paths) and deploys it to Cloudflare (Workers static assets) for free with `--deploy`. Each report keeps one random URL across updates, and team reports are listed on a hub page.

### Changed

- Default deliverables are the team page, the focus player's page (with narration and clips) and the explained video; the opponent dossier, court cues, replay, CV figures, event review and the single-file share are optional extras. `new-game` creates the opponent dossier only with `--dossier`.
- The playbook starts with the one-command run; step numbers changed.
- HTML pages carry `noindex, nofollow`.
- Coaching knowledge base checked page by page against its sources: the press-break entry now separates trap/zone presses (three passing options) from man-to-man presses (clear out, or a forward cuts back), page references were corrected (pick-and-roll show, help the helper, pack-line weaknesses, last-possession timing), Free Throw Golf scoring was fixed, and the team's own rules and all target and success numbers are labelled as "our rule" / trial values. The audience is an adult rec team.

### Fixed

- `film --video` with a relative path failed in ffmpeg; the path is now resolved first.
- The listen label said "About 0 min" for audio under 30 s.
- `calibrate --propagate` tracks targets before the start keyframe backward (they silently got the start frame's homography).
- `recalib` no longer stops with a NameError at its first progress line.
- `run`'s momentum step finds `lineup_intervals.json` in `run/` when the review folder has none (older runs wrote it there).

## [0.1.0] - 2026-10-16

### Added

- First public release as **hoop-tape-miner** (developed as gem-in-game).
- CV pipeline: detection, court homography, team split, tracking, jersey numbers, possessions and lineups.
- Agent film review: annotated sheets, review merge and per-segment summaries.
- Reports: bilingual coach report, player reviews, charts, plus-minus, momentum, narration MP3 and a single shareable HTML page.
- Contributor docs, issue forms and CI tests.

### Changed

- Renamed the package to `hoop_tape_miner`, the CLI to `hoop-tape-miner` and the workspace variable to `HOOP_WORKSPACE`.

[Unreleased]: https://github.com/mariusDing/hoop-tape-miner/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mariusDing/hoop-tape-miner/releases/tag/v0.1.0
