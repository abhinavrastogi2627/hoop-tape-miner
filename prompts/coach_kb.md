# Coaching knowledge base (coach brain)

Purpose: a fixed set of coaching entries that turn what the film review measured into an explanation (why it happened), an in-game rule, a drill and a next-game target. Each entry covers one recurring amateur problem.

Audience: an amateur adult team (rec league, about one 90-minute practice a week, 8-10 players at practice, short benches, mixed skill). Drills are adapted to that: small groups, few rules, game-like reps, no specialist roles assumed.

How agents use it:
- The film reviewer points a trip's `coach_note` at the matching entry's **Symptom** when the trip shows it.
- The insights writer cites entries by slug (`kb: ["transition-defence"]`), takes the mechanism from **Why it happens**, checks the film for the items in **What to check on film**, and copies the rule, drill and target only when the evidence supports them. If a symptom is not in the data, do not use the entry.
- The critic checks that every claim using an entry shows its symptom in at least two trips.
- Field names refer to the trip schema v2 (`prompts/film_review_brief.md`) and to the track features (`coach_features.py`: `numbers_back_2s`, `off_spacing_m`, `off_hull_m2`, `paint_crowd`, `standstill_share`, `cross_half_s`). Feature values may be `null`; a null is "unknown", never zero.
- Targets are starting points. Re-set the number after each game from what our team actually managed (aim for a clear step, not perfection).

Sources: entries are paraphrased in our own words from professional coaching material, with at most one short quoted sentence per entry. Page numbers are PDF pages of the local library copy (`<coach_library>/<slug>/`, the `coach_library` folder of the team profile; page N = text after the (N-1)th form feed); the printed page number in the manuals is usually 2 lower. Library slugs: `fiba-wabc-level1/2/3` (FIBA WABC Coaches Manual levels 1-3), `jrnba-allstar-plans` and `jrnba-mvp-plans` (Jr. NBA practice plans). Web sources are cited by URL. The full texts are not in this repo and must not be copied into it.

---

### KB-transition-defence

**Symptom (observable):** After our missed shot or turnover, few defenders are back: `numbers_back_2s` <= 2 or `transition_defence.back` <= 2, often with `rim_protector: "no"`; the opponent trip has `entry: transition` and ends `made2` at `shot.zone: rim`, or `foul_ft` with `foul.type: shooting_on_drive` from behind. Our trips before it show `turnover_lead_to: yes` or a missed shot with `oreb_crash.n` >= 3.

**Why it happens:**
- Nobody has a "safety" job when we shoot: everyone watches the shot or crashes, so the break starts 4-on-2 or worse.
- The last player back runs at the ball instead of to the basket, so one pass over the top gives a layup.
- Bad offence feeds the break: live-ball turnovers and early, contested shots leave our players out of position.
- Tired legs on a short bench: players jog back after a miss, especially late in a half.

**What to check on film:** At our shot release, who is above the free-throw line? Two seconds after the change of possession, how many of us are on our own half and who is under the rim? Did the first man back stop at the basket or chase the ball? Was the foul a chase from behind on a layup (and-one risk)? Did the outlet pass go uncontested?

**In-game rule:** When the shot goes up, the two players furthest from the rim (usually the guards) are "safeties" and sprint to the top of the key / own half; the first one back runs to the rim, not to the ball, and calls who takes the ball. Nobody chases a layup from behind: run to the rim or concede the two, no swipe.

**Drill:** Line-Up Transition (jrnba-mvp-plans). Setup: two teams of 4-5, one on the baseline, one on the free-throw line extended facing them; coach passes to a baseline player, that team attacks the far basket; the defender opposite the receiver must touch the baseline before getting back, so the defence starts one player short. Reps: 4 stops per team, then swap lines; 10-12 minutes. Success measure: defence stops the ball before half court and has someone under the rim on every rep; no layup conceded on 3 of 4 reps. Follow with 3-on-2 Trailer Game (jrnba-allstar-plans, a third defender sprints in from half court) to games of 5.

