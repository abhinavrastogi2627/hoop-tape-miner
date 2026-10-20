# Individual skill and conditioning knowledge base

Purpose: a fixed set of entries that turn what a personal training review measured into an explanation (why it happened), a cue, a drill and a next-session target. Each entry covers one recurring problem of an adult amateur player, either a skill (shooting, finishing, handling, one-on-one, defence) or conditioning (energy systems, sprints, landing, strength, warm-up, fatigue, recovery).

Audience: one adult player (about 30, rec league), training 1-2 times a week with a private skills trainer plus solo work, filmed on a phone. Drills are sized for one player, a rebounder or trainer at most, one basket and simple gear (cones, a chair, a pad, a towel, a line on the floor).

How agents use it:
- The training reviewers (`prompts/training_review_brief.md`) point a rep's `form` note or a block's notes at the matching entry's **Symptom** when the film shows it, and look for the items in **What to check on film**.
- The report writer (`prompts/training_report.md`) cites entries by slug (`kb: ["arc-short-long"]`), takes the mechanism from **Why it happens**, and copies the cue, drill and target into the page and `plan.json` only when the session data shows the symptom. If a symptom is not in the data, do not use the entry.
- Field names refer to the review JSON (`category` shot | finish, `zone` ft | rim | paint | mid | three, `spot`, `type` ft | catch-shoot | off-dribble | step-back | layup-right | layup-left | reverse | floater | power | hook | dunk | tip, `hand` R | L, `result`, `miss` short | long | left | right | rim-out | airball | blocked, `form`, `blocks[].category`, dribble segments with `losses` and `notes`), to `summary.json` (`totals`, `reps_per_active_min`, `zones`, `types`, `finish_hands`, `left_finish_share`, `misses`, `streak`, `thirds`, `form`, `form_finish`, `blocks`, `dribble`, `targets`, `progress`) and to the pose fields of `training.py` (`lift`, `knee_bend`, `dip_to_release`, `elbow_set`, `elbow_release`, `jump`, `travel`, `two_hands`; `form` gives per key `mean`, `sd`, `make_mean`, `miss_mean`).
- Pose numbers are 2D from one phone: compare them only between sessions filmed from the same spot, and write them as "about". A pose value may be missing; missing is "unknown", never zero.
- **Next-session target** is written as a `plan.json` target: `{"name": ..., "match": {...}, "attempts": N, "pct": P}`, where `match` uses any of `type`, `zone`, `hand`, `category`, `spot`. Set `pct` 5-10 points above the player's current number for that match (our rule), not the example value.
- Trial values: every number in a **Next-session target** and in a drill's **Success measure** is our own trial value, not taken from the sources (the manuals give no numeric targets for an adult amateur). Re-set it after each session from what the player actually managed (aim for a clear step, not perfection). Numbers that do come from a source (rest ratios, set and rep ranges, study results) are cited in **Source**.
- "(our rule)" marks a cue, threshold, drill variant or load choice that we chose ourselves; the cited pages support the principle, not that detail. Present these to the player as our choice, not as "the book says".
- Conditioning symptoms are proxies read from shooting film (late-session drops, rep rate, form spread), not fitness tests. Say "likely" and never diagnose an injury; pain, swelling or giving-way goes to a physio, not to a drill.

Sources: entries are paraphrased in our own words from professional coaching material and studies, with at most one short quoted sentence per entry. Page numbers are PDF pages of the local library copy (`<coach_library>/<slug>/`, the `coach_library` folder of the team profile; page N = text after the (N-1)th form feed); the printed page number in the manuals is usually 2 lower. Library slugs: `fiba-wabc-level1/2` (FIBA WABC Coaches Manual levels 1-2), `specialolympics-basketball-coaching-guide-2024` (Special Olympics basketball coaching guide). Web sources (studies, position stands, coaching pages) are cited by URL or DOI. The full texts are not in this repo and must not be copied into it.

---

## Skills

### KB-shooting-base-alignment

**Symptom (observable):** Misses lean sideways: `misses.left + misses.right` is more than about a third of missed shots, or one side dominates; `form` notes say "elbow out", "guide hand pushes", "ball spins sideways", "body turns"; pose `elbow_release` has a high `sd` relative to other sessions from the same camera spot.

**Why it happens:**
- The elbow is not under the ball, so the push goes off the line to the rim.
- The guide hand pushes or twists at release, which adds side spin and pulls the ball off line.
- The arms do the work instead of the legs, so the upper body twists to find power.
- Feet and hips are not set toward the basket, so the shooting line and the body line differ.

**What to check on film:** On side misses, where is the shooting elbow at the set point (under the ball or flared)? Does the guide-hand palm face the side in the follow-through, or has it turned toward the rim? Do the feet point at the rim on the catch? Does the ball spin straight back or sideways? Is the miss side the same every time (mechanical) or random (balance or fatigue)?

**Cue:** "Elbow under, guide hand quiet, hold the finish." / 中文："肘在球下，辅助手不动，保持出手姿势。"

**Drill:** Wall and one-hand form shooting (fiba-wabc-level2 pp. 149-150). Setup: stand about 1 m in front of a wall (or the rim at 1-2 m), shooting hand only, guide hand off; then add the guide hand on the side; follow-through held until the ball lands. Reps: 3 spots x 10 one-hand, then 3 x 10 two-hand, before every shooting block. Success measure: ball spins straight back on at least 8 of 10 (counted by eye or on film); in the live shooting block after it, side misses (`left` + `right`) at most 1 in 5 misses.

**Next-session target:** `{"name": "Mid-range straight line", "match": {"zone": "mid"}, "attempts": 40, "pct": 0.45}` and, in the report, side misses down to at most 25 % of misses (our rule).

**Source:** fiba-wabc-level1 pp. 204-205 (grip: shooting hand behind or under the ball, other hand on the side, elbow under the ball; guide hand does not push); fiba-wabc-level2 p. 149 (off-line shot: pushing with the arms instead of the legs, body twist, guide hand pulling away, elbow not under the ball; hold the follow-through, stand in front of a wall), p. 150 (side spin from the guide hand twisting, check the palm in the follow-through, elbow-to-elbow backspin drill). Quote: the guide hand "should not push the shot at all" (fiba-wabc-level1 p. 205).

