# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Film clips in reports: mark a play with `![caption](clip:mm:ss-mm:ss)`, cut it with the new `clips` stage, and the HTML page shows a numbered player with a slow-motion button next to the analysis (embedded in `--share` files). Writing guides say which plays deserve a clip.
- Explained video: the new `film` stage turns `film.<lang>.md` into one MP4 where the narration plays over chapter cards, charts and the report's clips, with burned-in subtitles; clips replay at half speed when the explanation is longer than the play. Writing guide: `prompts/film.md`. The film can freeze a clip and draw on it: `> 07:28 我#17 对#25 "label"` dims the frame, rings the players (found in the CV tracks, or placed by hand) and adds arrows. It also has animated court diagrams (`![caption](court:plays/x.json)`), big-number stat scenes (`stat:`) and chapter cards over blurred game footage (` · ` splits a title into lines). A `>` line on its own resumes the clip while the narration goes on. Speech has its trailing silence trimmed, so scene changes no longer pause.

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
