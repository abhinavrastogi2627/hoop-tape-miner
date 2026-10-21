# Writing the coaching insights (insights.json)

You turn one game's film review into a few coaching insights the team can act on: what kept happening, why it happened in basketball terms, one in-game rule, one drill and a number to hit next game. The coach report's conclusions and practice plan are built from your file, so every word must hold up when a player rewatches the clip.

Audience: an amateur adult team (one practice a week, short bench, mixed skill). Plain words; coaching terms only when the drill uses them.

You get the review folder path (`<review>`, e.g. `<run>/review_v1`). A critic subagent checks your file afterwards against the same film (`prompts/coach_critic.md`), so cite only what you can show.

## Inputs (read in this order)

1. `prompts/coach_kb.md`: the coaching knowledge base. Each `### KB-<slug>` entry has an observable symptom, the mechanisms behind it, what to check on film, an in-game rule, a drill and a next-game target. Your `why`, `rule`, `drill` and `target_next_game` start from the matching entry.
2. `<review>/summary.json` (per-stretch counts: `all` = whole game, other keys = the stretches chosen in the summary step), `<review>/plusminus.json` (and `pm_<N>.json` for the focus player, if present), `official.json` (in the run folder: box score and score flow; makes and fouls only).
3. `<review>/features.json` if it exists: per-trip numbers measured from the court tracks (`numbers_back_2s`, `off_spacing_m`, `off_hull_m2`, `paint_crowd`, `standstill_share`, `cross_half_s`). `null` means unknown, never zero.
4. `<review>/coach_part*.json`: the trips (schema v2: `pid`, `trip`, `t0`/`t1`, `offence`, `entry`, `result`, `shot`, `fts`, `foul`, `transition_defence`, `coach_note`, `evidence`, `confidence`, ...). Search them for patterns; count, do not estimate.
5. `<review>/memo_part*.md` and `notes_part*.txt`: the reviewers' reading of each stretch. Use them for leads; every claim still needs trip evidence.
6. Optional: the coach library folder named by key `coach_library` in `workspace/team.json`, if set. You may `grep` its text files for a passage that supports an entry's mechanism or drill and cite it (document + page) in `why` or `drill`. The KB entry is the default; never copy long passages.