### KB-arc-short-long

**Symptom (observable):** Short misses dominate: `misses.short` is the largest miss type, often with `airball` on threes; or `long` misses on flat shots. Pose: on misses `knee_bend` `miss_mean` is clearly lower than `make_mean`, or `lift` is lower on misses (low release); `form` notes "flat shot", "fades back", "lands on one foot".

**Why it happens:**
- Too little leg power: the knees barely bend or the legs and arms are out of sync, so the arms push and the shot comes up short.
- Fading back: watching the flight of the ball pulls the head and body back, landing behind the take-off spot.
- A low release point (elbow below the eyes) or a narrow stance gives a flat arc, which shrinks the target and gives long or rim-out misses.
- Distance creep: the same shot taken a step further out without more legs.

**What to check on film:** Does the player land on or in front of the take-off spot, on both feet? Where are the eyes at release (rim or ball)? Is the elbow above the eyes at release? Do short misses cluster in one zone (`three`) or late in the session (`thirds`, see KB-fatigue-shooting)?

**Cue:** "Legs up, finish high, land forward." / 中文："腿发力，高点出手，落地往前。"

**Drill:** Line landing and close-to-far ladder (fiba-wabc-level2 pp. 148, 151). Setup: towel or line on the floor at the take-off spot; start inside the key with the ball at the chin, finish on the toes; step back one distance only after 4 of 5 swishes or makes (our rule). Reps: 5 distances x 5 shots, twice. Success measure: lands on or in front of the line on at least 8 of 10 shots; short misses no more than half of misses at the last distance.

**Next-session target:** `{"name": "Threes without short misses", "match": {"zone": "three"}, "attempts": 50, "pct": 0.35}`; report `misses.short` share of misses, aim below 50 % (our rule).

**Source:** fiba-wabc-level1 p. 200 (balance, high arc, high release, backspin, power from the legs), p. 205 (high arc gives more chance, elbow above the eyes, look under the ball); fiba-wabc-level2 p. 148 (flat shot from a low release or narrow stance; fixes: look under the ball, swish only, wall target, wider stance), p. 151 (shooting short: too little leg power, fading back; shoot from inside the key from the chin, finish on the toes, land with both feet on or in front of a line or towel); Noah Basketball, https://www.noahbasketball.com/blog/the-art-and-science-of-45/11 (about 45° entry angle as the target arc; depth and left/right as the other factors; their claim). Quote: "Young players miss short five times more often than they miss long." (Noah Basketball).

### KB-release-follow-through

