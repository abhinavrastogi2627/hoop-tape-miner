# Writing the explained video script (film.<lang>.md)

One video the team can just watch: the narration plays over the clips, charts, diagrams and chapter cards it talks about, with subtitles burned in. `hoop-tape-miner film <folder>` renders `film.<lang>.md` into `film.<lang>.mp4`. Many players never open the report; this is the version they will watch together or on their phone with the sound off. Write it for watching, not for reading: every point should be *seen* (a frozen frame with the player circled, a diagram that moves), not just said over a card.

## Files

- Team report: `film.zh.md` and/or `film.en.md` next to `README.md` in the game folder. Player deep dive: `player-<N>/film.<lang>.md`.
- Court diagrams: `plays/<name>.json` in the same folder.
- Write it after the report and its clips are final; it uses the same facts and, mostly, the same clip windows.

## Format the renderer understands

```
# Writer's note (lines starting with # are not read and not shown)
Opening paragraph: goes over a title card built from game.json (teams, date, score).

## Why we lost the 22-4 run
A chapter card over blurred footage of the next clip. Keep it to one or two sentences.

![#17 dribbles alone into #25's press; steal, and-one](clip:07:26-07:38)
Watch the centre circle.

> 07:28 我#17 对#25 "nobody comes"
Stop here. Seventeen is alone against twenty-five, and nobody comes back for the ball.

>
Now watch: the steal, and the and-one.

![Fast-break points in the 22-4 run](stat:12)
Twelve of their twenty-two points came on the break.

![Get back: the safety rule](court:plays/safety.json)
Here is the set-up: we shoot, number nineteen is on the far wing.

The shot goes up, and nineteen is already running.

The guard and nineteen's defender sprint back.

![Score margin](momentum.png)
The chart shows where the game turned.
```

- Every visual line starts a new scene:
  - `## Title`: a chapter card over blurred game footage. ` · ` splits a long title into lines, e.g. three cues for the sign-off card.
  - `![caption](clip:mm:ss-mm:ss)`: our video, in video time; the caption is a banner at the top.
  - `![caption](stat:12)`: a big number with its caption, over blurred footage. Use it for the two or three numbers that matter.
  - `![caption](court:plays/x.json)`: an animated court diagram.
  - `![caption](picture.png)`: a figure from the folder, fitted to the frame. An empty caption shows no banner.
- The paragraphs after a visual line are read over it. Blank lines separate paragraphs (short pause). Paragraphs before the first visual go over the title card.
- **Freeze lines** (`> mm:ss marks "label"`, only after a clip line): the clip plays up to that moment and stops. The paragraphs after the `>` line are read over the frozen frame, then the clip plays on.
  - The frame is dimmed except for the marked players. Each marked player gets a yellow ring at the feet, and the label shows above the first one.
  - Marks: `我#17` / `对#25` (or `us#17` / `them#25`) are looked up in the CV tracks (`run/tracks.pkl`; `--run` if it is not next to the report or the video).
  - `0.42,0.61` is a spot on the frame, as fractions of width and height: where a player's feet are. Use it when the tracks do not know the player (`--dry` warns), e.g. a jersey number the CV pass never read.
  - `A->B` draws an arrow, e.g. `我#30->我#21` for a pass, or `我#3->0.30,0.55` for where help should come from.
  - A `>` line on its own resumes the clip at once; the paragraphs after it are read over the running play. Use it for "watch what happens next", so the words do not run over a frame that is still frozen.
  - Several freezes per clip are fine, in time order. A freeze without a paragraph holds two seconds.
- **Court diagrams** (`plays/<name>.json`, format in `src/hoop_tape_miner/film_draw.py`).
  - Court metres: x 0-28 from the left baseline (we attack the right basket), y 0-15 from the top sideline.
  - `"view"`: `"half"` (our offence), `"left"` (our defence) or `"full"` (transition, press).
  - Contents: start positions for `us` and `them`, the ball holder, then steps (`move`, `dribble`, `pass`, `shot`, `ball`, `ring`).
  - The first paragraph goes over the set-up; each further paragraph starts the next step, which animates in about a second.
