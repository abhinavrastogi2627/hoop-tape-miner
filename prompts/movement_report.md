# Writing a movement report (README.md + README.en.md + plan.json)

For one adult player's running form, force pattern, layup approach and stops, written to them in the second
person by a sprint and movement coach. Goal: after reading they know what the footage shows about how they move,
what it cannot show yet, why their pattern feels the way it does (the model), and exactly how to train, eat and
recover for the next 4-8 weeks, with re-tests that the next movement session checks. `README.md` is 中文 and
`README.en.md` the same content in English (the page switches between them).

Depth is the point: for every finding go film evidence (segment id + time + clip) -> cause (KB **Why it happens**)
-> the correct model -> the drill -> how they will know it changed. A checklist of faults is not a report.

## Inputs

- `facts.md` in the session folder: the only source of numbers, findings counts and the validation result. A metric
  that facts.md marks hidden (contact check failed, not side view) is never quoted; "unknown" stays "unknown".
- `<run>/move_review/memo_<g>.md` and `review_<g>.json` (what the reviewers saw, with times), `summary.json` (same
  content as facts.md, plus per-fault times and notes).
- Figures in the session folder: `faults.png`, `metrics.png` (only when metrics are shown), `progress.png` (2+
  sessions); the English page uses the `.en.png` twins.
- movement.json: `plan` (what the session is for), `look`, each segment's `kind`, `view` and `note`.
- `prompts/movement_kb.md`: the movement knowledge base. Cite entries by slug; take the mechanism from **Why it
  happens**, the cue, drill and dose from the entry. Its "Teammate claims", "Reference values", "Filming protocol",
  "Re-test battery" and "Pain and safety gate" sections feed the matching report sections.
- `prompts/fuel_recovery_kb.md`: fuel by day type, protein, carbs timing, game day, hydration, sleep, recovery
  ranked, soreness vs pain, load progression, the Chinese-food menus and the one-week recovery template.
- Optional context: the player KB (`workspace/players/<player>/README.md`, `focus.md`), the latest game deep dive,
  earlier observations the owner gave. Say where each comes from; never upgrade an earlier impression to "seen".

## Evidence rules

- **seen** = a reviewer saw it on this footage (facts.md "Film findings", "seen in"), with the segment and time.
- **hypothesis** = plausible from the KB or a non-side view but not measurable here (facts.md "hypothesis in",
  e.g. a running fault from a behind or game camera). Write "likely" or "to be checked on the side-view re-shoot".
- **not visible** = this footage cannot show it (e.g. forward trunk lean, shin angle, foot ahead of hips, step length,
  knee lift from behind). List these honestly in section 5 so the re-shoot covers them.
- Never write a number that is not in facts.md. Reference bands are directions from trained populations, not pass
  marks; say "sprinters are about X" rather than "you fail X".
- Segments whose reviewer set `identity_ok: false` (the crop followed someone else) count for nothing; facts.md
  already drops them. Do not rescue them from memory.

## Section skeleton

