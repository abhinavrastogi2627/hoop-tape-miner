# hoop-tape-miner 🏀

**Mine your basketball game tape for the insights that win the next game.**

[![tests](https://github.com/mariusDing/hoop-tape-miner/actions/workflows/tests.yml/badge.svg)](https://github.com/mariusDing/hoop-tape-miner/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](pyproject.toml)
[![Agent: Claude Code | Codex](https://img.shields.io/badge/agent-Claude%20Code%20%7C%20Codex-8A2BE2.svg)](AGENTS.md)
[![good first issues](https://img.shields.io/github/issues/mariusDing/hoop-tape-miner/good%20first%20issue.svg?label=good%20first%20issues)](https://github.com/mariusDing/hoop-tape-miner/issues?q=is%3Aopen+label%3A%22good+first+issue%22)

English · [中文](README.zh.md)

AI basketball video analysis for amateur and club teams. Turn the video of your game into a coach's report: what happened, why you lost or won, how the opponent plays, what each player should practise, and a narrated version your teammates can listen to.

You bring one game video. Your AI coding agent ([Claude Code](https://claude.com/claude-code) or [Codex](https://openai.com/codex)) runs the computer-vision pipeline in this repo on your own GPU, reviews the film like a coach, and writes the report. No subscription, no upload of your video to a sports-analytics service.

**Who it's for**

- Amateur, club and rec-league teams that film their games but never have time to study the tape.
- Captains and volunteer coaches who want a scouting report on the opponent before the rematch.
- Developers who want a working basketball computer-vision and AI-agent film-review pipeline to fork and build on.

![The report: score, a big play button for the narration, and the coach's write-up](docs/images/hero.png)

## What you get

For every game, one folder with:

- **A coach report** in English and Chinese, switchable on the page: how the game went, the opponent's key players and habits, what worked and what didn't for you, a game plan for the rematch, and a practice plan.
- **A review of every player on your team**, with what went well, what to fix, and two drills each. You can send it to the whole team.
- **Charts** of the score margin and scoring runs, shot zones, heat maps, and team comparisons.
- **A narrated MP3** of the report in both languages, with a big play button on the page. Teammates without time to read can listen on the way to practice.
- **An explained video**: the narration plays over the key plays and charts it talks about, with subtitles burned in (half-speed replays when the explanation runs longer than the play). The team can just press play.
- **One shareable HTML file**: images, audio and film clips embedded, opens offline, works in chat apps.
- **Optional extras:** a private deep dive for one player, and a short looping MP3 of on-court cues ("two dribbles, find a man") to listen to while you play.

Every claim in the report points to a video time, and the key plays come with **film clips right next to the analysis** (with slow motion), so the team can watch the moment while discussing what to change.

| Bilingual report | Charts | On a phone |
|---|---|---|
| ![Chinese version of the report](docs/images/report-zh.png) | ![Figures inside the report](docs/images/charts.png) | ![Mobile view](docs/images/mobile.png) |

*Screenshots are from a real game with the team names changed.*

## How it works

```
game video ──► computer vision (GPU, ~1 h) ──► film review by AI agents ──► report + charts + narration ──► one HTML file
               players, ball, court position      coach checklist per         written from structured facts
               teams, jersey numbers              stretch of the game         with video times for every claim
```

1. **Computer vision:** detects players and the ball every frame, maps them onto the court, splits the two teams by jersey colour, and reads jersey numbers.
2. **Possessions and lineups:** who was on court, who had the ball, when each possession started and ended. If your league publishes a box score, it is aligned with the video.
3. **Film review:** the game is cut into annotated frame sheets. Your agent sends subagents through them with a coach's checklist covering transition defence, ball pressure, shot selection and more.
4. **Facts first, then writing:** reviews are merged into fact sheets (plus-minus, stints, patterns, clips). The report is written from those facts using the templates in [`prompts/`](prompts/).
5. **Render:** charts, narration (Microsoft Edge neural voices), short film clips of the key plays (cut with ffmpeg from the windows the report marks) and a single self-contained HTML page.

Full details: [docs/pipeline.md](docs/pipeline.md).

## Quick start

### 1. Requirements

- An **NVIDIA GPU** with 8 GB or more of VRAM, on Windows or Linux. The jersey reader needs CUDA.
- [uv](https://docs.astral.sh/uv/), Python 3.11, and `ffmpeg` on your PATH.
- About 20 GB of disk for the models. They download on first use.
- Claude Code or Codex. The pipeline can also be run by hand, but the film review and the writing are agent work.
- One full game video from a single camera on the side of the court (a typical club recording).

### 2. Install

```bash
git clone https://github.com/mariusDing/hoop-tape-miner.git
cd hoop-tape-miner
uv sync
uv run hoop-tape-miner          # lists every stage
```

### 3. Start a game

```bash
uv run hoop-tape-miner new-game --opponent "Red Foxes" --date 2026-10-14 --video path/to/game.mp4 --us-team "Night Owls"
```

This creates `workspace/teams/red-foxes/2026-10-14/` with a `game.json` to fill in: team names, jersey colours, rosters and the final score. Everything in `workspace/` stays on your machine and is never committed.

### 4. Let your agent run it

Open Claude Code or Codex in the repo and say:

> Analyse the game in `workspace/teams/red-foxes/2026-10-14` following docs/playbook.md. We are Night Owls in dark blue.

The agent follows [docs/playbook.md](docs/playbook.md) step by step ([`CLAUDE.md`](CLAUDE.md) and [`AGENTS.md`](AGENTS.md) point it there). It will stop and ask you twice:

1. **Court calibration:** confirm a few court points on a frame.
2. **Team colours:** confirm which colour cluster is your team.

When it finishes, open `workspace/teams/red-foxes/2026-10-14/index.html`.

### 5. Share it

```bash
uv run hoop-tape-miner html workspace/teams/red-foxes/2026-10-14 --share --out Night-Owls_vs_Red-Foxes.html
```

The shared file embeds the film clips (480p, about 1 MB per 10 s of clip), so a report with a dozen clips is a few tens of MB. Clips show real players: send it to the team only (see [docs/privacy.md](docs/privacy.md)).

The result is a single file with images and audio inside. Send it in any chat app. If an in-app viewer blocks scripts, the page falls back to the phone's own audio player.

## Commands

| Stage | What it does |
|---|---|
| `new-game` | create the game folder and `game.json` |
| `calibrate` | court calibration keyframes |
| `extract` → `embed` → `tracks` → `jersey` | computer vision: detections, team split, tracking, jersey numbers |
| `analyze` | identities, possessions, tactical metrics |
| `official` | import a league box score and align it to the video (optional) |
| `coach-sheets` → `merge-reviews` → `coach-summary` | film-review sheets, merge and aggregate the agents' reviews |
| `plusminus`, `report`, `momentum`, `replay` | facts and figures |
| `narrate` | spoken script → MP3 (`--chime --gap 6 --loud` makes an on-court cue loop) |
| `clips` | cut the film clips a report marks (`![caption](clip:07:24-07:33)`) |
| `film` | explained video: narration over the clips, freeze frames with the players ringed, court diagrams and charts, with subtitles (`film.<lang>.md` → `film.<lang>.mp4`) |
| `html` | report folder → one bilingual HTML page (`--share` for a single sendable file) |

Run `uv run hoop-tape-miner <stage> -h` for the options of each stage.

## Project layout

```
docs/playbook.md         the procedure your agent follows, video → report
prompts/                 writing guides: film review brief, coach report, player deep dive, narration, court cues
templates/               game.json and opponent dossier skeletons
src/hoop_tape_miner/     the pipeline (one module per stage)
workspace/               YOUR data: videos, runs, reports (gitignored)
```

## FAQ

**Does it need the internet?** The models download once. After that the vision and analysis run locally. Narration sends the narration text (not the video) to Microsoft's text-to-speech service. Your agent runs on whichever service you use it with.

**Can I run it without a GPU, or on a Mac?** Not yet. Detection falls back to CPU, but that is very slow, and the jersey reader needs CUDA.

**My league has no box score.** That's fine. Put the final score in `game.json` and the report is built from the film review alone.

**How accurate is it?** The vision gives positions and possessions. The judgement comes from the film review, which flags anything uncertain (an unreadable jersey, for example) as "likely". Check the clips it points to before you act on them.

**Which languages?** The report and narration come in English and Chinese.

**Privacy.** The reports name players and show frames of real people. Read [docs/privacy.md](docs/privacy.md) before sharing, especially if minors play in your league.

## Status and roadmap

Working end to end on real games (one side-on camera, NVIDIA GPU). Known limits and what's next:

- [ ] Run without CUDA (CPU or Apple Silicon jersey reader)
- [ ] A synthetic demo game anyone can run, with no real players in it
- [ ] Box-score importers for more leagues (today: one league format, see [`official.py`](src/hoop_tape_miner/official.py))
- [ ] More report and narration languages beyond English and Chinese
- [ ] Better handling of panning or phone-recorded video

Ideas and votes are welcome in [Discussions](https://github.com/mariusDing/hoop-tape-miner/discussions).

## Contributing

Contributions are welcome, from a typo fix to a new league importer. Start with [CONTRIBUTING.md](CONTRIBUTING.md) and the [good first issues](https://github.com/mariusDing/hoop-tape-miner/issues?q=is%3Aopen+label%3A%22good+first+issue%22). Ask questions in [Discussions](https://github.com/mariusDing/hoop-tape-miner/discussions).

One hard rule: never attach game videos, frames, rosters or names of real players to issues or pull requests. See [docs/privacy.md](docs/privacy.md).

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report security issues privately as described in [SECURITY.md](SECURITY.md).

## Acknowledgements

Built on [RF-DETR](https://github.com/roboflow/rf-detr), [supervision](https://github.com/roboflow/supervision) / [trackers](https://github.com/roboflow/trackers), [SigLIP](https://huggingface.co/google/siglip-base-patch16-224), [Qwen3-VL](https://huggingface.co/Qwen), [edge-tts](https://github.com/rany2/edge-tts), and ideas from [basketball_analysis](https://github.com/abdullahtarek/basketball_analysis). See [docs/research.md](docs/research.md).

## License

[MIT](LICENSE). Models downloaded at run time keep their own licences.

To cite this project, use **Cite this repository** in the GitHub sidebar ([CITATION.cff](CITATION.cff)).

If this helps your team, a ⭐ helps others find it.