To confirm a moment you cite, look at the sheet that covers it (the trip's possession lists its sheets in `<review>/part*.json`) and, when a detail matters (a jersey, a foot on the line, who was back), zoom: `uv run hoop-tape-miner coach-sheets zoom SHEET TILE X Y W H OUT [--scale 3]` with `OUT` under `<review>/zoom/`. Do not read every sheet; check the ones you cite.

## How to find the insights

1. Start from the points. Which patterns cost us the most points or gave us the most (opponent transition scores, fouls that sent them to the line, turnovers that became breaks, our scoring trips)? Rank candidates by points involved, from `summary.json` and the trips. `all.four_factors` (eFG%, TOV% with live/dead split, ORB%, FT rate = FTM/FGA, possessions, points per possession, `decided` = the factor with the largest weighted gap) and `all.ppp` (points per trip: transition / half_court / second_chance / after_live_turnover) tell you where the points went; an insight on the deciding factor quotes those numbers by name in `numbers`.
2. For each candidate, find the KB entry whose **Symptom** matches the trip fields. No matching entry → leave the candidate out (or note it in your reply); do not invent a mechanism.
3. Collect the trips that show it (at least two) and the trips that contradict it (counter-examples: the same situation where we did it right, or where it did not cost us). Counter-examples are not a weakness; they show the fix is possible.
4. Check the entry's **What to check on film** items on the cited sheets. Name the mechanism you actually saw, not every mechanism the entry lists.
5. Write the rule, drill and target from the entry, adapted to what this game showed (who, which spot, which moment).

Write 3-6 team insights and 1-3 for each focus player (`player` = jersey). Fewer, well-proven insights beat many thin ones.

## Output: `<review>/insights.json`

A JSON array (UTF-8), most points involved first:

```json
[
  {
    "id": "T1",
    "player": null,
    "kb": ["transition-defence"],
    "claim": "After our missed shots, they scored on the break 6 times; on 5 of them only one of us was back.",
    "why": "Two or three of us crashed every miss and the guard stopped at the ball, so nobody stood between the outlet and the rim (KB transition-defence: no safety role).",
    "evidence": [{"t": 512.4, "pid": 31, "trip": 1, "what": "three crash, #4 last back at half court, layup"},
                 {"t": 1290.0, "pid": 77, "trip": 2, "what": "outlet over #9, nobody under the rim"}],
    "counter_examples": [{"t": 1650.2, "pid": 95, "trip": 1, "what": "#4 sprints to the rim, break stopped"}],
    "numbers": {"all.them.transition_scores": 6, "features.31-1.numbers_back_2s": 1},
    "rule": "Shot goes up: the two guards are safeties and sprint to the paint; first back takes the rim, not the ball.",
    "drill": "Line-Up Transition: 4-on-4, one defender touches the baseline first; 4 stops per side, 10 minutes; success = someone under the rim every rep.",
    "target_next_game": "numbers_back_2s >= 3 on at least 80 % of their trips after our miss; at most 3 transition scores against.",
    "confidence": "medium",
    "critic": null
  }
]
```

Field rules:

- `id`: `T1`, `T2`, ... for team insights, `P<jersey>-1`, ... for player insights. `player`: `null` for a team insight, the jersey string (e.g. `"17"`) for a player insight.
- `kb`: one or more slugs from `prompts/coach_kb.md` (without the `KB-` prefix); the check fails on an unknown slug.
- `claim`: one or two sentences, a pattern seen at least twice, with counts. Jersey numbers only, never names. Uncertain identities say "likely #N".
- `why`: the mechanism in basketball terms (who was where, what they did, what that opened), linked to the KB entry. Not a restatement of the claim.
- `evidence`: at least two items at different video times. Every item names its trip: `pid` always, and `trip` when the pid has more than one trip. The check fails on a missing `pid`, a pid or trip that is not in `coach_part*.json`, and a `t` outside the cited trip's `t0`-`t1` (3 s slack). `what` says what to watch at that moment (at most 15 words).
- `counter_examples`: same shape and same check; `[]` only when you looked and found none.
- `numbers`: every number the claim or target uses that comes from a file, by name. Names are dotted paths: `all.us.turnovers`, `B.them.transition_scores`, `all.four_factors.them.ft_rate_pct`, `all.ppp.them.transition.ppp` (summary.json); the prefixes `features.<pid>-<trip>.<field>` (features.json, e.g. `features.31-1.numbers_back_2s`), `official.<path>` (official.json), `plusminus.<path>` and `pm_<N>.<path>` (plusminus.json, pm_<N>.json in the review folder) read those files. The check compares each value with the file and fails on a name that does not resolve. When you need a number no file holds, write the value `"unknown"` (it is listed, not checked) and say "unclear" in the text. Counts you made yourself from the trips go in the claim with their trip times, not here. No number from memory or estimate.
- `player`: must be one of our jerseys in the official box score when official.json has one.
- `rule`: one in-game rule, phrased as an instruction a player can follow during play.
- `drill`: from the KB entry, adapted: name, setup, reps, success measure (one or two sentences).
- `target_next_game`: a number our pipeline can measure next game (a trip field count or share, a features value, a summary count, an official total). "Better transition defence" is not a target.
- Optional `target_check`: `{"number": "<a summary.json or official. name>", "max": 3}` (or `"min"`) (or both) when the target is one such number; the number must also be listed in `numbers`. `season` and `scout` then mark it met / missed from the next game's files. Leave it out for a target no single number measures.
- `confidence`: high (clear on several sheets) | medium | low (mostly inferred). Low-confidence insights go last.
- `critic`: leave `null`. A separate critic subagent records its verdicts in its own file, `critic.json`; never write that file and never set a verdict yourself (a self-set verdict that differs from critic.json fails the check).

## Do not

- Do not write generic advice. These phrases (and the like) fail review: "communicate better", "be more aggressive", "play harder", "stay focused", "work harder", "more energy", "加强沟通", "提高专注", "更积极", "更努力", "打得更硬", "注意力集中", "保持专注". Say who does what, where and when.
- Do not change or round a fact to make a total add up; write "unclear" or "likely".
- Do not cite an official-feed time as play evidence: the feed lags the play by 10-30 s. Cite the trip's own times.
- Do not blame one player for a team failure; frame team failures as team insights.

## Language

Write the text fields in the language of the memos (`memo_language`, default English). The report writer translates.

## Before you reply

Run `uv run hoop-tape-miner coach-insights check --review <review> --no-critic` (the writer's check; the critic is checked in its own step) and fix every error until it prints PASS. Then reply in at most 8 lines: number of insights (team / player), the top three claims in one line each, and the points involved.
