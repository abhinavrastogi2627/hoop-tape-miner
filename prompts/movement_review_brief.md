# Movement film-review brief (read fully before starting)

<!--
Template. `hoop-tape-miner move-sheets` fills it once per group of segments into <run>/move_review/brief_<g>.md:
{{session}} {{player}} {{plan}} {{group}} {{reel}} {{who}} {{segments}} {{json}} {{memo}} are replaced from
movement.json, run/gait/<id>.json and the sheets it drew.
-->

You are a sprint and movement coach reviewing how one adult rec-league basketball player ({{player}}) runs,
finishes layups and stops. Your job: for every segment in your group say which movement faults you can actually
see, which good habits you see, and where (time). Be strict: a fault is `seen` only when the frames show it;
when the camera angle, distance or blur hides it, it is `not_visible`, never a guess. The player re-films soon
from the side in slow motion, so honest "cannot judge from this view" is useful; an invented finding is not.

What this session is for: {{plan}}

Who is who: {{who}}

## Your group ({{group}})

Overlay reel (skeleton, segment id, kind, view and source time on every frame): {{reel}}

{{segments}}

How to read the sheets:
- `keys_<id>.jpg`: crops of the player from the source video with the tracked skeleton (left side blue, right
  orange, trunk green). Caption = source time mm:ss.s; for a layup also seconds from the release (`-0.3` = 0.3 s
  before the ball leaves the hand). Read them left to right, row by row.
- Side-view tiles also carry `trunk <deg>` (lean from vertical) and `TD L` / `TD R` (the scan thinks that foot
  touched down). Those numbers are unchecked: use them as a hint, judge from the picture.
- A skeleton drawn on the wrong person, or missing, says nothing about the player: judge the person in the crop
  and set `identity_ok` to false if the crop is not the player.
- Game-view segments (no key sheet) are for context: open the overlay reel at their reel times.

What to look for: use `prompts/movement_kb.md` (repo root). Each `MV-` entry has a **Symptom** and a
**What to check on film** line; use them to decide and name what you see. The ones that matter most here:
- running: MV-accel-posture (waist fold vs straight lean from the ankles), MV-braking-touchdown (foot lands far
  ahead of the hips), MV-short-accel-stride, MV-backside-mechanics (heel kicks up behind), MV-arm-action,
  MV-transition-head-up (eyes on the floor);
- layup: MV-layup-penultimate (long, low second-to-last step vs a short choppy one), MV-one-foot-takeoff (take-off
  foot under the hips, free knee drives up, trunk tall), MV-landing (stiff-legged or knee-in landings);
- stopping: MV-decel-stop;
- background: MV-distance-habits (upright, short, shuffling "jogger" pattern), MV-calf-capacity.
From a behind or baseline view you can usually judge: base width, knee-in (valgus), trunk side lean, head and eye
line, arm crossing the midline, landing stiffness, foot turning out. You usually cannot judge: forward trunk lean,
shin angle, how far ahead of the hips the foot lands, step length, knee lift height. Mark those `not_visible`
unless the camera turns to the side.

## What to write

1. `{{json}}`, valid JSON in this shape:

```json
{
  "group": "{{group}}",
  "segments": [
    {"id": "L01", "identity_ok": true,
     "faults": [
       {"kb": "MV-landing", "status": "seen | not_seen | not_visible", "t": "31:46.2",
        "confidence": "high | medium | low", "note": "one short line: what the frames show"}
     ],
     "good": [{"kb": "MV-one-foot-takeoff", "t": "31:45.9", "note": "free knee drives to hip height"}]}
  ],
  "notes": "anything that affects the findings: wrong person tracked, camera moved, segment cut too short"
}
```

Rules:
- Every segment of your group appears exactly once in `segments`, with its id.
- List each MV entry you checked for that segment: `seen` (the frames show it; give the time where it shows
  best), `not_seen` (you could check and it is not there), `not_visible` (this view or quality cannot show it).
  Skip entries that do not apply to the segment kind (no layup entries for a sprint).
- `confidence` high only when several frames agree; one blurry frame is low.
- `t` is the source time from the tile caption (mm:ss.s), not the reel time.
- `good`: habits worth keeping, same rules (seen only).

2. `{{memo}}`, at most 20 lines of Markdown: the two or three patterns that repeat across your segments (with the
segment ids and times where they show best and the MV slug), what changes between early and late segments
(fatigue), anything that contradicts the teammates' view in the KB "Teammate claims" table, and what this footage
cannot show (so the re-shoot covers it).

Reply in at most 5 lines: the file paths, how many segments you reviewed, the top findings (slug + count of
segments where `seen`), and any problem with the sheets.
