---
description: One training session, phone videos to deliverables - scan, review every rep, write, plan the next session
argument-hint: <phone video...> [--plan "what you meant to train"] | <session folder>
---

Produce this training session's deliverables from `$ARGUMENTS`, following `docs/playbook.md` ("Personal training sessions"):

1. The session page (`index.html`, bilingual, narration audio and clips of key reps): makes / attempts per zone and finish type, form numbers, dribbling, last session's targets checked, progress over sessions.
2. `plan.json` (next session's drills with checkable targets) and the plan section of the page.
3. The explained video `film.<lang>.mp4` (languages from `workspace/team.json`). It is never published; the user keeps or sends it themselves.

Loop:

- Run `uv run hoop-tape-miner train $ARGUMENTS > workspace/logs/train.log 2>&1` and read only the tail of the log. After the first run, pass the session folder it printed instead of the videos.
- Exit 3 means it is waiting for you: do exactly the step the log names (playbook, "Personal training sessions"), then run it again. Exit 1: read the stage log it names, fix the cause, run again. Exit 0: done.
- Film review: one subagent per `brief_part<N>.md`, at most 3 at once; they write files and reply in a few lines. Do not read the sheets yourself.
- Browser checks go to the browser-check subagent. Publish only when the user asks: then run once more with `--publish` (the page gets its own private link and is never listed on the team hub).

Rules: one session per conversation; reuse an existing `run/` and never re-run `train-scan` when `pose.npz` exists; never invent a make ("unclear"); every number in the report comes from `facts.md`; never commit anything from `workspace/` or any media.

Reply at the end with: the page path (or link), the explained video paths, and the next session's targets in three lines.