```
# Movement <date>: <one-line verdict, e.g. "a runner's engine in a basketball body: upright, short contacts not yet trained">

**In one line: <the pattern that matters most, with how many segments show it>.** <What the session was for; what
footage it uses (views, how many segments) and what that footage can and cannot judge.>

| | This session |
|---|---|
| Segments (side / behind / game) | ... |
| Findings seen / to test / good habits | ... |
| Metrics shown (contact check) | ... or "none: no side-view footage yet" |

---

## 1. The verdict
Three to five sentences: the movement pattern in plain words, the one change that would help most on court, and how
sure we are (seen vs hypothesis).

## 2. What your teammate said, checked
The KB "Teammate claims" table in the player's words: claim, verdict (supported / partly / not supported / unclear),
one-line reason, and what this footage adds (a segment that agrees, or "not filmed yet").

## 3. The model: how basketball running should work
Short and concrete: acceleration (steps 1-4: lean from the ankles, push back, foot lands under the hips), top
speed (taller, stiff short contacts, hips do the work), the layup approach (penultimate step, one-foot take-off),
the stop (lower, longer braking steps), and why a distance-running pattern differs (economy vs force). One figure or
clip each where possible. Cite slugs.

## 4. What the footage shows
One sub-section per finding that is seen or a strong habit (good habits too, they are worth keeping): what you saw
(segment ids, times, a clip marker), why it happens (KB), what the correct version looks like, and the cue.
Order by how much it costs on court. Then the hypotheses, each with what would confirm or rule it out. Measurements only from facts.md "Measurements
(side view)" rows that are shown.

## 5. What it cannot show yet
The not-visible list from the memos and facts.md, grouped (running mechanics from the side, contact times, layup
step lengths), and what the re-shoot (section 10) adds for each.

## 6. How to change it: the training plan
The plan table (same content as plan.json `drills`): 4-8 weeks in sessions A-D (e.g. A acceleration + braking,
B elastic and calf, C layup approach and landing, D strength), each drill with its KB slug, dose, cue, why (a
segment or KB reason) and progression. Sized for an adult who also plays 1-2 games a week; no hard day before a game.
Start with the pain check (section 7).

## 7. Pain check first
The KB "Pain and safety gate" in plain words: the next-morning 0-10 rule, what to do at > 3/10, red flags -> physio.

## 8. Fuel
By day type (rest, training, game day) from fuel_recovery_kb, with the Chinese-food menus (rough grams), pre-game
and post-game options, hydration and what supplements are and are not worth it. Use the player's body weight from
the player KB for the gram targets and say so.

## 9. Recovery
The one-week recovery template around the games and sessions, sleep, what helps most (ranked), soreness vs pain.

## 10. Re-shoot and re-tests
The KB filming protocol as a checklist the player can follow on their own, then the re-test battery with this
session's values (or "first test at the re-shoot") and the date of the next test.
```

Clips: the clip source is the skeleton overlay reel (movement.json `video_overlay`), so clip times are **reel**
times: segment `reel_from` + (source time - segment `from`) / `slowmo`. Mark each with
`![caption](clip:mm:ss.s-mm:ss.s)`, 2-5 s, 4-10 clips per report; a caption says the segment id and what to watch.
Link to a clip elsewhere with `[▶ mm:ss](#clip-<stem>)` as in prompts/coach_report.md.

## plan.json

```json
{
  "focus": ["one line per focus, same as the verdict and section 6"],
  "drills": [
    {"name": "wall drive, 3 x 3 marches then switches", "session": "A", "kb": "MV-accel-posture",
     "dose": "3 x 5 each side", "cue": "lean from the ankles, push the floor back",
     "why": "upright first steps in D2 at 36:22.0 (behind view, to confirm from the side)",
     "progress": "week 3: falling starts, week 5: 10 m sprints", "weeks": "1-8"}
  ],
  "tests": [
    {"name": "20 m sprint", "how": "2-point start, 240 fps side-on", "value": null, "unit": "s", "next": "2026-11-17"}
  ],
  "nutrition": {"rest": "...", "training": "...", "game": "...", "pre_game": "...", "post_game": "...",
                "hydration": "...", "kb": ["FR-energy-by-day", "FR-protein"]},
  "recovery": [{"day": "Mon", "what": "...", "kb": "FR-recovery-ranked"}]
}
```

- Every drill names its KB slug and its `session` (A-D); `why` points to a segment and time, or says "KB, not
  filmed yet".
- `tests[].value` is this session's value from facts.md or null (never a guess); the next movement session fills it.
- Doses come from the KB entries; raise one thing per week (KB load rules).

## Narration and explained video

- `listen.<lang>.md` (prompts/narration.md): 3-4 minutes: the verdict, what the teammate got right and wrong, the
  two or three changes that matter most with their cues, how to train, eat and recover this week, and the re-shoot.
- `film.<lang>.md` (prompts/film.md): title card; chapters verdict -> model -> what the footage shows -> fixes ->
  fuel and recovery -> re-shoot. Use `clip:` scenes on the overlay reel (reel times as above) with freeze lines on
  the point that matters (`> 01:12.4 0.45,0.70 "trunk tall at take-off"`), the faults and metrics figures as image
  scenes, and stat scenes for counts. No `court:` scenes or player marks: they need game tracks.
