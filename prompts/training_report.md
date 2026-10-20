# Writing a training session report (README.md + README.en.md + plan.json)

For one player's solo workout, written to them in the second person. Goal: in two minutes they know how the
session went in numbers, which two or three things decided the makes and misses, and exactly what to do in the
next session, with targets the next session checks automatically. `README.md` is 中文 and `README.en.md` the
same content in English (the page switches between them).

## Inputs

- `facts.md` in the session folder: the only source of numbers. Every percentage counts make / miss only;
  `unclear` attempts are reported apart and never counted as makes.
- `memo_part<N>.md` in `<run>/train_review/` (what the reviewer saw), `summary.json` (same numbers as facts.md).
- Figures in the session folder: `zones.png`, `timeline.png`, `form.png`, `progress.png` (only some may exist; the
  English page uses the `.en.png` twins).
- session.json `plan` (what the player meant to train) and `targets` (from the previous plan; facts.md has the
  status of each).
- `prompts/skill_kb.md`: the individual skill and conditioning knowledge base. Cite entries by slug where the
  session shows their symptom; take the mechanism from **Why it happens**, the cue, drill and target from the
  entry (re-set the trial numbers from this session), and never use an entry whose symptom is not in the data.
- Trainer-led sessions (session.json `look` set, or a trainer in the memos): the trainer chose the drills, so say
  what each block trained, how it went and what to do better in it next time, rather than judging the choice.
- Optional: the latest game deep dive (`workspace/teams/<opponent>/<date>/player-<N>/README.md`) to tie the plan to
  game habits. Say which game when you use it.

Pose numbers are 2D from one phone: compare them only between sessions filmed from about the same spot, and call
them "about". Never write a number that is not in facts.md.

## Section skeleton

```
# Training <date>: <one-line verdict, e.g. "free throws held, left-hand layups fell off when tired">

**In one line: <the contrast that matters, in counts>.** <What you set out to train vs what you actually did.>

| | This session | Last session |
|---|---|---|
| Attempts (active minutes) | ... | ... |
| Shots | made/att (%) | ... |
| Finishes | made/att (%), left hand share | ... |
| Free throws | ... | ... |
| Dribbling | minutes, losses | ... |
| Targets met | k of n | |

---

## 1. Targets from last time
One line per target: wanted, got, met / missed / not trained, and why in one sentence. Skip the section when
there were no targets (first session).

## 2. Shooting
Zones figure, then 2-4 bullets: the best and worst spot, the miss pattern (short / long / left / right) and what it
usually means (short = legs or fatigue, left/right = alignment or elbow), first vs last third. One or two clip
markers on typical makes and misses.

## 3. Finishing
Per type and hand; left-hand share; what the misses had in common. Clip markers.

## 4. Form
Form figure; 2-3 bullets where makes and misses differ (e.g. "makes: knee bend about 35°, misses about 20°") or
where the spread is large (consistency). Use the reviewer's form notes with their times. Only claims the numbers
or the notes support.

## 5. Dribbling
Minutes, drills, hand balance, losses, one cue. Skip when there was none.

## 6. Progress
Progress figure and one or two sentences on the trend (only with 2+ sessions).

## 7. What to fix and how
The 2-4 things that cost the most (from the misses, form notes and memos), each: what you saw (count or clip),
why it happens (skill_kb slug), the cue, and the drill that fixes it.

## 8. Next session
The plan table (same content as plan.json): drill, why (a number or clip from this session), volume, target.
3-5 drills, at most 45 minutes in total unless the player trains longer. End with one call to say to yourself.

## 9. Between sessions: skill and conditioning
The work until the next session (same content as plan.json `between_sessions`), from skill_kb: a weekly table
(day, what, dose) with 1-2 solo skill blocks and 2 conditioning blocks (strength / power, landing and
change of direction, repeated sprints, warm-up), sized for an adult who also plays games; how to progress over
2-4 weeks and how the next session will show it worked. No hard day before a game (KB-recovery-weekly-load).
```

Clips: mark each with `![caption](clip:mm:ss.s-mm:ss.s)` (session video time), window from 1 s before the set
point to 2 s after the ball reaches the rim, so 3-5 s; 4-8 clips per report. Link to a clip elsewhere with
`[▶ mm:ss](#clip-<stem>)` as in prompts/coach_report.md.

## plan.json

```json
{
  "focus": ["one line per focus, same as the report's next-session section"],
  "drills": [
    {"name": "left-hand Mikan, then left layups from the wing", "category": "finish", "reps": "3 x 10 each side",
     "why": "left layups 3/9 (33%) vs right 8/10; misses short off the rim at 12:40, 13:05",
     "target": {"name": "left-hand layups 60%", "match": {"type": "layup-left"}, "attempts": 20, "pct": 0.6}}
  ]
}
```

- `target.match` filters the next session's reviewed attempts by any field the review writes (`category`, `zone`,
  `spot`, `type`, `hand`), so use the review vocabulary exactly (zones: ft, rim, paint, mid, three; types: ft,
  catch-shoot, off-dribble, step-back, layup-right, layup-left, reverse, floater, power, hook, dunk, tip).
- `attempts` is the volume the player must reach; `pct` (0-1) is optional. Set targets a little above this
  session's number (e.g. +5 to +10 points), not a dream number.
- Every drill's `why` points to a number or a time from this session (or the named game).
- Optional `"between_sessions"`: the homework of section 9, not checked from film:
  `[{"day": "Tue", "category": "skill | conditioning | mobility", "name": "...", "dose": "3 x 8 each leg",
  "kb": "deceleration-landing", "progress": "add a hop each week", "check": "how the player or the next film can tell"}]`.
- Each drill may carry `"kb": "<slug>"` from `prompts/skill_kb.md`.

## Narration and explained video

- `listen.<lang>.md` (prompts/narration.md): 2-3 minutes: the verdict, two things that went well, two that did not,
  the plan and the call.
- `film.<lang>.md` (prompts/film.md): title card, then per section a chapter card, the clips of typical makes and
  misses with freeze lines on the form point (`> x,y text` at the elbow, knee or release point), the zones and
  form figures as image scenes, and the plan as the last chapter. Use only `clip:` scenes and image scenes: the
  `court:` and player marks need game tracks and do not apply to a session.
