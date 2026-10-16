# Optimization backlog

From GitHub/paper research and running the pipeline on full games (2026-10).

## Done
- ByteTrack `lost_track_buffer=60` (= 2 s; `trackers` counts it in 30 fps frames).
- `analyze.identities`: a tracklet whose vote is "none" is accepted when it has exactly one distinct non-none read that is on the team roster.
- `jersey.pick_crops`: group detections by frame once instead of filtering the whole frame per row (output identical, tested).
- Claude Code setup: `CLAUDE.md`, `.claude/settings.json` (output and auto-compact caps), `.claude/agents/browser-check.md` (Sonnet, effort high; keeps screenshots out of the main context; findings below).

## Todo, by expected gain
1. Ball track cleanup + ball-contact possession / shot signal (the ball is detected in roughly 70% of frames but unused downstream).
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
