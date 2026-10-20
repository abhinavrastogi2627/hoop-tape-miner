---
description: One movement session (running form, force pattern, layups) - segments to page, film and training / fuel / recovery plan
argument-hint: <segments.json> [--player 17 --look "what the player wears"] | <movement session folder>
---

Produce this movement session's deliverables from `$ARGUMENTS`, following `docs/playbook.md` ("Movement sessions"):

1. The movement page (`index.html`, bilingual, narration audio and clips from the skeleton overlay reel): verdict, teammates' claims checked, the model, what the footage shows and cannot show, training plan, pain check, fuel, recovery, re-shoot and re-tests.
2. `plan.json` (drills in sessions A-D with KB slugs, re-tests, nutrition, recovery).
3. The explained video `film.<lang>.mp4` (languages from `workspace/team.json`). It is never published; the user keeps or sends it themselves.

Loop:

- Run `uv run hoop-tape-miner move $ARGUMENTS > workspace/logs/move.log 2>&1` (with a spec: `move --spec <file>`) and read only the tail of the log. After the first run, pass the session folder it printed.
- Exit 3 means it is waiting for you: do exactly the step the log names (playbook, "Movement sessions"), then run it again. Exit 1: read the stage log it names, fix the cause, run again. Exit 0: done.
- Identity check, label check and review: subagents, at most 3 at once; they write files and reply in a few lines. Do not read the sheets yourself. When a reviewer says the crop follows someone else, fix `who` / `release` and re-run `move-scan --repick` and `move-sheets --force` before trusting that group.
- Browser checks go to the browser-check subagent. Publish only when the user asks (`--publish`; the page gets its own private link and is never listed on the team hub).

Rules: one session per conversation; reuse `run/seg/*.raw.npz` (never `--force` the scan without a reason); numbers only from `facts.md`, and only side-view metrics that passed the label check; what a view cannot show is "not visible", never a guess; never commit anything from `workspace/` or any media.

Reply at the end with: the page path (or link), the explained video paths, and the top three changes with their drills.
