# Writing the coach report (README.md + README.en.md)

Audience: the players and coach of an amateur team, reading on a phone, often in a group chat. Goal: they understand why the game went the way it did and know what to practise this week.

## Inputs (read these, not the raw sheets)

- `game.json`, `run/official.json` (if any), `run/review_v1/summary.json`, `run/review_v1/plusminus.json`, `players_facts.md`, focus players' `player<N>_facts.md`, the `memo_part<N>.md` files, the momentum figure (`hoop-tape-miner momentum`).
- Every number and every video time in the report must come from these files. If a fact is not there, leave it out or mark it "likely".

## Section skeleton

Keep the headings and order. The HTML page uses the H1 as page title and turns each H2 into a table-of-contents entry, so: exactly one H1, sections as H2, sub-points as H3.

```
# Coach's review: {us_team} {us_score}–{them_score} {them_team} ({date})

Us = {us_colour} {us_team} (home/away). Them = {them_colour} {them_team}. All times are **video time** (full video mm:ss), not the game clock.

**In one sentence: <where the game was won or lost, the biggest cause in numbers, and what worked>.**

| Score (us–them) | First half a–b · Second half c–d · Final **x–y** |
|---|---|
| Free-throw points | ... |
| Fouls | ... |
| Threes made | ... |

![momentum](momentum.en.png)        (README.md: momentum.png, rendered with --lang zh)

Sources: **official** = <league feed, what it records>; **film** = review of N possessions and M trips. <What is estimated; jersey-reading accuracy; what "likely" means.>

---

## 1. Game flow and momentum
- Table of 3-5 stretches: label, video time, score in the stretch, what happened.
- The decisive run, point by point: table of every opposing score in it (official time, score, how we gave it up, type), then totals by type.
- Our offence in the same stretch, in counts (possessions, points, ball screens, ball stops, isolations, transition trips and points).
- Check the team's own theory (e.g. "it was the substitutions") against the film and say plainly whether it holds.
- Comparison table: the bad stretch vs the good stretch, 3-5 rows.

## 2. Scouting report: how {them_team} play
### How they score (in order of importance)
### Key players   (table: #, official points, how to guard)
### How they defend

## 3. How we played and what went wrong
Numbered list, each item with a count and 1-3 video times. End with "What worked (keep doing it)".
Film clips (see "Film clips" below) go under the decisive-run table, the scouting weapons, our recurring mistakes and what worked.

## 4. Game plan for the next game against {them_team}
**Defence (top priority)** · **Offence** · **Rotation**: numbered, each rule one line, phrased as an instruction.

## 5. Team practice priorities (in order)
Table: #, focus, drill, measurable target.

## 6. Player-by-player review and practice plan
- 2-3 notes (minutes are estimates; official sheet limits; team problems are not one player's fault).
- Summary table: #, official line, est. minutes (video), one line.
- One H3 per player who played, most minutes first: **Went well** (first, with times) · **Fix** (with times) · **Practice** (two drills, each with a measurable target).
- Roster players the film cannot identify: one short line inviting them to say when they played.
```

## Film clips: show the play next to the claim

Readers discuss the report together, and an argument about "what happened at 12:42" ends the moment everyone watches it. Put a short clip of our video directly under the most important claims, so the page reads: claim, clip, then what to do differently.

**Marker.** One line of its own, under the paragraph, table or list item it proves:

```
![#17 dribbles alone into #25's press; no outlet, steal, and-one](clip:07:24-07:33)
```

Times are video time (mm:ss, optionally `mm:ss.s`). Use the *same* window in `README.md` and `README.en.md` (one file serves both); write the caption naturally in each language. Then run `hoop-tape-miner clips <folder>` (it cuts `clips/<from>-<to>.mp4` + poster) and `hoop-tape-miner html <folder>`. The page numbers the clips ("Clip 3 · 07:24–07:33") and adds a slow-motion button. Elsewhere in the text, link to a clip with `[▶ 07:24](#clip-0724-0733)`.

**Which plays get a clip (be selective).** Choose the plays a coach would stop the tape for: the ones that explain the result or that the team will change. Team report: 8–14 clips; player deep dive: 6–8. In order of priority:

1. The decisive run: the 3–5 opposing scores that best show *how* it happened (one clip per type: e.g. turnover → break, nobody back, help foul). Not every basket.
2. The opponent's main weapons from the scouting section: one clip per weapon (their best player's favourite move, their press, their set).
3. Our recurring mistakes from section 3, each with the clearest example.
4. **What worked**: at least 3 clips of us doing it right (the comeback, the best possession). The fix is easier to copy when the team can see it already did it.
5. Player sections: link to a team clip already shown (`[▶ 07:24](#clip-0724-0733)`) rather than adding new ones; add a clip only for a player's single most important habit if no team clip shows it.

Skip plays the film does not show clearly (camera off the ball, players hidden), and plays whose cause the facts sheets mark "unclear".

**Window.** 6–20 s; never over 45 s. Start 2–4 s before the cause (the bad pass, the missed box-out, the leak-out), not at the basket, and end 1–2 s after the result. Official feed times lag the play and have 10 s resolution: take the start from the film-review notes, not from the feed.

**Caption.** One sentence, 25 words at most: who, what happened, and the moment to watch ("watch #19 leave before the rebound"). Jersey numbers only. A caption states what is visible; uncertain identities say "likely".

**Check before you send.** Watch every clip once (or have a subagent read 3–4 frames of each): the play described must be in it, start to finish. Fix the window, re-run `clips` (`--force` re-cuts), delete clip files the stage reports as unused.

## Writing rules

1. **No possession ids, trip ids or file names** in the text. Refer to plays by video time (`12:05`, or `24:10–24:18` for a range). Readers rewatch by time.
2. **No methods appendix.** One "Sources" line under the scoreboard is all the method the reader sees. No talk of CV, clusters, models, pipelines or tokens.
3. Numbers before adjectives: "10 of their 16 points in that stretch came on the break", not "we struggled in transition".
4. Honest uncertainty: "likely #N" when the jersey was unreadable; "unclear" when the film does not show it. Never assign an undecided basket to make totals add up.
5. Every criticism has a video time; every fix has a drill; every drill has a measurable target (count, percentage or time).
6. Start each player's section with what went well. Criticise decisions and habits, not people. Team failures (e.g. nobody back on defence) are framed as team failures.
7. Refer to players by jersey number only, never by name.
8. Plain words for amateur players; short sentences; coaching terms only when the drill uses them.
9. Tables at most 4-5 columns so they fit a phone. Images by relative file name next to the README. Clip markers go on their own line below a table, never inside a cell.
10. No local paths and no links into the repo or the workspace.
11. **Both languages, each a complete file**: `README.md` in Chinese and `README.en.md` in English (the HTML page currently reads exactly these two). Same facts, numbers, times and section order; write each naturally in its language rather than translating word for word. Headings carry the same section numbers in every language.
12. Length: roughly 2,500-3,500 words per language. Cut prose before cutting evidence.

## Before you finish

- Recount every total you state against `official.json` / `game.json`.
- Check that every video time you cite exists in the facts sheets.
- Grep both files for `P0`, `pid`, `trip`, `.json`, `run/`: none should remain.
- Both files carry the same `clip:` windows (`hoop-tape-miner clips` lists them); every clip shows the play its caption describes.
