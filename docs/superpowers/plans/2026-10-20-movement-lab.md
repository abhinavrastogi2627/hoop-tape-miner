# Movement Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `move` flow (clips -> reel -> pose -> 2D gait/layup metrics -> overlays and sheets -> agent review -> summary -> page and film), two sourced knowledge bases (running/force pattern; fuel/recovery), and the 2026-10-20 baseline for the owner from existing footage.

**Architecture:** A movement session is a folder with `movement.json` listing segments (source video, from/to, kind, view). `move-new` cuts every segment into one 30 fps `reel.mp4` (so `clips`, `html`, `film` keep working on one video); `move-scan` runs pose on each segment from its *source* at native fps (cap 120) and computes metrics with pure functions in `gait.py`; `move-sheets` draws skeleton/angle overlays (`reel.overlay.mp4`), key-frame sheets, label strips and briefs; `move-summary` gates metrics by a hand-labelled check and writes `summary.json` / `facts.md` / figures. `move` drives it like `train` (exit 3 = agent step).

**Tech Stack:** Python 3.11, numpy, opencv (cv2), ultralytics YOLO pose (`yolo11s-pose.pt`), ffmpeg, matplotlib, pytest; uv.

**Spec:** `docs/superpowers/specs/2026-10-20-movement-lab-design.md`

## Global Constraints

- Personal data only under `workspace/players/<player>/movement/<date>/` (gitignored); heavy media under `<media_root>/players/<player>/movement/<date>/` (`<media root>/...` via `team.json` `media_root`). Never commit workspace, video, frames, audio, names.
- 2D pose numbers are written "about"; missing = unknown (None/NaN), never 0. Contact/flight time only when segment fps >= 100.
- No metrics on `view: "game"` segments (review-only).
- A metric whose hand-labelled check fails is not shown (`summary.json` `shown: false`).
- Sprint-gait faults without a side-view sprint clip are "hypotheses to test on the re-shoot", never "seen".
- `metrics_version` (int, start 1) in every `gait.json`; cross-session comparison only for equal kind, view and version.
- Follow the player (`seed` / `look`), not the ball.
- Code, docs, KB in English; page and film zh + en; replies to the owner in Chinese.
- Tests: `uv run pytest -q`, synthetic keypoints only, no GPU/video/network.

## Review Focus

1. Pose loses the player for some frames or swaps to the trainer mid-approach -> contacts in the gap are not invented; metrics from that segment are None, not wrong numbers. (Task 2 test `test_contacts_gap_no_invention`.)
2. Player runs right-to-left -> all signed metrics (lean, touchdown ahead, shin) keep the same sign convention. (Task 2 test `test_direction_mirror`.)
3. Segment `from/to` outside the source video or a missing source file -> `move-new` stops with a clear message, no half-written reel. (Task 3 test `test_reel_plan_rejects_bad_window`.)
4. A 240 fps phone slow-mo file -> scanned at 120 fps cap, contact times reported; reel plays it at real time. (Task 3 test `test_reel_plan_fps`, Task 4 test `test_scan_fps_cap`.)
5. Re-running after new clips are added -> existing segment scans are reused, only new ones scanned; earlier movement sessions feed progress only when kind/view/version match. (Task 4 test `test_scan_skips_done`, Task 6 test `test_progress_matches_only_same_kind`.)

---

### Task 1: Knowledge bases (movement + fuel/recovery) and skill-KB cross-links

**Files:**
- Create: `prompts/movement_kb.md`, `prompts/fuel_recovery_kb.md`
- Modify: `prompts/skill_kb.md` (add "see also" lines to the repeated-sprint, landing, recovery and warm-up entries)

**Interfaces:**
- Produces: entry slugs `MV-...` (movement) and `FR-...` (fuel/recovery) cited by `prompts/movement_review_brief.md`, `prompts/movement_report.md` and `review.json` `kb` fields; a "Reference values" table in `movement_kb.md` that Task 6's `REFERENCE` dict copies (metric key, band, view/kind it applies to, source).

