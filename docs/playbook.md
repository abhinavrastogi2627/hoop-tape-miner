# Playbook: one game video -> coach report

The single procedure for an agent (Claude Code or Codex) driving hoop-tape-miner. Follow the steps in order; each ends with an output you can check. Writing guides live in `prompts/`; stage details in `docs/pipeline.md`; privacy rules in `docs/privacy.md`. `uv run hoop-tape-miner <stage> -h` is authoritative for flags.

Conventions used below (POSIX shell; on PowerShell use `$env:G = ...` and `$env:G` instead of `$G`):

```
G=workspace/teams/<opponent-slug>/<YYYY-MM-DD>   # one game; created by new-game
RUN=$G/run                                       # heavy outputs
GJ=$G/game.json
V=/path/to/game.mp4                              # our video
```

- Workspace root = `$HOOP_WORKSPACE`, else `./workspace` (gitignored). Nothing in it is ever committed.
- Times in reports are **video times** (mm:ss of your file), never the game clock.
- Long runs: redirect to `workspace/logs/<stage>.log` and read only the tail (`tail -n 20`). Never stream a long log into the conversation.

## 0. Prerequisites (once per machine)

1. NVIDIA GPU with CUDA, 8 GB VRAM or more; Windows or Linux. Detection and embeddings fall back to CPU (very slow); the 4-bit jersey reader (bitsandbytes) effectively needs CUDA.
2. [uv](https://docs.astral.sh/uv/) and Python 3.11: `uv sync` in the repo.
3. `ffmpeg` and `ffprobe` on PATH, or set `$FFMPEG` / `$FFPROBE` to their full paths.
4. Hugging Face models download on first use (several GB: RF-DETR, ball detector, SigLIP, Qwen3-VL-4B). Point `HF_HOME` at a disk with ~20 GB free.
5. Internet for narration (edge-tts) and, optionally, your league's stats site.
6. For QA: Node.js (`npx`) and a Playwright MCP server in your agent.
7. Video: one full game from a single side camera that pans/zooms (typical club recording). Court is FIBA 28 x 15 m.

## 1. New game

```
uv run hoop-tape-miner new-game --opponent "Opponent Name" --date YYYY-MM-DD --video "$V" --us-team "Our Team"
```

Writes `$GJ` (from `templates/game.example.json`), `$RUN/`, and the opponent dossier `workspace/teams/<opponent-slug>/README.md` if missing; never overwrites without `--force`. Then fill `$GJ` (keys starting with `_comment` explain each field):

- `us` / `them`: `team` (display name), `label` (jersey description), optional `hex` (#rrggbb for charts and the page), `us.focus_player` (jersey number for the player figure, or null).
- `rosters`: jersey numbers as strings; reads not on the roster are rejected.
- `periods` and `result`: fill later (steps 5 and 6).
- Optional for the film-review brief: `date`, `competition`, `memo_language`, `watch_notes`, or a `brief` block overriding any brief placeholder, e.g. `"brief": {"us_colour": "dark navy", "them_colour": "light blue"}` (without it the brief uses `us.colour` / `them.colour`, which are cluster labels).
- Optional `narration.voices`: edge-tts voice per language.

Ask the user for anything you cannot see on film: team names, rosters, focus players.

## 2. Calibration

```
uv run hoop-tape-miner calibrate --video "$V" --times 120,900,1500 --out "$RUN/calib" --propagate 140,160
```

An OpenCV picker asks for court landmarks one by one at each `--times` frame (a minimap shows the target; keys: `s` skip, `u` undo, Enter accept, Esc quit). Choose frames covering both halves and the camera's zoom range; `--propagate` adds keyframes by camera tracking. Picks are saved to `$RUN/calib/points.json` (`--points` replays them without a display). Output: `$RUN/calib/keyframes.json` plus `ov_<t>.jpg` overlays. Check the overlays: projected lines sit on the painted lines.

## 3. CV stages (about 1 h per game on an 8 GB GPU)

```
uv run hoop-tape-miner extract --video "$V" --out "$RUN" --calib "$RUN/calib/keyframes.json" --fps 10 > workspace/logs/extract.log 2>&1
uv run hoop-tape-miner embed   --run "$RUN" --video "$V" > workspace/logs/embed.log 2>&1
uv run hoop-tape-miner tracks  --run "$RUN" --video "$V" --game "$GJ" > workspace/logs/tracks.log 2>&1   # pass 1: stops at the montage
```

Optional, if court lines drift: `uv run hoop-tape-miner recalib --run "$RUN" --video "$V" --calib "$RUN/calib/keyframes.json"` (`--dry` keeps existing outputs). Run long stages in the background and check the log tails. Do not re-run `extract` if `$RUN` already has `detections.pkl` and `camera.npz`.

## 4. Checkpoint: name the team clusters

1. Open `$RUN/cluster_montage.jpg`.
2. Write `$RUN/cluster_names.json`, one label per cluster id: `us`, `them`, `ref` or `unk`, e.g. `{"0": "unk", "1": "them", "2": "us", "3": "ref", "4": "us", "5": "unk"}`.
3. Re-run `tracks` (pass 2), then `jersey`:

```
uv run hoop-tape-miner tracks --run "$RUN" --video "$V" --game "$GJ" > workspace/logs/tracks.log 2>&1
uv run hoop-tape-miner jersey --run "$RUN" --video "$V" > workspace/logs/jersey.log 2>&1
```

## 5. Checkpoint: periods, then analyze

Fill `periods` in `$GJ`: playing periods in seconds of our video, e.g. two halves `[[0, 1000], [1120, 2184]]` (gaps are shaded as breaks). Then:

```
uv run hoop-tape-miner analyze --run "$RUN" --game "$GJ"
```

## 6. Official stats and result

Fill `result` in `$GJ` (final, halftime, home/away) as soon as you know it; the page header reads it.

- **League feed**: `official` currently reads one league format, a box-score JSON plus a point-chart JSON export:

```
uv run hoop-tape-miner official --boxscore box.json --pointchart points.json --us-home true --out "$RUN/official.json" \
    --video "$V" --official-video league_video.mp4     # last two only if the league has its own video, for alignment
```

  Fetching may need a login; do it via the browser-check subagent with credentials from a secrets file outside the repo (never print them). Keep the exports in `$RUN/official/`.
- **Other leagues**: convert their data to the same `official.json` shape (`final`, `totals`, `players`, `score_flow`), or write the score flow by hand while watching: `{"score_flow": [{"our_video_t": 61.5, "team": "us", "points": 2, "score_us": 2, "score_them": 0}, ...]}`.
- **No data at all**: nothing to do. `coach-sheets` notices there is no `official.json`, says so, and builds the sheets without a score flow; the review works from the recording alone. Skip `plusminus` and `momentum` (they need a score flow), put the final score in `game.json` `result`, and say in the report's sources line that it rests on film review alone.
- Alignment: every score-flow event needs `our_video_t`. If the video was edited (cuts, trimmed breaks), check three known baskets by eye and correct `video_alignment.segments` / the times.

## 7. Film review (the core)

1. Build the coach sheets, part files and briefs:

```
uv run hoop-tape-miner coach-sheets --run "$RUN" --game "$GJ" --out "$RUN/review_v1" --parts 6 --video "$V" \
    > workspace/logs/coach-sheets.log 2>&1
```

   Writes `p<pid>_<k>.jpg` sheets, `manifest.json`, `part<N>.json`, `lineup_intervals.json` and `brief_part<N>.md` (filled from `prompts/film_review_brief.md`). Read one brief: no `{...}` left, team names and jersey colours right. To fix values, edit `$GJ` and re-run with `--skip-sheets` (seconds, not minutes).
2. Launch one subagent per part, **at most 3 at once**. Each gets only its `brief_part<N>.md` path. It reads every sheet of its part, writes `coach_part<N>.json`, `memo_part<N>.md`, `notes_part<N>.txt` into `$RUN/review_v1`, and replies in at most 8 lines. Do not read the sheets yourself. Close-ups: `uv run hoop-tape-miner coach-sheets zoom SHEET TILE X Y W H OUT [--scale 3]`.
3. Check every `coach_part<N>.json` parses and covers all pids of its part; re-run a part that does not.
4. Aggregate. Choose the game's stretches (start, decisive run, comeback, finish) from the score flow first:

```
uv run hoop-tape-miner coach-summary --review "$RUN/review_v1" --segments "A:0-450,B:450-1272,C:1272-1810,D:1810-2184" --out "$RUN/review_v1/summary.json"
uv run hoop-tape-miner plusminus --lineup "$RUN/review_v1/lineup_intervals.json" --official "$RUN/official.json" \
    --out "$RUN/review_v1/plusminus.json" --windows 450-1272,1272-1810
uv run hoop-tape-miner plusminus --lineup "$RUN/review_v1/lineup_intervals.json" --lineup film_stints.json \
    --official "$RUN/official.json" --out "$RUN/review_v1/pm_<N>.json" --player <N>
```

   CV lineups are fragmentary. For focus players, write `film_stints.json` (same shape, `{"us#<N>": [[t0, t1], ...]}`) from substitutions seen in the memos and notes; later `--lineup` files override earlier ones. `--event-times` maps feed times to the real basket times when the feed lags.

Optional event review for shot charts: `uv run hoop-tape-miner review --run "$RUN" --video "$V" --game "$GJ"` writes `$RUN/review/`; reviewers follow `docs/review_protocol.md` and write `events_part<N>.json` + `coverage_part<N>.json` there; then `uv run hoop-tape-miner merge-reviews --run "$RUN" --review review` writes `events.json` and `review_coverage.json`.

## 8. Figures

```
uv run hoop-tape-miner report   --run "$RUN" --out "$RUN/report" --game "$GJ" [--events "$RUN/events.json" --coverage "$RUN/review_coverage.json"]
uv run hoop-tape-miner momentum --official "$RUN/official.json" --game "$GJ" --lineup "$RUN/review_v1/lineup_intervals.json" --out "$G/momentum.en.png" --lang en
uv run hoop-tape-miner momentum --official "$RUN/official.json" --game "$GJ" --lineup "$RUN/review_v1/lineup_intervals.json" --out "$G/momentum.png" --lang zh
uv run hoop-tape-miner replay   --run "$RUN" --out "$RUN/replay" --game "$GJ" --pid 13     # optional tactics-board clip
```

`momentum` detects scoring runs itself (`--min-run 8`); pass `--stretches "Start:0-450,Run:450-1272,..."` to match the stretches you chose in step 7. `--players us#4,us#7` limits the on-court lanes. `report --focus <N>` overrides `us.focus_player`.

## 9. Fact sheets (before any prose)

Write `$RUN/review_v1/players_facts.md` (all our players) and `player<N>_facts.md` per focus player from the coach parts, memos, notes, `summary.json`, plus-minus and official data:

- official line, estimated minutes (a lower bound; say so), on/off score;
- scoring attribution checked against official totals (mark undecided cases, do not force them);
- fouls with time, type, cause and the likely player;
- a chronological log of involvements with video times and the reviewer's coach note;
- for the decisive run(s): every opposing point matched to the play on film.

Every claim in the reports must trace back to these sheets.

## 10. Write the reports (in `$G`)

| Output | Guide |
|---|---|
| `README.md` + `README.en.md` | `prompts/coach_report.md` |
| `player-<N>/README.md` + `README.en.md` per focus player | `prompts/player_deep_dive.md` |
| `workspace/teams/<opponent-slug>/README.md` (update) | `prompts/opponent_dossier.md` |
| `listen.zh.md` + `listen.en.md` in `$G` and in each `player-<N>/` | `prompts/narration.md` |
| `workspace/players/<N>/cues.court.<lang>.md`, `cues.warmup.<lang>.md` (optional) | `prompts/court_cues.md` |

Language convention (current code): the HTML page is bilingual and reads exactly `README.md` (Chinese) and `README.en.md` (English); both must exist. The listen button appears only when both `listen.zh.mp3` and `listen.en.mp3` exist. Copy the figures a README embeds next to it (e.g. `momentum*.png` into `player-<N>/` too).

Film clips: while writing, put `![caption](clip:mm:ss-mm:ss)` under the claims that matter most (selection, window and caption rules: "Film clips" in `prompts/coach_report.md`). Then cut them:

```
uv run hoop-tape-miner clips "$G" --video "$V"
uv run hoop-tape-miner clips "$G/player-<N>" --video "$V"
```

Writes `clips/<from>-<to>.mp4` (480p, about 1 MB per 10 s) and a poster per marker; existing files are kept (`--force` re-cuts). Check each clip shows the play its caption describes (a subagent can read 3–4 frames per clip with ffmpeg) before building the HTML.

## 11. Narration

```
uv run hoop-tape-miner narrate "$G"
uv run hoop-tape-miner narrate "$G/player-<N>"
uv run hoop-tape-miner narrate --script workspace/players/<N>/cues.court.en.md --chime --gap 6 --loud
uv run hoop-tape-miner narrate --script workspace/players/<N>/cues.warmup.en.md --loud
```

`--lang en` renders one language only; `--rate "-5%"` slows the voice. Measure each MP3 with `ffprobe -v error -show_entries format=duration -of csv=p=0 <file>.mp3` and make the "about N minutes" line in the script match; re-render if it changed. Narration sends the script text to Microsoft's TTS service (see `docs/privacy.md`).

### Explained video (optional, recommended for the team report)

Write `film.<lang>.md` from the finished report following `prompts/film.md` (scenes: clips with freeze frames that ring the players, court diagrams in `plays/*.json` for the plan, stat scenes, figures, short chapter cards; the narration is written for what is on screen). Check new clip windows and freeze moments on a contact sheet first; `--run "$RUN"` points at the CV tracks when they are not next to the video. Then:

```
uv run hoop-tape-miner film "$G" --video "$V" --dry          # checks the script, lists scenes with estimated lengths
uv run hoop-tape-miner film "$G" --video "$V" --scenes 1-4   # short preview: fonts, subtitles, timing
uv run hoop-tape-miner film "$G" --video "$V" > workspace/logs/film.log 2>&1
```

Writes `film.<lang>.mp4` (720p, about 5 MB per minute). Let a subagent check a few frames before sending: the title card, a chart, a clip and its slow replay, every freeze (is the ring on the right player?) and every diagram. Like the narration, the text goes to Microsoft's TTS service.

## 12. HTML

```
uv run hoop-tape-miner html "$G"
uv run hoop-tape-miner html "$G/player-<N>"
```

Writes `index.html` in each folder (team names, colours and score from `game.json`, found in the folder or its parent). Clips stay as files in `clips/` next to it; `--share` embeds them.

## 13. QA via the browser-check subagent

Ask it (text result only, at most 10 lines) to serve `$G` over http and check, for each `index.html` and each language: title and score band correct, every image loads, audio plays and its length label matches, every clip plays and the slow-mo button works, tables do not overflow at 390 px width, no console errors, no dead links, no local paths visible. Fix and re-render until it passes.

## 14. Share

Send the team a link rather than a file (free on Cloudflare; `npx wrangler login` once):

```
uv run hoop-tape-miner publish "$G" "$G/player-<N>" --deploy --project <name>   # --project only the first time
```

- Each folder keeps the same random URL across updates: after any edit, re-run this and the link already sent shows the new version. No one downloads anything again.
- Team reports are also listed on a hub page (its link is printed); send the hub once and new games appear on it. `player-<N>` reports are only reachable through their own link: send each one only to that player.
- Audio and clips stay as separate files behind a small Worker that serves the Range requests iPhones need for video.
- Run the QA step against `$HOOP_WORKSPACE/site/` (serve it over http) before `--deploy`, then spot-check the live URLs.
- Links are unlisted, not password-protected. `--new-link` retires a leaked link. Read `docs/privacy.md` before sending frames of players to anyone.

Fallback, a single file (offline, or where workers.dev is blocked, e.g. mainland China):

```
uv run hoop-tape-miner html "$G" --share --out "$PWD/workspace/share/<us>_vs_<them>_<date>.html"
```

`--share` embeds the audio and clips and strips local paths and repo links, so the single file can be sent privately to the team (`--out` is a file name inside the folder or an absolute path). Re-run the QA step on the shared file. Never push workspace content or media.

## Working rules

- One game per session. If the context gets large, write a short status note and start a fresh session.
- Subagents: at most 3 at once; they write results to files and reply in a few lines.
- Browser work and screenshots go to the browser-check subagent, not the main session.
- Never invent a result; "unclear" and "likely" are valid answers.
