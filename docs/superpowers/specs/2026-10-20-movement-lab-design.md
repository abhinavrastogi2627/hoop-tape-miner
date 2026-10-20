# Movement lab: running pattern, force pattern, layup approach, fuel and recovery

## Intent

The owner (#17, adult rec league, ~30, 173 cm, 76 kg) can run 10 km but feels "heavy and clumsy" when he
sprints full court. His calves get very sore (worst on a treadmill), his knees ache after games, his glutes do not.
A teammate who trained with a track team diagnosed it in a chat: he runs like a distance runner (upright, short
steps, "dragging the lower leg", calf-driven), while basketball is almost all sprints, which need forward lean, full
hip-knee-ankle extension, long and fast steps, glute-driven. The owner suspects the same pattern hurts his layups
and his full-court speed dribble.

He wants three things: (1) an expert diagnosis of his running and force pattern and how it should look for
basketball (sprints, transition, speed dribble, layup approach and take-off), with how to fix and train it; (2) how
to eat and recover around this training; (3) a knowledge framework and pipeline that stay in the repo, so that when
he films new videos in a few days the analysis updates by running the pipeline again. Deliverables now: an HTML page
and an explained video per language, built from the footage that exists today, with every gap marked as such.

## Goals

- **Knowledge base** (repo, `prompts/`), sourced like `prompts/skill_kb.md` (Symptom / Why it happens / What to
  check on film / Cue zh+en / Drill / Target / Source, "(our rule)" labels, trial values marked):
  - `movement_kb.md`: running and force pattern for basketball. Starting entry list (builder may merge or split
    once the research is read): acceleration posture (upright first steps), braking touchdown / overstride, calf-
    or ankle-dominant push vs hip extension, short stride / low step length in acceleration, backside mechanics
    ("dragging the lower leg"), arm action, transition sprint with the head up, speed / push-ahead dribble, layup
    approach and penultimate step, one-foot take-off (horizontal to vertical), deceleration and stopping, landing,
    repeated-sprint fade, calf and knee load capacity, distance-running habits that carry over.
  - `fuel_recovery_kb.md`: energy and macros by day type, protein per meal, carbs around training and games,
    hydration and sweat rate, game-day timing (evening games), supplements with strong evidence only (AIS group A),
    sleep, recovery methods ranked by evidence, soreness vs pain and red flags, load progression and deload,
    body composition trade-off. Chinese-food examples.
  - Each entry says which measured field or film observation triggers it, so reviewers and writers can cite slugs.
- **Teammate claims checked**: every claim from the chat gets a verdict (supported / partly / not supported) with
  the source, shown on the page. The teammate is treated as a useful hypothesis, not as the authority. The chat
  (translated, no names) is in `workspace/players/<player>/movement/teammate_chat.md`. Claims to grade:
  1. full-court heaviness is a movement-pattern problem, not body weight or upper-body bulk;
  2. half court tolerates short steps, full-court sprinting needs long strides;
  3. fast-break sprinting = head down, forward lean, full hip-knee-ankle extension, very high frequency and very
     long stride (LeBron example);
  4. distance running does not need a lowered centre of mass / upright is fine there; basketball is all sprints;
  5. many basketball coaches do not know these details;
  6. run full court "bouncing like an antelope";
  7. he "drags the lower legs", which makes calves and thighs sore after a few trips;
  8. after basketball the glutes should be the sore muscles (glute-max drive), not calves or knees;
  9. (owner) this is why he can run 10 km but runs badly in basketball.
- **Pipeline** (repo, `src/hoop_tape_miner/`), a `move` flow that mirrors `train`: one command, deterministic
  stages, exit 3 where the agent looks or writes, rerunnable when new clips arrive.
- **Baseline analysis now** from existing footage, written to the player KB and delivered as page + film.
- **Plan** that slots the running work into the existing 8-week program (`program/2026-10-20/`, sessions
  A braking strength / B court movement / C skill with trainer / D power + conditioning) instead of a second,
  competing program, plus a filming protocol for the re-shoot and re-tests.

## Non-goals

- No 3D biomechanics, force plates, IMUs or ground-reaction forces. "Force pattern" is inferred from kinematics
  (joint angles, foot placement, timing) and stated as inference.
- No medical diagnosis. Knee and calf complaints get load advice, capacity work and red flags that send him to a
  physio.
- No re-run of the game CV pass. No new game analysis.
- No numeric sprint claims from game tracking: the 2026-10-14 tracks identify only 4 sprint bursts for #17 (median
  peak about 5.7 m/s, camera pans, jersey identity on few tracklets), too few to judge; report as "unclear".