- [ ] **Step 1:** Read `prompts/skill_kb.md` header (format, "(our rule)", trial values, source rules) and the three research files in `<media root>/players/<player>/movement/research/`.
- [ ] **Step 2:** Write `movement_kb.md`: header like skill_kb (how agents use it; fields refer to `gait.json` keys of Task 2 and `review.json` of Task 5), then entries with Symptom / Why / What to check on film (side phone, 120-240 fps, and game camera) / Cue zh+en / Drill (sets, reps, rest, progression) / Success measure / Source / Evidence level. Entries at least: MV-accel-posture, MV-braking-touchdown, MV-ankle-dominant-push, MV-short-accel-stride, MV-backside-mechanics, MV-arm-action, MV-transition-head-up, MV-speed-dribble, MV-layup-penultimate, MV-one-foot-takeoff, MV-decel-stop, MV-landing (links skill_kb landing), MV-distance-habits, MV-calf-capacity, MV-knee-load, MV-hamstring-safety. Add "Teammate claims" verdict table (9 claims from the spec) and "Reference values" table. Add the filming protocol (camera height, distance, 120/240 fps, which clips) and the re-test battery (10/20 m sprint, full-court speed dribble each hand, 5-10-5, CMJ app, one-leg approach jump reach).
- [ ] **Step 3:** Write `fuel_recovery_kb.md` in the same format: FR-energy-by-day, FR-protein, FR-carbs-timing, FR-game-day (evening game), FR-hydration, FR-supplements (AIS A: creatine 3 g/d, caffeine rules; "AIS A = evidence in specific contexts, not fit for everyone"), FR-sleep, FR-recovery-ranked, FR-soreness-vs-pain (pain 0-10 rule, red flags -> physio), FR-load-progression, FR-body-comp; Chinese-food menus per day type and a plate method.
- [ ] **Step 4:** Add cross-links in `skill_kb.md`. Check: every number in both KBs has a source or "(our rule)"; claims the research marked unverified are marked "unverified" or dropped.
- [ ] **Step 5:** Commit `git add prompts/movement_kb.md prompts/fuel_recovery_kb.md prompts/skill_kb.md && git commit -m "Add the movement and fuel/recovery knowledge bases"`.

### Task 2: `gait.py` — contacts, step, layup and dribble metrics (pure)

**Files:**
- Create: `src/hoop_tape_miner/gait.py`, `tests/test_gait.py`

**Interfaces:**
- Consumes: `training.angle`, `training.masked`, `training.rolling_nanmedian`, COCO constants from `training`.
- Produces:
  - `METRICS_VERSION = 1`
  - `direction(t, kp) -> int` (+1 = moving to image right, -1 left, 0 unknown; from hip-x trend)
  - `leg_length(kp) -> float` (median hip-to-ankle px, NaN if unknown)
  - `foot_contacts(t, kp, conf, min_gap_s=0.12) -> list[dict]` items `{"foot": "L"|"R", "on": float, "off": float|None, "i_on": int, "i_off": int|None}`
  - `step_metrics(t, kp, conf, contacts) -> list[dict]` per touchdown: `t, foot, trunk_lean, shin, touchdown_ahead, knee_lift, heel_recovery, step_len, step_time, contact_s` (signed so forward = positive in running direction; lengths in leg lengths; `contact_s` None when fps < 100)
  - `clip_metrics(steps, fps) -> dict` `{n_steps, cadence_spm, <key>: {"mean", "sd", "first3"}}`
  - `layup_metrics(t, kp, conf, contacts, release_t) -> dict` `{takeoff_t, takeoff_foot, last3_len, penultimate_ratio, hip_drop, takeoff_knee, takeoff_trunk, takeoff_ahead, landing_knee_min}`
  - `dribble_metrics(t, kp, ball) -> dict` `{bounces, bounces_per_10m (None without scale), ball_top_vs_hip}`
  - `compare_contacts(detected, labelled, tol_s) -> dict` `{matched, missed, extra, mae_s, recall, precision}`
  - `gate(check: dict, fps: float) -> bool` pass when recall >= 0.8, precision >= 0.8 and mae_s <= 1.5 / fps (our rule)