**Next-game target:** On opponent trips after our missed shot or turnover, `numbers_back_2s` >= 3 on at least 80 % of trips with a known value, and `rim_protector: "yes"` on at least 70 %; opponent transition points (trips with `entry: transition` and a made shot) at most half of the reference game's count; fouls from behind on breaks (`foul.cause` mentions "from behind") <= 1.

**Source:** fiba-wabc-level1 pp. 270-273 (defence starts with the shot, safety to the top of the key, "basket before ball", jam the outlet without reaching, 1v2 and 2v3 tandem); jrnba-mvp-plans p. 25 (Line Up Transition Drill); jrnba-allstar-plans pp. 28-29 (3 on 2 Trailer Game). Quote (heading): "Defence Starts With a Shot" (fiba-wabc-level1 p. 270).

### KB-press-break

**Symptom (observable):** Our trips with `pickup_point` full, 3/4 or half end in `result: turnover` with `turnover_cause: steal_on_ball`, `lost_dribble` or `violation`, and `cross_half_s` is long (for example over 8 s); `initiator` is the same single ball-handler on most trips; `ball_stops` >= 1 before half court; the turnover has `turnover_lead_to: yes`.

**Why it happens:**
- One ball-handler and no outlet: the other four run away or stand still, so the defence can double him with no risk.
- The dribbler keeps the ball in the trap instead of passing out of it; dribbling straight ahead into the second defender.
- Receivers stand in the defender's shadow rather than in a gap, so there is no safe pass.
- The ball is caught too close to the baseline or sideline, leaving no room to back out.

**What to check on film:** When pressure picked up, where were the other four (behind the ball, level, ahead in a gap, or far downcourt)? Was there a receiver within one pass on the same side, opposite, and in the middle? Did the dribbler retreat or try to split? Who was open when the second defender left his man?

**In-game rule:** Against pressure, always three options for the ball: one player level on the other side (reversal), one ahead in the middle gap, one deep. When the second defender comes, pass to the man he left; when trapped, take two retreat dribbles at an angle and then pass. Pass over half court rather than dribbling into the half-court trap. A second ball-handler must be on the floor in every lineup.

**Drill:** Half-Court Line Battles (jrnba-allstar-plans) to warm up, then a 5-area press-break game (fiba-wabc-level1). Setup: pairs in lanes from baseline to half court, offence must get the ball across, defender live, 4 minutes; then 5 offence vs 3-4 defenders spread through 5 zones of the backcourt, offence must cross half court within 8 s using at least two passes. Reps: 6-8 possessions per group, switch; 15 minutes. Success measure: at least 5 of 6 possessions cross half court without a turnover, with at least two passes, and the ball-handler never picks up the dribble in a trap.

**Next-game target:** On trips where the opponent picks up at full, 3/4 or half court: turnovers (`turnover_cause` steal_on_ball / lost_dribble / violation) <= 1 per half; `cross_half_s` median under 8 s; at least two different `initiator` jerseys bring the ball up in each half.

**Source:** fiba-wabc-level1 pp. 365-368 (retreat dribble, move receivers into gaps, pass over half way, three passing options, purposeful movement) and p. 371 (5-area framework for practising against pressure); fiba-wabc-level2 p. 102 (best pass against a double team is to the player the second defender left); jrnba-allstar-plans p. 34 (Half-Court Line Battles); https://www.coachesclipboard.net/BasketballPressOffenses.html.

### KB-half-court-spacing

**Symptom (observable):** Our half-court trips (`entry: halfcourt_set` or `early_offense`) show low `off_spacing_m` (players bunched), high `paint_crowd`, high `standstill_share`; `primary_action: isolation` or `none/stagnant`; `ball_reversals` 0, `paint_touches` 0-1, `ball_stops` >= 1; the shot is `contested` or `heavily_contested`, often by 2-3 defenders.

