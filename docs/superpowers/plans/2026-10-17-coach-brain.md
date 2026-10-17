# Coach Brain v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task ends with an **Eval gate**: measure, write the result to the eval log, and stop for the owner's go/no-go before the next task.

**Goal:** Make the film review produce correct facts, explanations of *why* things happened, and advice a team can practise, and prove each improvement with a measurement.

**Architecture:** Keep the current pipeline (CV → coach-sheets → review subagents → summary → facts → reports) and harden it in layers. Order: an evaluation harness first, then a validated trip schema, then a coaching knowledge base plus an "insights" agent step with a critic, then features computed from court-space tracks, and last, sharper visual input for facts. Each layer is A/B-measured on the reference game before the next one starts.

**Tech Stack:** Python 3.11, uv, pandas/numpy, pytest; agent steps are Claude Code subagents driven by `run.py`; prompts in `prompts/`.

**Spec:** this file (owner's request, 2026-10-17). The owner needs all three: facts right, explanations, actionable advice. Explanations and advice matter most, because the team acts on them. Owner-approved ideas: features from ball/court tracks (after measuring ball-track continuity), and a coaching knowledge base.

## Global Constraints

- Never commit `workspace/`, videos, frames, audio, rosters, names or official stats. Eval results with real numbers live in the game's `run/review_*/eval/` (outside git). Tests use small synthetic fixtures only.
- One module per CLI stage in `src/hoop_tape_miner/`, registered in `cli.py` `STAGES`; agent steps are registered in `run.py` `STEPS`.
- No new runtime dependencies (no jsonschema, no yaml): validators are plain Python.
- Never invent a game fact; unknown stays `null`/`"unclear"`.
- Update `docs/pipeline.md`, `docs/playbook.md` and `CHANGELOG.md` (*Unreleased*) when a stage or step changes.
- Model A/B with non-Anthropic vision models (Task 7) only after the owner consents to sending minors' frames to another vendor.

## Baseline facts measured 2026-10-17 (reference game, local)

- Detections at 10 fps. Ball detections: conf ≥ 0.3 in 43 % of sampled frames, conf ≥ 0.5 in 18 %; 27 % of frames with a ball have ≥ 2 ball boxes (false positives). Gaps at conf ≥ 0.3: median 0.2 s, p90 0.8 s.
- Person tracks: `tracks.pkl` columns `frame t kind x1 y1 x2 y2 conf cx cy colour track team cx_s cy_s number` (court metres, x 0–28, y 0–15).
- `official.json`: `score_flow` (team, points, our_video_t, running score; lags play 10–30 s; no scorer), per-player `PTS`/`PF`, made shots only.
- Review v1: 94 trips; `result` contains values outside the brief's list; confidence high 3 / medium 56 / low 35.

## Review Focus

1. A trip with no shot, no foul and `result: "unclear"` must pass validation and count as "unknown" in every metric, never as a miss.
2. Official score events with lagged times near a part boundary must match a trip in either part (matching runs over all trips, not per part).
3. An insight citing a video time that falls in no trip must fail validation (no orphan evidence).
4. Features for a trip where one team has < 3 tracked players must be `null`, not 0.
5. Migration of v1 trips with free-text `result` (e.g. "made2 + FT 1/1 (and-one)") must keep the information (shot made 2 + FT 1/1) or mark it unclear, never drop it silently.

---

### Task 1: Evaluation harness (`coach-eval`)

**Files:**
- Create: `src/hoop_tape_miner/coach_eval.py`, `tests/test_coach_eval.py`
- Modify: `src/hoop_tape_miner/cli.py` (register `coach-eval`)

**Interfaces:**
- Produces: `facts_eval(trips: list[dict], official: dict, lag: tuple[float, float] = (-40.0, 8.0)) -> dict` with keys `score_events`, `matched`, `recall`, `points_acc`, `team_pts` (`{"us": [review, official], "them": [...]}`), `player_pts_abs_err` (`{"us": int, "them": int}`), `player_pf_abs_err`, `fouls_found` / `fouls_official`, `unclear_share`, `invalid_result_share`.
- Produces: `insight_lint(text_or_insights) -> dict` with `n`, `with_evidence` (≥ 2 times), `with_why`, `with_drill`, `with_target`, `generic_phrases` (count of phrases from a fixed list in the module, e.g. "communicate better", "be more aggressive", "加强沟通", "提高专注").
- Produces: CLI `coach-eval --review DIR --official FILE [--insights FILE] --label NAME` → `DIR/eval/<label>.json` and one line appended to `DIR/eval/log.md`.

A score event matches a trip when the trip's scoring team equals the event's team and the trip's shot time (v2 `shot.t`, else v1 `t1`) lies in `[event.our_video_t + lag[0], event.our_video_t + lag[1]]`; each trip matches at most one event (greedy by time). Points from a trip = shot points + FT made.

Status 2026-10-17: done (uncommitted), 9 tests; baseline `v1-baseline` in the reference game's `review_v1/eval/log.md`. Note: sheet headers show the official events, so team-level points recall mostly measures reconciliation; per-player attribution, fouls and the insight lint are the informative numbers. Events with no video time are reported as `official_pts_off_video`.

- [x] Step 1: tests `test_facts_eval_matches_lagged_events` (event at 100 s, trip shot at 80 s → matched), `test_facts_eval_unclear_is_not_a_miss` (Review Focus 1), `test_facts_eval_boundary_events` (Review Focus 2), `test_insight_lint_counts_generic` — synthetic dicts.
- [x] Step 2: run `uv run pytest tests/test_coach_eval.py -q` → FAIL (module missing).
- [x] Step 3: implement; v1 `result` strings parsed with a small regex table (`made2`, `made3`, `FT n/m`, `and-one`).
- [x] Step 4: tests pass; full `uv run pytest -q` passes.
- [x] **Eval gate:** run on `review_v1` with label `v1-baseline`; also `insight_lint` over the "3 key conclusions" of each `memo_part*.md`. Report the numbers to the owner.
- [ ] Commit (when the owner asks).

### Task 2: Trip schema v2 with validation and migration

**Files:**
- Create: `src/hoop_tape_miner/coach_schema.py`, `tests/test_coach_schema.py`
- Modify: `prompts/film_review_brief.md` (v2 fields), `src/hoop_tape_miner/run.py` (`parts_done` requires valid parts), `src/hoop_tape_miner/coach_summary.py` (read v2), `src/hoop_tape_miner/cli.py` (`coach-check`)

**Interfaces:**
- Produces: `RESULTS = ("made2", "made3", "missed", "turnover", "foul_ft", "foul_side", "dead_ball", "end_period", "unclear")`.
- Produces: v2 trip = v1 fields with `result` from `RESULTS`, plus `shot: null | {t, shooter, made: bool|null, points: 2|3, zone, type, contested}`, `fts: null | {shooter, made, att}`, `foul: null | {t, by_team, by, on, type, cause, led_to}`, `evidence: {field: [video seconds]}` for `result`, `shot`, `foul`, `coach_note`.
- Produces: `validate_trip(trip: dict) -> list[str]`, `validate_part(path: Path) -> list[str]`, `migrate_v1(trip: dict) -> dict` (sets `schema: 2`, keeps the original text in `result_v1`).
- Produces: CLI `coach-check --review DIR [--migrate OUTDIR]` exits 1 with the error list when any part is invalid.

Status 2026-10-17: done (uncommitted); `coach_schema.py` + `coach-check`, `parts_done` requires valid parts, eval/summary read v2, brief on v2; full suite 136 tests pass. Eval gate: `v1-migrated` invalid share 0, facts metrics identical to `v1-baseline`; per-trip points, scorer totals and trip times identical.
Migration differs only by 3 extra fouls hoisted from a nested `defence` block that v1 eval ignored (information gained, not lost); event-level line added: shots/FT matched one-to-one per team.

- [x] Step 1: tests `test_validate_rejects_free_text_result`, `test_eval_reads_v2_fields` (`trip_points` and the matcher use `shot.points`/`shot.t`/`fts.made`, so a `foul_ft` trip with `fts.made 2` scores 2), `test_eval_event_level` (report events matched one-to-one, shot events and FT events separately, next to the points reconciliation), `test_validate_accepts_unclear_trip`, `test_migrate_and_one` (Review Focus 5: "made2 + FT 1/1 (and-one)" → `result made2`, `shot.points 2`, `fts {made 1, att 1}`), `test_parts_done_requires_valid` in `tests/test_run.py`.
- [x] Step 2: FAIL. Step 3: implement; update the brief's field list and its "Final reply" to include `coach-check` output. Step 4: PASS.
- [x] **Eval gate:** `coach-check --migrate review_v2m` on v1; `coach-eval` label `v1-migrated`: invalid share must be 0 and facts metrics must not drop vs baseline. Also check migration keeps information: every v1 trip's points and fouler survive (diff of per-trip points v1 vs v2m = 0).

### Task 3: Coaching knowledge base

**Files:**
- Create: `prompts/coach_kb.md`, `tests/test_coach_kb.py`
- Modify: `prompts/film_review_brief.md` (point `coach_note` at KB symptoms)

Built from professional coaching material, not from the model's own knowledge (owner, 2026-10-17):
- Source library outside git: the `coach_library` folder of the team profile (outside git) (`CATALOG.md` = free official manuals downloaded with extracted text; `SOURCES.md` = recommended books and online knowledge bases with terms). Only legal sources; no shadow libraries. Books the owner buys are added there as text.
- `prompts/coach_kb.md` (in git) holds our own paraphrased entries; each `**Source:**` cites document + page/section, quotes at most one short sentence. The full texts never enter the repo.
- The insights writer (Task 4) may `grep` the local library for a supporting passage and cite it; the KB entry is the default.

About 12 entries, one per recurring amateur problem: transition defence, ball pressure / press break, half-court spacing, off-ball movement (cuts), drive help and recovery, closeouts, defensive rebounding / box-out, offensive rebounding balance, foul discipline (reach-ins, chasing from behind), shot selection, pick-and-roll basics, late-clock / end-of-period.

Each entry is a `### KB-<slug>` section with exactly these bold labels: `**Symptom (observable):**` (what the event log or features show), `**Why it happens:**` (2–4 mechanisms), `**What to check on film:**`, `**In-game rule:**`, `**Drill:**` (name, setup, reps, success measure), `**Next-game target:**` (a number the eval can measure), `**Source:**`.

Status 2026-10-17: KB written (uncommitted), 12 entries, test passes; spot-check passages for 3 entries in the local eval notes (`task3_kb.md`, outside git); brief pointer to KB symptoms still open.

- [x] Step 1: test `test_kb_entries_complete` parses `prompts/coach_kb.md` and asserts every entry has all seven labels non-empty and a unique slug. Step 2: FAIL. Step 3: write the KB. Step 4: PASS.
- [ ] **Eval gate:** owner skims 3 entries for basketball sense (5 minutes).

### Task 4: Insights step with critic

**Files:**
- Create: `prompts/coach_insights.md` (insight writer), `prompts/coach_critic.md` (critic), `src/hoop_tape_miner/coach_insights.py`, `tests/test_coach_insights.py`
- Modify: `src/hoop_tape_miner/run.py` (agent step `insights` after `summary`, before `facts`), `prompts/coach_report.md` (the "what to practise" and conclusions sections come from `insights.json`), `src/hoop_tape_miner/cli.py` (`coach-insights check`), docs.

**Interfaces:**
- Consumes: validated v2 trips (Task 2), `summary.json`, `official.json`, `prompts/coach_kb.md`; later also `features.json` (Task 5).
- Produces: `insights.json` = list of `{id, kb: [slug], claim, why, evidence: [{t, pid, trip, what}], counter_examples: [{t, pid, trip, what}], numbers: {name: value}, rule, drill, target_next_game, confidence, critic: {verdict: keep|revise|drop, note}}`, 3–6 team insights + 1–3 per focus player.
- Produces: `validate_insights(insights: list[dict], trips: list[dict], kb_slugs: set[str], summary: dict) -> list[str]`: ≥ 2 evidence times, each inside some trip's `[t0, t1]` (Review Focus 3); every `kb` slug exists; every number in `numbers` equals the value of the same name in `summary.json` when present; critic verdict present; no `drop` insights in the final file.

Flow: writer subagent (reads trips, summary, KB; may zoom sheets for evidence) → critic subagent (re-checks each claim against the cited sheets and official totals; never changes a fact to fit a total, marks it instead) → `coach-insights check`.

Status 2026-10-17: code and prompts done (uncommitted): `coach_insights.py` (`validate_insights`, `kb_slugs`, CLI `coach-insights check|ab`), run step `insights` (done = `insights.json` passes the check), `prompts/coach_insights.md`, `prompts/coach_critic.md`, report guide reads `insights.json`, optional profile key `coach_library`. Number names are dotted paths into `summary.json` (`all.us.turnovers`) or `features.<pid>-<trip>.<field>`; unresolvable names are not checked. Eval gate not run yet.

- [x] Step 1: tests `test_insight_needs_two_evidence_times`, `test_insight_orphan_time_fails`, `test_unknown_kb_slug_fails`, `test_number_mismatch_fails`, `test_insights_step_order` (in `tests/test_run.py`: `insights` after `summary`, before `facts`). Step 2: FAIL. Step 3: implement. Step 4: PASS. Also `test_dropped_insight_fails`, `test_ab_sheet_is_blind`.
- [ ] **Eval gate (main one):** `insight_lint` is a diagnostic, never the gate. The blind sheet uses the same inputs and similar length for A and B, scores truth, explanation and actionability separately, and any fact error the owner or critic finds blocks a pass even if B is preferred. Hold out one part that the prompts were not tuned on. run writer + critic on the reference game. Build a blind A/B sheet in `review_*/eval/ab_insights.md`: the current memos' conclusions vs the new insights, shuffled, labelled A/B. Owner rates each 1–5 on "explains why", "I can act on it", "is it true". `insight_lint` both. Go only if the owner prefers the new set.

Result 2026-10-17 (owner rating pending): writer + critic on `review_v3`: 6 insights (4 team, 2 focus player), critic revised all 6, dropped 0 (biggest fix: T3's "crowded paint" mechanism contradicted by tracked spacing 4.0 m vs 3.7 m; rewritten as the decision after the paint touch, "likely"). `coach-insights check` PASS. Lint (diagnostic): memos n 18, evidence 0, why 2, drill 0, target 10 -> insights n 6, all 6 with evidence, why, drill and target, generic phrases 0. Blind sheet: `review_v3/eval/ab_insights.md` (key in `ab_insights.key.json`).

### Task 5: Track features (spacing, numbers back, ball quality)

**Files:**
- Create: `src/hoop_tape_miner/coach_features.py`, `tests/test_coach_features.py`
- Modify: `src/hoop_tape_miner/run.py` (cmd step `features` after `film-review`), `prompts/coach_insights.md` (use features), `cli.py`, docs.

**Interfaces:**
- Consumes: `tracks.pkl`, `detections.pkl`, v2 trips; reuses `metrics.hull_area`, `metrics.mean_nn`, `metrics.zone_of`.
- Produces: `trip_features(tracks: pd.DataFrame, trip: dict, attack_side: str) -> dict` with `numbers_back_2s` (defenders on their own half 2 s after `t0`), `off_spacing_m` (mean nearest-neighbour distance of offence), `off_hull_m2`, `paint_crowd` (mean offence players in the paint), `standstill_share` (offence player-seconds under 0.5 m/s), `cross_half_s`; any value `None` when a team has < 3 tracked players in the window (Review Focus 4).
- Produces: `ball_quality(dets: pd.DataFrame, conf: float) -> dict` (`coverage`, `multi_share`, `gap_p50`, `gap_p90`) and `clean_ball(dets) -> pd.DataFrame` (one ball per frame, chosen by motion consistency; gaps ≤ 0.5 s interpolated).
- Produces: CLI `coach-features --run DIR --review DIR` → `features.json` (per trip) + `ball_quality.json`.

- [ ] Step 1: tests on synthetic tracks: `test_numbers_back_counts_own_half`, `test_spacing_null_when_few_players`, `test_clean_ball_picks_consistent_candidate`. Step 2: FAIL. Step 3: implement. Step 4: PASS.
- [x] **Eval gate:** agreement of `numbers_back_2s` with reviewer `transition_defence.back` on medium/high-confidence trips; ball: owner or critic spot-checks 50 random `clean_ball` frames for precision. Also spot-check 10 continuous 5 s stretches for identity switches and gaps; coverage alone does not prove continuity. Ball-based features (paint touches, ball reversals) are added only if precision ≥ 0.8; otherwise the gate records "ball not usable yet". Re-run Task 4 insights with features and repeat the A/B.

Result 2026-10-17: `numbers_back_2s` vs reviewer back count on 31 medium/high trips: exact 0.32, within one 0.71, Spearman 0.53 (supporting number only). Ball: ~0.3 precision on 108 cleaned frames (bags, bins, spare balls by the bench), 1-11 identity switches per 5 s stretch: ball not usable yet, no ball features. Registered as stage `coach-features`, run step `features` after `film-review`.

### Task 6: Event-focused visual input for facts

**Files:**
- Modify: `src/hoop_tape_miner/coach_review.py` (new `event-sheets` subcommand), `prompts/film_review_brief.md`, tests in `tests/test_coach_review.py`

**Interfaces:**
- Produces: `event_windows(official: dict, trips: list[dict], pre: float = 35.0, post: float = 6.0) -> list[dict]` — windows around each official score event and each reviewed foul.
- Produces: `coach-sheets event --run --video --review --fps 4` → sheets at 4 fps around each window with the candidate shooter/fouler boxed thicker (from tracks), plus a narrow question file per event (who shot, made, points, foul by/on/type).

- [x] Step 1: tests `test_event_windows_cover_lag`, `test_event_windows_merge_overlaps`. Step 2–4 as usual.
- [x] **Eval gate:** a fact-check subagent answers the narrow questions; merge into v2 trips; `coach-eval` label `v2-events`: recall, `player_pts_abs_err`, `player_pf_abs_err` vs `v1-migrated`.

Result 2026-10-17: 3 fact-check subagents, 19 windows, 54 events. At 4 fps from this camera most jerseys are unreadable (about 15 of 37 score events got a jersey). Merged with `coach-sheets event-merge --official` (box-score guard rejected 1 answer that would give a player more points than the box score): `v2-events` vs `v1-migrated`: player PTS error us 11 -> 13, them 19 -> 15 (sum 30 -> 28); PF error us 13 -> 13, them 11 -> 10; them shot events matched 11/14 -> 13/14. Small gain; the two 'ruled out' attributions raise the us error because the metric rewards a guess over unattributed. Next idea: assign unclear shooters under the box-score constraint.

### Task 7 (gated on owner consent): vision model A/B

Same event sheets/clips from Task 6, fixed inputs, answered by Claude vs GPT (Codex CLI) vs Gemini native video; scored with `coach-eval`. Not started without explicit consent about sending frames of minors to another vendor.