- [ ] **Step 1: Write failing tests** in `tests/test_gait.py` with a synthetic runner generator `runner(fps, speed_px_s, cadence_spm, lean_deg, direction, touchdown_ahead)` that moves hips at constant speed, alternates feet, keeps the stance ankle fixed in x on the floor line for `contact` seconds and lifts the swing ankle. Tests:
  - `test_contacts_found`: 30 fps, 180 spm, 3 s -> 9 contacts +-1, alternating feet, onset error <= 1 frame.
  - `test_direction_mirror`: same runner mirrored in x -> `direction == -1`, `trunk_lean`, `touchdown_ahead`, `shin` means equal within 1e-6 of the unmirrored ones.
  - `test_lean_and_touchdown`: lean 20 deg, touchdown 0.3 leg -> `first3` trunk_lean about 20 (+-3), touchdown_ahead about 0.3 (+-0.05).
  - `test_contact_time_needs_100fps`: 30 fps -> every `contact_s is None`; 120 fps -> contact_s within 1 frame of truth.
  - `test_contacts_gap_no_invention`: NaN keypoints for 0.5 s mid-run -> no contact with `on` inside the gap.
  - `test_layup_penultimate`: runner whose last-but-one step is 1.3x longer with hips 0.08 leg lower, then both wrists rise at `release_t` -> `penultimate_ratio` about 1.3, `hip_drop` about 0.08, `takeoff_foot` correct.
  - `test_compare_and_gate`: detected vs labelled lists with one miss and one extra -> recall/precision/mae exact; `gate` false at recall 0.75.
- [ ] **Step 2:** Run `uv run pytest tests/test_gait.py -q` -> FAIL (module missing).
- [ ] **Step 3:** Implement `gait.py`. Contact rule: per ankle, smoothed (3-frame median) x and y; a contact is a run of >= 2 frames (>= 1 at < 40 fps) where the ankle's horizontal speed < 25 % of the hip's horizontal speed and its y is within 0.06 leg lengths of the rolling 1 s max y (floor); frames with NaN break runs. Signs: multiply x-differences by `direction`. `trunk_lean` = angle of hip->shoulder vs vertical; `shin` = knee->ankle vs vertical at touchdown (positive = knee ahead of ankle); `touchdown_ahead` = (ankle_x - hip_x) * dir / leg; `knee_lift` = max thigh angle from vertical in the swing before the touchdown; `heel_recovery` = min (hip_y - ankle_y)... expressed as ankle height above floor at its peak in swing / leg; `step_len` = horizontal distance between consecutive touchdown ankles / leg.
- [ ] **Step 4:** Run `uv run pytest tests/test_gait.py -q` -> PASS; `uv run pytest -q` -> all pass.
- [ ] **Step 5:** Commit `git add src/hoop_tape_miner/gait.py tests/test_gait.py && git commit -m "Add 2D gait, layup and dribble metrics from pose keypoints"`.

### Task 3: `movement.py` helpers + `move-new` (session, reel)

**Files:**
- Create: `src/hoop_tape_miner/movement.py`, `src/hoop_tape_miner/move_new.py`, `templates/movement.example.json`, `tests/test_movement.py`
- Modify: `src/hoop_tape_miner/cli.py` (register `move-new`), `src/hoop_tape_miner/game_config.py` (`load_game` also finds `movement.json`; `is_movement(game)`; `is_personal(game)` = training or movement)

**Interfaces:**
- Produces (`movement.py`): `KINDS = ("sprint","run","dribble-sprint","layup","decel","game","training")`, `VIEWS = ("side","front","behind","game")`, `REEL_FPS = 30`, `REEL_H = 720`, `SCAN_FPS_CAP = 120`, `root(player) -> Path`, `media_root_for(player, prof=None) -> Path`, `session_name(player, date) -> str`, `is_movement(folder) -> bool`, `load(folder) -> dict`, `path(folder, m, key, default) -> Path`, `earlier(folder) -> list[Path]`, `seg_seconds(seg) -> tuple[float, float]` (parses mm:ss.s / h:mm:ss / seconds).
- Produces (`move_new.py`): `reel_plan(segments: list[dict], durations: dict[str, float], fps: dict[str, float]) -> list[dict]` (adds `reel_from`, `reel_to`, `fps`, `scan_fps = min(fps, 120)`; raises `ValueError` naming the segment on a missing source or a window outside the file); `build_reel(segments, out: Path, height=REEL_H)` (ffmpeg: trim each window, optional `crop` [x,y,w,h] fractions, scale/pad to 16:9, burn a top-left label `S01 · layup · 31:46`, 30 fps, concat); `create(specs: list[dict], player, date, name=None, plan="") -> Path`.
- `movement.json` keys: `kind: "movement"`, `player`, `name`, `date`, `title`, `hex`, `look`, `plan`, `video` (reel.mp4), `video_overlay` (reel.overlay.mp4, set by Task 5), `run`, `segments` (list of `{id, kind, view, source, from, to, crop?, seed?, release?, note}` + reel fields), `labels_checked`.
- CLI: `move-new --player P --date D --spec specs.json` and `move-new <video>... --kind sprint --view side` (each file one whole-file segment).