**Why it happens:**
- Players drift toward the ball to "help", which brings their defenders into the driving lane.
- No agreed spots, so two players fill the same space and one corner stays empty.
- The ball-handler attacks before the floor is set, into a crowded paint.
- Players spot up inside the arc, so their defenders can help and recover in one step.

**What to check on film:** At the moment of the drive or isolation, how many of our players were within 3-4 m of each other? Were both corners filled? How many defenders were in the paint when the drive started? Did anyone relocate when the ball moved?

**In-game rule:** Four out, one in (or five out): fill both corners and both wings at the three-point line, one player at the top or in the dunker spot; one player per spot. If your defender helps, you move to the open spot in his line of sight, never toward the ball. No drive starts until two corners are filled.

**Drill:** 2-on-1 / 3-on-2 Bunch Spacing Game (jrnba-allstar-plans) progressed to spot-based 4-on-4 (fiba-wabc-level1 "head-hands-feet" spots marked with cones). Setup: start all players bunched, play goes live on the first touch, offence must spread out immediately; then 4-on-4 half court with cones on the five perimeter spots, one player per spot. Reps: 3-4 possessions per group in the bunch game (5 min), then 4-on-4 for 10 minutes. Success measure: coach freezes play at random; at least 4 of 5 freezes show no two offensive players within about 3 m of each other and both corners filled.

**Next-game target:** On our half-court trips, `off_spacing_m` mean at least 1 m higher than in the reference game and `paint_crowd` lower; `primary_action` isolation or none/stagnant on fewer than 30 % of half-court trips; `standstill_share` below the reference game's value.

**Source:** fiba-wabc-level1 pp. 310-311 (basic floor spacing, head-hands-feet spots, one player per spot, cuts go into the key and come out), p. 246 (why players crowd the ball); fiba-wabc-level3 p. 202 (lifted middle pick-and-roll: three players on the perimeter create space to attack the rim); jrnba-allstar-plans p. 5 (2 on 1 Bunch Spacing Game).

### KB-off-ball-cuts

**Symptom (observable):** Our half-court trips have high `standstill_share`, `primary_action` not `cut` / `off_ball_screen` (mostly isolation or none/stagnant), `ball_reversals` 0, few `paint_touches`, `ball_stops` >= 1; the ball-handler is denied a pass and holds or forces a shot late.

**Why it happens:**
- Players watch the ball after passing it: no pass-and-cut, no basket cut when the defender turns his head.
- Denied wings stand still instead of back-cutting, so the defence wins with simple denial.
- No replacing: after a cut nobody fills the spot, so the floor tilts and the next pass is long.
- Ball goes to one side and stays there, so the help side never has to move.

**What to check on film:** After each pass, did the passer cut or stand? When a receiver was denied, did he back-cut or keep reaching for the ball? Was the cutter's spot refilled? Count how often the ball crossed the middle before the shot.

**In-game rule:** Pass and cut (give-and-go) or pass and screen away, every time; never stand where you passed. If you are denied on the wing, back-cut to the rim and come out to the corner. When a cutter leaves a spot, the nearest player fills it. Swing the ball side-to-side at least once before a contested shot.

**Drill:** Shell Drill, pass and cut only (jrnba-mvp-plans "4 on 4 Shell to Rebound"; fiba-wabc-level1 shell stages). Setup: 4-on-4 half court, offence may only pass and cut (no screens, no dribble for the first round); after 5 passes the ball is live; a shot counts only after two ball reversals and one paint touch. Reps: first team to 5 defensive rebounds wins, then swap; 12-15 minutes. Success measure: offence makes at least two reversals and one cut that receives the ball on most possessions; defence scores a point for every stop.

**Next-game target:** On our half-court trips, mean `ball_reversals` >= 1.0 (and at least one reversal on 50 % of trips), mean `paint_touches` >= 1.0, `primary_action: cut` or `off_ball_screen` on at least 15 % of trips, `standstill_share` below the reference game's value.