- A scene lasts as long as its narration. A clip that is shorter than what you say over it plays once, then replays at half speed (marked "slow motion"), then holds its last frame. Clips with freezes do not replay. Game sound is turned down under the voice. A clip with no paragraph plays at full sound, as it is.

## Writing rules

1. **Show, then say.** Each point needs a picture that proves it.
   - A mistake: freeze at the moment it happens, ring the player(s), say what should have happened.
   - A habit to fix: the clip of it plus the clip of us doing it right.
   - A rule or a drill: a court diagram, then a clip from this game where we did it.
   - Text-only cards are chapter breaks (one or two sentences), never the explanation itself.
2. **Talk about what is on screen.**
   - Over a running clip, say what to watch: "Watch number nineteen leave before the shot goes up".
   - On a freeze, say what is wrong or right *in this frame* and what the player should do.
   - Over a chart, name the one thing to see in it.
3. **Fit the words to the picture.**
   - Pace: about 2.5 words per second in English, 4 Chinese characters per second in Chinese.
   - A running 12-second clip carries about 30 English words / 45 characters. Put the longer explanation on a freeze; the clip waits for it.
4. Spoken-language rules from `prompts/narration.md` apply: numbers spelled out as they are said, no symbols or abbreviations, jersey numbers only, short sentences. The subtitles show the text exactly as written. Captions and freeze labels may use digits and `#`.
5. **Structure:**
   - Open with the title: who, opponent, result, bottom line.
   - One chapter per report section that matters (decisive run, opponent's weapons, our recurring mistakes, what worked), each built from clips with freezes and one stat.
   - The game plan and practice priorities as court diagrams, each followed by a clip of us doing it in this game.
   - One good play and one fix per player, each a short clip with that player ringed.
   - Close on the sign-off card.
   - Show at least three clips of us doing it right.
6. **Clips:**
   - Reuse the report's windows (`clip:` markers in `README.md`); same selection and window rules as "Film clips" in `prompts/coach_report.md`.
   - A film may add a clip the report does not have, but every claim must still come from the report and its fact sheets.
   - Check new windows and freeze moments on frames (a subagent with a contact sheet: frames every second, the track boxes drawn) before writing over them. Track jersey numbers can be wrong, so look at who is actually ringed.
7. **Captions:** one short line (Chinese up to about 25 characters, English up to about 12 words), stating what is visible. Freeze labels: up to about 8 Chinese characters / 4 English words.
8. **Length:** team film about 10-14 minutes, player film about 3-5 minutes. Cut words before cutting pictures.
9. Never add a claim that is not in the report; uncertain things stay "likely" or "unclear".

## Render and check

1. `uv run hoop-tape-miner film <folder> --dry` checks the script and lists the scenes with estimated lengths. Nothing is rendered yet. It checks:
   - pictures and diagrams exist;
   - clip windows are inside the video;
   - freeze lines are readable and inside their clip;
   - marked players are in the tracks.
   Fix anything over the length target here.
2. `uv run hoop-tape-miner film <folder> --scenes 3-6` renders a short `film.<lang>.preview.mp4` to check fonts, subtitles, freezes and timing.
3. `uv run hoop-tape-miner film <folder>` renders `film.<lang>.mp4` (720p by default, `--height 480` for a smaller file). Speech is cached in `.film-cache/`, so re-rendering after an edit only re-speaks the changed paragraphs.
4. Check a few frames from every freeze and diagram (a subagent can extract them with ffmpeg):
   - each ring is on the player the narration names;
   - subtitles are readable and not clipped;
   - Chinese glyphs render (else pass `--font` with an installed CJK font);
   - each clip shows the play its caption describes.
5. The video shows real players: same consent rules as clips (`docs/privacy.md`); send it to the team only.
