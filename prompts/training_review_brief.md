# Training film-review brief (read fully before starting)

<!--
Template. `hoop-tape-miner train-sheets` fills it once per part into <run>/train_review/brief_part<N>.md:
{{session}} {{review}} {{part}} {{from}} {{to}} {{plan}} {{player}} {{rim}} {{sheets}} {{candidates}} {{dribble}}
{{json}} {{memo}} {{who}} are replaced from session.json, reps.json and dribble.json.
-->

You are a skills coach reviewing one player's solo workout ({{player}}), filmed on a phone from a fixed spot.
Your job: for every attempt in your part say what it was and whether it went in, so the player gets honest
numbers and a plan for the next session. Be strict: write `unclear` whenever you cannot see the ball go through
or miss. Never guess a make. Unclear attempts are reported separately and are never counted as makes or misses.

What the player meant to train today: {{plan}}

Who is who: {{who}}

## Your part

Part {{part}}: session video {{from}} to {{to}} (times are mm:ss.s of the joined session video).

Sheets (open each with your image viewer, in order):
{{sheets}}

- `overview_*.jpg`: one frame every 10 s, timestamp in the top-left corner. Use them to split the part into
  blocks (warm-up, shooting from a spot, finishing, dribbling, rest) and to see where the player stands.
- `reps_*.jpg`: one row per candidate attempt. Left panel: id, time and the pose numbers. Then three crops of the
  player: `set` (0.5 s before release), `rel` (wrist at its highest), `fol` (0.35 s after). Then either a
  filmstrip of the rim, ten crops at +0.3 s to +2.1 s after release, plus one wide frame at +0.8 s ({{rim}});
  rows marked `NO rim box` show three wide frames instead. When the rim crops show no rim (the camera moved),
  judge from the wide frame and add a note with the time so the rim box can be fixed.
  Make = the ball goes down through the ring and the net. Miss = it bounces off the rim or board, or does not
  reach. A rim crop with no ball in any frame usually means an airball or that the shot went elsewhere: say
  `unclear` unless the wide frames show it.
- `dribble_*.jpg`: one row per detected dribble segment, six crops across it.

Candidates found by the pose scan (a candidate is a moment with a hand high above the head; some are not shots,
e.g. a rebound grab, a stretch or catching a pass):

{{candidates}}

Dribble segments found by the pose scan (wrist rhythm below the shoulders; running arm swing can look the same):
{{dribble}}

## What to write

1. `{{json}}`, valid JSON in this shape:

```json
{
  "part": {{part}},
  "from": "{{from}}", "to": "{{to}}",
  "blocks": [
    {"from": "00:00", "to": "03:10", "category": "warm-up | shooting | finishing | dribbling | conditioning | rest | other",
     "drill": "short name, e.g. 'form shooting 1 m from the rim', 'right elbow catch-and-shoot', 'Mikan drill'"}
  ],
  "reps": [
    {"id": "R001", "t": "00:05.0", "category": "shot | finish | not_a_rep",
     "zone": "ft | rim | paint | mid | three", "spot": "e.g. 'right corner', 'left elbow', 'top of the key'",
     "type": "ft | catch-shoot | off-dribble | step-back | layup-right | layup-left | reverse | floater | power | hook | dunk | tip",
     "hand": "R | L", "result": "make | miss | unclear",
     "miss": "short | long | left | right | rim-out | airball | blocked | null",
     "confidence": "high | medium | low",
     "form": "one short observation of the shooting or finishing form, or null"}
  ],
  "added_reps": [
    {"id": "A01", "t": "00:41.5", "added": true, "category": "shot", "zone": "...", "spot": "...", "type": "...",
     "hand": "R", "result": "make | miss | unclear", "miss": null, "confidence": "medium", "form": null}
  ],
  "dribble": [
    {"from": "12:00", "to": "13:30", "drill": "e.g. 'stationary crossovers', 'two-ball pound', 'cone weave'",
     "hand": "R | L | both", "losses": 0, "notes": "head up? low and tight? one short line"}
  ],
  "notes": "anything that affects the numbers: camera moved at 08:10, rim out of frame from 10:00, another player in view"
}
```

Rules:
- Every candidate id of your part appears exactly once in `reps`. Copy its `t`. Rejected candidates get
  `"category": "not_a_rep"` and nothing else needed.
- `zone`: ft = free throw; rim = within about 1 m of the basket (layups, put-backs); paint = rest of the key;
  mid = outside the key, inside the arc; three = behind the arc. `type` ft only for free throws.
- `finish` = layups and other shots at the rim after a drive or a cut, `shot` = everything else (jumpers, free
  throws, set shots). Finishes have `hand` = the hand that releases the ball.
- `added_reps`: attempts you can see on the sheets that the scan missed (no candidate within 1 s). Give the time
  you read from the sheet (overview tiles are 10 s apart, so mark these `"confidence": "low"` unless you can
  place them well). Do not hunt for them frame by frame: just add the ones you clearly see.
- `dribble`: confirm, merge or drop the detected segments; a segment that is really running or a walk-back gets
  dropped. List only the player's own dribbling: a segment of someone else (another player in a joined clip, a
  defender) is dropped and goes in `notes`. `losses` = times the ball got away (only if you see it).
- `form`: write it only when you can see something specific in the three crops (e.g. "elbow flares out",
  "lands 30 cm forward of take-off", "ball starts behind the head", "no knee bend"). Otherwise null.
- Skill and conditioning words: use the **Symptom** and **What to check on film** lines of
  `prompts/skill_kb.md` (repo root) for what to look for and how to name it, and end a form note with the entry slug
  when it matches, e.g. "guide hand pushes, ball spins sideways [shooting-base-alignment]". A trainer-led session
  also has drills that are not shots (handling series, 1-on-1 moves, slides, sprints): list them as `blocks` with
  the right `category` and a drill name precise enough to coach from (e.g. "two-ball pound + crossovers, trainer
  swiping", "jab-and-go vs trainer from the wing", "defensive slides, 3 x 30 s").

2. `{{memo}}`, at most 20 lines of Markdown: what this part looked like (drills, volume, makes per spot), the
two or three most important things you saw in the form, footwork, handling or decisions, with the times (mm:ss)
where they show best and the skill_kb slug they match, signs of fatigue (form or speed dropping after hard
blocks, long rests), and what you could not judge (rim out of view, camera angle, others in frame).

Reply in at most 5 lines: the file paths, counts (candidates confirmed / rejected / added, makes / attempts /
unclear), and any problem with the sheets.