**Source:** fiba-wabc-level1 pp. 311-312 (v-cut, back cut when the defender is in the passing lane, pass and cut / give and go), p. 315 (replacing the cutter keeps the floor spaced), pp. 256-257 (shell drill stages: 5 ball reversals, must reverse twice and penetrate before shooting), p. 319 (ball reversal makes defenders move and opens drives); jrnba-mvp-plans p. 24 (4 on 4 Shell to Rebound).

### KB-drive-help

**Symptom (observable):** Opponent trips with `primary_action` isolation or drive_kick end in `made2` at `shot.zone: rim`, or in `foul_ft` with `foul.type: shooting_on_drive` and a `foul.cause` like "late help" or "reached"; `help_rotation: late` or `none`; `paint_touches` >= 1 with the shot `open`.

**Why it happens:**
- Help defenders sit too close to their own man (denial everywhere), so they are too far away to stop a drive.
- No one owns the rim: the post defender is pulled out, and the next player does not "help the helper".
- Help arrives after the driver has gathered, so the only option is a foul (and often an and-one).
- On-ball defenders get beaten straight-line because they expect help that is not there.

**What to check on film:** When the drive started, where were the help defenders (inside the "pack line" about 5 m from the rim, or on their man)? Who was the first helper and was he set before the driver reached the key? Did anyone rotate to the helper's man? Was the foul a late arm from the side or behind?

**In-game rule:** Off the ball, sag to the pack line (both feet inside about 5 m from the rim, halfway between your man and the ball) and see both. The closest defender stops the ball early, before the gather, with chest and vertical arms; the next one rotates to the rim ("help the helper"). If you are late, let the shot go: no swipe from the side or behind.

**Drill:** 3-on-3 from Help the Helper (jrnba-mvp-plans), then Disadvantage Shell Drill (fiba-wabc-level1). Setup: each possession starts with a baseline drive, a help defender must stop the ball and the third defender rotates to the rim, then live; in the shell version the ball defender starts beaten so the team must rotate. Reps: games to 3 stops, 3 groups rotating (8-10 minutes), then 4-on-4 disadvantage shell for 8 minutes with a point to the offence for every paint touch. Success measure: help is set (feet outside the restricted arc, vertical) before the driver gathers on at least 4 of 5 drives; zero reach-in fouls in the drill.

**Next-game target:** Opponent drives: `help_rotation: good` on at least 60 % of trips with a drive, `foul.type: shooting_on_drive` by us <= 3 per game, and opponent `shot.zone: rim` makes in the half court below the reference game's count.

**Source:** fiba-wabc-level1 pp. 260-261 (help and recover, step with both feet, do not reach), p. 267 ("Basket-High-Ball" rotation activity), p. 268 (Disadvantage Shell Drill); fiba-wabc-level3 pp. 83-84 (pack line defence: protect against dribble penetration, help position halfway between man and ball); jrnba-mvp-plans p. 12 (3 on 3 From Help the Helper).

### KB-closeouts

**Symptom (observable):** Opponent trips with `closeout: late` or `ran_past` end in `made3`/`made2` with `shot.contested: open`, or in a drive past the closing defender (`paint_touches` >= 1 after a kick-out); `foul.type: shooting_on_jumper` by us.

**Why it happens:**
- The defender waits for the catch instead of moving while the pass is in the air.
- Sprinting all the way in and flying past: no chop steps, no balance, so a shot fake beats him.
- Help defenders are too deep after helping and have to cover a long distance (often to the corner after a drive).
- Nobody calls "ball", so two defenders go to one shooter and leave another open.

**What to check on film:** On each kick-out, where was the closing defender when the pass left the hand? Did he chop his feet in the last third, hands up, or run past? After his closeout, did the shooter shoot open, drive, or pass? Which spot (corner vs wing) was left open most?

**In-game rule:** "Fly with the ball": move on the pass, call "ball", sprint two-thirds of the way, then short chop steps with hands high; take away the shot first but stay balanced to stop the drive. Against a known shooter, run past the shooting shoulder without contact; against a non-shooter, stop short and take the drive.

