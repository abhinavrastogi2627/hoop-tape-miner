# Writing a player deep dive (player-<N>/README.md + README.en.md)

For one focus player only, written to them in the second person. Goal: they see their game in numbers and clips, know the two or three habits that decide their impact, and leave with a four-week plan and three calls for the next game.

## Inputs

- `player<N>_facts.md` (official line, stints and on/off score, chronological log of involvements with video times and coach notes), the team report, `hoop-tape-miner plusminus --player <N>` output (with film-checked stints), the momentum figure.
- If the facts sheet lacks something, leave it out. Mark inferred identities "likely".

## Section skeleton

```
# #N personal deep dive: {us_team} {us_score}–{them_score} {them_team} ({date})

For #N only. Times are video times (full video mm:ss); "likely" means the jersey was unclear and the call is inferred.

**In one line: <the contrast that decided your game, in counts: when you did X we scored a/b; when you did Y it was c/d>.** <Where you were during the decisive run and the comeback, with on-court score.>

| Item | This game |
|---|---|
| Official | points, makes by type, fouls |
| Minutes (from video) | about M, in K stints |
| Score with you on | a–b (±n); with you off c–d (±n) |
| Likely assists | ... |
| Turnovers | confirmed + likely |

---

## 1. Minutes and plus-minus
Stint table: #, video time in–out, length, score while on, +/-. Then 2-3 bullets reading it (what drove the worst and best stints; precision, e.g. ±30 s per stint).

## 2. Your role
Two short paragraphs: what the team used you for, and the one shape your best and worst possessions share.

## 3. Key patterns (3-5)
One H3 each. A small table (time, what happened, result) or a short list, then the answer, ideally a moment from this game where the player already did it right ("you already showed the answer: at mm:ss ..."). End each with a one-line rule in bold.

## 4. Rewatch these 6 clips
**Best 3** and **Worst 3**: time range (mm:ss–mm:ss) + what to look for (the exact cue: hips turning, last moment to pass, feet set before the catch).
Each item gets its clip marker on the next line, e.g. `![Hand-off, drive, two defenders jump, kick-out](clip:33:49-33:58)`, so the player watches it right there.
In section 3, link a pattern's key moment to its clip instead of repeating it: `[▶ 33:49](#clip-3349-3358)`. Window and caption rules: "Film clips" in `prompts/coach_report.md`.

## 5. Practice plan (4 weeks, N sessions a week)
Table: #, what, how, volume, target. 4-6 drills, each tied to a pattern in section 3.

## 6. Calls and targets for the next game
**Three calls**: 2-6 words each, said to yourself during play, with one sentence on when to use it.
**Three measurable targets**, each with this game's number for comparison.

---

Data note: <what the official sheet does and does not record; which official events cannot be confirmed on film; what is off-video>.
```

## Writing rules

1. Second person, direct, encouraging, honest. Start from what works; every criticism has a time and a fix.
2. No possession ids or file names; video times only. No methods appendix beyond the final data note.
3. Separate team problems from personal ones (e.g. a stint's minus is mostly team transition defence plus one turnover).
4. Conditioning, fatigue and late-game drops are stated plainly with the minute count behind them.
5. The three calls must be the same words used in the court cues (`prompts/court_cues.md`), so they become anchors.
6. Jersey numbers only, no names. No local paths or repo links.
7. Both languages, each a complete file (`README.md` Chinese, `README.en.md` English, as the HTML page expects) with the same facts, times and section order, written naturally. Run `hoop-tape-miner clips <game>/player-<N>` then `hoop-tape-miner html <game>/player-<N>`; `game.json` is found in the parent folder.
8. Length: roughly 1,200-1,800 words per language.