**Symptom (observable):** The same shot looks different from rep to rep: high `sd` on `lift`, `elbow_release` or `dip_to_release` within one session (compare with the player's own earlier sessions from the same spot); `form` notes "pause at forehead", "no follow-through", "arm drops early", "ball dips". Makes and misses differ in `dip_to_release` (`make_mean` vs `miss_mean`).

**Why it happens:**
- A pause at the forehead splits the shot into two motions, slows the release and loses the leg power.
- Lowering the ball while bending the knees lengthens the stroke and changes it from shot to shot.
- No held follow-through: the arm pulls back early, so wrist flick and backspin vary.
- Rushing after a miss or under fatigue changes the rhythm (see KB-fatigue-shooting).

**What to check on film:** Is there a stop between set point and release? Does the ball drop below the chest after the catch? Is the wrist relaxed and the arm held up until the ball lands ("hand in the basket")? Are misses the reps with the longest `dip_to_release`?

**Cue:** "One motion, up and out, hold it." / 中文："一个连贯动作，向上出手，保持住。"

**Drill:** Rhythm form shooting (fiba-wabc-level1 p. 206; specialolympics-basketball-coaching-guide-2024 p. 48). Setup: side-on at the no-charge circle, 90° pivot to face, step, push up and finish on the toes; ball stays at chest height while the knees bend. Reps: 3 x 10 close shots, then 3 x 10 at the free-throw line, holding the follow-through until the ball lands. Success measure: no visible pause on 9 of 10 (trainer or film); within one session `dip_to_release` `sd` lower than the previous session filmed from the same spot (our rule).

**Next-session target:** `{"name": "Catch-and-shoot rhythm", "match": {"type": "catch-shoot"}, "attempts": 60, "pct": 0.45}`; report pose `sd` for `lift` and `dip_to_release` against last session (about, same camera spot only).

**Source:** fiba-wabc-level1 p. 205 (relaxed wrist flick with backspin), p. 206 (fluid shot, no pause at the forehead, a pause slows the release and loses leg power; side-on pivot and step drill); fiba-wabc-level2 p. 146 ("High 5" follow-through with fingers up); specialolympics-basketball-coaching-guide-2024 p. 48 (lowering the ball while flexing the knees lengthens the stroke: keep it high and move only the legs; follow through). Quote: none.

### KB-catch-and-shoot-footwork

**Symptom (observable):** `type: catch-shoot` makes clearly below stationary `ft` and below close shots; `form` notes "catches flat-footed", "hands down before the pass", "extra dip", "steps after catch"; pose `dip_to_release` long on catch-and-shoot reps; `travel` after the catch (drifting) on misses.

**Why it happens:**
- Hands and knees not ready before the ball arrives, so the player catches, then loads, then shoots: slow and out of rhythm.
- Catching standing still forces a dip to find power; catching on the move (hop or 1-2) gives it for free.
- Inconsistent footwork: sometimes hop, sometimes 1-2, sometimes a shuffle, so the base changes every shot.
- Feet not turned to the rim on the catch, so the body twists in the air.

**What to check on film:** Are the knees bent and hands up (shooting hand behind the ball) before the catch? Is the ball caught with the feet in the air? Hop (both feet land together) or 1-2 (inside foot first)? Is the second foot down when the shot starts? Does the player land where he took off?

**Cue:** "Ready before the ball: hands up, knees bent, catch in the air." / 中文："球到之前就准备：手举起，膝弯曲，空中接球。"

**Drill:** Spin-out catch and shoot (fiba-wabc-level2 p. 144). Setup: spin the ball out to yourself (or the trainer passes at hip height), catch in the air, inside foot lands first and turns the body to the rim (1-2), then the same with a hop; one footwork per set (our rule). Reps: 5 spots x 6 shots per footwork. Success measure: hands ready before the catch on 9 of 10 (film); makes at least equal to stationary shots from the same spots.

**Next-session target:** `{"name": "Catch-and-shoot from the wings", "match": {"type": "catch-shoot", "zone": "mid"}, "attempts": 50, "pct": 0.45}`.

**Source:** fiba-wabc-level1 pp. 223-224 (be on the move as you receive, catch with the feet in the air with a small hop or step, hands ready with the shooting hand behind the ball, no hesitation unless faking), p. 208 (prepare before the catch: low and ready); fiba-wabc-level2 p. 119 (catching stationary forces a "dip" that slows the shot; no exaggerated knee bend; with a stride stop shoot as the second foot hits; pass at hip height), p. 144 (jump stop vs stride stop; catch in the air for pivot choice, leg power and a quicker release; spin-out stride drill); specialolympics-basketball-coaching-guide-2024 p. 48 (slow after the catch: knees bent and hands ready before the pass). Quote: none.

### KB-pull-up-off-dribble

**Symptom (observable):** `type: off-dribble` (or `step-back`) makes far below `catch-shoot` from the same zone; `form` notes "drifts sideways", "picks up late", "long last step", "lands forward/back"; pose `travel` large and `jump` low on misses; side misses (`left`/`right`) rise on off-dribble reps.

**Why it happens:**
- The last dribble is too far from the body or the pick-up is slow, so the player has to reach and lose balance.
- Long final steps carry momentum into the shot, which fades or drifts sideways.
- The pick-up hand and pivot foot do not match, so the body turns late.
- Rising before the ball is in the shooting pocket gives a low, flat release.

**What to check on film:** Is the last dribble hard and in front of the shooting hip? Inside foot as the pivot on a stride stop? Is the ball picked up with the feet in the air? Does he land on the take-off spot? Is the release at or just before the top of the jump?

**Cue:** "Hard last dribble, short steps, straight up." / 中文："最后一下运球用力，步子小，垂直起跳。"

**Drill:** Last-dribble pull-up (fiba-wabc-level1 p. 207). Setup: start at the elbow, one hard dribble then pull-up, rhythm "1-2-3"; then 2-3 dribbles from the wing; then the trainer steps up as a help defender to force the pull-up. Reps: 4 spots x 2 directions x 5 shots. Success measure: lands within about one foot length of take-off on 8 of 10 (line on the floor, our rule); off-dribble makes within 10 points of catch-and-shoot from the same spot.

**Next-session target:** `{"name": "Pull-ups going right and left", "match": {"type": "off-dribble"}, "attempts": 40, "pct": 0.40}`.

**Source:** fiba-wabc-level1 p. 207 (stride stop with the inside foot as pivot, catch with the feet in the air, short steps, fluid pick-up; practise the last dribble with rhythm 1-2-3, then 2-3 dribbles, coach steps up as help), p. 208 (jump shot: land in the same spot using a line; release at or just before the top of the jump, on the way down the leg power is gone); fiba-wabc-level2 p. 145 (one-dribble pull-up toward the side opposite the pivot foot). Quote: none.

### KB-free-throw-routine

**Symptom (observable):** `zone: ft` pct below the player's catch-and-shoot pct from the same distance, or a big spread between sessions; `form` notes "rushes", "different number of bounces", "feet move", "not set"; first FT of each pair worse than the second (`streak` or per-rep order).

**Why it happens:**
- No fixed routine, so each attempt starts from a different state.
- Feet placed differently each time (not on the same floorboard or nail), so the line changes.
- FTs practised only when fresh and in long blocks, never tired and one or two at a time as in a game.

**What to check on film:** Same sequence every time (look, bounce count, breath, set)? Same foot spot relative to the line and the centre nail? Release and follow-through the same as on the jump shot? Does the routine break down after a miss?

**Cue:** "Same feet, same routine, every time." / 中文："同样的脚位，同样的程序，每一次都一样。"

**Drill:** Pairs between sprints (our rule, built on fiba-wabc-level1 p. 37 low-intensity work after high-intensity work). Setup: choose one routine (e.g. foot on the nail, three bounces, breath, shoot) and write it into `plan.json` notes; shoot 2 FTs after each conditioning or finishing block, never more than 2 in a row. Reps: 10 pairs per session. Success measure: the routine is identical on at least 18 of 20 attempts (film); FT pct within 5 points of the player's rested block pct.

**Next-session target:** `{"name": "Free throws in pairs", "match": {"zone": "ft"}, "attempts": 20, "pct": 0.75}`.

**Source:** Lonsdale & Tam 2008, J Sports Sci 26(3):259-266, abstract via Europe PMC (PMID 17943592) (284 NBA playoff FTs: routine length did not matter; following the player's usual behavioural sequence went with a higher success rate, 83.77 % vs 71.43 %); fiba-wabc-level2 p. 148 (foot position on the floorboards for free throws); fiba-wabc-level1 p. 37 (follow high-intensity activity with low-intensity work such as free throws). Quote: none.

### KB-layup-footwork-weak-hand

**Symptom (observable):** `left_finish_share` low (few left-hand finishes) or `finish_hands` shows `L` makes far below `R`; `type: layup-left` pct much lower than `layup-right`; `form` notes "wrong foot", "switches to right hand", "jumps long", "picks up early/late", "reverse avoided"; pose `travel` very large with low `jump` on finish misses (`form_finish`).

**Why it happens:**
- The weak hand is avoided in practice, so the player switches to the strong hand and finishes on the wrong side of the rim, into the defender.
- Footwork unclear: wrong take-off foot, or the ball is picked up with a foot on the floor, so the last steps are rushed.
- Jumping long instead of up carries the body under or past the rim.
- Only one finish (straight layup) is trained, so there is no answer when the line is blocked (reverse, Euro step, inside hand).

**What to check on film:** Which foot takes off on each side (opposite foot to the hand for a standard layup)? Is the ball picked up with the feet in the air? Same-side knee lifted, reach high? Does he use the rim to protect the ball on reverses? How many left-side finishes are taken with the right hand?

**Cue:** "Left side, left hand: pick up in the air, knee up, jump up not long." / 中文："左边用左手：空中收球，提膝，向上跳不要往前冲。"

**Drill:** Footwork ladder plus weak-hand series (fiba-wabc-level1 pp. 201-202; fiba-wabc-level2 pp. 139-143). Setup: from the block, one step then two-step layups each side; then from the wing with one dribble: standard layup, inside-hand layup, reverse, Euro step, alternating sides; left side always left hand (our rule). Reps: 5 finishes x 2 sides x 5 reps; the left side gets the first and last set. Success measure: correct take-off foot and hand on 9 of 10 (film); `layup-left` pct within 10 points of `layup-right`.

**Next-session target:** `{"name": "Left-hand finishes", "match": {"category": "finish", "hand": "L"}, "attempts": 40, "pct": 0.60}`; report `left_finish_share` aim at least 0.4 (our rule).

**Source:** fiba-wabc-level1 pp. 201-202 (layup teaching sequence; land the baseline-side foot on the block and shoot with the same-side hand; pick the ball up with the feet in the air); fiba-wabc-level2 p. 139 (jump-stop and two-step layups, same hand as the side, reach high, lift the same-side knee, jump up not long; Euro step), p. 140 (outside-foot and inside-foot layups, floater, wrong-foot layup), pp. 141-142 (hook and scoop), p. 143 (reverse layup, the rim protects the ball). Quote: none.

### KB-finishing-contact

**Symptom (observable):** Finishes miss when someone is there: `miss: blocked` or many `rim` misses with `form` notes "contact", "brings the ball low", "fades away", "lands off balance"; `form_finish` `jump` lower on misses than makes; in game-like blocks (trainer defending) `category: finish` pct far below unopposed layups.

**Why it happens:**
- The ball comes down to the hip on the gather, where it can be stripped or knocked down.
- The player avoids the body and fades away, so the shot leaves the rim's protection and gets longer.
- Too many dribbles and steps in the key give the help time to arrive.
- Finishes are only practised unopposed, so contact is new each game.

**What to check on film:** Ball height on the gather (shoulder or forehead vs hip)? Shoulders square to the rim or turned away? Is the jump up into the contact or away? How many dribbles inside the key before the shot?

**Cue:** "Ball high, chest into him, finish up." / 中文："球举高，用胸去顶，向上完成。"

**Drill:** Pad finishing (our rule, built on fiba-wabc-level2 pp. 146-147). Setup: the trainer stands beside the rim with a pad and bumps the hip or shoulder on the gather (light, then firmer); the player takes one dribble from the elbow or wing, gathers high and finishes with either hand; start with the "High 5" close shot (fingers up, backspin off the glass). Reps: 4 sets x 8 finishes, alternating sides. Success measure: ball stays at shoulder height or above on 9 of 10 gathers (film); makes on contact at least 60 % of unopposed makes.

**Next-session target:** `{"name": "Finishes through contact", "match": {"category": "finish", "zone": "rim"}, "attempts": 40, "pct": 0.55}`; tag the contact reps in `form` so the report can split them.

**Source:** fiba-wabc-level2 p. 146 (practise inside shots contested; "High 5" follow-through with fingers up and backspin around the rim; fewer dribbles and steps in the key), p. 147 (fake slowly, move fast; keep the ball high at shoulder or forehead; keep the knees flexed); fiba-wabc-level1 p. 209 (follow-up shots, including contested layups). The pad and the bump are our own variant; no opened source describes them. Quote: none.

### KB-ball-handling

**Symptom (observable):** Dribble segments show `losses` > 0 or `notes` "head down", "ball high", "slaps the ball"; weak-hand (`hand: L`) segments shorter or with more losses than `R`; `dribble` seconds low compared with the plan; in moves, off-dribble shots preceded by a loose last dribble.

**Why it happens:**
- Eyes on the ball, so the player cannot see the defence and the ball control is visual, not by feel.
- Slapping instead of pushing with the wrist and fingers; the ball rises above the waist and is easy to reach.
- The weak hand is trained less, so the player turns his body to protect a hand he trusts.
- Slow pace: drills done at walking speed do not hold up at game speed.

**What to check on film:** Head up for the whole segment? Ball below the knee in the stationary drills and waist in moves? Fingers spread, wrist pushing? Same speed with both hands? Does he change pace (hesitation) or only change hands?

**Cue:** "Eyes up, push it hard, low and tight." / 中文："抬头，用力推球，低而紧。"

**Drill:** Punch and retreat plus two-ball (fiba-wabc-level1 pp. 195-198). Setup: punch-dribble toward the elbow in 1-2 dribbles, retreat, open to the basket, 30 s per hand, count touches at the elbow; then two-ball pound and alternating dribble (Bongo drums idea), eyes on a target on the wall (our rule). Reps: 3 x 30 s each hand, 3 x 30 s two-ball. Success measure: zero losses in the last set; weak-hand touch count at least 80 % of the strong hand (our rule).

**Next-session target:** dribbling is not in the shot targets; set in the report: 6 minutes of handling with `losses` <= 2 and "head up" noted on every segment. Add a related finish target, e.g. `{"name": "Left-hand drive to layup", "match": {"type": "layup-left"}, "attempts": 20, "pct": 0.60}`.

**Source:** fiba-wabc-level1 p. 195 (push with the wrist, don't look at the ball, keep it below the knee, use the hesitation dribble), p. 196 (fingers spread, push the ball with force, either hand, dribble with the hand away from the defender; Punch and Retreat, 30 s, count touches), p. 197 (speed dribble relay; Dribble Chicken: quick first step, attack the hips), p. 198 (dribble mirror, Bongo drums with several balls). Quote: "see with your fingers" (fiba-wabc-level1 p. 196).

### KB-triple-threat-jab-first-step

**Symptom (observable):** One-on-one reps (with the trainer) end in a forced shot or pick-up: few `finish` reps after a catch, many `off-dribble` reps taken far from the rim; `form` notes "first step sideways/backwards", "stands up on catch", "big jab, off balance", "ball behind head"; pose `travel` small in the first second after a catch (no attack).

**Why it happens:**
- Straight-legged stance on the catch, so the first step goes nowhere or backwards.
- A jab that is too big takes the player off balance; he has to recover before he can go.
- Faking with the ball or head only, not the whole body, so the defender does not react.
- No read after the jab: the player decides before the catch instead of reacting to the defender.

**What to check on film:** On the catch, are the knees bent with "nose behind the toes" and the ball protected? Is the jab short and toward the basket? Is the first step long and past the defender's hip? After the jab, did the defender step back (shoot), shift (go the other way) or lose balance (drive)?

**Cue:** "Low catch, short jab, read, then explode." / 中文："低位接球，小试探步，看防守，再爆发。"

**Drill:** Jab series and 1v1 from the elbow (fiba-wabc-level1 pp. 219-220). Setup: catch at the elbow or wing in triple threat; jab and shoot, jab and drive same side, jab and cross-over drive; the trainer shows a read (step back, shift, lean) and the player answers; then live Foul Line 1v1, max 2 dribbles. Reps: 3 moves x 2 sides x 5, then 10 live possessions. Success measure: first step goes past the defender's front foot on 8 of 10 (film); live possessions end in a shot inside the paint or an open jumper on at least 6 of 10 (our rule).

**Next-session target:** `{"name": "Drives finished at the rim", "match": {"category": "finish", "zone": "rim"}, "attempts": 30, "pct": 0.55}`; count live 1v1 possessions in `blocks` notes.

**Source:** fiba-wabc-level1 p. 185 (protect the ball: two hands, head up, pivot away, use fakes, not behind the head), p. 186 (triple threat), pp. 210-211 (first step explosive from a low balanced stance; common mistake: first step goes nowhere or backwards from a straight-legged stance), p. 219 (drive fake: stay balanced, fake with the whole body toward the basket, ball outside the jab leg, don't overstep, read the defender), p. 220 (Foul Line 1v1 with max 2 dribbles, Penetrate or Shoot). Quote: "nose behind the toes" (fiba-wabc-level1 p. 219).

### KB-closeout-attack

**Symptom (observable):** On reps where the trainer closes out, the player shoots over a hard close-out (`miss: blocked`, `form` "contested") or drives into a defender who is set; few one-dribble pull-ups (`type: off-dribble`) or finishes after a close-out; long `dip_to_release` on contested catches.

**Why it happens:**
- The decision is made before the catch, not from the close-out.
- No shot fake, so a long, fast close-out is never punished with a drive.
- Too many dribbles after beating the close-out, so the help recovers.

**What to check on film:** Distance of the closing defender at the catch? Shot when he is far or short, drive when he flies at the shooter? One or two dribbles to the pull-up or rim, or more? Was a shot fake used?

**Cue:** "Short close-out: shoot. Long close-out: go by. Max two dribbles." / 中文："防守扑得近就投，扑得远就突，最多两下运球。"

**Drill:** Penetrate or Shoot vs close-out (fiba-wabc-level1 p. 220). Setup: the trainer starts under the rim, passes out and closes out at different speeds; the player reads: shoot, one-dribble pull-up, or drive to the rim with max 2-3 dribbles; scoring as in the source (1 point for a shot, 2 for getting into the key). Reps: 3 spots x 8 reps. Success measure: correct read on 8 of 10 as judged by the trainer or on film (our rule).

**Next-session target:** `{"name": "Close-out catch-and-shoot", "match": {"type": "catch-shoot", "zone": "three"}, "attempts": 30, "pct": 0.35}` plus `{"name": "Close-out pull-up", "match": {"type": "off-dribble", "zone": "mid"}, "attempts": 20, "pct": 0.40}`.

**Source:** fiba-wabc-level1 p. 186 (triple threat; a long close-out is a cue to drive at once; catch-and-shoot after penetration), p. 220 (Penetrate or Shoot, 1 point for a shot, 2 for getting into the key, max 3 dribbles; Attack the Elbow). Quote: none.

### KB-defensive-stance-slides

**Symptom (observable):** Conditioning or defence blocks (`blocks[].category: conditioning` or `other` with a defence drill) show `form`/block notes "stands up", "crosses feet", "lunges", "first step behind"; in 1v1 the trainer gets past on the first step. Stance height is not a pose field; it comes from the reviewer's notes only.

**Why it happens:**
- Legs tire and the stance rises; a high centre of gravity makes every change of direction slow.
- Stepping first with the wrong foot (behind the body) turns the defender sideways.
- Lunging or reaching instead of moving both feet.

**What to check on film:** Feet a bit wider than the shoulders, knees and hips bent, weight on the balls of the feet, head up? Lead foot first on slides, no feet crossing? On a direction change, a drop step at an angle followed by a long second step? Does the stance hold for the whole set or rise after 15-20 s?

**Cue:** "Nose behind the toes, step and slide, never cross." / 中文："鼻子在脚尖后，迈步滑步，不交叉。"

**Drill:** Slide-and-sprint lane drill (fiba-wabc-level1 pp. 138-139). Setup: lane line to lane line slides, then drop step and sprint to the elbow, then slide back; work bouts short enough to keep the stance (our rule: 10-15 s on, 45-60 s off, see KB-repeated-sprint-cod). Reps: 6-8 bouts. Success measure: no crossed feet and no visible rise in stance in the last two bouts (film).

**Next-session target:** not a shot target; record in `blocks` notes: 8 bouts with clean stance. Pair with KB-fatigue-shooting targets when shots follow the slides.

**Source:** fiba-wabc-level1 p. 138 (balanced stance, nose behind the toes; lateral move "big to bigger", step with the foot on the side of travel first), p. 139 (change direction with a drop step at an angle; mistake: first step behind turns you sideways; long, explosive second step into the sprint), p. 148 (move both feet, don't lunge), p. 166 (basic stance: feet a bit wider than shoulders, knees and hips flexed, head up, weight on the balls of the feet). Quote: none.

## Conditioning

### KB-energy-demands

**Symptom (observable):** Proxy only. `reps_per_active_min` drops through the session, `thirds` shows the last third clearly worse than the middle, and `blocks` has many `rest` blocks or long gaps; the player reports getting tired in the last quarter of games.

**Why it happens:**
- Basketball is intermittent: short maximal efforts (sprints, jumps, slides) repeated with short recoveries, on top of a high average heart rate. Long steady jogging trains the wrong system.
- An adult training 1-2 times a week has little extra conditioning, so the repeated-effort capacity is the first thing to fade.
- Too much slow aerobic work can cost speed and explosiveness.

**What to check on film:** Time between reps in the live blocks (rest creeping up)? Are reps in the last third slower to start? Does the shot or finish quality drop at the same time (see KB-fatigue-shooting)?

**Cue:** "Short, hard, repeat: train like the game moves." / 中文："短、强、重复：按比赛的节奏练。"

**Drill:** Court intervals (fiba-wabc-level1 p. 237; fiba-wabc-level2 p. 172). Setup: 15-30 s of hard on-court work (sprints, slides, layups) with 15-30 s easy (walk, free throws) at 1:1, at least 10 minutes in total, once a session; or a solo 1v0 "game" block of 2-3 min with 1 min rest. Reps: 10-12 min. Success measure: last 3 bouts done at the same pace as the first 3 (count lengths or reps per bout); heart rate if a watch is worn, as an "about" value only (our rule).

**Next-session target:** report `reps_per_active_min` and `thirds` against the last session; aim for a last-third pct within 10 points of the first third (our rule), with a shot target in the last block, e.g. `{"name": "Late-session mid-range", "match": {"zone": "mid"}, "attempts": 30, "pct": 0.40}`.

**Source:** fiba-wabc-level1 p. 236 (maximal efforts last 5-10 s, play phases rarely exceed 3 min, fitness is performing in the last quarter as at the start, aerobic work but not at the expense of explosiveness), p. 237 (long steady runs are not useful; interval training and on-court activities of 2-3 min; explosive work every session); fiba-wabc-level2 p. 162 (too much aerobic work can cost speed), p. 172 (aerobic intervals of 15-30 s hard and 15-30 s at 50-70 %, 1:1, more than 15 reps and at least 10 min; small-sided games); Stojanović et al. 2018, Sports Med 48(1):111-135, DOI 10.1007/s40279-017-0794-z, abstract via Europe PMC (about 5-6 km per 40 min of live play, mean intensity above lactate threshold at about 85 % HRmax, fewer vigorous activities in the fourth quarter); Petway et al. 2020, PLoS One 15(3):e0229212, https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0229212 (match demands review; distance, heart rate and accelerations by level). Quote: "Temporal comparisons show a reduction in vigorous activities in the fourth quarter." (Stojanović et al. 2018).

### KB-repeated-sprint-cod

**Symptom (observable):** Proxy. Conditioning blocks show slower runs or fewer touches in later bouts; `form` notes "rounds the cut", "slows down 3-4 steps early", "stands up in the turn"; finishes after a sprint (`category: finish` late in a sprint block) worse than rested finishes.

**Why it happens:**
- The phosphocreatine (alactic) system covers only the first 10-15 s of maximal work and needs long rests to refill; too short a rest turns a speed drill into a tiring drill.
- Changes of direction done as a curve, with a high centre of gravity and early shortening of the steps, waste time.
- The last step uses the wrong foot, so the push into the new direction is weak.

**What to check on film:** Bout length and rest (watch the clock)? Is the cut an angle (plant the foot away from the new direction, low hips) or a curve? Is the first step after the plant long and powerful?

**Cue:** "Plant outside foot, low hips, explode out." / 中文："外脚蹬地，降重心，爆发出去。"

**Drill:** Alactic sprints and cuts (fiba-wabc-level2 p. 171; fiba-wabc-level1 p. 171). Setup: power set: efforts under 7 s (baseline to free-throw line and back with a cut, or 5 backboard jumps) with 1:8 work:rest, 5-10 reps; capacity set: 4-10 s efforts at 1:6, 8-15 reps (e.g. backboard jumps 6 s on, 40 s off, x8). Reps: one set type per session. Success measure: the last rep within about 10 % of the first (time or jump count; our rule).

**Next-session target:** not a shot target; record bouts and times in `blocks` notes. If shots follow, add `{"name": "Layups after sprints", "match": {"category": "finish"}, "attempts": 20, "pct": 0.65}`.

**Source:** fiba-wabc-level1 p. 171 (change of direction: last step with the foot away from the new direction, long powerful first step; mistakes: shortening 3-4 steps early, high centre of gravity, a curve instead of an angle); fiba-wabc-level2 p. 171 (alactic covers the first 10-15 s; alactic power: under 7 s, 1:8, 5-10 reps; alactic capacity: 4-10 s, 1:6, 8-15 reps, backboard jumps 6 s on / 40 s off x8; lactic capacity: 1:3, use sparingly); Petway et al. 2020, https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0229212 (elite matches have about 43-145 accelerations and 24-95 decelerations per player; evidence inconsistent). Quote: none.

### KB-deceleration-landing

**Symptom (observable):** `form` or block notes "knees cave in", "lands stiff", "lands on one foot", "loud landing", "can't stop at the line"; pose not reliable for knee valgus from one phone angle, so treat as a trainer or film observation; jump-shot reps with the player landing well forward or sideways (`travel` large on misses).

**Why it happens:**
- Stopping is loaded harder than starting: braking forces are much higher than in acceleration, and hard decelerations often come just before non-contact knee injuries.
- Landing on locked joints (straight knees and hips) or with the knees falling inward puts the load on the ligaments instead of the muscles.
- Weak eccentric strength (quads, hamstrings) and poor balance make a controlled stop impossible late in a session.
- Ankle sprains are common in basketball; balance and neuromuscular training in the warm-up likely reduce knee and ankle injuries (the evidence for ankles in adults is thin).

**What to check on film:** On landings and stops, do the knees stay over the feet (not in or out)? Hips and knees bend together (soft landing)? Is the stop spread over several steps or one jarring step? Does the landing get worse in the last third?

**Cue:** "Land soft, knees over toes, hips back." / 中文："轻落地，膝盖对脚尖，臀部后坐。"

**Drill:** Landing and stopping series in the warm-up (fiba-wabc-level2 pp. 165-167). Setup: step to vertical jump and stick 3 per leg, single-leg hop and stick in three directions, then run-to-stop at a line: decelerate over 3-4 steps, jump stop, hold 2 s; two to three times a week as 5-10 minutes of the warm-up (our rule, based on the injury studies). Reps: 3 x 3 per drill. Success measure: knees stay over the feet and the landing is quiet on all reps of the last set (trainer or film).

**Next-session target:** not a shot target; record "landing series done" in `blocks` (`category: warm-up`). For shooters who drift, add the jump-shot line target from KB-arc-short-long.

**Source:** Harper et al. 2022, Sports Med, https://pmc.ncbi.nlm.nih.gov/articles/PMC9474351/ (braking forces up to about 2.7 times those of the first acceleration steps; intense decelerations often precede non-contact ACL injury; lower the centre of mass with triple flexion, brake over several steps, train eccentric strength and both legs, progress the drills); Struzik et al. 2014, J Hum Kinet, https://pmc.ncbi.nlm.nih.gov/articles/PMC4234772/ (jump-shot landing forces about 5.5 times body weight; soft-landing technique recommended); fiba-wabc-level2 p. 165 (screen landing: do they absorb shock or land on locked joints), pp. 166-167 (step to vertical jump with a soft landing, single-leg hop and stick in three directions); fiba-wabc-level1 p. 241 (ankle sprain is common; ACL injury from a twisting force); Donnell-Fink et al. 2015, PLoS One 10(12):e0144063, PMC4670212 (meta-analysis of 24 studies: knee injury IRR 0.731, ACL IRR 0.493 with neuromuscular and proprioceptive training); Cumps et al. 2007, JSSM, https://jssm.org/jssm-06-212.xml-Fulltext (basketball balance programme in the warm-up, 5-10 min, 3 times a week; ankle sprain RR 0.30; pilot study); Longo et al. 2012, AJSM 40(5):996-1005, PEDro https://search.pedro.org.au/search-results/record-detail/32191 (FIFA 11+ in youth basketball: fewer injuries overall, no significant difference for knee or ankle). Quote: "Knees remain over feet (don't come in or out)" (fiba-wabc-level2 p. 167).

### KB-strength-power

**Symptom (observable):** Proxy. Pose `jump` low and falling across the session, `misses.short` rising late, finishes through contact lost (see KB-finishing-contact), and the player reports little or no gym work. No direct strength measure exists in the session data.

**Why it happens:**
- Skill sessions 1-2 times a week give little strength stimulus, and strength fades within days to weeks without training (detraining).
- Weak legs make every shot and landing a larger share of maximum effort, so form fades earlier.
- Myth: strength work makes you slow. Power needs a strength base first.

**What to check on film:** `jump` mean and `sd` against earlier sessions from the same spot (about values); landing quality (KB-deceleration-landing); whether short misses track falling `jump` and `knee_bend`.

**Cue:** "Strong legs, easy shot." / 中文："腿有力量，投篮才轻松。"

**Drill:** Two strength sessions a week on non-court days (our rule for a 1-2 sessions a week player; fiba-wabc-level2 pp. 169, 174-176). Setup: bodyweight first: single-leg hamstring bridge 4 x 8 per leg, Bulgarian split squat 4 x 8 per leg, single-leg squat to box, single-leg calf raise, backboard tips 3 x 5; with a gym: squat or trap-bar deadlift, lunge, hip hinge, 3 sets of 8-12 for a novice, big multi-joint lifts first, about 2 min rest, last 2 reps hard but not to failure. Reps: progress the load by about 2-10 % when the player can do 1-2 reps more than the target; change the programme every 4-6 weeks. Success measure: the screening tests in the source (single-leg hamstring bridge 12 per leg, push-ups 12, prone hold 1 min, single-leg calf raise 20 per leg) all passed within 6 weeks (our rule for the time frame).

**Next-session target:** not a shot target; log strength sessions in the plan notes. On court, watch `jump` mean late in the session against early (about values).

**Source:** fiba-wabc-level2 p. 162 (strength training does not make you slow; stronger muscles make shots less fatiguing), p. 165 (detraining starts within about 5 days), p. 163 (change the programme every 4-6 weeks; periodise), p. 166 (screening tests: single-leg hamstring bridge 12/leg, push-ups 12, prone hold 1 min, single-leg calf raise 20/leg), p. 169 (progressive resistance; strength-endurance, hypertrophy, maximal-strength and power rep and load ranges; maximal strength usually first), p. 170 (power needs a strength base and longer rests), pp. 174-176 (beginner programmes, big lifts first, 2 min rests, last 2 reps very hard but no failure, bodyweight programme); ACSM 2009 position stand "Progression Models in Resistance Training for Healthy Adults", summary PDF https://www.sportgeneeskunde.com/wp-content/uploads/ACSM-Position-Stand-Progression-Models-in-Resistance-Training-for-Healthy-Adults.pdf (novice loads of 8-12 RM; increase the load by 2-10 % when the player can do one to two repetitions over the target; novice frequency 2-3 days a week). Quote: none.

### KB-warm-up-mobility

**Symptom (observable):** The first `thirds` third is the worst of the session (warm-up effect), the first `blocks` entry is already `shooting` with no `warm-up` block, or the warm-up block is under about 10 minutes; `form` notes "stiff", "short arm", "can't get elbow up"; early-session pose `knee_bend` and `lift` lower than later.

**Why it happens:**
- Starting to shoot cold: the first 10-15 minutes become the warm-up, so the session data underrates the player and the risk of strain is higher.
- Static stretching before training instead of dynamic movement.
- Limited range of motion (e.g. shoulder) makes parts of the technique hard, such as getting the elbow under the ball.

**What to check on film:** Is there a warm-up block, how long, and does it go from general movement to dynamic range of motion to basketball movements (stationary shots, then jump shots, then contact)? Does `thirds` show a slow start?

**Cue:** "Raise, activate, mobilise, then potentiate before the first real shot." / 中文："升温、激活、活动、再强化，然后才开始正式投篮。"

**Drill:** RAMP warm-up, about 15 minutes (Human Kinetics RAMP; fiba-wabc-level2 pp. 166-168). Setup: Raise: easy jog and skips 3-4 min. Activate and Mobilise: walking lunges with knees over toes, side lunges, single-leg hamstring bridge 2 x 8 per leg, knee-to-wall calf mobility 10 per leg, squats 10. Potentiate: step to vertical jump 3 per leg with a soft landing, accelerations, defensive slides, backboard jumps, then close-range shots to jump shots. Static stretching 10-30 s only after the session. Reps: every session. Success measure: a `warm-up` block of at least 12 minutes logged (our rule), and the first third within 10 points of the second (our rule).

**Next-session target:** report the first-third pct against the session mean; a close-shot warm-up target such as `{"name": "Warm-up close shots", "match": {"zone": "paint"}, "attempts": 20, "pct": 0.70}`.

**Source:** Human Kinetics, "The RAMP system", https://us.humankinetics.com/blogs/strength-conditioning-fitness/the-ramp-system (names Raise, Activate, Mobilise, Potentiate, by Ian Jeffreys; the page gives no exercise list); fiba-wabc-level2 p. 161 (range of motion matters: limited shoulder ROM makes it hard to get the elbow under the ball), pp. 166-167 (training warm-up: general movement, then dynamic range of motion, then sport-specific; the example exercises above), p. 168 (game warm-up: 3-4 min aerobic, 2-3 min mobility, accelerations, defensive slides, backboard jumps), p. 173 (static stretching 10-30 s after training, dynamic before); fiba-wabc-level1 p. 240 (warm-up 5-10 min with dynamic stretching, cool-down with static stretching); specialolympics-basketball-coaching-guide-2024 p. 30 (at least 15 min, sport-specific), p. 31 (aerobic, dynamic stretching, sport-specific movements). Quote: none.

### KB-fatigue-shooting

**Symptom (observable):** `thirds` shows the last third clearly below the first two (e.g. 10+ points); `misses.short` share rises late; late-session pose `knee_bend` and `jump` lower and `dip_to_release` longer than early (about values); shots taken right after a `conditioning` block worse than rested ones.

**Why it happens:**
- Fatigue slows the release and flattens the arc: in a study of high-level players, after a fatigue protocol release time rose about 15-25 % and entry angle fell, and three-point success fell.
- Tired legs give less power, so the arms take over and shots fall short (KB-arc-short-long).
- Shooting is usually practised fresh, so the form under game fatigue is never trained.

**What to check on film:** Does the drop line up with a conditioning block or with the session clock? Are late misses short (legs) or sideways (focus, alignment)? Do pose values change late?

**Cue:** "Tired legs: bend more, same rhythm." / 中文："腿累了更要弯膝，节奏不变。"

**Drill:** Sprint-then-shoot sets (Bourdas et al. 2024; fiba-wabc-level1 p. 37). Setup: 15-20 s of sprints or slides, then 5 shots from one spot, then 40-60 s of easy free throws or walking; supervised or filmed so technique is not lost (stop the set when form breaks, our rule). Reps: 4-6 rounds, late in the session. Success measure: fatigued-set pct within 10 points of the rested pct from the same spot (our rule).

**Next-session target:** `{"name": "Shots after sprints", "match": {"zone": "mid", "spot": "left elbow"}, "attempts": 30, "pct": 0.40}` (use the spot that the plan tags as the post-sprint spot); report `thirds` last vs first.

**Source:** Bourdas et al. 2024, Sports (Basel) 12(3):63, https://pmc.ncbi.nlm.nih.gov/articles/PMC10974731 (38 high-level players; after the BEST fatigue protocol release time up about 15-25 %, entry angle down about 3-4 %, successful threes down about 14-19 %; recommends shooting drills under aerobic and anaerobic fatigue, supervised, with heart rate in mind); Stojanović et al. 2018, DOI 10.1007/s40279-017-0794-z (fewer vigorous activities in the fourth quarter); fiba-wabc-level1 p. 37 (follow high-intensity activity with low-intensity work such as free throws). Quote: "designing shooting programs should consider players' heart rate levels to optimize training effectiveness." (Bourdas et al. 2024).

### KB-recovery-weekly-load

**Symptom (observable):** Session-to-session (`progress`, previous `delta_pct`) pct falls for two or more sessions in a row with no change in drills; `reps_per_active_min` and pose `jump` lower than usual from the start; the player notes poor sleep, a game the day before or a hard work week.

**Why it happens:**
- Load without recovery: a game, a skills session and a gym session close together, with no easy day between.
- Short or irregular sleep: partial sleep loss hurts repeated submaximal efforts more than single maximal ones, and extra sleep improved sprint and shooting in a small study of college players.
- Dehydration: about 2 % body-weight loss can cost about 10 % of performance.
- No progression or deload pattern: the same load every week, or a sudden jump after a break (detraining starts within about 5 days).

**What to check on film:** Session date against the last game and gym day; first-third pct and `jump` against the player's normal; any notes on sleep, illness, soreness or work stress.

**Cue:** "Hard day, easy day; sleep is training." / 中文："一天强一天弱；睡眠也是训练。"

**Drill:** Weekly plan (our rule, built on fiba-wabc-level1 p. 37 and fiba-wabc-level2 pp. 22-23, 163). Setup: keep a short diary (load 1-10, sleep hours, how I feel); no hard session the day before a game, lighter the day after; build load for 3 weeks, then one lighter week (about 60-70 % of the volume, our rule); if the diary shows poor sleep or high fatigue, shorten the session or switch to technique-only shooting. Reps: weekly. Success measure: diary filled in for every session; no two hard days back to back (our rule).

**Next-session target:** keep the previous targets; on a planned light day lower `attempts` by about a third and keep `pct` (our rule), e.g. `{"name": "Light day free throws", "match": {"zone": "ft"}, "attempts": 20, "pct": 0.75}`.

**Source:** fiba-wabc-level1 p. 37 (volume vs intensity; balance work and rest; lighter load in the day or two before a game and the day after), p. 238 (2 % dehydration can mean a 10 % performance drop); fiba-wabc-level2 p. 22 (diary of load, sleep and "how I feel"), p. 23 (reduce the session or change its content with signs of fatigue; work stress counts), p. 163 (change the programme every 4-6 weeks, periodise), p. 165 (detraining starts within about 5 days), p. 201 (active recovery), p. 205 (sleep: partial loss hurts repeated submaximal efforts more, naps, regular sleep-wake routine, dark cool room, avoid alcohol and caffeine before bed); Mah et al. 2011, Sleep 34(7):943-950, https://pmc.ncbi.nlm.nih.gov/articles/PMC3119836/ (11 college players, about 111 min more sleep a night; sprint 16.2 to 15.5 s, free throws +9 %, threes +9.2 %; small sample). Quote: none.