**Drill:** 2-Person Close-Out to Live Game (jrnba-allstar-plans), with the Close-out 4 scoring rule (fiba-wabc-level1). Setup: two offensive players on opposite wings, line of defenders under the rim; on each skip pass the next defender closes out while the previous one jumps to help and calls "help"; after 2-3 skips the coach calls "live" for 2-on-2; offence has at most 3 dribbles to reach the key. Reps: 3-5 minutes per group, two groups on two baskets, about 10 minutes. Success measure: defender gets a point when the attacker does not reach the key; target at least 3 of 5 stops per defender, no fouls on shooters.

**Next-game target:** Opponent catch-and-shoot or kick-out trips: `closeout: good` on at least 60 % of trips where a closeout happened; `ran_past` <= 2 per game; opponent `shot.contested: open` threes fewer than in the reference game.

**Source:** fiba-wabc-level1 pp. 140-142 (closing out: fly with the ball, sprint, chop steps, two hands high, call "ball", practise contested; close-out activities 1-4); fiba-wabc-level2 pp. 91-92 (closing out a shooter: run past the shooting shoulder without fouling; Close Out Shooter activity); fiba-wabc-level3 pp. 194-195 (corner kick-outs force the longest closeouts); jrnba-allstar-plans p. 41 (2 Person Close-Out to Live Game).

### KB-defensive-rebounding

**Symptom (observable):** Opponent trips with a missed first shot have `oreb_crash.got: them` (their offensive rebound) and `entry: OREB_putback` on the next trip; `boxout` 0-2 when the shot went up; putbacks or `foul.type: over_the_back` by us.

**Why it happens:**
- Defenders turn to watch the ball instead of finding their man, so the rebounder runs past.
- Help defenders are in the paint but do not find a body; long rebounds go over everyone.
- Players stand under the rim, so the ball bounces over them.
- Guards leak out early for the break before the rebound is secured.

**What to check on film:** At release, how many of us turned to find a man and made contact? Where did the rebound land (long / short / weak side)? Who secured it and who was closest? Did a guard leave early?

**In-game rule:** On every shot: see your man, step in and make forearm contact, then pivot to face the rim with hands up, one step outside the restricted arc. Help-side defenders step to the edge of the key and hit whoever comes. Guards leave for the break only after we have the ball.

**Drill:** Split-Line Box Out, then 4-on-4 Shell to Rebound (fiba-wabc-level1; jrnba-mvp-plans). Setup: defender starts in help, coach passes to the shooter, the help defender must close the distance and box out the crasher; then 4-on-4 shell, live after 5 passes, possession ends only on a defensive rebound. Reps: box-out pairs until each defender gets 5 rebounds (5 min); shell game first to 5 defensive rebounds (10 min). Success measure: in the shell game the defence concedes at most 1 offensive rebound per 5 shots.

**Next-game target:** Opponent missed shots: `boxout` >= 3 on at least 60 % of misses with a known value; opponent offensive rebounds (`oreb_crash.got: them`) on at most 30 % of their misses; over-the-back fouls by us 0.

**Source:** fiba-wabc-level1 pp. 156-157 (blocking out: see, balance, contact, turn, hands up; one step away from the basket; help defenders step to the edge of the key), p. 160 ("Split Line Box Out" and "Penetrate & Rebound" activities); jrnba-mvp-plans pp. 24-25 (4 on 4 Shell to Rebound).

### KB-offensive-rebounding-balance

**Symptom (observable):** Our missed shots show `oreb_crash.n` >= 3 with `got: them`, followed by opponent trips with `entry: transition` and low `numbers_back_2s`; or the opposite, `oreb_crash.n` 0 with nobody contesting a miss.