- [ ] **Step 1: Failing tests** in `tests/test_movement.py`: `test_reel_plan_offsets` (two segments 4.5 s and 3 s -> reel 0-4.5, 4.5-7.5), `test_reel_plan_rejects_bad_window` (to beyond duration -> ValueError mentioning the id; missing source -> ValueError), `test_reel_plan_fps` (240 fps source -> scan_fps 120), `test_seg_seconds` ("31:46.5" -> 1906.5, "1:02:03" -> 3723, 12 -> 12), `test_load_game_finds_movement` (tmp folder with movement.json -> `load_game` returns it, `is_movement` and `is_personal` true).
- [ ] **Step 2:** `uv run pytest tests/test_movement.py -q` -> FAIL.
- [ ] **Step 3:** Implement; durations/fps via ffprobe in `create` only (keep `reel_plan` pure). Write `templates/movement.example.json`.
- [ ] **Step 4:** Tests pass; `uv run hoop-tape-miner move-new --help` prints usage.
- [ ] **Step 5:** Commit.

### Task 4: `move-scan` (pose per segment at native fps, gait.json)

**Files:**
- Create: `src/hoop_tape_miner/move_scan.py`; Test: `tests/test_movement.py` (add)
- Modify: `src/hoop_tape_miner/train_scan.py` (`frames(video, fps, t0=0.0, t1=None)`, `scan(video, fps, ball, t0=0.0, t1=None)`; seek with `CAP_PROP_POS_MSEC`, times stay source seconds), `cli.py` (register `move-scan`)

**Interfaces:**
- Consumes: `train_scan.scan`, `train_scan.pick(raw, seed, follow="player")`, `gait.*`, `movement.*`.
- Produces: `run/seg/<id>.npz` (picked pose: t, kp, conf, box, ball, size), `run/gait/<id>.json` `{id, kind, view, fps, scan_fps, metrics_version, direction, leg_px, contacts, steps, clip, layup?, dribble?, visible_share}`, `run/gait.json` (list of all). `scan_segments(folder, force=False, only=None) -> list[str]` returns ids scanned. Game-view segments get `{"id", "kind", "view": "game", "metrics": null}` only.

- [ ] **Step 1: Failing tests:** `test_scan_skips_done` (monkeypatch `train_scan.scan` to return a synthetic raw dict; second call with an existing `<id>.npz` scans nothing), `test_scan_fps_cap` (segment fps 240 -> scan called with fps 120), `test_game_segment_no_metrics`.
- [ ] **Step 2:** Run -> FAIL.
- [ ] **Step 3:** Implement; `layup_metrics` uses the segment's `release` time when given, else the highest-wrist peak (training.body_series `lift`) inside the window.
- [ ] **Step 4:** Tests pass; full suite passes.
- [ ] **Step 5:** Commit.

### Task 5: `move-sheets` (overlays, key-frame sheets, label strips, briefs) + review prompt

**Files:**
- Create: `src/hoop_tape_miner/move_sheets.py`, `prompts/movement_review_brief.md`; Test: `tests/test_movement.py` (add)
- Modify: `cli.py` (register `move-sheets`)

