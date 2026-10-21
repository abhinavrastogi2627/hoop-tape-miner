"""ffmpeg / ffprobe calls and safe file writes, shared by every stage.

$FFMPEG and $FFPROBE override the binaries (without $FFPROBE, an ffprobe next to $FFMPEG is used). Every ffmpeg
call runs with -nostdin (a backgrounded ffmpeg that reads the terminal can stall or misread keys) and every
ffprobe call has a timeout (a cloud placeholder file can hang it).

Writers that take a while go through `partial(out)`: they write into a hidden `.partial/` folder next to `out`,
and the file moves into place only when the block ends cleanly. A crash or Ctrl-C then never leaves a half file
that the next run would count as done, and globs such as `clips/*.mp4` never see one. Small text and JSON files
use `write_text_atomic` / `write_json_atomic` (temp file + replace).
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
from pathlib import Path

PROBE_TIMEOUT = 120  # seconds


def ffmpeg_exe() -> str:
    return os.environ.get("FFMPEG", "ffmpeg")


def ffprobe_exe() -> str:
    if os.environ.get("FFPROBE"):
        return os.environ["FFPROBE"]
    ff = os.environ.get("FFMPEG")
    if ff:
        cand = Path(ff).with_name("ffprobe" + Path(ff).suffix)
        if cand.exists():
            return str(cand)
    return "ffprobe"


def ffmpeg(*args, cwd: Path | None = None, timeout: float | None = None) -> None:
    """Run ffmpeg quietly, overwriting outputs; raises CalledProcessError on failure."""
    subprocess.run([ffmpeg_exe(), "-nostdin", "-v", "error", "-y", *map(str, args)], check=True, cwd=cwd,
                   timeout=timeout)


def ffprobe(*args) -> str:
    """ffprobe's stdout as text."""
    return subprocess.run([ffprobe_exe(), "-v", "error", *map(str, args)], capture_output=True, text=True,
                          encoding="utf8", errors="replace", check=True, timeout=PROBE_TIMEOUT).stdout


def probe(p: Path) -> dict:
    """Format and streams of a media file (ffprobe JSON)."""
    return json.loads(ffprobe("-print_format", "json", "-show_format", "-show_streams", p))


def duration_s(p: Path) -> float:
    return float(ffprobe("-show_entries", "format=duration", "-of", "csv=p=0", p).strip())


def video_size(p: Path) -> tuple[int, int]:
    out = ffprobe("-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", p)
    w, h = out.strip().split(",")[:2]
    return int(w), int(h)


def has_audio(p: Path) -> bool:
    return bool(ffprobe("-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", p).strip())


def concat(parts: list[Path], out: Path, workdir: Path) -> None:
    """Join same-format files without re-encoding (list file in `workdir`), web-ready (+faststart)."""
    quote = lambda p: Path(p).as_posix().replace("'", "'\\''")  # concat syntax: ' ends the quote, \' is a quote
    listing = Path(workdir) / "list.txt"
    listing.write_text("".join(f"file '{quote(p)}'\n" for p in parts), encoding="utf8")
    ffmpeg("-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", "-movflags", "+faststart", out)


@contextlib.contextmanager
def partial(out: Path):
    """Yield a path to write instead of `out` (same name, in `<dir>/.partial/`); it replaces `out` only when the
    block ends without an exception, else it is deleted and an existing `out` stays as it was."""
    out = Path(out)
    d = out.parent / ".partial"
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / out.name
    tmp.unlink(missing_ok=True)
    try:
        yield tmp
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            d.rmdir()  # only when empty: another writer may still be busy in it


def write_text_atomic(path: Path, text: str) -> None:
    """Write UTF-8 text via a temp file + replace, so readers see the old or the new file, never half of one."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf8")
    os.replace(tmp, path)


def write_json_atomic(path: Path, data, indent: int | None = 2) -> None:
    write_text_atomic(path, json.dumps(data, indent=indent, ensure_ascii=False) + "\n")