**Why it happens:**
- No assigned roles: everyone decides on his own, so either all crash or none do.
- Players do not anticipate the shot, so they arrive late and still are not back on defence.
- Shots are taken with no rebounder in position (early pull-ups), so a miss is a lost possession and a break.

**What to check on film:** At release, how many of us went to the glass, how many to the top / half court? Who was the safety and did he stay? Did the crashers who lost the rebound sprint back right away?

**In-game rule:** Two crash (the two bigs or the two closest to the rim), one goes to the free-throw line as a "half" rebounder for long misses, two get back (the shooter only crashes if he is a big). If the crash fails, the crashers sprint back immediately, no complaints to the referee.

**Drill:** Play-to-a-finish scrimmage with rebounding roles (fiba-wabc-level1). Setup: 5-on-5 half court, possession does not end with the shot but only with a made basket or the defence securing the ball and crossing half court; coach awards a point to every player who reached his assigned crash or safety spot, not only to the rebounder. Reps: 8-10 possessions per side, 12 minutes. Success measure: on at least 80 % of shots the team has 2 crashing and 2 back; offensive rebounds won on at least a quarter of misses.

**Next-game target:** On our missed shots: `oreb_crash.n` 2 on at least 60 % of misses (not >= 3 unless `numbers_back_2s` >= 2), and `numbers_back_2s` >= 3 on at least 80 % of the following opponent trips; our offensive rebound share (`oreb_crash.got: us`) no lower than the reference game.

**Source:** fiba-wabc-level1 pp. 375-376 (rebounding and defensive transition: anticipate the shot, assign rebounding pathways, reward moving to a rebounding spot, play activities on to a score or defensive control), p. 270 (on a shot, each player goes either into the key to rebound or to the top of the key to defend the break).

### KB-foul-discipline

**Symptom (observable):** Many fouls by us with `foul.type: reach_in`, `shooting_on_drive` or `over_the_back`, and `foul.cause` such as "reached from behind", "late help", "swiped at the ball"; `result: foul_ft` trips for the opponent, and-ones (`made2` + `fts`); opponent free-throw attempts high relative to their field-goal attempts.

**Why it happens:**
- Beaten off the dribble and trying to win the ball back with the hands instead of the feet.
- Late help that arrives after the gather, moving sideways or forward into the shooter.
- Chasing a fast break from behind, reaching for a block or the ball.
- Frustration late in a bad stretch; amateur defenders "foul to stop the run".

**What to check on film:** For each foul: was the defender in front (legal guarding position) or beside / behind? Were his arms vertical inside his cylinder or reaching? Was it at the end of a long defensive possession? Who fouled and was it his 3rd or 4th foul?

**In-game rule:** No reach, no swipe: defend with the feet and keep hands up and vertical (inside your own cylinder). If you are beaten, run to the rim and contest straight up, or let it go; never foul a layup from behind. In the bonus, every "50/50 reach" is two free throws for them.

**Drill:** "No grab" scrimmage (fiba-wabc-level3). Setup: 5-on-5 or 4-on-4 half court with one simple rule: a defender may intercept passes but may not take the ball from an offensive player's hands; every reach, swipe or contact from behind gives the offence a point and the ball back. Reps: two 5-minute games, 10 minutes total. Success measure: at most 1 reach / from-behind call per team per 5 minutes; stops still achieved on at least half the possessions.

