# Writing the opponent dossier (workspace/teams/<opponent-slug>/README.md)

One living page per opponent, updated after every game against them. Readers: the coach and players preparing for the next meeting. Short: about one screen.

## Inputs

- Each game's `game.json`, `official.json` (if any) and coach report (sections 2 and 4).
- `scout.md` / `scout.json` next to the dossier (`hoop-tape-miner scout --opponent <name>`): record, their top
  scorers, pooled Four Factors and points per trip, what decided each game, our past targets. Take numbers from it;
  what it marks "unclear" stays unclear.

## Skeleton

```
# {them_team} team dossier

{them_colour} jerseys. Competition: {competition}. Head-to-head: W–L.

## Games

| Date | Score (us–them) | Half | Report |
|---|---|---|---|
| YYYY-MM-DD | a–b W/L | c–d | [page](YYYY-MM-DD/index.html) · [report](YYYY-MM-DD/README.md) · personal: [#N](YYYY-MM-DD/player-N/index.html) |

## Key players (official data, latest game)

| # | Points | Breakdown | Role (from film) |
|---|---|---|---|

Roster: <numbers>. <Known jersey-reading pitfalls, e.g. one number often misread as another.>

## How they play (confirmed YYYY-MM-DD)
- 4-6 bullets: how they score (ranked), how they defend, tempo, bench depth, free-throw and foul profile, three-point volume. Numbers where possible.

## Keys for the next game
Link to the latest report's game plan section, then the 3-5 rules that matter most, one line each, each with the evidence from last time.
```

## Rules

1. New game: add a row on top of "Games", refresh "Key players" and "How they play", and keep a pattern only if it held again; otherwise note what changed and when ("zone in the first meeting, man in the second").
2. Every pattern carries the date it was confirmed.
3. Links are relative and stay inside the opponent folder. No local paths, no league URLs.
4. Jersey numbers only, no names. Opponents did not consent to analysis: keep this page within the team.
5. `hoop-tape-miner new-game` creates this file from `templates/team-readme.md` the first time; fill it in, never overwrite it with `--force` after it has content. Write it in the language the team reads; it is not rendered to HTML.
