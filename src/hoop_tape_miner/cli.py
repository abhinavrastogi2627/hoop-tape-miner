"""`hoop-tape-miner <stage> ...` — thin dispatcher over the pipeline stages.

Stage modules are imported lazily, so `hoop-tape-miner html` does not load torch, and a stage whose module is
missing fails with a short message instead of breaking the whole CLI.
"""
from __future__ import annotations

import importlib
import sys

STAGES = {
    "run": ("hoop_tape_miner.run", "one game end to end: run every stage in order, stop where the agent must judge"),
    "fetch": ("hoop_tape_miner.fetch", "league game url -> game folder, game.json, official.json and the game video"),
    "new-game": ("hoop_tape_miner.new_game", "scaffold workspace/teams/<opponent>/<date>/ with game.json + run/"),
    "scout": ("hoop_tape_miner.scout", "rematch dossier: past games vs one opponent -> scout.json + scout.md"),
    "extract": ("hoop_tape_miner.extract", "pass 1: detection + court homography + colour features"),
    "embed": ("hoop_tape_miner.embed", "pass 2a: SigLIP embeddings for team classification"),
    "recalib": ("hoop_tape_miner.recalib", "re-run court homography only, reuse detections"),
    "calibrate": ("hoop_tape_miner.calibrate", "court calibration keyframes for extract/recalib"),
    "tracks": ("hoop_tape_miner.build_tracks", "pass 2b: team clusters + court-space tracking"),
    "jersey": ("hoop_tape_miner.jersey", "pass 3: jersey numbers with Qwen3-VL"),
    "analyze": ("hoop_tape_miner.analyze", "pass 4: identities, possessions, tactical metrics"),
    "ball-track": ("hoop_tape_miner.ball", "smoothed ball track from the detections + ball-to-rim distances"),
    "rim-scan": ("hoop_tape_miner.rim_scan", "ball-sized movers in the air at each rim (video pass, CPU)"),
    "shot-proposals": ("hoop_tape_miner.shots", "shot attempts from rim arcs; made / likely miss from the official chart"),
    "review": ("hoop_tape_miner.review", "pass 5: annotated possession sheets for event review"),
    "coach-sheets": ("hoop_tape_miner.coach_review", "film-review sheets + lineup intervals for the coach review"),
    "merge-reviews": ("hoop_tape_miner.merge_reviews", "merge reviewed event parts after checking sheet coverage"),
    "coach-check": ("hoop_tape_miner.coach_schema", "validate coach review trips (schema v2); --migrate converts v1 parts"),
    "coach-summary": ("hoop_tape_miner.coach_summary", "aggregate coach review trips into per-segment numbers"),
    "coach-features": ("hoop_tape_miner.coach_features", "per-trip numbers from the court tracks (numbers back, spacing); ball quality"),
    "coach-insights": ("hoop_tape_miner.coach_insights", "check insights.json (evidence, KB, numbers, critic); blind A/B rating sheet"),
    "coach-eval": ("hoop_tape_miner.coach_eval", "score the coach review against official facts; lint insights"),
    "load": ("hoop_tape_miner.load", "running load per stint from the tracks: distance, sprints, top speed -> load.json"),
    "matchups": ("hoop_tape_miner.matchups", "defender distance at each reviewed shot + who guarded whom -> matchups.json"),
    "report": ("hoop_tape_miner.report", "pass 6: figures + stats.json"),
    "official": ("hoop_tape_miner.official", "league box score + score flow + video alignment"),
    "plusminus": ("hoop_tape_miner.plusminus", "on-court plus-minus per player from lineups + official score flow"),
    "momentum": ("hoop_tape_miner.momentum", "score-margin figure with scoring runs and on-court lanes"),
    "replay": ("hoop_tape_miner.replay", "2D tactics-board replay (mp4) of possessions from CV tracks"),
    "clips": ("hoop_tape_miner.clips", "cut the video clips a report marks with ![caption](clip:mm:ss-mm:ss)"),
    "posters": ("hoop_tape_miner.posters", "telestrate clip posters: ring the players a clip is about, arrow fouler -> fouled"),
    "reels": ("hoop_tape_miner.reels", "9:16 phone reel of one player's clips, crop follows the player (never published)"),
    "narrate": ("hoop_tape_miner.narrate", "listen.<lang>.md -> listen.<lang>.mp3 (edge-tts + ffmpeg)"),
    "film": ("hoop_tape_miner.film", "film.<lang>.md -> explained video: narration over clips and charts, subtitled"),
    "html": ("hoop_tape_miner.render_html", "report folder (README.md + README.en.md) -> one bilingual index.html"),
    "publish": ("hoop_tape_miner.publish", "reports -> private-link website (Cloudflare Workers), one stable link per report"),
    "season": ("hoop_tape_miner.season", "every game folder -> season page: results, Four Factors trends, targets checked, pooled on/off; --brief"),
    "train": ("hoop_tape_miner.train_run", "one personal training session end to end: phone videos -> page, film, next plan"),
    "train-new": ("hoop_tape_miner.train_new", "start a training session: session folder + joined session.mp4"),
    "train-scan": ("hoop_tape_miner.train_scan", "training: player pose, shot/finish candidates, dribble segments"),
    "train-sheets": ("hoop_tape_miner.train_sheets", "training: rim probe, rep and dribble review sheets, briefs"),
    "train-summary": ("hoop_tape_miner.train_summary", "training: reviewed reps -> summary.json, facts.md, figures"),
    "move": ("hoop_tape_miner.move_run", "one movement session end to end: clips -> gait metrics, review, page, film"),
    "move-new": ("hoop_tape_miner.move_new", "start a movement session: segments of any video -> movement.json + reel"),
    "move-scan": ("hoop_tape_miner.move_scan", "movement: pose per segment at native fps -> contacts, gait metrics"),
    "move-sheets": ("hoop_tape_miner.move_sheets", "movement: skeleton overlay reel, key-frame sheets, label strips, briefs"),
    "move-summary": ("hoop_tape_miner.move_summary", "movement: label check, review -> summary.json, facts.md, figures"),
}


def usage() -> str:
    w = max(map(len, STAGES))
    lines = ["usage: hoop-tape-miner <stage> [args]   (hoop-tape-miner <stage> -h for a stage's options)", ""]
    lines += [f"  {k:{w}s}  {d}" for k, (_, d) in STAGES.items()]
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(usage())
        sys.exit(0 if argv else 1)
    if argv[0] not in STAGES:
        print(f"unknown stage {argv[0]!r}\n\n{usage()}")
        sys.exit(1)
    name = STAGES[argv[0]][0]
    try:
        mod = importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name != name:
            raise
        sys.exit(f"stage {argv[0]!r} is not available in this checkout ({name} is missing)")
    sys.argv[0] = f"hoop-tape-miner {argv[0]}"  # argparse prog for stages that do not set one
    mod.main(argv[1:])


if __name__ == "__main__":
    main()
