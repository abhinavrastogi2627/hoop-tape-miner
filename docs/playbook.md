# Playbook: one game -> coach pages + explained video

The single procedure for an agent (Claude Code or Codex) driving hoop-tape-miner. Writing guides live in `prompts/`; stage details in `docs/pipeline.md`; privacy rules in `docs/privacy.md`. `uv run hoop-tape-miner <stage> -h` is authoritative for flags.

Each game produces two deliverables:

1. **Pages**: the team report and the focus player's report (`index.html`, bilingual, with the narration audio and film clips), published as private links.
2. **The explained video** `film.<lang>.mp4` (one per language). It is a file the user sends themselves (e.g. in a chat app); it is never published.

Everything else the code can make (opponent dossier, court cues, tactics-board replay, single-file share, event review) is optional; see "Optional extras" at the end.

## One-command run (start here)

Once per machine, create the team profile: copy `templates/team.example.json` to `workspace/team.json` and fill it (our team name as the league shows it, jersey description, colour, focus player, `media_root` for heavy files, the league secrets file, languages).

Then, per game, either type `/game <league game url>` in Claude Code (`.claude/commands/game.md`), or run the loop yourself:

```
uv run hoop-tape-miner run <league game url | game folder> > workspace/logs/run.log 2>&1
```

- A url is fetched first (step 1); the run then works in the game folder it prints. Use that folder for every later run. Running the url again is safe: a game already fetched (its `game.json` has the league game id) reuses its folder without fetching; `--refetch` fetches the league data again.
- Each step knows its output file, so a run resumes where it stopped. A command step whose inputs or settings changed since its last run (a new video, edited `periods`, a re-run upstream stage) runs again; nothing else is redone. CV stages log to `workspace/logs/<team>-<date>-<step>.log`.
- **Exit 3**: the run waits for you. The log names the step and what to do (the matching section below). Do it, then run again.
- **Exit 1**: a command failed; the log shows the tail of its stage log. Fix the cause and run again.
- **Exit 0**: done. It prints the page paths and the explained video paths.
- `--status` lists every step and whether it is done; `--dry` prints the next command; `--until STEP` stops after a step (also when that step was already done); `--redo STEP` runs a done step again, and the command steps that depend on it follow (`--status` marks them `(stale: ...)`).
- Publishing is outward-facing, so it only happens with `--publish`: once `qa.md` says PASS with the current `checked:` stamp, run again with `--publish`, then have the browser-check subagent check the live links.

Steps in order (agent steps marked *):

| Step | Section |
|---|---|
| video*, teams* | 1 |
| periods* | 2 |
| calib-grid, calibrate* | 3 |
| extract, embed, montage | 4 |
| clusters*, tracks, jersey, analyze | 5 |
| official* | 6 |
| coach-sheets, film-review*, features, coach-eval, summary*, insights*, critic* | 7 |
| momentum | 8 |
| facts* | 9 |
| reports*, clips | 10 |
| listen-script*, narrate | 11 |
| html | 12 |
| qa* | 13 |
| publish (only with `--publish`) | 14 |
| film-script*, film | 15 |

The sections below also work by hand. Conventions (POSIX shell; on PowerShell use `$env:G = ...` and `$env:G`):

```
G=workspace/teams/<opponent-slug>/<YYYY-MM-DD>   # one game folder: game.json, reports, pages
RUN=<run dir>                                    # heavy outputs: game.json "run", else $G/run
GJ=$G/game.json
V=<video>                                        # game.json "video"
```

- Workspace root = `$HOOP_WORKSPACE`, else `./workspace` (gitignored). Nothing in it is ever committed.
- The review folder is `$RUN/review_v1` (written `review_v1` below). To re-write a game's reports from a new review of the same run (for example after `coach-sheets event-merge`) without touching the old ones, copy `game.json` and `official.json` into a new game folder and set `"review_dir": "<folder name under $RUN, or absolute path>"` there.
- Times in reports are **video times** (mm:ss of the file), never the game clock.
- Long runs: redirect to `workspace/logs/<stage>.log` and read only the tail (`tail -n 20`).

## 0. Prerequisites (once per machine)

