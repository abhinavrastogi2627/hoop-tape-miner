# hoop-tape-miner docs

hoop-tape-miner is AI basketball video analysis for amateur and club teams. A local computer-vision pipeline (player and ball detection, court mapping, team split, tracking, jersey numbers, possessions) feeds an AI-agent film review (Claude Code or Codex), which writes the team page and the focus player's page (bilingual, with narration audio and film clips, published as private links) and an explained video. Give it a league game link and `hoop-tape-miner run` does the rest, stopping only where the agent has to judge.

Start with the [project README](../README.md) ([中文](../README.zh.md)) for what you get and the quick start.

| Doc | For | What's in it |
|---|---|---|
| [playbook.md](playbook.md) | users and AI agents | The one-command run and every step from a league link (or a video) to the pages and the explained video |
| [pipeline.md](pipeline.md) | contributors | Every stage, its inputs and outputs, and the design choices behind them |
| [review_protocol.md](review_protocol.md) | contributors | The optional possession event review that feeds the shot charts |
| [privacy.md](privacy.md) | everyone | What stays in `workspace/`, sharing reports, minors and consent |
| [research.md](research.md) | contributors | Open-source projects and papers this builds on, and what was adapted |
| [optimization-backlog.md](optimization-backlog.md) | contributors | Measured speed and cost improvements, done and to do |

Writing guides the agent uses for each report, and the coaching knowledge base the insights cite ([`coach_kb.md`](../prompts/coach_kb.md)), are in [`prompts/`](../prompts/). To contribute, see [CONTRIBUTING.md](../CONTRIBUTING.md).
