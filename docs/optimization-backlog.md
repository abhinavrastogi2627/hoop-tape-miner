# Optimization backlog

From GitHub/paper research and running the pipeline on full games (2026-10).

## Done
- ByteTrack `lost_track_buffer=60` (= 2 s; `trackers` counts it in 30 fps frames).
- `analyze.identities`: a tracklet whose vote is "none" is accepted when it has exactly one distinct non-none read that is on the team roster.
- `jersey.pick_crops`: group detections by frame once instead of filtering the whole frame per row (output identical, tested).
- Claude Code setup: `CLAUDE.md`, `.claude/settings.json` (output and auto-compact caps), `.claude/agents/browser-check.md` (Sonnet, effort high; keeps screenshots out of the main context; findings below).
- Ball track cleanup and shot-attempt candidates (`ball-track`, `rim-scan`, `shot-proposals`; 2026-10-21). Measured on the reference game (36 min, 27 official made FGs, 10 FT events, 23 reviewed makes with a release time, 31 reviewed missed trips); "chance" = the same candidates shifted to random times (100 draws):
  - Extract's ball candidates cover 0.43 of sampled frames (not the 0.7 assumed before); the cleaned and smoothed track 0.48 (0.31 detected, the rest interpolated). Only 56 track frames come within 1.5 m of a rim: the detector loses the ball in the air, so the track feeds the sheet trail only.
  - `rim-scan` (registered background difference above each rim, CPU, 329 s for the game) finds the ball in flight; on a montage the blobs are the ball. 22 of 23 reviewed makes had the rim in view.
  - `shot-proposals` with the defaults (min 6 points, ballistic fit RMS <= 0.25 m, ends within 0.6 m of the rim): 122 candidates, 29 labelled made, 93 likely miss. Official made-FG recall within the feed lag window (-40 s, +5 s) 22/27 = 0.81 (chance 0.62; the wide window inflates both). FT events matched 7/10 (chance 5.1). Reviewed makes with a candidate within -1..+3 s of the release 15/23 (chance 5.2). Candidates inside a reviewed shot trip 99/122 = 0.81 (chance 0.74), so roughly 1 in 5 is not a shot; made labels inside a reviewed made trip 22/29. Reviewed missed trips with a candidate 22/31, no better than chance (21.4) because those windows are long.
  - Possession from ball contact (team of the player box holding the ball vs the reviewed offence): 0.66 agreement on 89 of 90 trips, not reliable enough; not used.

## Todo, by expected gain
1. Shot candidates: raise recall of reviewed makes (8 of 23 missed; their arcs mostly fail the fit-RMS or the min-points test) and precision outside shot trips (23 of 122), e.g. a learned ball/not-ball patch classifier on the rim-scan blobs or a WASB-style heatmap ball detector run on the rim patches only; then a ball-contact possession signal once the track holds the ball near players.
2. Tracklet stitching on `tracks.pkl` (median tracklet is about 27 frames), pooling jersey reads across a chain.
3. `extract` real resume with append-only chunk files (it currently restarts from scratch and rewrites the full pickle periodically).
4. Batched Qwen3-VL reads and logprob-weighted jersey voting (re-runs the jersey stage only).
5. Profile `extract` on a 2-minute clip (fp16, batching, threaded decode).

## Claude Code cost findings (browser-check subagent)

Task: QA of one finished report page, once clean and once with 6 seeded defects (2 wrong table cells, broken image, broken link, 390 px overflow, console error), graded against a scripted Playwright ground truth. 5 runs per configuration; cost is the subagent's own tokens.

| Configuration | Score | False positives | $/run | Wall s |
|---|---|---|---|---|
| model inherited, effort unset | 28/28 | 0 | 0.834 | 452 |
| sonnet, effort unset | 28/28 | 0 | 0.479 | 533 |
| opus, effort medium | 27/28 (lost point = MCP tools not loaded) | 1 (same run) | 0.175 | 106 |
| sonnet, effort medium | 27.5/28 | 0 | 0.093 | 109 |
| opus, effort high | 28/28 | 0 | 0.292 | 235 |
| **sonnet, effort high** (current) | 28/28 | 1 (harmless duplicate) | 0.110 | 126 |
| sonnet medium + omitClaudeMd + tools allowlist | 27.5/28 | 1 | 0.057 | 72 |
| haiku, effort medium | 14/28 | 0 | 0.006 | 84 |

Re-check of sonnet high as a real subagent (spawned through the Agent tool, 3 seeded + 2 clean runs): 28/28, 0 false positives, $0.114/run, 77 s.

Findings:
- Set `effort:` explicitly in every custom subagent. Unset, it inherits the session effort; with a high session effort that, not the model, was about 70% of the cost and 6x the wall time.
- Playwright MCP blocks `file://`; the agent serves the folder over http first.
- Inline `mcpServers` in an agent file failed to load tools in 9 of 39 runs; use the session's plugin MCP servers instead.
- Haiku is not reliable for tool-heavy verification; `omitClaudeMd` / `tools` restrictions save little and cost some quality.
- Keep subagent replies to a few lines and have them write bulky output to files; read only log tails in the main session.
- Do not pass `model` or `effort` to the Agent tool for a custom agent that sets them; the call parameters override the agent file.
- Relative links may point outside the served folder; check local links on disk, not by HTTP status.
- Parallel agents that all serve on the same port read each other's pages; check the port is free before serving.
- Opus at high effort adds cost and time but no score for browser checks.
