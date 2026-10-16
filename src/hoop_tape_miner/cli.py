"""`hoop-tape-miner <stage> ...` — thin dispatcher over the pipeline stages.

Stage modules are imported lazily, so `hoop-tape-miner html` does not load torch, and a stage whose module is
missing fails with a short message instead of breaking the whole CLI.
"""
from __future__ import annotations

import importlib
import sys

STAGES = {
    "new-game": ("hoop_tape_miner.new_game", "scaffold workspace/teams/<opponent>/<date>/ with game.json + run/"),
    "extract": ("hoop_tape_miner.extract", "pass 1: detection + court homography + colour features"),
    "embed": ("hoop_tape_miner.embed", "pass 2a: SigLIP embeddings for team classification"),
    "recalib": ("hoop_tape_miner.recalib", "re-run court homography only, reuse detections"),
    "calibrate": ("hoop_tape_miner.calibrate", "court calibration keyframes for extract/recalib"),
    "tracks": ("hoop_tape_miner.build_tracks", "pass 2b: team clusters + court-space tracking"),
    "jersey": ("hoop_tape_miner.jersey", "pass 3: jersey numbers with Qwen3-VL"),
    "analyze": ("hoop_tape_miner.analyze", "pass 4: identities, possessions, tactical metrics"),
    "review": ("hoop_tape_miner.review", "pass 5: annotated possession sheets for event review"),
    "coach-sheets": ("hoop_tape_miner.coach_review", "film-review sheets + lineup intervals for the coach review"),
    "merge-reviews": ("hoop_tape_miner.merge_reviews", "merge reviewed event parts after checking sheet coverage"),
    "coach-summary": ("hoop_tape_miner.coach_summary", "aggregate coach review trips into per-segment numbers"),
    "report": ("hoop_tape_miner.report", "pass 6: figures + stats.json"),
    "official": ("hoop_tape_miner.official", "league box score + score flow + video alignment"),
    "plusminus": ("hoop_tape_miner.plusminus", "on-court plus-minus per player from lineups + official score flow"),
    "momentum": ("hoop_tape_miner.momentum", "score-margin figure with scoring runs and on-court lanes"),
    "replay": ("hoop_tape_miner.replay", "2D tactics-board replay (mp4) of possessions from CV tracks"),
    "clips": ("hoop_tape_miner.clips", "cut the video clips a report marks with ![caption](clip:mm:ss-mm:ss)"),
    "narrate":("hoop_tape_miner.narrate", "listen.<lang>.md -> listen.<lang>.mp3 (edge-tts + ffmpeg)"),
    "film": ("hoop_tape_miner.film", "film.<lang>.md -> explained video: narration over clips and charts, subtitled"),
    "html": ("hoop_tape_miner.render_html", "report folder (README.md + README.en.md) -> one bilingual index.html"),
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