**Interfaces:**
- Consumes: `run/seg/<id>.npz`, `run/gait/<id>.json`, `reel.mp4`.
- Produces: `draw_overlay(frame, kp, conf, marks: dict) -> frame` (skeleton; trunk line and shin line with degree labels at touchdowns; "TD"/"TO"/"P" (penultimate)/"T-OFF" tags); `reel.overlay.mp4` (same timing as reel; segments without pose copied); `run/move_review/keys_<id>.jpg` (touchdown/take-off/landing frames with overlays and times); `run/move_review/strip_<id>.jpg` (every frame of the last 1.5 s before take-off for layups, or the 2 s of most steps for runs, numbered by source time, for hand labels); `run/move_review/brief_<group>.md` (groups of <= 8 segments; filled from `prompts/movement_review_brief.md` with segment list, sheet paths, gait numbers, KB slugs to check); `run/move_review/manifest.json`. Sets `video_overlay` in movement.json.
- Review output (written by agents): `run/move_review/review_<group>.json` = `{"segments": [{"id", "faults": [{"kb", "status": "seen"|"not_seen"|"not_visible", "t": [..], "confidence": "high"|"medium"|"low", "note"}], "good": [...], "identity_ok": bool}], "memo": "..."}` and `run/move_review/labels.json` = `{"<id>": {"contacts": [{"foot", "on"}], "takeoff": t|null}}`.

- [ ] **Step 1: Failing tests:** `test_draw_overlay_shape` (returns same shape/dtype, pixels changed where the skeleton is), `test_brief_groups` (17 segments -> 3 briefs; each lists its ids and sheet paths), `test_strip_frames_window` (picks frame times inside [takeoff-1.5, takeoff]).
- [ ] **Step 2:** Run -> FAIL.
- [ ] **Step 3:** Implement; write `prompts/movement_review_brief.md` (what to look at per kind, use KB slugs, `not_visible` when the angle or resolution cannot show it, identity check against `look`, never infer muscles from 2D).
- [ ] **Step 4:** Tests pass.
- [ ] **Step 5:** Commit.

### Task 6: `move-summary` (validation gate, summary, facts, figures, progress)

**Files:**
- Create: `src/hoop_tape_miner/move_summary.py`; Test: `tests/test_movement.py` (add)
- Modify: `movement.py` (`REFERENCE` dict from the KB "Reference values" table: `{metric: {"band": (lo, hi), "kinds": (...), "phase": "accel"|"maxv"|"layup", "kb": slug}}`), `cli.py`

**Interfaces:**
- Consumes: `run/gait.json`, `run/move_review/review_*.json`, `labels.json`, earlier movement sessions' `summary.json`.
- Produces: `summary.json` `{headline: {segments, reviewed, seen, hypotheses, validated}, validation: {<id>: compare_contacts + pass}, metrics: {<kind>/<view>/<metric>: {mean, sd, n, band, shown}}, faults: [{kb, status, segments, times}], progress: [...] , metrics_version}`; `facts.md` (every number the report may quote); figures `metrics.png`/`metrics.en.png` (strip plot per metric against the reference band, hidden metrics omitted), `faults.png`/`faults.en.png` (seen / not seen / not visible per KB slug).
- `progress(folder, metrics) -> list[dict]` uses only earlier sessions with equal kind, view and `metrics_version`.

- [ ] **Step 1: Failing tests:** `test_gate_hides_metric` (labels disagree -> metric `shown: false`, absent from facts.md), `test_progress_matches_only_same_kind` (earlier session with a different view/version is ignored), `test_faults_merge` (two review groups -> fault counts and times merged), `test_facts_unknown_not_zero` (None metric printed as "unknown").
- [ ] **Step 2:** Run -> FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Tests pass.
- [ ] **Step 5:** Commit.

### Task 7: `move` orchestrator, page band, film title, report prompt, docs

**Files:**
- Create: `src/hoop_tape_miner/move_run.py`, `prompts/movement_report.md`; Test: `tests/test_movement.py` (add)
- Modify: `cli.py` (`move`), `render_html.py` (movement band: name · 运动模式/Movement · date; stats from `summary.json` `headline`), `film.py` (title `'<name> · movement'`), `docs/playbook.md` ("Movement sessions" section with the filming protocol), `docs/pipeline.md`, `CHANGELOG.md` (Unreleased), `README.md` (one line), `.claude/commands/` only if a `/train` command file exists (add `/move` the same way)

