# Making a player's court cue loop (cues.court.<lang>.md + cues.warmup.<lang>.md)

A short MP3 a player loops on earbuds before the game, on the bench or at halftime, so the two or three habits from their deep dive come back as automatic self-talk during play. Two versions: a one-minute **court loop** (cues only) and a two-minute **warm-up** version (cue + why + how). Check the league's rules: most do not allow earbuds during play.

## Files

- `workspace/players/<N>/cues.court.<lang>.md` and `cues.warmup.<lang>.md` (per player, not per game; update after each deep dive).
- `<lang>` is `en` or `zh`; the suffix picks the voice. One language is enough.
- Same format as narration scripts: `#` lines are not read, blank lines separate paragraphs (see `prompts/narration.md`).

## Court loop: rules

1. **5-7 cues, in possession order**: ball handling -> drive -> shot -> getting back -> defence -> mindset. The player hears them in the order the game asks for them.
2. **One idea per cue**, 2-8 words, imperative, rhythmic. Two short sentences at most ("Two come, ball goes. No numbers, pull it out.").
3. Use **the same words as the "three calls" in the player's deep dive**; the deep dive explains them, the loop repeats them.
4. Prefer the action over the prohibition ("Move your feet" beats "Don't reach"); pair them only when the prohibition is the habit to break ("Feet, not hands.").
5. No numbers, no opponents, no times, no names. These cues must still be true next game.
6. **Last cue = the reset cue**, for when the player loses their head after a miss, a turnover or a whistle: one breath, then one simple job. Example: "Head hot? One breath. Next play, one thing." It never mentions referees or blame.
7. Header lines (`#`): who it is for, how it is rendered, the order of the cues.
8. Render with a chime before each cue and a gap after it, loud enough for a gym, about one minute in total:

```
uv run hoop-tape-miner narrate --script workspace/players/<N>/cues.court.<lang>.md --chime --gap 6 --loud
```

Without `--tight` each gap is about a second longer than `--gap` (the voice's own lead-in and tail). For a loop played *during* practice or a scrimmage, use no chime, `--gap 0.4 --tight --rate +0%`: the next point follows within half a second.

## Warm-up version: rules

1. Under two minutes. Opening line: "Number N, listen once before you go on. Six phrases today."
2. For each cue, in the same order: **the cue** (exact words), **why** (one sentence with last game's evidence, e.g. "Last game, alone against pressure, two steals"), **how** (one concrete action: where to look, what to do before the second dribble).
3. Finish with the dead-ball check-in: "At every dead ball, ask: which phrase did I do on that play? If yes, keep going; if not, do that one next play." Then a short send-off ("Okay. Go.").
4. Render without the chime:

```
uv run hoop-tape-miner narrate --script workspace/players/<N>/cues.warmup.<lang>.md --loud
```

## Check

- Measure both files with `ffprobe` (court loop about 1 minute, warm-up under 2 minutes) and listen once end to end: each cue must be understandable over background noise on the first hearing.