## Anti-goals

- Generic running advice not tied to his footage or his complaints.
- Stating a gait fault as seen when the footage cannot show it. Today's footage has no side-view sprint: the
  training video (phone, side-on, 30 fps) shows drives, first steps, layup approaches and landings; the game video
  shows transition runs at about 50 px player height. Sprint-gait faults are "hypotheses to test on the re-shoot" until
  filmed, never "seen". 2D pose cannot show which muscle drives a step or the force direction; "glute-driven"
  and similar are explained as models from the literature, not as measurements.
- A diet that turns into a cut that saps power during the 8-week block.
- Reusing the rejected claim "finishes made ~41° vs missed ~30° knee bend" (3 misses only).

## Constraints

- Privacy as in `docs/privacy.md`: all personal output under `workspace/players/<player>/` (gitignored), heavy media
  under `<media root>/players/<player>/movement/<date>/`. Repo gets only code, prompts (KB), docs, tests.
- 2D pose from one camera (YOLO `yolo11s-pose`, 17 COCO keypoints, as in `train_scan.py`): angles are projections,
  comparable only between clips from a similar camera spot; contact and flight times are reported only at 100 fps or more (a 2D running study needed >=100 Hz for
  event detection) and only after the validation check below; at 30 fps report step counts, cadence, posture and placement only.
- The tree has uncommitted work from an earlier session (training scan, `prompts/skill_kb.md`). Do not overwrite it;
  commit only this project's files unless the owner says otherwise. Master is the main branch.
- At most 3 subagents at once; browser checks via the `browser-check` subagent.
- Reply language Chinese; code, docs, KB in English; page and film bilingual (zh first).

## Design (decided)

Layout. A movement session lives in `<workspace>/players/<player>/movement/<YYYY-MM-DD>[-n]/` with
`movement.json` (kind `movement`, player, date, clips with `kind`, `fps`, camera `view` side | front | behind | game,
time ranges, and `sources` for footage reused from training or game folders), the review, `summary.json`,
`facts.md`, figures, page, film scripts and `plan.json`. Heavy files go to the media root as in training.

Clip kinds: `sprint` (side view, 20-30 m from standing / falling start), `run` (side, steady or treadmill),
`dribble-sprint` (speed dribble full court), `layup` (approach, take-off, landing, side or 45°), `decel`
(sprint to stop), `game` (reference moments from a game video), `training` (reference moments from a training
session).

Stages (one module each, registered in `cli.py`):

| Stage | Does |
|---|---|
| `move-new` | scaffold the session folder from clips or from references into existing training/game videos |
| `move-scan` | pose per clip at native fps (cap 120), follow the main person (reuse `train_scan.scan/pick`), detect foot contacts, compute per-step and per-clip metrics (below), write `gait.json` per clip |
| `move-sheets` | key-frame sheets (touchdown, mid-stance, toe-off, penultimate, take-off, landing) with skeleton and angle overlays; overlay mp4 per clip; filled briefs from `prompts/movement_review_brief.md` |
| agent | reviewer per clip group writes `review.json`: faults seen / not seen / not visible, each tied to times and KB slugs, confidence |
| `move-summary` | merge metrics + review -> `summary.json`, `facts.md`, figures (zh + en), reference ranges from the KB, progress vs earlier movement sessions |
| agent | `README.md` / `README.en.md` (`prompts/movement_report.md`), `plan.json`, `listen.<lang>.md`, `film.<lang>.md` |
| existing | `narrate`, `film`, `html`, `publish` reuse (`game_config.load_game` must find `movement.json`) |
| `move` | orchestrator over the above, same exit-code contract as `train` |

Metrics (2D, per clip; missing = unknown, never zero): step count and cadence; step length in leg lengths when the
camera is static and side-on; trunk lean (hip to shoulder vs vertical) at the first three touchdowns and at speed;
shin angle at touchdown; touchdown point ahead of the hip in leg lengths (braking indicator); knee lift (thigh angle
peak); heel recovery height; thigh separation at toe-off; hip-height bounce; arm swing range; contact / flight time
when fps >= 100. Layup: length of the last three steps relative to each other, hip drop on the penultimate step,
take-off knee angle and trunk angle, take-off foot ahead of the hip, landing knee flexion. Dribble-sprint: dribbles
per court length, ball height vs hip (when the ball is detected), head angle.