**Interfaces:**
- `MOVE_STEPS`: `video`(agent: reel exists) -> `scan`(cmd move-scan, long) -> `sheets`(cmd move-sheets) -> `labels`(agent: labels.json + `labels_checked: true`) -> `review`(agent: one subagent per brief, <= 3 at once) -> `summary`(cmd) -> `report`(agent: README.md, README.en.md, plan.json from `prompts/movement_report.md`) -> `clips`(cmd, `--video` = `video_overlay`) -> `listen-script` -> `narrate` -> `html` -> `qa`(browser-check) -> `film-script` -> `film`(cmd, overlay video). `publish` only with `--publish`.
- `prompts/movement_report.md`: page order (verdict; teammate claims; model; what the footage shows with clip markers; what it cannot show; fixes with KB slugs and where they go in sessions A-D; pain check first; fuel by day type; recovery week; filming protocol and tests), wording rules (about / likely / hypothesis), plan.json shape (`focus`, `drills`, `tests`, `nutrition`, `recovery`).

- [ ] **Step 1: Failing tests:** `test_move_steps_order` (names in the order above), `test_movement_board` (render_html board text contains name, date and headline numbers for a tmp movement folder), `test_film_title_movement`.
- [ ] **Step 2:** Run -> FAIL.
- [ ] **Step 3:** Implement and write docs.
- [ ] **Step 4:** `uv run pytest -q` all pass; `uv run hoop-tape-miner move --help`.
- [ ] **Step 5:** Commit.

### Task 8: Baseline 2026-10-20 for the owner (run the flow; no repo commits of personal data)

**Files (gitignored / media):** `workspace/players/<player>/movement/2026-10-20/` (movement.json, review, summary, README zh/en, plan.json, listen/film scripts, index.html, film.zh.mp4, film.en.mp4), `<media root>/players/<player>/movement/2026-10-20/` (reel, run).

- [ ] **Step 1:** Write `specs.json`: training video `<media root>/players/<player>/training/2026-10-20/session.mp4` windows ~2 s before to 1.5 s after each clean finish (31:46, 32:39, 33:05, 33:45, 34:12, 35:10, plus contested 06:08, 06:37, 16:00, 17:31, 24:40, 25:27, 26:42, 37:33, 38:26), drive/first-step moments (07:11-07:14, 25:22-25:25, 36:22-36:25, 38:25-38:28), landing 25:30-25:32; game video `<media root>/teams/<opponent>/2026-10-14/video/15-10-2026.mp4` moments 07:27-07:31, 12:31-12:34, 35:12-35:17 (view game, crop around the player if it helps). Seeds from the training session's `pose.npz`/`session.json` follow settings; `look` from the training session.
- [ ] **Step 2:** `uv run hoop-tape-miner move-new --player <player> --date 2026-10-20 --spec specs.json`, then `move <folder>` until exit 3; logs to `<media root>/logs/move_2026-10-20.log`, read the tail.
- [ ] **Step 3 (labels):** hand-label contacts and take-off on >= 10 layup strips into `labels.json` (subagent, writes the file, replies in a few lines); set `labels_checked`.
- [ ] **Step 4 (review):** one subagent per brief (<= 3 at once).
- [ ] **Step 5:** `move` continues: summary. Then write README.md / README.en.md / plan.json with `prompts/movement_report.md` (deep: film evidence -> cause -> correct model -> drills -> check), listen and film scripts; `move` renders clips, narration, html, film.
- [ ] **Step 6 (QA):** browser-check subagent on the page (both languages, audio, clips) -> `qa.md` PASS; watch-check film duration and first frames with ffprobe.
- [ ] **Step 7:** Merge the running work into `workspace/players/<player>/program/2026-10-20/index.html` (backup `index.v1.html`): warm-up sprint drills in every session, acceleration/decel in B, plyo/calf/hamstring in A/D, pain check gate; update `focus.md`, `log.md`, `README.md` of the player KB; copy films and MP3s to the Desktop (`17号_运动模式_2026-10-20.*`); update the `player KB` memory.
