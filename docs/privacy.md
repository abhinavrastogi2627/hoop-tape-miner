# Privacy

hoop-tape-miner analyses real people: your teammates, opponents and referees, often amateurs and sometimes minors. The code is public; everything about your games is not.

## What never leaves `workspace/`

`$HOOP_WORKSPACE` (default `./workspace`) is gitignored. Keep all of this inside it (or under the `media_root` your `team.json` names, also outside the repo) and never commit, push or upload it:

- game videos, extracted frames, review sheets, crops, zooms, evidence images, tactics-board clips;
- `team.json`, `game.json` (team names, rosters, colours), `official.json` and any league exports, including the raw responses `fetch` saves under `league/` (they contain player names);
- film-review outputs, fact sheets, reports, narration scripts and MP3s, cue loops, `index.html` pages (they embed figures and may embed frames);
- logs and screenshots of league sites.

Before any commit: `git status` must show no file from `workspace/`, no media (`*.mp4`, `*.mov`, `*.jpg` frames, `*.mp3`) and no personal names. If something slipped into history, rewrite it (`git filter-repo`) before the repo goes public; deleting it in a later commit is not enough.

Design notes, plans and prompts (`docs/`, `prompts/`) are public too: write "the owner", "#17", `<player>`, `<opponent>` and `<media root>` instead of names, team names and local paths. Before a push, `git grep -i` the outgoing commits for your own names and paths.

## People in the footage

- Refer to players by jersey number in all outputs. Do not add names, even if you know them.
- **Minors**: if any player in the game is under 18, get a parent or guardian's consent before sharing anything that shows them (frames, clips, personal reports), and keep their personal reports between the player, their guardians and the coach.
- **Consent for frames**: share frames or clips of players only with the team, and only with the consent of the people shown. Opponents and referees did not agree to be analysed: their frames never go beyond your coaching staff and players, and never onto public sites or social media.
- Personal deep dives go to that player (and the coach), not to the whole group, unless the player agrees.
- Delete a player's material when they ask.

## Where data goes off your machine

- **Local**: detection, tracking, embeddings and jersey reading run on your GPU; video does not leave the machine for these stages.
- **Your AI agent**: when Claude Code, Codex or another agent reads review sheets, frames, stats or reports, that content is sent to the model provider under your account's terms. Only use the film-review step if your team is comfortable with that.
- **Narration**: `narrate` uses edge-tts, which sends the script text to Microsoft's online text-to-speech service. Keep names out of scripts (jersey numbers only), or skip narration.
- **Model downloads**: Hugging Face is contacted to download weights; no game data is uploaded.
- **League sites**: `fetch` logs in with your own credentials (from the environment or the secrets file in `team.json`; it never prints or saves them or the session token). Keep them in a secrets file outside the repo, never in prompts, logs or commits, and follow the site's terms of use.

## Sharing reports

- `hoop-tape-miner html <folder> --share --out FILE` makes a single self-contained file without local paths or repo links. Send it privately (team chat, email), not on a public page.
- Re-check the shared file for frames of people who did not consent before sending.
- `hoop-tape-miner publish --deploy` puts reports on Cloudflare (workers.dev) behind random, unlisted URLs (`noindex`, no referrer, robots blocked). Pages carry no raw HTML from the reports and only media files from the report folder itself, and the Worker adds a Content-Security-Policy and `nosniff`. That keeps them out of search, but it is not access control: anyone who gets a link can open it and forward it. Send links only to the team, give personal reports their own recipient, and use `--new-link` to retire a link that leaked. For real access control, put Cloudflare Access (email one-time PIN, free for small teams) in front of the site.
- The explained video (`hoop-tape-miner film`) is footage of players too: same rules as clips, send it to the team only.
- Report clips (`hoop-tape-miner clips`) are footage of players and are embedded in `--share` files and uploaded by `publish`: the same consent rules as for frames apply, and a shared page or link with clips goes only to the team.
