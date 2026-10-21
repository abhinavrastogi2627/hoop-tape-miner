---
description: One game, link to deliverables - fetch the league game, run the pipeline, review, write, publish
argument-hint: <league game url | game folder>
---

Produce this game's deliverables from `$ARGUMENTS`, following `docs/playbook.md` ("One-command run"):

1. The team page and the focus player's page (`index.html` with narration audio and clips), published as links.
2. The explained video `film.zh.mp4` + `film.en.mp4` (languages from `workspace/team.json`). It is never published; the user sends it themselves.

Loop:

- Run `uv run hoop-tape-miner run "$ARGUMENTS" > workspace/logs/run.log 2>&1` in the background (the CV stages take about an hour) and read only the tail of the log. After the first run, pass the game folder it printed instead of the url.
- Exit 3 means it is waiting for you: do exactly the step the log names, as the playbook section it points to describes, then run it again. Exit 1: read the stage log it names, fix the cause, run again. Exit 0: done.
- Film review: one subagent per `brief_part<N>.md`, at most 3 at once; they write files and reply in a few lines.
- Browser checks go to the browser-check subagent. When `qa.md` says PASS (with the `checked:` stamp the run printed at the QA step), run once more with `--publish`, then have the subagent check the live links.

Rules: one game per session; reuse an existing `run/` and never re-run a CV stage whose output exists; never invent a result ("unclear" / "likely"); never commit anything from `workspace/` or any media.

Reply at the end with: the hub link, the team page link, the focus player's link (and who gets it), and the paths of both explained videos.