**Next-game target:** Our fouls with `foul.type: reach_in` or a `foul.cause` mentioning "from behind" <= 1 per half; opponent `foul_ft` trips plus and-ones fewer than in the reference game; opponent FT attempts / FGA (Oliver's free-throw factor) lower than in the reference game.

**Source:** fiba-wabc-level3 p. 151 (late-clock fouls from reaching; the "no grab" practice rule); fiba-wabc-level2 p. 95 (do not reach beyond your cylinder or hit the shooter before he lands), p. 102 (hands high and active, not reaching for the ball); fiba-wabc-level1 p. 272 (resist reaching on the outlet, it often results in a foul); FIBA Official Basketball Rules, Art. 33 (cylinder, verticality, legal guarding position), https://about.fiba.basketball/en/our-sport/official-basketball-rules; Dean Oliver's four factors (free throws factor FT/FGA), https://www.basketball-reference.com/about/factors.html.

### KB-shot-selection

**Symptom (observable):** Our trips end in `missed` with `shot.type: pullup_mid` / `three_pullup` / `catch_shoot_mid` and `shot.contested: contested` or `heavily_contested`, often early in the trip with `ball_reversals` 0 and `paint_touches` 0; few shots at `shot.zone: rim` or open corner threes; missed free throws (`fts.made` < `fts.att`).

**Why it happens:**
- No shared idea of a good shot: players shoot the first look rather than the best one.
- Isolations into a crowded paint (see KB-half-court-spacing) leave only contested jumpers.
- Drives end in a fade-away instead of a jump stop and pass-out to the open shooter.
- Under pressure late in a period, players force a shot instead of a pass.

**What to check on film:** For each miss, was it contested, and was a teammate open (corner, rim)? How many passes and paint touches came before it? Which shot types does each player make in this game and the official stats? Free throws: who missed and at what point of the game?

**In-game rule:** Good shots for us: layups, open catch-and-shoot threes (corners first), free throws. A contested mid-range pull-up is a last resort. Drive to get two feet in the key, jump stop, then score or kick to the corner. One paint touch before any contested jumper. A shot is good only if we have rebounders and a safety (see KB-offensive-rebounding-balance).

**Drill:** Paint-touch scoring scrimmage (fiba-wabc-level1 shell stage 2 rules plus shot points). Setup: 4-on-4 or 5-on-5 half court; layups and open corner threes score normal points, any shot after a paint touch scores +1 bonus, a contested pull-up jumper with no paint touch scores 0 even if made. Finish each block with Free Throw Golf (jrnba-allstar-plans: 2 FTs at a time, 10 each, lowest misses wins). Reps: 10 minutes scrimmage, 5 minutes free throws. Success measure: at least 60 % of shots in the scrimmage come at the rim, from the corners or after a paint touch; team FT 70 % or better in the golf game.

**Next-game target:** Share of our shots with `shot.zone: rim` or `shot.type: three_catch` with `contested: open` higher than in the reference game; `heavily_contested` shots <= 15 % of attempts; at least one `paint_touches` before 60 % of our half-court shots; team FT made / attempted higher than in the reference game.

**Source:** fiba-wabc-level3 pp. 193-195 (shot value of twos vs threes, corner three created by penetration and kick-outs, mostly assisted); fiba-wabc-level1 p. 321 (dribble penetration: both feet in the key, jump stop, be a scorer first, receiver spots), p. 375 (rebounders present decide whether a shot is a good option); jrnba-allstar-plans pp. 25-26 (Free Throw Golf); https://www.coachesclipboard.net/basketball-shot-selection.html; Dean Oliver's four factors, shooting weighs most, https://www.basketball-reference.com/about/factors.html.

### KB-pick-and-roll

**Symptom (observable):** Opponent trips with `primary_action: PnR` and our `pnr_coverage: none/blown` end in an open shot or a roll to the rim (`shot.zone: rim`, `contested: open`) or a `foul` on the roller; on our side, trips with `primary_action: PnR` produce no `paint_touches` and a late, contested shot.

**Why it happens:**
- No agreed coverage: the two defenders guess (both go with the ball, or both stay), leaving the roller or the shooter free.
- The screener's defender does not show or step "vertically", so the ball-handler turns the corner.
- Weak-side defenders do not sag into the key to tag the roller.
- On offence, our screener sets a soft screen and does not roll or pop, so there is no second threat.

**What to check on film:** On each ball screen, what did the ball defender do (over, under, stuck) and the screener's defender (show, drop, nothing)? Who picked up the roller? On our ball screens: did the screener make contact, then roll or pop, and was the help side spaced?

**In-game rule:** One simple coverage for the whole game: the screener's defender shows hard for one dribble and recovers, the ball defender goes over the screen against a shooter and under against a non-shooter, and the lowest weak-side defender tags the roller. On offence: the screener sprints into the screen, sets it with contact, and either rolls to the rim or pops to the three-point line; the other three space out (lifted, both corners filled).

**Drill:** 3-on-3 Dictated Pick and Roll (jrnba-mvp-plans). Setup: teams of 3, each possession must start with a ball screen at the top, then live; make-it-take-it; defence calls the coverage aloud ("show", "over"/"under", "tag"). Reps: games to 3 makes, rotate teams; 12 minutes on two baskets. Success measure: the defence executes the called coverage (no two defenders on the ball, roller tagged) on at least 4 of 5 possessions; the offence gets a paint touch or an open shot from the screen on most possessions.

**Next-game target:** Opponent ball screens: `pnr_coverage: none/blown` on at most 20 % of their PnR trips; opponent PnR trips ending in an open rim shot <= 2 per game. Our PnR trips: at least one `paint_touches` on 60 % of them.

**Source:** fiba-wabc-level3 pp. 96-98 (defending on-ball screens: decisive, coordinated; screen defender steps vertically; over vs under by shooter; weak side sags into the key on side PnR), pp. 201-202 (pick and roll offence: screener sets up, sprints into the screen, angle, then roll or pop; other players replace and space); jrnba-mvp-plans p. 43 (3 on 3 Dictated Pick & Roll).

### KB-late-clock-end-of-period

**Symptom (observable):** Trips in the last minute of a period or near the shot clock end in `result: turnover` (`violation`, `bad_pass`) or a `heavily_contested` shot with `ball_stops` >= 1 and `ball_reversals` 0; or our defence fouls (`foul.type: reach_in`) at the end of a good defensive possession; or `result: end_period` with no shot attempted while we needed points.

**Why it happens:**
- No shared late-clock plan: the ball-handler dribbles out the clock and forces a shot.
- Players do not track the clock or the score situation (when to take a two, when we need a three, when not to foul).
- Defenders reach at the end of a long possession instead of letting the clock "defend".
- Short bench: tired players make worse decisions at the end of halves.

**What to check on film:** With under 10 s on the shot clock or under a minute in the period: who had the ball, how many passes and paint touches, and was the final shot the one we wanted? Did we foul on defence late in the clock? Did anyone signal the time and score?

**In-game rule:** Under 10 s on the shot clock: ball to our best decision-maker, a ball screen or a drive with two in the corners, and shoot before 3 s remain. Last possession of a period: shoot with about 5 s left so there is time for a rebound; down 3, look for a three, up 3, do not foul a shooter. On defence late in the clock: no reaching; the clock is our extra defender.

**Drill:** 5-on-5 Situational (jrnba-allstar-plans) with late-clock starts (fiba-wabc-level3). Setup: scrimmage segments that start with a set situation (for example "12 s on the shot clock, ball on the wing", "down 2, 30 s left, our ball", "up 1, their ball"); the coach counts the last 10 s aloud; the defence plays with the "no grab" rule. End with 10 free throws per player under fatigue (after a sprint). Reps: 3 situations per side, 12-15 minutes. Success measure: the offence gets a shot off before the clock ends with at least one paint touch on 4 of 6 reps; the defence commits 0 reach-in fouls.

**Next-game target:** In the last minute of each period and in late-clock trips: turnovers <= 1 per game, no `result: end_period` without a shot when we need points, our reach-in fouls 0; at least one `paint_touches` on 60 % of these trips.

**Source:** fiba-wabc-level3 p. 151 (late shot clock defence: team rules, the clock as a defender, no-grab rule), pp. 234-235 (late shot clock offence: clock awareness drills, structures, who should shoot), p. 236 (last possession plays: shooting time, 2- and 3-point options, not fouling when up 3); jrnba-allstar-plans p. 29 (5 on 5 Situational).