1. NVIDIA GPU with CUDA, 8 GB VRAM or more; Windows or Linux. Detection and embeddings fall back to CPU (very slow); the 4-bit jersey reader (bitsandbytes) effectively needs CUDA.
2. [uv](https://docs.astral.sh/uv/) and Python 3.11: `uv sync` in the repo.
3. `ffmpeg` and `ffprobe` on PATH, or set `$FFMPEG` / `$FFPROBE` to their full paths.
4. Hugging Face models download on first use (several GB: RF-DETR, ball detector, SigLIP, Qwen3-VL-4B). Point `HF_HOME` at a disk with ~20 GB free.
5. Internet for the league data, narration (edge-tts) and publishing.
6. For QA: Node.js (`npx`) and a Playwright MCP server in your agent. For publishing: a free Cloudflare account (`npx wrangler login` once).
7. Video: one full game from a single side camera that pans/zooms (typical club recording). Court is FIBA 28 x 15 m.

## 1. Start a game

**From a league link** (Glory League today):

```
uv run hoop-tape-miner fetch <game url> [--video OUR_VIDEO] [--no-video]
```

- Logs in with `GLORY_EMAIL` / `GLORY_PASSWORD` from the environment or the secrets file in `team.json` (never print them), reads the game, box score and point chart, and downloads the league's game video (720p, resumable).
- Writes `$GJ` (teams, rosters, final and halftime score, periods, league id) and `$RUN/official.json` (box score, score flow, video alignment). Heavy files go to `<media_root>/teams/<slug>/<date>/` (`video/`, `run/`, raw `league/` responses, which contain names).
- `--video OUR_VIDEO` keeps our own recording as the game video; the league video is then only used to align the score flow to it.
- An existing `game.json` keeps the fields you filled, and an existing `$RUN/official.json` keeps its video alignment when it is not the identity (aligned to our own video, or fixed by hand); `--force` overwrites both with league data. The last line printed is the game folder.

**Without league data**:

```
uv run hoop-tape-miner new-game --opponent "Opponent Name" --date YYYY-MM-DD --video "$V" --us-team "Our Team"
```

Writes `$GJ` from `templates/game.example.json` (keys starting with `_comment` explain each field) and `$RUN/`; never overwrites without `--force`. Fill `us` / `them` (`team`, `label`, `hex`, `us.focus_player`), `rosters` (jersey numbers as strings), `periods` and `result`. Ask the user for anything you cannot see on film.

Optional `game.json` fields for the film-review brief: `date`, `competition`, `memo_language`, `watch_notes`, or a `brief` block overriding any brief placeholder, e.g. `"brief": {"us_colour": "dark navy", "them_colour": "light blue"}`. `narration.voices`: edge-tts voice per language.

## 2. Periods

`periods` are the playing periods in seconds of our video, e.g. two halves `[[78, 1078], [1268, 2400]]`; gaps are shaded as breaks and calibration frames are chosen inside them. The league's periods split the whole video, pre-game footage and the break included, so `fetch` marks them `"periods_checked": false`. Grab stills around each boundary (`ffmpeg -ss T -i "$V" -frames:v 1 x.jpg`), set the real start and end of play, then set `"periods_checked": true`. With our own video, shift the league times by the alignment in `$RUN/official.json`.

## 3. Calibration (no GUI needed)

```
uv run hoop-tape-miner calibrate --video "$V" --times 330,830,1500,2100 --out "$RUN/calib" --grid
```

Writes `grid_<t>.jpg` per time: the frame with a labelled pixel grid and a numbered court landmark map below it. Pick four frames inside play covering both halves and the camera's zoom range (`run` chooses them from `periods`). Read each grid image and write `$RUN/calib/points.json`, 4–6 clearly visible landmarks per frame:

```
{"330": [{"name": "L_lane_base_far", "px": [180, 355]}, {"court": [14, 15], "px": [1137, 282]}]}
```

`name` is a landmark from the map (`calibrate -h` lists them); `court` gives raw court metres instead (x from the left baseline, y from the near sideline). Then solve and verify:

```
uv run hoop-tape-miner calibrate --video "$V" --times 330,830,1500,2100 --out "$RUN/calib" --points "$RUN/calib/points.json"
```

Each frame prints `PASS` or `WEAK` with its fit and its worst three points (`loo` = how far the other points put it; a large one marks the misplaced point); exit 2 while any frame is weak or missing. Move or drop the points it names and run again until every frame passes, then look at the `ov_<t>.jpg` overlays (the lane and three-point arc on the painted lines matter most). Only passing frames go to `keyframes.json`. Once all pass, add `--propagate 60,1040,...` to add keyframes by tracking the camera from the solved ones (backward and forward). With a display you can also click the points in a window (no `--grid` / `--points`).

Tips: prefer sharp line crossings (lane x baseline, free-throw line ends, halfway line x far sideline); a raw `court` point is fine for a painted feature you can see, e.g. the centre circle `[14, 7.5]`. Avoid circle-top landmarks unless they are clear (in perspective the top is where the tangent runs parallel to the baseline, not the outermost pixel). To read pixels precisely, crop and enlarge a region of the grid image. Gyms often have other courts' lines painted on the same floor, and the near sideline may hide behind chairs.

## 4. CV stages (about 1 h per game on an 8 GB GPU)

```
uv run hoop-tape-miner extract --video "$V" --out "$RUN" --calib "$RUN/calib/keyframes.json" --fps 10 > workspace/logs/extract.log 2>&1
uv run hoop-tape-miner embed   --run "$RUN" --video "$V" > workspace/logs/embed.log 2>&1
uv run hoop-tape-miner tracks  --run "$RUN" --video "$V" --game "$GJ" > workspace/logs/tracks.log 2>&1   # pass 1: stops at the montage
```

Do not re-run `extract` if `$RUN` already has `detections.pkl` and `camera.npz`. If court lines drift: `uv run hoop-tape-miner recalib --run "$RUN" --video "$V" --calib "$RUN/calib/keyframes.json"` (`--dry` keeps existing outputs).

## 5. Team clusters, then tracks, jersey, analyze

1. Open `$RUN/cluster_montage.jpg`.
2. Write `$RUN/cluster_names.json`, one label per cluster id: `us`, `them`, `ref` or `unk`, e.g. `{"0": "unk", "1": "them", "2": "us", "3": "ref", "4": "us", "5": "unk"}`. Jersey descriptions are `us.label` / `them.label` in `$GJ`.
3. Then:

```
uv run hoop-tape-miner tracks  --run "$RUN" --video "$V" --game "$GJ" > workspace/logs/tracks.log 2>&1
uv run hoop-tape-miner jersey  --run "$RUN" --video "$V" > workspace/logs/jersey.log 2>&1
uv run hoop-tape-miner analyze --run "$RUN" --game "$GJ"
```

## 6. Official stats and result

- **League link**: `fetch` already wrote `$RUN/official.json` and `result`. Nothing to do.
- **Other leagues**: convert their data to the same `official.json` shape (`final`, `totals`, `players`, `score_flow`), or write the score flow by hand while watching: `{"score_flow": [{"our_video_t": 61.5, "team": "us", "points": 2, "score_us": 2, "score_them": 0}, ...]}`. `official --boxscore box.json --pointchart points.json --us-home true --out "$RUN/official.json"` converts saved Glory League exports.
- **No data at all**: set `"no_league_data": true` in `$GJ` and put the final score in `result`. `coach-sheets` builds the sheets without a score flow, `momentum` is skipped, and the report's sources line says it rests on film review alone.
- Alignment: every score-flow event needs `our_video_t`. If the video was edited (cuts, trimmed breaks), check three known baskets by eye and correct `video_alignment.segments` / the times.

## 7. Film review (the core)

0. Ball and shot-attempt candidates (before the sheets; `run` does this as the `ball-track`, `rim-scan` and `shot-proposals` steps, and skips them when the sheets already exist; by hand, labels need `official.json`):

```
uv run hoop-tape-miner ball-track --run "$RUN" > workspace/logs/ball-track.log 2>&1
uv run hoop-tape-miner rim-scan --run "$RUN" --game "$GJ" > workspace/logs/rim-scan.log 2>&1   # CPU, ~6 min
uv run hoop-tape-miner shot-proposals --run "$RUN" --official "$RUN/official.json" > workspace/logs/shots.log 2>&1
```

   `ball_track.pkl` draws the ball trail on the sheets; `shot_proposals.json` draws a cyan "CV attempt? made +2 / likely miss" marker on the rim and lists `cv_attempts` per possession in the part files. They are candidates for the reviewers to confirm or reject, never results: the label only says an official score event matched within the feed lag. On the reference game (numbers in `docs/optimization-backlog.md` item 1) about 4 in 5 candidates fell inside a reviewed shot trip, and about 1 in 3 reviewed makes had no candidate, so reviewers still look for shots without a marker. Rebuild existing sheets to get the layers (drop `--skip-sheets`).

1. Build the coach sheets, part files and briefs:

```
uv run hoop-tape-miner coach-sheets --run "$RUN" --game "$GJ" --out "$RUN/review_v1" --parts 6 --video "$V" \
    > workspace/logs/coach-sheets.log 2>&1
```

   Writes `p<pid>_<k>.jpg` sheets, `manifest.json`, `part<N>.json`, `lineup_intervals.json` and `brief_part<N>.md` (filled from `prompts/film_review_brief.md`). Read one brief: no `{...}` left, team names and jersey colours right. To fix values, edit `$GJ` and re-run with `--skip-sheets`.
2. Launch one subagent per part, **at most 3 at once**. Each gets only its `brief_part<N>.md` path. It reads every sheet of its part, writes `coach_part<N>.json`, `memo_part<N>.md`, `notes_part<N>.txt` into `$RUN/review_v1`, and replies in at most 8 lines. Do not read the sheets yourself. Close-ups: `uv run hoop-tape-miner coach-sheets zoom SHEET TILE X Y W H OUT [--scale 3]`.
3. Check every `coach_part<N>.json` passes `uv run hoop-tape-miner coach-check --review "$RUN/review_v1"` (reviewers run it themselves); `run` waits on `film-review` and lists the errors until it does. It checks trip schema v2 and part coverage (our rule): every pid of `part<N>.json` has a trip, no more than 20 s inside a possession are covered by no trip, and every made shot, made free throw and foul names its jersey or carries `shooter_note` / `by_note` `"unknown: <why>"`. Send a part's errors back to its reviewer. Old v1 reviews: `coach-check --review <v1> --migrate <v2 folder>`.
   Then `run` measures per-trip numbers from the court tracks (step `features`): `uv run hoop-tape-miner coach-features --run "$RUN" --review "$RUN/review_v1"` writes `features.json` and `ball_quality.json`.
   Then it scores the review against the league data (step `coach-eval`, skipped without `official.json`): `coach-eval --review "$RUN/review_v1" --official "$RUN/official.json" --label run --gate` writes `eval/run.json` and a line in `eval/log.md`. Gate (our rule, not a league standard): points recall and precision at least 0.8 for both teams; a number it cannot compute is listed as "not computed" and does not block. A failed gate exits 1: re-review the parts around the unmatched official events and run again. A drop against the previous eval entry is printed as a WARNING (not blocking); `run --status` shows the last result.
4. Aggregate. Choose the game's stretches (start, decisive run, comeback, finish) from the score flow first:

```
uv run hoop-tape-miner coach-summary --review "$RUN/review_v1" --official "$RUN/official.json" --segments "A:0-450,B:450-1272,C:1272-1810,D:1810-2184" --out "$RUN/review_v1/summary.json"
uv run hoop-tape-miner plusminus --lineup "$RUN/review_v1/lineup_intervals.json" --official "$RUN/official.json" \
    --out "$RUN/review_v1/plusminus.json" --windows 450-1272,1272-1810
uv run hoop-tape-miner plusminus --lineup "$RUN/review_v1/lineup_intervals.json" --lineup film_stints.json \
    --official "$RUN/official.json" --out "$RUN/review_v1/pm_<N>.json" --player <N>
```

   CV lineups are fragmentary. For the focus player, write `film_stints.json` (same shape, `{"us#<N>": [[t0, t1], ...]}`) from substitutions seen in the memos and notes; later `--lineup` files override earlier ones. `--event-times` maps feed times to the real basket times when the feed lags.

5. Coaching insights, then a separate critic (run steps `insights` and `critic`). Launch the writer subagent with `prompts/coach_insights.md` and the review folder: it reads the trips, `summary.json`, `plusminus.json`, `official.json`, `features.json` (if present), `prompts/coach_kb.md` and the memos, and writes `$RUN/review_v1/insights.json` (3-6 team insights and 1-3 per focus player, each a pattern on at least two trips with a KB mechanism, a rule, a drill and a measurable target). The writer's check:

```
uv run hoop-tape-miner coach-insights check --review "$RUN/review_v1" --no-critic
```

   It fails on evidence without a `pid` (and `trip` when the pid has several), a pid or trip not in the trips, a time outside the cited trip, an unknown KB slug, a `numbers` name that does not resolve in its file (`summary.json`, `features.`, `official.`, `plusminus.`, `pm_<N>.`; the value `"unknown"` is allowed) or a different value, and a player not on our box-score roster. Send the errors back to the writer until it prints PASS.

   Then launch a different subagent as the critic with `prompts/coach_critic.md`. It re-opens the cited sheets, writes its own `critic.json` (`{"verdicts": [{id, verdict, note, reopened: [sheet files]}]}`), moves dropped insights to `insights_dropped.json`, and signs with `uv run hoop-tape-miner coach-insights critic --review "$RUN/review_v1"`. A verdict without re-opened sheets, a sheet that does not cover an evidence time (5 s padding), or a verdict set only inside insights.json fails; the signature is the hash of insights.json, so a later edit sends it back to the critic. `coach-insights check` (no flag) is the full check the `critic` step uses.

   Games finished before these gates: `run` waits on `film-review`, `insights` or `critic` with the errors and a note naming what is newly required. Fix them and re-run, or keep the pages already published. The report's conclusions and practice plan (step 10) come from this file. To compare with the memo conclusions, `coach-insights ab --review "$RUN/review_v1" --out "$RUN/review_v1/eval/ab_insights.md"` writes a blind A/B rating sheet (the key goes to `ab_insights.key.json`; do not show it to the rater).

## 8. Figures

```
uv run hoop-tape-miner momentum --official "$RUN/official.json" --game "$GJ" --lineup "$RUN/review_v1/lineup_intervals.json" --out "$G/momentum.png" --lang zh
uv run hoop-tape-miner momentum --official "$RUN/official.json" --game "$GJ" --lineup "$RUN/review_v1/lineup_intervals.json" --out "$G/momentum.en.png" --lang en
```

`momentum` detects scoring runs itself (`--min-run 8`); pass `--stretches "Start:0-450,Run:450-1272,..."` to match the stretches you chose in step 7. `--players us#4,us#7` limits the on-court lanes.

Tracking numbers (no video pass, seconds each):

```
uv run hoop-tape-miner load --run "$RUN"                                  # running load per stint -> $RUN/load.json
uv run hoop-tape-miner matchups --run "$RUN" --review "$RUN/review_v1" --game "$GJ"   # -> $RUN/matchups.json
```

`load` gives each player's stints (from `lineup_intervals.json`) with distance, sprints, top speed and high-speed distance, plus how much of the stint the tracks saw; a stint under 50% is flagged, and gaps are never filled, so distance is a lower bound for the tracked time. `matchups` measures the nearest defender at each shot (tight / contested / open, or unknown) and who guarded whom over our and their possessions. The pages pick both up (step 12); quote them in a report only with their coverage, and prefer the reviewer's `contested` label when the two disagree.

## 9. Fact sheets (before any prose)

Write `$RUN/review_v1/players_facts.md` (all our players) and `player<N>_facts.md` for the focus player from the coach parts, memos, notes, `summary.json`, plus-minus and official data:

- official line, estimated minutes (a lower bound; say so), on/off score;
- scoring attribution checked against official totals (mark undecided cases, do not force them);
- fouls with time, type, cause and the likely player;
- a chronological log of involvements with video times and the reviewer's coach note;
- for the decisive run(s): every opposing point matched to the play on film.

Every claim in the reports must trace back to these sheets.

## 10. Reports and film clips

| Output | Guide |
|---|---|
| `$G/README.md` + `README.en.md` | `prompts/coach_report.md` |
| `$G/player-<N>/README.md` + `README.en.md` for the focus player | `prompts/player_deep_dive.md` |

The HTML page is bilingual and reads exactly `README.md` (Chinese) and `README.en.md` (English); both must exist. Copy the figures a README embeds next to it (e.g. `momentum*.png` into `player-<N>/` too).

Film clips: while writing, put `![caption](clip:mm:ss-mm:ss)` under the claims that matter most (selection, window and caption rules: "Film clips" in `prompts/coach_report.md`). Then cut them:

```
uv run hoop-tape-miner clips "$G" --video "$V"
uv run hoop-tape-miner clips "$G/player-<N>" --video "$V"
```

Writes `clips/<from>-<to>.mp4` (480p, about 1 MB per 10 s) and a poster per marker; existing files are kept (`--force` re-cuts). Check each clip shows the play its caption describes (a subagent can read 3–4 frames per clip with ffmpeg).

The same command also cuts the clips of the shot chart and the playlists (one 7–8 s window per reviewed shot, turnover and foul with a video time in the review's `coach_part*.json`; see step 12), so a team page gains about 40–60 clips (about 0.8 MB each). A window that is both a marker and a chart dot is cut once. Trips without a time (old v1 reviews) use their `key_clip`, or stay on the chart without a clip.

Then mark the posters, so a reader sees who to watch before pressing play:

```
uv run hoop-tape-miner posters "$G" --video "$V"
uv run hoop-tape-miner posters "$G/player-<N>" --video "$V"
```

Writes `clips/<from>-<to>.mark.jpg`: the players named in the caption (`我#17`, `对#25`, or a bare `#17`) and the shooter / fouler of the reviewed event get a ring, the rest of the frame is dimmed, a foul gets an arrow to the player fouled. Only players the tracks see at the poster frame are drawn; the others stay plain. Pages use the marked poster; re-cut clips (`clips --force`) fall back to the plain one until `posters` runs again. Spot-check a few marked posters (is the ring on the right player?).

## 11. Narration

Write `listen.<lang>.md` for each language in `$G` and in `$G/player-<N>/` (`prompts/narration.md`), then:

```
uv run hoop-tape-miner narrate "$G"
uv run hoop-tape-miner narrate "$G/player-<N>"
```

`--lang en` renders one language only; `--rate "-5%"` slows the voice. Measure each MP3 with `ffprobe -v error -show_entries format=duration -of csv=p=0 <file>.mp3` and make the "about N minutes" line in the script match; re-render if it changed. The listen button appears when both `listen.zh.mp3` and `listen.en.mp3` exist. Narration sends the script text to Microsoft's TTS service (see `docs/privacy.md`).

## 12. HTML

```
uv run hoop-tape-miner html "$G"
uv run hoop-tape-miner html "$G/player-<N>"
```

Writes `index.html` in each folder (team names, colours and score from `game.json`, found in the folder or its parent). Audio and clips stay as files next to it.

When the game has a review (`game.json` `run` / `review_dir`), each page also gets two sections after the report, in both languages and in the contents:

- **Shot chart**: every reviewed shot as a dot in its zone on a half court (filled = made, ring = missed, dashed ring = make/miss unclear; never guessed), zones shaded by points per shot over the shots whose outcome is known, a zone table, filters by team, player and half; a dot plays its clip under the chart. The player page shows only that player's shots.
- **Playlists**: per player (their shots and fouls; turnovers carry no jersey in the trip schema) and per theme: our turnovers, live-ball turnovers (when the trips have `turnover_kind`), fouls we gave, their scores, transition defence (when the trips have `transition`), our offensive rebounds. Each plays straight through in one player; at most 12 clips per playlist (`film_index.MAX_PLAYLIST`, the earliest ones).

With `$RUN/load.json` / `$RUN/matchups.json` (step 8) the pages also get, at the end: **Running load per stint** (player page only; low-coverage stints dimmed) and **Matchups and shot defence** (team page: shots by defender distance per team, and for each attacker the defender who guarded them most and the share of time unguarded; player page: that player's line).

`--share` files keep the chart without clips and drop the playlists (they would embed dozens of videos).

## 13. QA via the browser-check subagent

Ask it (text result only, at most 10 lines) to serve `$G` over http and check, for each `index.html` and each language: title and score band correct, every image loads, audio plays and its length label matches, every clip plays and the slow-mo button works, shot chart dots and filters work and a dot plays its clip, each playlist plays and moves to the next clip, tables do not overflow at 390 px width, no console errors, no dead links, no local paths visible. Fix and re-render until it passes, then write `$G/qa.md` with `PASS` as its first word and the line `checked: <stamp>` that `run` printed when it stopped at QA (the run waits for both). The stamp covers the pages, READMEs, audio and clips of both reports: any edit after QA changes it, and the run asks for QA again before anything is published.

## 14. Publish the pages

```
uv run hoop-tape-miner publish "$G" "$G/player-<N>" --deploy [--project <name>]   # --project only the first time
```

(`run --publish` does this.) Then have the browser-check subagent spot-check the live URLs.

- Each folder keeps the same random URL across updates: after any edit, publish again and the link already sent shows the new version. Links are stored in `workspace/publish.json`.
- Team reports are also listed on a hub page (its link is printed); send the hub once and new games appear on it. `player-<N>` reports are only reachable through their own link: send each one only to that player.
- The season page (see "Season page and pre-game brief" below) is published the same way, `publish workspace/season/<season-id> --deploy`: it keeps its own stable link and is pinned at the top of the hub.
- Audio and clips stay as separate files behind a small Worker that serves the Range requests iPhones need for video. The explained video is never published.
- A report counts as published (for `run`) only after `--deploy` succeeded; when wrangler fails, the links stay the same and the next `run --publish` tries again. `publish.json` is written atomically, with the previous version kept as `publish.json.bak`.
- Pages are markdown only: raw HTML in a README shows as text, and only media files inside the report folder are copied to the site (anything else, e.g. `../` or an absolute path, is left out with a warning). The Worker sends a Content-Security-Policy, `nosniff`, `no-referrer` and `noindex` on every response; each page also pins its own script by hash.
- Links are unlisted, not password-protected. `--new-link` retires a leaked link. Read `docs/privacy.md` before sending frames of players to anyone.

Reply to the user with: the hub link, the team page link, the focus player's link (and who gets it).

## 15. Explained video

Write `film.<lang>.md` for each language from the finished team report following `prompts/film.md` (scenes: clips with freeze frames that ring the players, court diagrams in `plays/*.json` for the plan, stat scenes, figures, short chapter cards; the narration is written for what is on screen). Check new clip windows and freeze moments on a contact sheet first. Then:

```
uv run hoop-tape-miner film "$G" --video "$V" --run "$RUN" --dry          # checks the script, lists scenes with estimated lengths
uv run hoop-tape-miner film "$G" --video "$V" --run "$RUN" --scenes 1-4   # short preview: fonts, subtitles, timing
uv run hoop-tape-miner film "$G" --video "$V" --run "$RUN" > workspace/logs/film.log 2>&1
```

Writes `film.<lang>.mp4` (720p H.264, `--crf 23` by default; raise it for a smaller file) and a poster `film.<lang>.jpg`. Let a subagent check a few frames: the title card, a chart, a clip and its slow replay, every freeze (is the ring on the right player?) and every diagram. Like the narration, the text goes to Microsoft's TTS service. Give the user both file paths; they send the videos themselves.

## Optional extras

Not part of the default run; make them when the user asks.

| Extra | How |
|---|---|
| Opponent dossier `workspace/teams/<slug>/README.md` | `new-game --dossier` creates it; update it with `prompts/opponent_dossier.md` |
| On-court cue loops | `prompts/court_cues.md` -> `workspace/players/<N>/cues.court.<lang>.md`, then `narrate --script <file> --chime --gap 6 --loud` (during play: `--gap 0.4 --tight`, no chime) |
| 9:16 phone reel of one player | `reels "$G/player-<N>" --video "$V"` (or `reels "$G" --player <N>`): `reels/reel.<N>.<lang>.mp4`, title card + their shot and foul clips with the crop following them (centre crop where the tracks lose them). Never published; give the path, the user sends it |
| Tactics-board replay | `replay --run "$RUN" --out "$RUN/replay" --game "$GJ" --pid 13` |
| Figures from CV (shot zones, heat maps) | `report --run "$RUN" --out "$RUN/report" --game "$GJ" [--events "$RUN/events.json" --coverage "$RUN/review_coverage.json"]` |
| Event review for shot charts | `review --run "$RUN" --video "$V" --game "$GJ"`; reviewers follow `docs/review_protocol.md`, then `merge-reviews --run "$RUN" --review review` |
| Single sendable file (offline, or where workers.dev is blocked) | `html "$G" --share --out "$PWD/workspace/share/<us>_vs_<them>_<date>.html"`: embeds audio and clips, strips local paths; re-run QA on it |

## Season page and pre-game brief

A standalone stage, not a step of `run`: make it after a game is finished, or before the next one.

```
uv run hoop-tape-miner season [--season <id>] [--brief --opponent "<next opponent>"]   # writes workspace/season/<id>/
uv run hoop-tape-miner narrate --script workspace/season/<id>/brief.zh.md            # and brief.en.md
uv run hoop-tape-miner publish workspace/season/<id> --deploy                          # own link, pinned on the hub
```

- Reads every `workspace/teams/<opponent>/<date>/` game: result, official.json, the review's `summary.json` (Four Factors), `insights.json`, `plusminus.json` / `pm_<N>.json`, `lineup_intervals.json`. Of `<date>` and `<date>-v2` folders of one opponent only the last counts. Whatever an older game lacks is listed under "Missing data", never filled in.
- The page: results, points per half, Four Factors per game (table + small SVG charts), last game's targets checked, recurring KB themes, per-player minutes and on / off pooled over the season, 5-player lineups.
- Targets: each insight's `target_next_game` from game N is checked in game N+1 where a clause names a number as `summary <path>` (or `official <path>`) followed by "at most N", "at least N", "below N" ..., e.g. `Their fast-break scores (summary them.transition_scores) at most 4 (was 9)`. An insight may also carry a structured `"target": {"metric": "summary.all.us.turnovers", "op": "<=", "value": 10}`. Everything else shows as "not measurable". Write targets this way in step 7 so the season page can check them.
- Small samples, our rule: a net per 10 minutes is `10 * net / (minutes + 20)`, i.e. 20 minutes of 0 net are added, which pulls short stints toward 0. Under 20 minutes or under 3 games is flagged "small sample". Lineups count only time slices with exactly 5 of our players in the lineup file (CV lineups often have gaps; then the section stays empty).
- `--brief` writes `brief.<lang>.md`, a spoken script (about 5 minutes once edited): record, recurring themes (else the last game's themes), the last game's targets, and with `--opponent` our past results against them. Lines starting with `#` are notes, not read. Edit it, then `narrate --script`.
- Preview without touching the workspace: `--out <folder>` (and `--no-html` to skip the page).

## Personal training sessions

One player's solo workout (shooting, finishing, dribbling) filmed on a phone -> a session page (makes / attempts by zone and finish type, form, dribbling, last session's targets, progress), an explained video and `plan.json`, the next session's drills with targets that the next run checks. Claude Code: `/train <videos> [--plan "what you meant to train"]` (`.claude/commands/train.md`). The loop is the same as the one-command run:

```
uv run hoop-tape-miner train <phone video...> --player 17 --plan "free throws, left-hand layups" > workspace/logs/train.log 2>&1
uv run hoop-tape-miner train workspace/players/17/training/<date> > workspace/logs/train.log 2>&1   # every later run
```

| Step | Training step |
|---|---|
| video*, scan | 1-2 |
| rim-probe, rim* | 3 |
| sheets | 4 |
| film-review* | 5 |
| summary | 6 |
| report*, clips | 7 |
| listen-script*, narrate, html, qa* | 8 |
| publish (only with `--publish`) | 9 |
| film-script*, film | 10 |

**Training step 1: record.** Phone on a tripod (or a fence), landscape, still for the whole session. The rim and the player's whole body in frame, side-on or from behind the shooter at about 45°; one player in frame. Several files are fine; they are joined in the given order. Say what you meant to train in `--plan`.

**Training step 2: start and scan.** `train <videos>` runs `train-new` (session folder `workspace/players/<player>/training/<date>[-n]/`, `session.json`, joined `session.mp4`, targets copied from the last `plan.json`) and `train-scan` (YOLO pose at 15 fps, about real time on a GPU; the models download once). `--seed x,y` (frame fractions) picks the player when several people are in frame. With a trainer or partner in frame, set `"follow": "ball"` (the scan follows whoever holds the ball, so the shooter is picked at every shot) and `"look"` (what the player wears, e.g. "short dark hair, glasses, black shorts"; the reviewers reject the other person's reps) in `session.json` before the scan. The scan keeps every person in `run/pose_all.npz`, so `train-scan <session> --repick [--follow ...] [--seed ...]` chooses again without re-running the models. Both files remember what they were made from: a changed `seed` or `follow` (flag or `session.json`) re-picks from `pose_all.npz` on the next plain `train-scan`, and a changed video, `--fps` or `--no-ball` scans again.

**Training step 3: rim boxes.** View `run/train_review/rim_probe.jpg` (four frames across the session, grid lines every 0.1). In `session.json` set `rim` to the rim's box as frame fractions `[x, y, w, h]` (top-left, size), e.g. `[{"from": "00:00", "box": [0.47, 0.18, 0.06, 0.03]}]`. Add an entry with a later `from` when the camera moved, `"box": null` when the rim leaves the frame, or `[]` when it is never in view. Then set `"rim_checked": true`.

**Training step 4: sheets.** `train-sheets` writes overview sheets (a frame every 10 s), rep sheets (set / release / follow-through crops, a rim filmstrip from +0.3 s to +2.1 s, a wide frame at +0.8 s) and dribble sheets, split into parts of 50 candidates with one brief each. Once any `review_part<N>.json` exists it will not rebuild (the parts could shift under the reviews); run `hoop-tape-miner train-sheets <session> --force` to rebuild, then review every part again.

**Training step 5: film review.** One subagent per `brief_part<N>.md` (at most 3 at once). Each writes `review_part<N>.json` (every candidate confirmed or rejected, make / miss / unclear, zone, spot, type, miss direction, form notes, drill blocks, dribble drills, reps the scan missed) and `memo_part<N>.md`. Do not read the sheets yourself. Re-run a part whose json does not parse or misses candidate ids.

**Training step 6: summary.** `train-summary` merges the parts with the pose numbers into `summary.json`, `facts.md` and the figures. Every number in the report comes from `facts.md`.

**Training step 7: report and plan.** Write `README.md` (中文), `README.en.md` and `plan.json` with `prompts/training_report.md`: the verdict, targets from last time, shooting, finishing, form, dribbling, progress, what to fix and how, 3-5 drills for next time (each with a reason from this session and a checkable target) and the skill and conditioning work between sessions (`plan.json` `between_sessions`). Causes, cues, drills and conditioning doses come from the individual skill and conditioning knowledge base `prompts/skill_kb.md`. Mark 4-8 clips; `clips` cuts them.

**Training step 8: narration, page, QA.** `listen.<lang>.md` (2-3 minutes, `prompts/narration.md`), then `narrate` and `html` run. The browser-check subagent checks the page in both languages, the audio and every clip and writes `qa.md` (first word PASS, plus the `checked: <stamp>` line the run printed).

**Training step 9: publish (optional).** Only when the user asks: run again with `--publish`. The page gets its own private link and is never listed on the team hub.

**Training step 10: explained video.** `film.<lang>.md` (`prompts/film.md`, training notes in `prompts/training_report.md`): clips of typical makes and misses with freeze lines on the form point (`> 00:41.0 0.45,0.80 "knee drive"`), the zones and form figures, the plan as the last chapter. Check it with `film <session> --dry`; the run renders `film.<lang>.mp4`. Give the user the paths; it is never published.

The next session: film it, run `train <videos>` again. Its `targets` come from this `plan.json`, the page shows met / missed / not trained for each, and the progress figure grows by one session.

## Movement sessions

How one player runs, finishes layups and stops (running form, force pattern, layup approach), judged by a sprint and movement coach against `prompts/movement_kb.md`, with fuel and recovery from `prompts/fuel_recovery_kb.md`. Input = windows (segments) of any video: phone clips filmed for it, a training session, a game. Output = a movement page (`index.html`, bilingual, narration, clips from a skeleton overlay reel; a private link with `--publish`, never on the team hub), an explained video `film.<lang>.mp4` (send it yourself) and `plan.json` (drills in sessions A-D, re-tests, fuel, recovery). Claude Code: `/move <segments.json | session folder>` (`.claude/commands/move.md`).

```
uv run hoop-tape-miner move --spec segments.json --player 17 --look "black T-shirt, glasses" > workspace/logs/move.log 2>&1
uv run hoop-tape-miner move workspace/players/17/movement/<date> > workspace/logs/move.log 2>&1   # every later run
```

| Step | Movement step |
|---|---|
| video*, scan, who* | 1-2 |
| sheets | 3 |
| labels* (side-view segments only) | 4 |
| review* | 5 |
| summary | 6 |
| report*, clips | 7 |
| listen-script*, narrate, html, qa* | 8 |
| publish (only with `--publish`) | 9 |
| film-script*, film | 10 |

**Movement step 1: film (the protocol).** Numbers need a **side view**: phone on a tripod at hip height, landscape, locked, 8-10 m from the lane and perpendicular to it; 240 fps slow motion (120 at least; contact times are shown only at >= 100 real fps); tape marks every 1-5 m for scale; nobody crossing the frame. Clips: 3 x 20 m sprints from a 2-point start (`sprint`), 3 x full-court speed dribble each hand (`dribble-sprint`), 6 layups each side at game speed (`layup`, side or 45°), 3 x sprint-to-stop (`decel`), one easy jog (`run`). A front or behind view is optional (knee-in, base width, arm crossing). Same spot, shoes and floor at every re-test. Full protocol and the re-test battery: `prompts/movement_kb.md`.

**Movement step 2: start, scan, identity.** The spec is a JSON list of segments, or `{"look": .., "plan": .., "segments": [..]}`. A segment is `{"kind": sprint|run|dribble-sprint|layup|decel|game|training, "view": side|front|behind|game, "source": "<video>", "from": "mm:ss.s", "to": "mm:ss.s"}` plus optional `"release"` (layup: when the ball leaves the hand), `"slowmo": 8` (an exported slow-motion file that plays 8x slower), `"seed": [x, y]` (frame fractions of the player at the window start), `"anchor": "mm:ss.s"` (a moment the player clearly holds the ball) and `"follow": "ball"` (scan the ball too). `move-new` cuts every window into one 30 fps `reel.mp4`; `move-new --into <session> --spec more.json` adds segments later. `move-scan` runs pose on each window of its source at native fps (capped at 120 real fps) and keeps everyone the models saw in `run/seg/<id>.raw.npz`. When more than one person is in frame (a trainer, a defender), it writes `run/move_review/who_<id>.jpg` (three frames around the release, every person boxed and numbered) and `who.json`; one subagent with the movement.json `look` fills `"t"` (the clearest frame's caption) and `"box"` (the player's number) per segment, then `move-scan <session> --repick` follows that person through the window: the cheapest path over the detected boxes, scoring the movement between frames and how unlike the player each box looks (a clothing-colour model built from every pick in the session). Extra picks pin the path where colour is not enough (a trainer in the same shirt): add `{"t": "mm:ss.s", "box": null}` items to the segment's `"more"` list in `who.json`, run `--repick` (it writes `who_<id>.more.jpg`, one tile per item), fill each box (`-1` when the player has no box of his own in that tile) and `--repick` again. Picks at the start and end of the window plus one at each contact work well. Without a pick it falls back to the ball holder at the `anchor` (else `release`), then `seed`, then the largest person. Picks are pinned to the box they name, so they still find the same person after a re-scan. A plain `move-scan` reuses only what is still valid: the raw detections while the source file (by content), window, fps and ball pass are unchanged, the picked track while `who.json`, `anchor`, `release`, `seed` and `follow` are unchanged; after `who.json` changes it picks again on its own, and the run does not pass the identity step until every picked segment was re-picked. Metrics come only from side-view segments; from other views the page shows findings, never numbers.

**Movement step 3: sheets.** `move-sheets` draws the skeleton overlay reel (`reel.overlay.mp4`, the clip and film source), a key-frame sheet per segment (around the release for a layup), label strips for side-view segments, and one brief per group of about 8 segments from `prompts/movement_review_brief.md`.

**Movement step 4: label check (side view only).** One subagent opens every `strip_<id>.jpg` and writes `labels.json` with each frame where a foot first touches the floor (at least 10 segments when there are that many); then set `"labels_checked": true`. A metric is shown only when the scan's contacts match the labels (recall and precision >= 0.8, mean error <= 1.5 frames). Labels are in source time; for a slow-motion file the check divides by the slow-down first, so the tolerance and the error are in real time and real frames. A check speaks only for segments of the same kind, view, source file and real frame rate: a segment counts when its own check passed, or when it has none and every labelled segment of its group passed. Values of segments with no check in their group are listed in `facts.md` as unvalidated and are not quoted. Sessions without side-view segments skip this step.

**Movement step 5: review.** One subagent per `brief_<g>.md`, at most 3 at once. Each writes `review_<g>.json` (per segment: `identity_ok`, each KB fault `seen` / `not_seen` / `not_visible` with time and confidence, good habits) and `memo_<g>.md`. Do not read the sheets yourself. Where the crop follows someone else for part of a window, the reviewer lists those stretches in `wrong_person` (findings inside them are dropped); `identity_ok: false` drops the whole segment. Add `more` picks at those times (step 2), or fix `release` / `anchor`, run `move-scan --repick` and `move-sheets --force`, and review that group again.

**Movement step 6: summary.** `move-summary` writes `summary.json`, `facts.md` and the figures: findings merged per KB entry (seen, hypothesis, not seen, not visible), good habits, measurements that passed the label check, progress against earlier sessions with the same kind, view and metrics version. Running faults seen from a non-side camera are hypotheses for the re-shoot; segments with `identity_ok: false` count for nothing, and findings inside a segment's `wrong_person` stretches are dropped. Missing values are "unknown", never 0.

**Movement step 7: report and plan.** `README.md` (中文), `README.en.md` and `plan.json` with `prompts/movement_report.md`: the verdict, the teammates' claims checked, the model, what the footage shows (clip markers on the overlay reel) and what it cannot show, the training plan in sessions A-D, the pain check, fuel by day type, recovery, the re-shoot and re-tests. `clips` cuts the clips from the overlay reel.

**Movement steps 8-10** work as training steps 8-10: narration (3-4 minutes), `html` (a movement band instead of the score), QA by the browser-check subagent, `--publish` only when asked, then `film.<lang>.md` on the overlay reel and `film`.

The re-shoot: film the protocol (`prompts/movement_kb.md`, "Filming protocol": side-on at hip height, 120-240 fps, alone or with a trainer in a clearly different colour), start a new session with `move --spec`, and the page compares the measurements with this one. Only side-view segments give numbers, so a baseline filmed from behind or the front has findings and hypotheses but no measurements.

## Working rules

- One game per session. If the context gets large, write a short status note and start a fresh session.
- Subagents: at most 3 at once; they write results to files and reply in a few lines.
- Browser work and screenshots go to the browser-check subagent, not the main session.
- Never invent a result; "unclear" and "likely" are valid answers.
- Never commit anything from `workspace/`, any media, or credentials.
