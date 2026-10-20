# Movement knowledge base: running and force pattern for basketball

Purpose: a fixed set of entries that turn what a movement session measured (2D pose metrics plus a reviewer's film notes) into an explanation (why it happens), a cue, a drill and a success measure. The entries cover how an adult amateur guard sprints, pushes the ball in transition, approaches and takes off for a layup, stops and lands, and the load capacity (calves, knees, hamstrings) that this needs.

Audience: one adult player (about 30, 173 cm, 76 kg, rec league guard who pushes the ball in transition) with a distance-running background (runs 10 km comfortably). Teammates say his full-court running looks "heavy". Calves get very sore (worst on a treadmill), knees ache after games, glutes do not. He trains 1-2 times a week with a trainer plus solo work, filmed on a phone. Drills are sized for one player, one court, cones, tape, a phone on a tripod, a box and a gym when available.

How agents use it:
- The movement reviewers (`prompts/movement_review_brief.md`) tie each fault they mark in `run/move_review/review_<group>.json` to an entry slug (`"kb": "MV-braking-touchdown"`) with `status` `seen` | `not_seen` | `not_visible`, times and a confidence. They look for the items in **What to check on film**.
- The report writer (`prompts/movement_report.md`) cites entries by slug, takes the mechanism from **Why it happens**, and copies cue, drill and success measure into the page and `plan.json` only when the session data or the review shows the symptom. A fault that is `not_visible` is written as "not filmed yet / hypothesis", never as seen.
- Field names refer to `run/gait/<id>.json` (metrics version in `metrics_version`). Per step: `trunk_lean` (hip-to-shoulder line vs vertical, degrees, + = forward), `shin` (knee-to-ankle vs vertical at touchdown, + = knee ahead of ankle), `touchdown_ahead` (ankle ahead of hip at touchdown, in leg lengths, + = foot ahead of hip), `knee_lift` (peak thigh angle from vertical in the swing before the touchdown), `heel_recovery` (peak ankle height above the floor in swing, leg lengths), `step_len` (leg lengths), `step_time` (s), `contact_s` (s, only at >= 100 fps, else null). Per clip: `n_steps`, `cadence_spm`, and per key `mean`, `sd`, `first3`. Layup: `takeoff_t`, `takeoff_foot`, `last3_len`, `penultimate_ratio` (penultimate step length / the step before it), `hip_drop` (leg lengths), `takeoff_knee`, `takeoff_trunk`, `takeoff_ahead` (leg lengths), `landing_knee_min`. Dribble: `bounces`, `bounces_per_10m` (null without a court scale), `ball_top_vs_hip` (ball peak height / hip height).
- Missing is "unknown", never zero. Write pose numbers as "about". Compare numbers only between clips with the same camera spot, the same action and the same `metrics_version`.

2D pose limits (state them on the page when they matter):
- Sagittal angles (`trunk_lean`, `shin`, `knee_lift`, knee angles, `touchdown_ahead`, `step_len`) are valid only from a side view (`view: side`), camera roughly perpendicular to the run. Front or behind views give knee-in / knee-out (valgus) and arm crossing only.
- Game camera (`view: game`) is review-only: panning, oblique, players about 50 px tall. The reviewer may count steps and dribbles and judge gross posture; no metric is computed from it.
- Reliability (from the research): trunk lean, step count, rough cadence and arm swing are reliable enough; shin angle, knee angle at toe-off and thigh separation need a manual frame check (ankle keypoints are the noisiest, about 7° error even in walking); `touchdown_ahead` is the hip keypoint, not the centre of mass, so it is an approximation; contact time needs >= 100 fps and an eye check (Stenum et al. 2021, PLoS Comput Biol, doi:10.1371/journal.pcbi.1008935; Needham et al. 2021, Sensors, https://pmc.ncbi.nlm.nih.gov/articles/PMC8074772/).
- Never infer which muscle does the work, or the force direction, from 2D keypoints. "Calf-driven", "glute-driven" and "braking force" are models from the literature linked to a kinematic sign; say "consistent with", not "shows".
- A sprint-gait fault that has not been filmed from the side at speed is a hypothesis to test on the re-shoot, not a finding.

Evidence levels used in each entry:
- **strong**: systematic review / meta-analysis or several consistent controlled studies.
- **moderate**: observational or lab studies (often trained sprinters, track jumpers or junior players, not adult rec players), or a single controlled trial.
- **expert opinion**: coaching manuals and coaching websites.
- **our rule**: our own threshold, translation or drill dose; the sources support the principle, not the number.

Trial values: every **Success measure** number is our trial value unless cited. Re-set it from what the player actually manages after each session. "(our rule)" marks our own choices; present them to the player as our choice, not as "the research says". "unverified" marks a number the research could not check against a primary source.

Sources: paraphrased from the research notes `<media root>/players/<player>/movement/research/sprint_mechanics.md` and `basketball_movement.md` (not in the repo) and from `prompts/skill_kb.md`. Studies are cited by author, year and DOI or URL. Related skill-KB entries are cross-referenced by slug instead of repeated: `KB-deceleration-landing`, `KB-repeated-sprint-cod`, `KB-strength-power`, `KB-warm-up-mobility`, `KB-recovery-weekly-load`, `KB-layup-footwork-weak-hand`, `KB-ball-handling`. Fuel and recovery details are in `prompts/fuel_recovery_kb.md`.

Context for every entry: basketball speed is mostly short. Elite U19 sprints last about 2.1 s on average, with a change of activity about every 2 s; sprinting is about 5.3 % of live time (Ben Abdelkrim et al. 2007, BJSM, https://pmc.ncbi.nlm.nih.gov/articles/PMC2658931). In basketball, high-intensity decelerations (about 3.2-4.5 per min) outnumber high-intensity accelerations (about 0.8-1.5 per min) (Harper et al. 2022, Sports Med, https://pmc.ncbi.nlm.nih.gov/articles/PMC9474351/). Experienced non-elite players ran only about 3 % of distance above 18 km/h at about 90 % HRmax (Puente et al. 2017, JSCR, https://repositorio.ucjc.edu/handle/20.500.12020/415). So the first 3-10 m, the stop and the re-start matter most; a 28 m full-court push is his longest effort (our rule, from these data).

---

## Sprinting

### MV-accel-posture

**Symptom (observable):** In the first steps of a sprint the trunk is upright: `trunk_lean` `first3` clearly below the accel band (see Reference values), or the reviewer notes "upright from step 1", "stands up", or "bends at the waist with hips behind" (a hinge, not a lean). Game camera: upright first 2-3 steps on transition starts.

**Why it happens:**
- In acceleration, the direction of the push matters more than its size: the horizontal share of ground force predicted 100 m performance, total force did not (Morin et al. 2011).
- Body lean at toe-off sets that direction (r = 0.93 between lean and force orientation; Kugler & Janshen 2010). An upright body pushes mostly upward, which feels like effort without going anywhere ("heavy").
- Distance running trains the opposite: economy favours low vertical oscillation and an upright body (Moore 2016). The habit carries into sprints (see MV-distance-habits).
- Bending at the waist is not lean: the force line still runs through hips that sit behind the feet (expert opinion).

**What to check on film:** Side phone, 120-240 fps: hip-to-shoulder line at the first three touchdowns and toe-offs; is the whole body leaning from the ankles (straight line head to heel) or only the upper body folding? Does the lean rise gradually over about 10 steps? Game camera: on transition starts, is the first step forward and low or up and tall?

**Cue:** "Lean from the ankles like a falling plank; push the ground away behind you." / 中文："从脚踝整体前倾，像一块木板倒下；把地面往身后推。" If folding at the waist: "Long line from head to heel; hips stay tall." / "头到脚跟一条直线，髋部别塌、别撅。"

**Drill:** Wall drill and falling starts (expert opinion; dose our rule). Wall drill: hands on a wall, body straight at the acceleration angle, single leg exchanges, 3 x 5 per leg. Falling start into 3 steps 4 x 3, then 6 x 10 m falling or 2-point starts at about 85 % effort, walk-back rest >= 2 min. Progression: weeks 3-4 heavy sled 5 x 15 m (load that slows him about 30-50 %), 3 min rest, then 4 x 15 m unresisted at about 90 %; weeks 5-6 hill sprints (about 5-8 % slope) 4 x 15 m. Weekly volume: 1 acceleration session, 100-300 m of sprinting at the most (Haugen et al. 2019), start at the low end.

**Success measure:** `trunk_lean` `first3` inside the accel band on 2 of 3 filmed 20 m sprints, and the lean visibly rising over steps 1-10 (our rule). 10 m time faster than the week-0 test.

**Source:** Morin, Edouard & Samozino 2011, MSSE 43:1680, doi:10.1249/MSS.0b013e318216ea37 (force orientation "seems more important to performance than its amount"); Kugler & Janshen 2010, J Biomech 43:343, doi:10.1016/j.jbiomech.2009.07.041 (lean vs force orientation r = 0.93; acceleration needs "optimal, not maximal" force); King et al. 2023, J Sports Sci, doi:10.1080/02640414.2023.2172797 (trunk 34 ± 8° at touchdown and 44 ± 8° at toe-off from horizontal, steps 1-4, collegiate sprinters of 1.73 m; within trained sprinters trunk angle itself did not correlate with force ratio); Nagahara et al. 2014, Biol Open, https://pmc.ncbi.nlm.nih.gov/articles/PMC4133722 (trunk rises to about 76° from horizontal by step ~25); Moore 2016, Sports Med, doi:10.1007/s40279-016-0474-4; Haugen et al. 2019, Sports Med Open, https://pmc.ncbi.nlm.nih.gov/articles/PMC6872694/ (acceleration reps 10-50 m, rest 2-7 min, 100-300 m per session, 48 h between high-intensity sessions); Morin et al. 2017, IJSPP, https://pubmed.ncbi.nlm.nih.gov/27834560/ (heavy sled pilot in amateur soccer players: moderate 5 m gain, better force orientation). Wall drills, falling starts and hill sprints: no controlled trials found (expert opinion).

**Evidence level:** moderate (lean and force orientation, lab studies); expert opinion (drills); our rule (doses, band translation).

### MV-braking-touchdown

**Symptom (observable):** The foot lands well ahead of the hip with a vertical or back-tilted shin: `touchdown_ahead` positive and above the accel band in the first steps, `shin` near zero or negative; reviewer notes "reaching", "heel first far in front", "brakes every step". At speed: foot far ahead with a straight knee.

**Why it happens:**
- Landing further ahead of the hip raises braking force; landing further ahead of the knee raises impact peaks (Lieberman et al. 2015, jogging).
- In sprint acceleration a larger touchdown distance went with more braking impulse, and at 16 m propulsive impulse explained 57 % of speed variance vs 7 % for braking (Hunter et al. 2005).
- Trained sprinters land behind the hip on steps 1-2 and only slightly ahead after (King et al. 2023). A jogging stride that "reaches" for ground stops the body on every step, which costs speed and loads the knee (see MV-knee-load).
- The variables that matter are distance ahead of the hip and shin angle, more than which part of the foot lands first: a heel landing under the body is a different case (Lieberman et al. 2015; King et al. 2023).

**What to check on film:** Side phone, 240 fps preferred (a touchdown angle needs a frame within about 4 ms of contact): at the touchdown frame, where is the ankle relative to the hip, is the shin tilted forward, is the foot moving back at landing ("active") or still swinging forward? Check `touchdown_ahead` by eye on the key-frame sheet (keypoint value is an approximation). Game camera: not visible; mark `not_visible`.

**Cue:** "Step down under your hips, not out in front." / 中文："脚落在髋部正下方，不要往前伸。" Shin: "Shins forward, punch the knee ahead." / "小腿前倾，膝盖往前送。"

**Drill:** Sled or hill starts plus wall drill (as MV-accel-posture); they force a behind-the-hip contact (our rule, consistent with Kugler & Janshen 2010). Add a 3-step "push-push-push" drill from a falling start: 6 x 3 steps, walk back. For steady running (10 km): raise step rate 5-10 % at the same pace for a part of easy runs (Heiderscheit et al. 2011), e.g. 2 x 5 min with a metronome (our rule).

**Success measure:** `touchdown_ahead` `first3` at or below about zero on the first step and inside the accel band over steps 1-4, on 2 of 3 filmed sprints (our rule, from King et al. 2023).

**Source:** Lieberman et al. 2015, J Exp Biol, doi:10.1242/jeb.125500 (each +5 strides/min moved the landing 5.9 % closer to the hip; landing ahead of the hip went with larger braking forces, ahead of the knee with higher impact peaks; optimum about 170 steps/min with a fairly vertical tibia, in jogging); Hunter, Marshall & McNair 2005, J Appl Biomech 21:31, doi:10.1123/jab.21.1.31; King et al. 2023 (touchdown distance / trochanter height over steps 1-4: -0.15, -0.05, +0.02, +0.07; shank 55 ± 3° from horizontal; more negative touchdown distance with higher force ratio, r = -0.672; more forward shank, r = -0.764); Heiderscheit et al. 2011, MSSE 43:296, doi:10.1249/MSS.0b013e3181ebedf4 (+5-10 % step rate reduced knee energy absorption in 45 recreational runners).

**Evidence level:** moderate.

### MV-ankle-dominant-push

**Symptom (observable):** Reviewer notes "runs on the toes", "pushes with the ankle only", "short push, knee and hip not extending at toe-off", "springy but going nowhere"; calf soreness after games and especially after treadmill runs (player report). No 2D metric shows which muscle works; this entry is triggered by film notes plus the soreness pattern.

**Why it happens:**
- Up to about 7 m/s the soleus and gastrocnemius supply most of the support force; above that, the hip muscles (iliopsoas, gluteus maximus, hamstrings) drive faster leg swing (Dorn et al. 2012, simulation). Ankle work plateaus above about 5 m/s while hip-extensor and knee-flexor load keeps rising (Schache et al. 2011).
- Honest caveat: game sprints of rec and sub-elite guards are often below 7 m/s (sub-elite guards about 6.6 m/s in one game; Petway et al. 2020). So heavy calf work in his sprints is partly normal, not only a technique fault.
- Forefoot landing raises plantarflexor moment and Achilles force (Kulmala et al. 2013). On a motorised treadmill foot strike was about 9.8° flatter and the ankle moment higher than overground (Van Hooren et al. 2020, low-GRADE evidence), which fits "calves worst on the treadmill" (likely, not measured on him).
- An incomplete push (knee and hip not extending at toe-off) leaves the ankle to finish the job (our synthesis; distance runners showed less knee extension at toe-off than sprinters at max speed, Bushnell & Hunter 2007).

**What to check on film:** Side phone, 120-240 fps: knee angle at the last ground frame (sprinters about 158° in steps 1-4, not locked straight), does the hip extend behind the body at toe-off, does the heel stay high through the whole contact? Treadmill clip vs overground clip, if both exist. Game camera: `not_visible`.

**Cue:** "Push with the whole leg from the hip; ankles stay springy, not pointing." / 中文："从髋发力用整条腿推；脚踝保持弹性，别刻意踮脚尖蹬。" Or: "Finish the push; push the track back till the foot leaves." / "推到底，脚离地前把地面推完。"

**Drill:** Hip-extension strength plus sled pushes (dose our rule). Hip thrust 3 x 8 and Romanian deadlift 3 x 8 at RPE 7, twice a week, progress load (see KB-strength-power); heavy sled 5 x 15 m from week 3 (as MV-accel-posture). Keep calf capacity work separate (MV-calf-capacity). Move part of easy running from the treadmill to overground while calves are sore (our rule, from Van Hooren et al. 2020).

**Success measure:** Knee at toe-off visibly closer to the sprinter value on the key-frame sheet in 2 of 3 sprints; calf soreness the morning after a game <= 3/10 (our rule, see Pain and safety gate).

**Source:** Dorn, Schache & Pandy 2012, J Exp Biol 215:1944, doi:10.1242/jeb.064527; Schache et al. 2011, MSSE 43:1260, doi:10.1249/MSS.0b013e3182084929; Lieberman et al. 2006, J Exp Biol, doi:10.1242/jeb.02255 (gluteus maximus nearly silent in walking, much more active in running); Petway et al. 2020, PLoS One, https://pmc.ncbi.nlm.nih.gov/articles/PMC7058381/; Kulmala et al. 2013, MSSE, https://pubmed.ncbi.nlm.nih.gov/23748735/; Van Hooren et al. 2020, Sports Med 50:785, doi:10.1007/s40279-019-01237-z; Bushnell & Hunter 2007, Sports Biomech 6:261, doi:10.1080/14763140701489728; King et al. 2023 (knee 158 ± 5° at toe-off); Contreras et al. 2017, JSCR, https://pubmed.ncbi.nlm.nih.gov/27253835/ (hip thrust "potentially beneficial" for 10 and 20 m sprint vs front squat in adolescent males). The "triceps surae up to 12x body weight" figure is unverified (secondary source) and not used.

**Evidence level:** moderate (speed-dependent muscle roles, simulation and lab data); our rule (link to his soreness, drill doses).

### MV-short-accel-stride

**Symptom (observable):** Over a 20 m sprint the steps stay short and choppy: `step_len` does not grow after about step 5, `n_steps` per 20 m high for his height, flight phases tiny or none (`contact_s` long when measured); reviewer notes "shuffling", "no flight", "same short step all the way". Game camera: many short steps per court length.

**Why it happens:**
- Short steps are normal for steps 1-4; step frequency stops rising at about step 4 and speed then comes mostly from longer steps up to about step 14 (Nagahara et al. 2014).
- Step length and step rate trade off; take-off vertical velocity drives most of the trade (Hunter et al. 2004). "High frequency and long stride" is the outcome, not an instruction; the controllable inputs are push direction, push completeness and fast foot return (our rule).
- A short stride with no flight usually means a small, incomplete push (MV-ankle-dominant-push) or a jogging stride kept at sprint effort (MV-distance-habits).

**What to check on film:** Side phone with 1 m tape marks: count steps over 0-10 m and 10-20 m, step length growth after step 5, visible flight between contacts, contact time at 120-240 fps. Game camera: step count over a known court distance (rough).

**Cue:** "Push long, the steps will open by themselves." / 中文："推得远，步幅自然会打开。" (our rule) For early steps: "Push the ground back, stay low and lean for three steps." / "前三步向后蹬地，身体前倾压低。"

**Drill:** Cone ladder 5-10-15 m (sprint to each cone, walk back), 2 rounds; mini-hurdles (low, about 22 cm) 4 x 20 m from week 3, wicket runs 4-6 x 20-30 m from week 5 (spacing from a coaching table, expert opinion). Plyometrics with horizontal bias (broad jump with stick, bounding 3-5 contacts per rep), counted in the weekly plyo volume: start about 60-80 contacts per session and build toward 80-100 (Potach & Chu tiers, expert opinion; sprint gains more likely above 80 jumps per session, de Villarreal et al. 2012). Twice a week on non-consecutive days.

**Success measure:** Fewer steps over 10-20 m at the same or faster time than week 0 (our rule); `step_len` rising from step 5 on the filmed sprints.

**Source:** Nagahara et al. 2014, Biol Open, https://pmc.ncbi.nlm.nih.gov/articles/PMC4133722 (breakpoints at step 4.4 and 14.1; boundaries approximate, Ettema et al. 2016 questioned them); Hunter, Marshall & McNair 2004, MSSE, https://pubmed.ncbi.nlm.nih.gov/14767249/; mini-hurdle acute study 2016, SpringerPlus, https://pmc.ncbi.nlm.nih.gov/articles/PMC4963333/ (10 x 10 mini-hurdles raised max velocity 3.2 % and step frequency 3.3 % straight after; acute only, no long-term wicket trial found); de Villarreal, Requena & Cronin 2012, JSCR 26:575, doi:10.1519/JSC.0b013e318220fd03; Ramirez-Campillo et al. 2022, J Sport Health Sci, https://pmc.ncbi.nlm.nih.gov/articles/PMC9729929/ (plyometrics in basketball: sprint > 10 m g about 0.92, CMJ g about 0.88); plyo dose tiers via ISBS review, https://ojs.ub.uni-konstanz.de/cpa/article/view/6015/5496 (80-100 contacts per session for beginners; no research has set the optimal volume).

**Evidence level:** moderate (step pattern); strong (plyometrics improve sprint and jump in basketball players, meta-analysis); expert opinion (wickets, dose tiers).

### MV-backside-mechanics

**Symptom (observable):** "Dragging the lower leg": after toe-off the heel kicks up behind the body, the knee comes through late and low, then the shin swings out ahead so the foot reaches ("casting"); `knee_lift` low, `heel_recovery` high but behind the hip, `touchdown_ahead` positive at speed. Reviewer notes "heel flicks behind", "knee late".

**Why it happens:**
- Coaching models call this backside mechanics: most of the leg cycle happens behind the body (expert opinion).
- At max speed distance runners differed from sprinters in recovery-knee position at touchdown and knee extension at toe-off, and looked like non-runners (Bushnell & Hunter 2007).
- Faster men showed more front-side thigh motion and 28 % faster thigh retraction before touchdown (Clark et al. 2020), but in another sprinter group front- and back-side variables did not predict top speed (Haugen et al. 2018). Net: a plausible description of a distance-style swing at speed; its effect on speed is debated.
- It matters most at top speed, which in basketball happens only on long pushes (our rule).

**What to check on film:** Side phone, 120-240 fps, at the flying part of a 20-30 m sprint: swing heel path (under the hip or behind), thigh angle at max knee lift, swing knee position at the opposite foot's toe-off (thigh separation), thigh still moving forward at touchdown? Game camera: `not_visible`.

**Cue:** "Step over the opposite knee; heel comes up under the hip, not behind." / 中文："脚跨过另一侧膝盖；脚跟在髋下收回，不往后甩。" Or: "Knee races knee." / "两膝赛跑：离地马上把大腿往前摆。"

**Drill:** A-march 2 x 15 m, A-skip 3 x 15 m, then B-skip 3 x 15 m from week 3, as position teaching in the warm-up only (expert opinion: ALTIS; no training study shows these drills make people faster). Then the position at speed: mini-hurdles or wickets (MV-short-accel-stride) and 3 x 30 m build-ups to about 80 %.

**Success measure:** On the flying part of a filmed sprint, the swing heel recovers under the hip and the knee is ahead of the stance hip at toe-off in most visible strides (reviewer judgement, our rule). No band for `heel_recovery` or `knee_lift` (no normative values found).

**Source:** Bushnell & Hunter 2007, Sports Biomech, doi:10.1080/14763140701489728; Clark, Meng & Stearne 2020, Biol Open, https://pmc.ncbi.nlm.nih.gov/articles/PMC7595692; Haugen et al. 2018, IJSPP 13:420, doi:10.1123/ijspp.2016-0812; ALTIS on A-drills, https://altis.world/center-news/stop-doing-a-drills-the-full-context-behind-stu-mcmillans-comment/ (hip flexion is rarely the limiter; drills fit less coordinated athletes as teaching tools); Matijašević et al. 2025, IJES, https://digitalcommons.wku.edu/ijes/vol18/iss8/20 (B-skip quality correlated moderately with short-sprint times, correlational). Normative thigh separation, heel recovery and knee-drive values: none found (unverified).

**Evidence level:** moderate but conflicting (mechanics); expert opinion (drills).

### MV-arm-action

**Symptom (observable):** Arms cross the body, swing small, or stay bent and stiff; shoulders rise; reviewer notes "arms across", "no arm drive", "tense shoulders". Front or behind view shows crossing best; side view shows range.

**Why it happens:**
- Coaching models want a strong front-back arm drive with elbows near 90° (expert opinion). No sprint-performance study of arm action was located.
- Tension in the face and shoulders is a coaching flag for effort that does not turn into speed (expert opinion).

**What to check on film:** Side phone: shoulder-elbow path from cheek height to behind the hip; front or behind view: hands crossing the midline. Game camera: gross only.

**Cue:** "Elbows drive back, hands cheek to hip." / 中文："肘往后打，手从脸颊摆到髋部。" Tension: "Fast but loose: jaw and shoulders relaxed." / "快但放松：下巴和肩膀松开。"

**Drill:** Seated or kneeling arm swings 3 x 10 s fast, then 2 x 20 m build-ups with the cue (our rule). Keep it inside the warm-up.

**Success measure:** No midline crossing on a front-view clip; reviewer sees full front-back swing on 2 of 3 sprints (our rule).

**Source:** sprint_mechanics research notes, marker table (coaching models, no sprint-performance study located); cues from the same notes.

**Evidence level:** expert opinion.

---

## Basketball transitions

### MV-transition-head-up

**Symptom (observable):** On transition the player waits for the outlet before running, or runs with the head down and then turns the whole trunk to look; reviewer notes "late start", "watches the ball", "turns shoulders to look, slows down". Game camera is the main source here.

**Why it happens:**
- FIBA coaching material: the second guard sprints to half court as soon as the rebound is secure, without watching the ball; waiting for the outlet is a common fault (expert opinion).
- No study measured how head-turning changes sprint kinematics in basketball. Turning the trunk to look likely costs lean and speed (our rule).
- "Head down" is not a separate sprint action: in sprinters the head follows the trunk to about neutral (head angle about 91° at top speed, Nagahara et al. 2014). So head up and looking is compatible with a good sprint.

**What to check on film:** Game camera: time from defensive rebound to his first sprint step; head and shoulder orientation during the push; does he slow when he looks? Side phone: head angle relative to the trunk during the eyes-up drill.

**Cue:** "Go on the rebound, not on the outlet." / 中文："抢到篮板就跑，不要等传球。" Looking: "Turn your head, not your hips." / "转头看，髋不要转。"

**Drill:** Eyes-up push: a partner at half court flashes fingers or a colour; call it out while sprinting or pushing the ball, 6 x full court, full rest (our rule). Check over the inside shoulder every 2-3 strides with hips square (our rule).

**Success measure:** Reviewer counts his transition starts in the next game: first step on the rebound, not the outlet, on most possessions (our rule); called-out flashes correct on 5 of 6 reps without visible slowing.

**Source:** FIBA WABC coaching manual, https://wabc.fiba.com/?p=510; Coach's Clipboard transition offense, https://www.coachesclipboard.net/TransitionOffense.html (fill lanes fast); Nagahara et al. 2014 (head angle); defender gaze study, https://lida.sport-iat.de/dbb/Record/4081965 (experts fixate the opponent's body, consistent with "eyes up").

**Evidence level:** expert opinion; our rule (drill).

### MV-speed-dribble

**Symptom (observable):** The full-court push has many low "pound" dribbles: `bounces_per_10m` above the band, `ball_top_vs_hip` well below 1 (wrist below the hip on every step), stride shorter with the ball than without; reviewer notes "ball at the hip every step", "looks at the ball", "extra gather dribble before the layup". Large dribble deficit in the re-test.

**Why it happens:**
- Coaching sources: push the ball out ahead, let it rise to about waist height, and run into it; advanced school players cover the court in about 3-4 dribbles (expert opinion).
- A pound dribble at every step forces the ball hand to work at the hip, shortens the stride and tilts the trunk sideways (our rule; no study measured stride with vs without a ball in adults).
- Dribble speed has two independent parts: sprint time correlated with 20 m dribble time (R = 0.64-0.77), but the dribble deficit (dribble time minus sprint time) was almost unrelated to sprint speed (R = 0.01-0.15) (Scanlan et al. 2018). So test and train both.
- The non-dominant hand costs more (children's data: deficit about 0.7 s dominant vs 1.2 s non-dominant over 20 m; Conte et al. 2020). Adult norms were not found.

**What to check on film:** Side phone: dribbles per court length and per 10 m, ball peak height vs hip, ball bouncing ahead of the front foot, stride with vs without the ball, head up. Game camera: dribble count per push and extra dribbles before the gather.

**Cue:** "Throw it ahead and chase it." / 中文："把球推到前面，追着球跑。" Height: "Waist-high, out in front." / "球弹到腰，放在身前。"

**Drill:** Full-court 4-dribble layup: baseline to the far rim in <= 5 dribbles, layup without an extra gather dribble, alternate hands, 3 x 4 reps, 60-90 s rest (our rule; dribble count from Breakthrough Basketball). Speed dribble with stop-and-go ("Hot Griddle", Special Olympics) 4 x full court. Left-hand length-of-court to left-hand layup, 3 min (Coach's Clipboard). See KB-ball-handling for stationary handling.

**Success measure:** Full court in 4-5 dribbles with either hand at game speed (our rule); dribble deficit smaller than at week 0 for each hand; weak-hand deficit closer to the strong hand.

**Source:** Coach's Clipboard dribbling, https://www.coachesclipboard.net/Dribbling.html (push ahead, about waist height, never faster than you can control); Breakthrough Basketball, https://www.breakthroughbasketball.com/drills/1on1speeddribble (3-4 dribbles over the court for advanced middle/high-school players); Scanlan et al. 2018, J Sports Sci 36(22):2596, doi:10.1080/02640414.2018.1470217 (10 semi-professional players); Conte et al. 2020, Biol Sport, https://pmc.ncbi.nlm.nih.gov/articles/PMC7433332 (81 U9-U10 players, direction only); Special Olympics basketball drills 2024, https://media.specialolympics.org/resources/sports-essentials/coaching-guides/Sports-Essentials-Basketball-Drills-2024-English.pdf; Coach's Clipboard full-court drills, https://www.coachesclipboard.net/FullCourtDribblingDrills.html.

**Evidence level:** moderate (dribble deficit is a separate quality); expert opinion (technique); our rule (stride effect, targets).

---

## Layup

### MV-layup-penultimate

**Symptom (observable):** On the approach the step before take-off is not the long one: `penultimate_ratio` below 1, `hip_drop` about zero (jumping from tall) or very large (sitting), extra short steps or a re-gather dribble before the take-off (`last3_len` shows stutter); reviewer notes "gathers at the block", "stutter steps", "no long step", "jumps forward not up".

**Why it happens:**
- In a two-step layup the long first step after the gather is the penultimate step and the short second step is the take-off (coaching sources and track jumping agree on this).
- Track jumping: arrive at take-off with a lowered centre of mass to lengthen the push and raise vertical velocity, and lower it without much speed loss (high-jump and long-jump studies, track athletes, not basketball). Too much drop is bad too: the plant leg cannot get in front of the body (javelin coaching, expert opinion).
- An upright trunk and short steps into the gather give high hips at the plant, so the take-off becomes a forward lean-and-reach (our rule; not tested in a layup study).
- FIBA allows a gather step ("step 0") plus two steps, which gives room to gather earlier, outside the lane (rule interpretation).

**What to check on film:** Side phone or 45°, 120-240 fps: where does he gather (cone distance, lane line), length of the last three steps, hip height on the penultimate contact vs the strides before, number of steps from last dribble to take-off. Game camera: gather point and step count only (rough).

**Cue:** "Gather early, outside the lane." / 中文："提早收球，在禁区外。" Then: "Long step, sit a little, then pop." / "倒数第二步迈大、稍微沉，然后弹起。"

**Drill:** Gather-distance ladder: cones just inside the 3-point line, mid-lane and at the block; gather at the cone, two steps, finish; 3 cones x 2 sides x 4 reps (our rule). Long-low-up without ball: walking, jogging, then running approach with a long penultimate step, slightly lower hips, quick plant, knee drive; 3 x 4 each side (our rule). Then 6 game-speed layups each side. Pair with the footwork in KB-layup-footwork-weak-hand.

**Success measure:** `penultimate_ratio` >= 1.0 and no re-gather dribble on at least 8 of 12 filmed layups (our rule); one-leg approach jump reach higher than week 0 (re-test).

**Source:** ULPGC elite high-jump kinematics, https://accedacris.ulpgc.es/bitstream/10553/106692/2/Kinematic%20analysis%20of%20the%20final%20stride%20approach%20in%20Spanish%20elite%20high%20jumpers%20%281%29.pdf; ISBS take-off study, https://ojs.ub.uni-konstanz.de/cpa/article/view/2950/2797 (lower the centre of gravity without significant loss of running speed); ISBS long jump case study, https://ojs.ub.uni-konstanz.de/cpa/article/view/1753 (centre of mass dropped about 8 cm in the penultimate flight of a world-record jump); Just Fly Sports, https://www.just-fly-sports.com/the-penultimate-step/ (too much drop); Basketball for Coaches, https://www.basketballforcoaches.com/?p=7401 (long first step, short explosive second step; gathering too close to the rim is a common error); FIBA Tough Calls, https://www.fiba.basketball/en/news/bcl-21-22-news-tough-calls-play-ins-week-2 (step 0 + two steps). The online claim that the penultimate step makes "up to 60 % of vertical velocity" has no traceable primary source and is not used.

**Evidence level:** moderate by analogy (track jumping; no basketball layup study of penultimate length or hip drop found); expert opinion (layup coaching); our rule (drills, thresholds).

### MV-one-foot-takeoff

**Symptom (observable):** The take-off does not turn speed into height: plant foot far ahead with a locked knee (`takeoff_ahead` large, `takeoff_knee` near straight), or plant under the body with no braking and a long forward drift into the defender; free knee low (`knee_lift` on the take-off step well short of horizontal); trunk leaning forward at take-off (`takeoff_trunk` large); reviewer notes "jumps long", "no knee drive", "drifts under the rim".

**Why it happens:**
- Converting speed to height is a trade: horizontal velocity is lost in exchange for vertical velocity on the plant (triple jump "conversion coefficient", Yu 1999; in a world-record long jump, more than 2 m/s horizontal for about 4.3 m/s vertical).
- A faster approach gave higher one-leg running jumps in basketball players and active men (Tai et al. 2016; Tai et al. 2026); the authors claim no optimal speed. So arriving slow (after heel-first braking steps, MV-braking-touchdown) leaves a near-standing one-leg jump.
- One-leg vs two-leg: the two-leg running jump went higher; the one-leg jump used stiffer legs and larger knee and hip impulses (volleyball players, Tai et al. 2018). One foot keeps speed and is quicker on the break; two feet (jump stop, power layup) give more height and balance from a slower approach (our rule).
- The free knee drive adds height (expert opinion).

**What to check on film:** Side phone, 120-240 fps: plant foot vs hip at take-off, knee angle at plant (flexed and firm vs locked), free thigh height at take-off, take-off to landing distance (drift). Which foot (inside / outside) and whether both are used. Game camera: drift and take-off foot only.

**Cue:** "Plant fast, knee to the sky." / 中文："踩地要快，摆动腿膝盖向上顶。" Contact: "Go up, not out." / "往上跳，不要往前冲。"

**Drill:** 2-step approach one-leg jumps to touch a backboard or wall mark, 3 x 4 per leg (medium-intensity plyo, counted in the weekly volume). Both-feet menu: inside-foot, outside-foot, jump-stop power layup, euro step, 3 reps each side at full speed (Coaches Insider; Human Kinetics). Add contact finishes from KB-finishing-contact.

**Success measure:** Plant slightly ahead of the hips with a flexed knee and the free thigh near horizontal on 8 of 12 filmed layups (reviewer, our rule); one-leg approach reach clearly above the CMJ reach (if they are about equal he is not using the approach, our rule).

**Source:** Yu 1999, https://lida.sport-iat.de/twm/Record/4002284?lng=en; ISBS long jump case study, https://ojs.ub.uni-konstanz.de/cpa/article/view/1753; Tai et al. 2016, https://lida.sport-iat.de/dbb/Record/4041318?lng=en (12 basketball players, fast approach and 9 m run-up gave higher one-leg jumps); Tai et al. 2026, Life 16:160, https://pmc.ncbi.nlm.nih.gov/articles/PMC12843030/ (25 active men, approaches > 4 m/s gave higher jumps and shorter contacts); Tai, Wang & Peng 2018, J Hum Kinet 64:71, https://johk.pl/?p=4761; youth coaching handout, https://websites.mygameday.app/get_file.cgi?id=388052 (knee drive); Coaches Insider, https://coachesinsider.com/mens-basketball/outside-foot-layup-drill/ (land low on the take-off step; outside-foot layup); fatigue layup study, https://sponet.de/sponet/Record/4026565?lng=en (fatigue changed knee flexion at take-off contact in 7 recreational men).

**Evidence level:** moderate (approach speed and one- vs two-leg jumps, small lab samples); expert opinion (layup technique).

---

## Stopping and landing

### MV-decel-stop

**Symptom (observable):** At the end of a push the player stops in one big plant or coasts: few braking steps, upright trunk, straight knee on the final plant, always the same leg; reviewer notes "one-step stop", "leans back", "slides past the line", "coasts then stops". Hip speed curve has a long flat coast.

**Why it happens:**
- Braking is a multi-step skill: from a 20 m approach about 5.4 braking steps for a 90° cut and 6.3 for 180°; from 4 m about 2.7 and 3.3 (Harper et al. 2022).
- Early-stance braking forces reach about 2.7 times those of the first acceleration steps, and intense decelerations carry about 41 % more mechanical load per metre (Harper et al. 2022).
- A lower, more posterior centre of mass and triple flexion lengthen braking time and point force horizontally; faster 505 performers showed more penultimate hip and knee flexion. Braking in the penultimate contact prepares cuts of 60° or more (Dos'Santos et al. 2019, abstract seen).
- Distance running never trains this: it uses long ground contacts at low force (our rule, from Harper et al. 2022).

**What to check on film:** Side phone: number of braking steps from push speed to stop, hip height and trunk angle during braking, final plant knee flexion, which leg plants. Game camera: braking step count and final plant leg (rough).

**Cue:** "Chop, chop, sit: brake in three steps." / 中文："碎步、碎步、坐：三步刹住。" Position: "Hips low and behind the feet." / "髋部压低，在脚后面。" Legs: "Stop on either leg." / "两条腿都要会刹车。"

**Drill:** Sprint-to-stick: 5 m sprint, stop in 3 steps, hold 2 s in an athletic stance; progress to 10 m and 15 m; alternate the final-plant leg; 6 reps (our rule). Accelerate-decelerate-reaccelerate: 10 m sprint, brake to a line within 3 m, backpedal 2 m, sprint 5 m, 4-6 reps (our rule). Jump-stop series: speed dribble, two-foot jump stop at the elbow, pivot, pass or shot. Progress by stopping from higher speed in a shorter distance (expert opinion). Do not always stop on the same leg (enforced-stopping study increased knee-flexor asymmetry).

**Success measure:** 2-4 progressive braking steps and alternating plant legs on all filmed sprint-to-stop reps (our rule, from Harper et al. 2022); no knee pain above the gate the next morning.

**Source:** Harper et al. 2022, Sports Med 52:2321, doi:10.1007/s40279-022-01693-0, https://pmc.ncbi.nlm.nih.gov/articles/PMC9474351/; Dos'Santos et al. 2019, Strength Cond J 41(1):87, doi:10.1519/SSC.0000000000000395 (abstract seen); enforced-stopping trial, https://lida.sport-iat.de/ta/Record/4032123?lng=en; AUT rugby thesis, https://openrepository.aut.ac.nz/handle/10292/12159 (progression principle). See also KB-deceleration-landing and KB-repeated-sprint-cod.

**Evidence level:** moderate (review of lab and match data); our rule (drills, step targets).

### MV-landing

**Symptom (observable):** After layups and contested finishes the player lands stiff, on one foot, or with the knee falling inward: `landing_knee_min` near straight (small knee flexion), reviewer notes "stiff landing", "lands on one leg", "knee in" (valgus needs a front or behind view).

**Why it happens:**
- In 39 basketball ACL cases most were non-contact or indirect contact, with small knee flexion at initial contact (men about 9°), often after an opponent perturbed the movement (Krosshaug et al. 2007; summary read, full text not).
- Small knee flexion at contact is linked to higher non-contact ACL risk; foot placement influences knee flexion in recreational players (landing study, search-record level).
- Layup take-off and landing load the heel and forefoot heavily (13 university players).
- The general landing mechanism, cues and the warm-up landing series are in `KB-deceleration-landing` (skill KB); this entry adds the layup-specific film check.

**What to check on film:** Side phone: knee and hip bend together at landing, one vs two feet after contact. Front or behind view: knee over toes, no inward collapse. Game camera: one- vs two-foot landings after contested finishes.

**Cue:** "Land soft on two, knees over toes." / 中文："双脚轻落地，膝盖对脚尖。"

**Drill:** Drop-to-stick: drop from a 30-40 cm box, land on two feet, stick 2 s, 3 x 4; progress to single leg after 2-3 weeks of clean reps (our rule). Stick landings from a 2-step approach 3 x 4. Plus the landing series in KB-deceleration-landing, 5-10 min of the warm-up 2-3 times a week.

**Success measure:** Two-foot, soft landings with knees over toes on all reps of the last set (front-view clip) and on most contested finishes in game film (our rule).

**Source:** Krosshaug et al. 2007, AJSM, summary https://klokavskade.no/en/projects/mechanisms-of-acl-injury-inbasketball-video-analysis-of-39-cases; landing study, https://pmc.ncbi.nlm.nih.gov/articles/PMC9778979; layup plantar loading, https://lida.sport-iat.de/ta/Record/4042406; chronic ankle instability layup study, https://pmc.ncbi.nlm.nih.gov/articles/PMC10618240/ (relevant if he has had ankle sprains); see KB-deceleration-landing for Donnell-Fink et al. 2015 (neuromuscular training: knee injury IRR 0.731) and Harper et al. 2022.

**Evidence level:** moderate (injury-mechanism video analysis; prevention meta-analysis in the skill KB); our rule (drill dose).

---

## Background and capacity

### MV-distance-habits

**Symptom (observable):** The sprint looks like his jog, only faster: upright, short self-selected stride, low knee lift, small push (several of MV-accel-posture, MV-short-accel-stride, MV-backside-mechanics seen together); player runs a lot of easy 10 km volume, sometimes on speed or strength days. Use this entry for the overall explanation, the specific entries for the fixes.

**Why it happens:**
- When collegiate distance runners sprinted, they differed from sprinters (hip angle, toe-off knee extension, stride length, contact time, recovery knee) and resembled non-runners: "as distance runners attempt to sprint, the desired adjustments do not necessarily occur" (Bushnell & Hunter 2007).
- Distance running is about economy (low vertical oscillation, self-selected stride; Moore 2016); acceleration is about pointing force forward (Kugler & Janshen 2010); top speed is about large vertical force in short contacts (Weyand et al. 2000).
- Endurance training frequency and duration correlated negatively with strength and power gains; power was blunted most (Wilson et al. 2012). The claim that running interferes more than cycling is unverified (secondary summaries only).
- His aerobic base is still useful: rec games run at about 90 % HRmax (Puente et al. 2017), and strength plus plyometric work improved running economy in trained runners (SMD -1.42; Balsalobre-Fernández et al. 2016), so sprint and strength work should not hurt his 10 km.

**What to check on film:** Side phone: one jog clip and one 20 m sprint from the same spot; compare `trunk_lean`, `step_len`, `knee_lift` and `cadence_spm`. If they barely differ, the jog pattern is carried into the sprint. Game camera: not enough; `not_visible` for gait detail.

**Cue:** "Sprinting is a different skill: lean, push, let it open." / 中文："冲刺是另一种技术：前倾、蹬地、让步幅打开。" (our rule)

**Drill:** No single drill; the fix is the sprint entries above. Planning (our rule): keep 10 km runs easy and separate them from speed or strength sessions by >= 6 h or a day; no long run the day before a game or a sprint session.

**Success measure:** Jog and sprint clips clearly differ in lean and step length at week 4 (our rule).

**Source:** Bushnell & Hunter 2007, Sports Biomech 6:261, doi:10.1080/14763140701489728; Moore 2016, Sports Med, doi:10.1007/s40279-016-0474-4; Weyand et al. 2000, J Appl Physiol 89:1991, doi:10.1152/jappl.2000.89.5.1991 (faster runners got higher step rate from shorter contacts, swing time did not differ); Wilson et al. 2012, JSCR 26:2293, doi:10.1519/JSC.0b013e31823a3e2d; Balsalobre-Fernández et al. 2016, JSCR 30:2361, doi:10.1519/JSC.0000000000001316; Puente et al. 2017; Costill et al. 1976, J Appl Physiol 40:149 (sprinters have more fast-twitch fibres; cross-sectional, cannot separate genes from training).

**Evidence level:** moderate (distance runners keep their pattern; one cross-sectional study); strong (endurance-power interference and economy benefits, meta-analyses).

### MV-calf-capacity

**Symptom (observable):** Player reports calves very sore after games and worst after treadmill runs; reviewer may note "on the toes the whole run". Calf strength screen below the bar (single-leg calf raise < 20 per leg).

**Why it happens:**
- The calves carry most support force up to about 7 m/s (Dorn et al. 2012); peak Achilles force rose about 19.5 % and loading rate 57.3 % from 3.3 to 5.6 m/s in endurance runners (Starbuck et al. 2021, abstract-level).
- Treadmill running: flatter foot strike and higher ankle moment than overground (Van Hooren et al. 2020, low-GRADE) (likely link to his treadmill soreness).
- Basketball adds many accelerations, jumps and stops on top; soreness also depends on volume and novelty, not only technique (our synthesis).
- A previous calf strain is itself a hamstring-strain risk factor (RR 1.5; Green et al. 2020).

**What to check on film:** Not a film fault. Side phone can show a heel that never touches during slow running. Use the strength screen and the pain gate.

**Cue:** "Ankles stiff and quiet, then let the hips do the speed." / 中文："脚踝稳而轻，速度交给髋。" (our rule) Pogo: "Hot ground, quick and stiff ankles." / "地面很烫，脚踝绷紧，一碰就弹起。"

**Drill:** Calf block twice a week (dose our rule): bent-knee (soleus) calf raise 3 x 12 and straight-knee calf raise 3 x 12, 3 s down; after 2 weeks heavier 3 x 8-10, then single-leg. Pogo jumps 3 x 15 s, quiet contacts (counts as low-intensity plyo); single-leg pogo 3 x 10 per leg from week 7. 60-90 s rest between sets (our rule).

**Success measure:** Single-leg calf raise 20 per leg (screening test, fiba-wabc-level2 p. 166 via skill KB) within 6 weeks (our rule for the time frame); calf soreness the morning after a game <= 3/10.

**Source:** Dorn et al. 2012; Starbuck et al. 2021, https://salford-repository.worktribe.com/output/1341565 (abstract-level); Van Hooren et al. 2020, doi:10.1007/s40279-019-01237-z; Green et al. 2020, BJSM 54:1081, doi:10.1136/bjsports-2019-100983; fiba-wabc-level2 p. 166 (screen, see KB-strength-power). No sprint-specific calf RCT was found for adult rec players.

**Evidence level:** moderate (mechanism); our rule (dose, link to his soreness).

### MV-knee-load

**Symptom (observable):** Knees ache after games (player report); film shows braking touchdowns (MV-braking-touchdown), one-step stops (MV-decel-stop) or stiff landings (MV-landing). Use this entry for the explanation and the strength work; the movement fixes live in those entries.

**Why it happens:**
- In basketball decelerations are the bigger knee load: hard braking steps about 58 N/kg vs 21 N/kg for the first acceleration steps (75 kg example), quadriceps activation about 161 % of maximal voluntary isometric contraction, and eccentric quadriceps strength is a main determinant of braking ability (Harper et al. 2022).
- Overstriding adds impact (Lieberman et al. 2015); a low step rate raises knee energy absorption (Heiderscheit et al. 2011).
- Likely picture for him (hypothesis to test on film and with a strength screen): a long-reaching stride that brakes on every step plus eccentric quads not prepared for game decelerations.

**What to check on film:** See MV-braking-touchdown, MV-decel-stop, MV-landing. Note the knee angle on final plants and landings.

**Cue:** "Stop in short choppy steps, hips low, chest over knees." / 中文："急停用小碎步，降低重心，胸口压在膝盖上方。"

**Drill:** Eccentric quad block twice a week (dose our rule): split squat with 3 s lowering 2-3 x 8 per leg, Spanish squat or reverse Nordic 3 x 8, single-leg RDL 3 x 8; snap-downs 3 x 5. Progress load when the last set feels easy (see KB-strength-power for load rules). Raise easy-run step rate 5-10 % (MV-braking-touchdown).

**Success measure:** Knee pain the morning after a game <= 3/10 and gone within 24 h for 3 games in a row (our rule, see the gate); split squat load up from week 0.

**Source:** Harper et al. 2022, https://pmc.ncbi.nlm.nih.gov/articles/PMC9474351/; Lieberman et al. 2015, doi:10.1242/jeb.125500; Heiderscheit et al. 2011, doi:10.1249/MSS.0b013e3181ebedf4; Harper & Kiely 2018 editorial, https://researchrepository.ul.ie/articles/journal_contribution/Damaging_nature_of_decelerations_do_we_adequately_prepare_players_/24024750 (few validated deceleration training recommendations).

**Evidence level:** moderate (load data); our rule (link to his pain, doses). Not a diagnosis.

### MV-hamstring-safety

**Symptom (observable):** Applies to every plan that adds maximal sprinting. Trigger extra caution on: any posterior-thigh "grab" or cramp, previous hamstring or calf strain (ask before starting), sprints planned late in a session or when tired.

**Why it happens:**
- Older age (SMD 1.6) and previous hamstring injury (RR 2.7; recent RR 4.8) are the strongest risk factors; previous calf strain RR 1.5 (Green et al. 2020). A 30-year-old starting maximal sprinting is in the higher-age group.
- Hamstrings are most likely strained in late swing, when active and lengthening, which is why max-velocity sprinting is the riskiest part (Chumanov et al. 2012); acceleration work comes first (our rule).
- In competitive sprinters, two thirds of hamstring injuries happened when training speed jumped toward competition speed (Haugen et al. 2019).

**What to check on film:** Not a film fault. The reviewer flags reps filmed late in a session or after a game, and any visible limping or grabbing.

**Cue:** "Build up, never cold, never tired." / 中文："循序渐进，不冷身冲刺，累了不冲刺。" (our rule)

**Drill:** Nordic hamstring (eccentric only) 2 x 4-5 in weeks 1-2, 3 x 6 in weeks 3-4, 3 x 8 in weeks 5-6, 3 x 8-10 in weeks 7-8, once or twice a week (our rule; the RCT used 25 sessions over 13 weeks). Sprint ramp: start at about 80-85 % effort, add about 5 % per week, keep sprint metres at the low end of Haugen's ranges, max-velocity (flying) sprints only from week 5 and only without hamstring symptoms (our rule). Warm-up 15-20 min in FIFA 11+ style: jog, dynamic mobility, skips, build-ups at about 60, 75 and 90 % (our rule; see KB-warm-up-mobility).

**Success measure:** All Nordic sessions done for 8 weeks; no posterior-thigh symptoms (our rule).

**Source:** Green et al. 2020, BJSM 54:1081, doi:10.1136/bjsports-2019-100983; Chumanov et al. 2012, BJSM 46:90, https://bjsm.bmj.com/content/46/2/90; Haugen et al. 2019, https://pmc.ncbi.nlm.nih.gov/articles/PMC6872694/ (flying sprints 10-30 m, 4-15 min rest, 50-150 m per session, 48-72 h recovery); van der Horst et al. 2015, AJSM 43:1316, doi:10.1177/0363546515574057 (579 amateur soccer players, OR 0.282); Al Attar et al. 2017, Sports Med 47:907, doi:10.1007/s40279-016-0638-2 (RR 0.49); van Dyk et al. 2019, BJSM 53:1362 (about 51 % fewer); Impellizzeri et al. 2021, J Clin Epidemiol, doi:10.1016/j.jclinepi.2021.09.007 (true RCTs only: RR 0.59, 95 % CI 0.27-1.29, inconclusive); Mendiguchia et al. 2020, PLoS One, doi:10.1371/journal.pone.0228283 (sprint training increased biceps femoris fascicle length more than Nordics); Thorborg et al. 2017, BJSM 51:562 (FIFA 11+: IRR 0.61). Verdict on Nordics: cheap, low-risk, probably helpful, not proven.

**Evidence level:** strong (risk factors, structured warm-up); moderate to strong but contested (Nordics); our rule (ramp, dose).

---

## Teammate claims

Graded against the research; the teammate's ideas are useful hypotheses, not the authority. "For him" parts stay unclear until a side-view sprint is filmed.

| # | Claim | Verdict | Reason | Source |
|---|---|---|---|---|
| 1 | Full-court heaviness is a movement-pattern problem, not body weight or upper-body bulk | unclear (plausible) | Distance runners keep distance-style mechanics when sprinting, and steady running does not train short high-force contacts; but no data on him and no study rules body mass in or out | Bushnell & Hunter 2007; Harper 2022 (mismatch is our rule) |
| 2 | Half court tolerates short steps; full-court sprinting needs long strides | partly | Short steps are normal in steps 1-4 and step length grows only from about step 5 to 15; most game sprints last about 2 s, so long strides matter only on long pushes | Nagahara 2014; Ben Abdelkrim 2007 |
| 3 | Fast break = head down, forward lean, full hip-knee-ankle extension, very high frequency and very long stride | partly | Forward lean in acceleration: supported. Head down: not supported (head goes neutral). Full extension: sprinters still leave the knee about 158° at toe-off. Frequency and length trade off; they are outcomes, not a cue | Kugler & Janshen 2010; Nagahara 2014; King 2023; Hunter 2004 |
| 4 | Distance running does not need a lowered centre of mass; basketball is all sprints | partly | First half supported: economy favours low vertical oscillation; the low lean is for acceleration and braking. "All sprints" overstates: sprinting is about 5.3 % and high intensity about 16 % of live time, though those efforts decide plays | Moore 2016; Harper 2022; Ben Abdelkrim 2007 |
| 5 | Many basketball coaches do not know these details | unclear (not verifiable) | No survey data found; acceleration mechanics are standard in S&C literature | Haugen 2019; Wild et al. 2011 |
| 6 | Run full court "bouncing like an antelope" | partly | Fits top speed (large vertical force, short stiff contacts); early acceleration wants only moderate vertical impulse, and basketball sprints are mostly acceleration | Weyand 2000; Hunter 2005; Nagahara 2018 |
| 7 | He "drags the lower legs", which makes calves and thighs sore after a few trips | partly | "Dragging" fits backside mechanics seen in distance runners, but its effect on speed is debated and it is not filmed for him yet; calf soreness is better explained by plantarflexor load below about 7 m/s, treadmill mechanics, volume and novelty | Bushnell & Hunter 2007; Clark 2020; Haugen 2018; Dorn 2012; Van Hooren 2020 |
| 8 | After basketball the glutes should be the sore muscles, not calves or knees | partly | Gluteus maximus and hip muscles do take over at high speed (model from simulation and EMG), but soreness depends on eccentric novelty, and knee load in basketball comes mostly from decelerations; "no sore glutes" is weak evidence by itself (a model, not a measurement) | Dorn 2012; Schache 2011; Lieberman 2006; Harper 2022 |
| 9 | (Owner) This is why he can run 10 km but runs badly in basketball | partly (likely, unverified for him) | Different demands (economy vs short high-force efforts and braking), distance runners keep their pattern when sprinting, endurance work blunts power gains; video and tests needed to confirm for him | Bushnell & Hunter 2007; Wilson 2012; Harper 2022 |

---

## Reference values

Bands for `move-summary` (`REFERENCE` dict). Read every band as a reference from the cited population, not a pass mark for an adult rec player; trained-sprinter bands are a direction of change. Convention conversions: our `trunk_lean` and `shin` are measured from vertical, the studies from horizontal, so band = 90° minus the study value (our arithmetic). `touchdown_ahead` uses hip-to-ankle leg length; King et al. normalised to trochanter height, which is close but not identical (our rule: treat as approximate). All sagittal rows need `view: side`.

| metric key | band (lo-hi) | phase | view | kb slug | source |
|---|---|---|---|---|---|
| `trunk_lean` (`first3`, at touchdown) | 48-64° | accel | side | MV-accel-posture | King et al. 2023: 34 ± 8° from horizontal, steps 1-4 (our conversion) |
| `trunk_lean` (at speed) | 9-20° | maxv | side | MV-accel-posture | Nagahara et al. 2014: upper trunk 75.7 ± 5.6° from horizontal by step ~25 (our conversion; upper trunk, not hip-shoulder) |
| `shin` (`first3`) | 32-38° | accel | side | MV-braking-touchdown | King et al. 2023: shank 55 ± 3° from horizontal (our conversion); marginal 2D reliability, frame check |
| `touchdown_ahead` (steps 1-4) | -0.15 to +0.07 | accel | side | MV-braking-touchdown | King et al. 2023 (trochanter-height units, approximate); hip keypoint is not the centre of mass |
| `contact_s` (steps 1-4) | 0.175-0.203 s | accel | side, >= 100 fps | MV-short-accel-stride | King et al. 2023: 0.189 ± 0.014 s, trained sprinters (rec values will be longer) |
| `contact_s` (flying 10 m) | 0.13-0.16 s | maxv | side, >= 100 fps | MV-ankle-dominant-push | Clark et al. 2020 regression Tc ≈ -0.013·v + 0.23 at 6-8 m/s (our arithmetic) |
| `cadence_spm` (steps 1-4) | 238-273 | accel | side | MV-short-accel-stride | King et al. 2023: 4.26 ± 0.29 steps/s x 60 (our arithmetic); trained sprinters |
| `cadence_spm` (peak) | 283-302 | maxv | side | MV-short-accel-stride | Nagahara et al. 2014: 4.87 ± 0.16 Hz x 60 (our arithmetic); trained sprinters |
| `penultimate_ratio` | 1.0-1.4 | layup | side or 45° | MV-layup-penultimate | lo: track-jump pattern (ULPGC high jump; analogy, not basketball); hi 1.4 (our rule) |
| `hip_drop` | 0.02-0.08 | layup | side | MV-layup-penultimate | (our rule) "a few % of leg length" from coaching and track-jump sources; no basketball value |
| `takeoff_ahead` | 0.0-0.3 | layup | side | MV-one-foot-takeoff | (our rule) from "plant slightly ahead of hips" (expert opinion) |
| `free_knee` (take-off, free leg thigh from vertical) | 75-95° | layup | side | MV-one-foot-takeoff | (our rule) from "free thigh near horizontal" (expert opinion) |
| `bounces_per_10m` | 1.1-1.8 | dribble | side (court scale) | MV-speed-dribble | 3-4 bounces per 28 m for advanced school players (Breakthrough, expert opinion) up to our 5-per-court target (our rule); our arithmetic |
| `ball_top_vs_hip` | 0.9-1.15 | dribble | side | MV-speed-dribble | (our rule) numeric reading of "upper thigh to slightly above the waist"; ball top height above the floor / leg length, 1.0 = hip height (Coach's Clipboard, expert opinion) |

No band (no normative value found; report raw values and change over time only): `heel_recovery`, `step_len`, `knee_lift` in running, thigh separation, `takeoff_knee`, `takeoff_trunk`, `landing_knee_min` (judge landings by eye; small knee flexion at contact is the risk sign, Krosshaug et al. 2007). Do not use the jogging optimum of about 170 steps/min (Lieberman et al. 2015) as a sprint band.

---

## Filming protocol (re-shoot)

Set-up (our rule, within the research ranges of 8-15 m and hip height):
- Phone on a tripod at about hip height, landscape, locked (no zoom, no panning), 8-10 m from the running lane and perpendicular to it.
- 240 fps slow motion if available, else 120 fps; never below 60 fps for sprints (60 fps is good only for trunk lean and arm action). Contact times are reported only at >= 100 fps.
- Tape marks on the floor every 1 m (or at least every 5 m) in the filmed zone for scale; measure his hip (trochanter) height once.
- Same spot, same lane, same shoes and floor for every re-test; note the spot in `movement.json`.
- Plain clothing that contrasts with the background; nobody else crossing the frame (the tracker can switch to another person).
- Film alone when you can. If a trainer or partner must be in shot, they wear a clearly different colour from the player, top and shorts: in the first baseline the trainer's T-shirt matched the player's, the clothing-colour model could not tell them apart and most landings were lost.
- Front or behind view optional (knee-in on landings and stops, arm crossing).

Clips (each as its own segment, kind in brackets):
1. 3 x 20 m sprint from a standing 2-point start, full rest (`sprint`); film steps 1-4 in frame first, a second set with the camera at 10-20 m if possible.
2. 3 x full-court speed dribble, each hand (`dribble-sprint`).
3. 6 layups each side at game speed from a full-court or half-court push (`layup`), side or 45°.
4. 3 x sprint-to-stop: 10-15 m sprint, stop at a line, hold (`decel`).
5. One easy jog past the camera for contrast (`run`).

## Re-test battery (every 4 weeks, our rule for the interval)

| Test | How | Notes |
|---|---|---|
| 10 m and 20 m sprint | 2-point start, phone at 240 fps side-on at the line, count frames from first movement to torso crossing; or the MySprint app; best of 3 | MySprint agreed with photocells, r = 0.989-0.999, in trained sprinters (Romero-Franco et al. 2017, doi:10.1080/17461391.2016.1249031) |
| Full-court speed dribble (28 m), each hand, plus 20 m version | Same timing; count dribbles and steps | Dribble deficit = dribble time - sprint time, per hand (Scanlan et al. 2018) |
| 5-10-5 (pro agility) | Straddle the middle line, 5 m each way, both directions | Correlates strongly with the lane agility test (thesis, https://minds.wisc.edu/items/9f18721a-5a85-4467-822b-d3fb68aeeb49) |
| CMJ (hands on hips) | My Jump app (flight time from slow-motion video), best of 3 | Validated against a force plate in active men (Balsalobre-Fernández 2015, as cited in https://pmc.ncbi.nlm.nih.gov/articles/PMC6193468) |
| One-leg approach jump reach, each leg | 3-5 step approach, touch a backboard or wall mark | Compare with CMJ reach: about equal = not using the approach (our rule) |

Test fresh, after the standard warm-up, never after a game day (our rule). Same camera spot as the previous test.

---

## Pain and safety gate

Run before every session that adds sprint, jump or braking load, and log it in the plan notes.

- **Next-morning rule (our rule, from the research notes):** rate knee, calf/Achilles and hamstring pain 0-10 the morning after each session or game.
  - 0-3 and settling: continue; load may rise as planned.
  - Calf or Achilles pain above 3/10 the next morning, or knee pain that lasts more than 24 h: stop the new sprint and jump load, keep strength and easy work, repeat the last step that stayed <= 3.
  - Any posterior-thigh "grab" or cramp during a sprint: stop sprinting that day.
- **Load rules (our rule):** raise only one thing per week (sprint metres, plyo contacts or intensity); plyo contacts +10-20 per week up to about 100-120 per session; never sprint maximally cold, fatigued or at the end of a game; 48 h between high-intensity sprint or plyo sessions (Haugen et al. 2019; plyo 48-72 h, expert opinion). Count game jumps as load (an elite junior makes about 44 jumps per game; Ben Abdelkrim et al. 2007).
- **Red flags -> physio, not a drill:** swelling, the knee or ankle giving way, sharp or worsening pain, pain that changes how he walks, pain that does not settle within a few days, or any suspected strain (skill KB rule; thresholds our rule). We never diagnose; write "likely" for causes and refer.
- More on soreness vs pain, sleep and load progression: `prompts/fuel_recovery_kb.md` (FR-soreness-vs-pain, FR-load-progression) and `KB-recovery-weekly-load`.