Baseline now (2026-10-20): sources are the training session `training/2026-10-20` (and its `pose.npz`; exclude
19:35-21:20, the tracker followed the trainer) and the game video `<opponent>/2026-10-14` (moments already listed in
`<media root>/players/<player>/program/2026-10-20/movement_review.md`). The page shows: the teammate claims with verdicts;
the model (distance running vs sprint vs basketball movement) with simple diagrams; what his footage shows, with
overlay stills and clips; what it cannot show yet; the fixes (cues, drills) and where they go in sessions A-D;
fuel by day type with Chinese-food menus; recovery week and calf/knee care with red flags; the filming protocol
and tests for the re-shoot. The film follows the same story in about 4-6 minutes per language.

Baseline sources in detail (builder-check answers):
- Pose: `move-scan` re-runs pose at the video's native fps (30 for the training video) only inside reference
  windows (about 2 s before to 1.5 s after each reviewed finish, plus the drive / first-step / landing moments in
  `movement_review.md`), not over the whole 44-minute video. The existing 15 fps `pose.npz` is not used for gait.
- Layups: the training review already has about 30 reviewed finishes with times (`run/train_review/review_part*.json`,
  `category: finish`); 31:46-35:10 is a clean block of wing drives into layups, both hands, side-on camera. Layup
  metrics are built, tested and used in the baseline with "about" wording; contested reps are labelled.
- Game footage is review-only: the reviewer watches the listed moments; `move-scan` computes no metrics on
  `view: game` clips (panning camera, ~50 px players). (my call)
- Shared code: `move-scan` imports `train_scan.scan/pick` as they are in the working tree (`pick(..., follow=)` is
  part of the uncommitted work); `game_config.load_game` is unmodified and gets the `movement.json` lookup.
- Overlap with `prompts/skill_kb.md` (19 entries, uncommitted, incl. repeated sprints, landing, strength, warm-up,
  recovery): `movement_kb.md` cross-references those slugs instead of duplicating them; `fuel_recovery_kb.md`
  goes deeper than the skill KB's recovery entry and the skill KB entry points to it. (my call)
- Program: the running work is merged into `program/2026-10-20/index.html` in place (it starts 2026-10-21, no
  ticks yet); the old file is kept as `index.v1.html`. (my call)
- Sharing: page and films stay local, MP3/MP4 copied to the Desktop like the training page; publish only if the
  owner asks (the training page was never published). (my call)

Player KB updates: `focus.md` gains the running/force focus, `log.md` gets a dated entry, `README.md` lists the
movement folder, and the `player KB` memory is updated.

Measurement validation (before any metric reaches the page): hand-label foot contacts, penultimate step and
take-off frame by frame on about 10 real layup approaches from the training video; compare with `move-scan`
(timing error, missed and extra contacts, identity switches to the trainer). A metric whose check fails is not
shown; the reviewer reads it off the key-frame sheets instead and says so. Synthetic tests cover the code, the
hand-labelled check covers the measurement. The movement flow follows the player (`seed` / `look`), not the ball.

Safety order on the page and in the plan: a pain check (knee and calf, 0-10 scale, next-morning response) comes
before any new sprint or jump load; load rises only when the check stays low (thresholds from the KB). Cross-session
comparisons need the same camera spot, action and metric version (`metrics_version` in `gait.json`).

Build order: KB from the research -> measurement validation on real clips -> baseline page and film from what is
confirmed (layup review with times, game moments, model, fixes, fuel, recovery) -> more automatic metrics ->
program merge.

## Left to the builder

- Final KB entry list and wording, from the three research files in
  `<media root>/players/<player>/movement/research/` (`sprint_mechanics.md`, `basketball_movement.md`,
  `nutrition_recovery.md`).
- Foot-contact detection method and thresholds (ankle height / velocity minima, toe keypoints are not in COCO-17),
  smoothing, how to pick the main person in sprint clips.
- Figure designs, page layout (follow the existing training page and program page styles), film scene list.
- Test coverage: synthetic keypoint series for contact detection and each metric; no GPU or video in tests.
