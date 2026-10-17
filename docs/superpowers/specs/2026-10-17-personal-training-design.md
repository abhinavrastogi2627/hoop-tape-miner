# Personal training sessions: video -> session report, explained video, next-session plan

## Intent

A player records their own solo workout on a phone (shooting, dribbling, finishing) and wants, after every
session, (1) a private web page and (2) an explained video that say how the session went and, above all, what to
change in the next one. Over weeks the sessions form a loop: game report -> training plan -> session -> report ->
adjusted plan. The game pipeline already turns one game video into pages, clips, narration and a film; this adds
the same deliverables for one training session.

## Goals

- One command flow, like `run` for games: `hoop-tape-miner train <video...>` creates the session, runs the
  deterministic stages, and stops (exit 3) where the agent has to look or write.
- Numbers a player can act on, all traced to video times:
  - shooting: makes / attempts per zone (ft, rim, paint, mid, three), spot and shot type; miss pattern
    (short / long / left / right); longest make streak; first vs last third of the session (fatigue);
  - finishing: makes / attempts per finish type and hand (left-hand share);
  - dribbling: drill time, hand balance, ball losses, estimated bounce rate (pose);
  - shooting form from pose (2D, same camera set-up only): knee bend at the dip, elbow angle and release
    height at release, dip-to-release time, jump; mean, spread (consistency) and makes vs misses;
  - volume: session length, active time, reps per active minute.
- Progress across sessions: every earlier session of the same player feeds a progress table and chart.
- A next-session plan with measurable targets (`plan.json`); the next session checks them (met / missed / not
  trained) automatically.
- Deliverables, same as games: `index.html` (bilingual, narration, clips) published as a private link that is
  never listed on the team hub, and `film.<lang>.mp4` sent by hand.

## Non-goals

- No automatic make/miss detection from CV in this version (the agent reviewer decides from a rim filmstrip);
  no ball tracking, no court calibration, no multi-player sessions.
- No 3D biomechanics: pose angles are 2D projections and only comparable between sessions filmed from a
  similar spot.

## Anti-goals

- Inventing makes or numbers: unclear reps stay `unclear` and are reported separately.
- A plan that is generic advice: every plan item must point to a number or clip from this session (or the
  latest game deep dive) and carry a target the next session can check.
- Publishing training pages on the team hub or sending them to teammates.

## Design

Layout. A session lives in `<workspace>/players/<player>/training/<YYYY-MM-DD>[-n]/` (gitignored like all
workspace data): `session.json`, the report files, figures, `summary.json`, `plan.json`. Heavy files
(`session.mp4`, `run/`) go to `<media_root>/players/<player>/training/<date>/` when `team.json` sets
`media_root`, else into the session folder.

`session.json` (template `templates/session.example.json`): `kind: "training"`, `player`, `name`, `date`,
`sources` (the phone files), `video` (the joined session video), `run`, `hex`, `plan` (what the player meant to
train), `targets` (copied from the previous session's `plan.json`), `rim` (list of `{from, box}` rim boxes as
frame fractions, filled by the agent; `box: null` from a time on = rim out of view from then; `[]` = rim never
visible), `rim_checked`, optional `narration.voices`.
`game_config.load_game` finds `session.json` when there is no `game.json`, so `clips`, `narrate`, `film` and
`html` work on a session folder unchanged.

Stages (one module each):

| Stage | Does |
|---|---|
| `train-new` | scaffold the session, join the phone videos into one `session.mp4` (ffmpeg, rotation applied, 30 fps), copy targets from the previous session's `plan.json` |
| `train-scan` | YOLO pose (ultralytics, `yolo11s-pose.pt`) at 15 fps; follow the main person; write `pose.npz`, `reps.json` (shot/finish candidates at hands-above-head peaks with form metrics), `dribble.json` (wrist-oscillation segments; short segments never near the detected ball are dropped), `activity.json` |
| `train-sheets` | overview sheets (one frame every 10 s), rep sheets (set, release, follow-through frames + a rim filmstrip from the `rim` box), parts and filled briefs `brief_part<N>.md` from `prompts/training_review_brief.md` |
| agent | one subagent per part writes `review_part<N>.json` (blocks, reps with result / zone / spot / type / miss, dribble drills, reps the scan missed) and `memo_part<N>.md` |
| `train-summary` | merge parts with pose metrics -> `summary.json`, `facts.md`, figures (`zones`, `timeline`, `form`, `progress`; zh + en), target check, progress over earlier sessions |
| agent | `README.md` / `README.en.md` (`prompts/training_report.md`), `plan.json`, `listen.<lang>.md`, `film.<lang>.md` |
| existing | `clips`, `narrate`, `html` (training band instead of the score), `publish` (not on the hub), `film` (training title card) |
| `train` | orchestrator over the steps above (reuses `run`'s step driver; exit 3 = agent step) |

Rep detection: per frame the main person's 17 COCO keypoints; `lift(t)` = height of the higher wrist above the
shoulders in torso lengths (rolling median); candidates are peaks of `lift` above 0.75 (`LIFT_MIN`) at least
1.2 s apart (a set shot or layup release sits around 1.0-1.3, dribbling and arm swing below 0.5). Kind hint: `finish` when
the hips travelled more than 1.2 torso lengths in the 1.2 s before the peak, else `shot`. The reviewer confirms
or rejects every candidate (`not_a_rep`) and adds reps the scan missed, so detection only has to be recall-heavy.

Next-session plan (`plan.json`): `{"focus": [...], "drills": [{"name", "category", "reps", "why", "target":
{"name", "match": {field: value}, "attempts", "pct"}}]}`. `match` filters reviewed reps by any rep field
(e.g. `{"zone": "ft"}`, `{"type": "layup-left"}`). `train-new` copies the targets into the next `session.json`.

## Decided by the builder (Claude's calls)

- Make/miss by agent review of a rim filmstrip, not CV: the repo's rule "agents for meaning, CV for geometry",
  and no reliable open hoop/ball make-miss model is available locally.
- Pose via ultralytics YOLO pose (already a dependency, GPU or CPU) rather than MediaPipe (new dependency).
- Report language: bilingual pages like games (the HTML needs both); the film defaults to the languages in
  `team.json`.
- Session folders under `players/<player>/training/`, next to the existing `players/<N>/` cue loops.
