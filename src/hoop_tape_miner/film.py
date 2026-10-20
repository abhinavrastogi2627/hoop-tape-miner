"""Turn a report into one explained video: the narration plays over the clips, charts and chapter cards it talks
about, with burned-in subtitles, so the team can just watch.

Script: film.<lang>.md in the report folder (writing guide: prompts/film.md). Every visual line starts a scene:

    # note for the writer                                  not read, not shown
    ## Why the 22-4 run happened                           chapter card (over blurred footage of the next clip)
    ![#17 loses it to #25's press](clip:07:26-07:38)       game footage (video time); caption = banner at the top
    > 07:28 我#17 对#25 我#17->0.62,0.55 "nobody comes"   freeze the clip there and draw on it (see film_draw)
    >                                                      (alone) the clip plays on; what follows is read over it
    ![Score margin](momentum.png)                          a picture from the folder, fitted to the frame
    ![fouls in the 4th quarter](stat:9)                    a big number with its caption
    ![Get back on defence](court:plays/safety.json)        an animated court diagram (format: film_draw)

Paragraphs after a visual line are narrated over it (blank line = paragraph, as in listen.<lang>.md); paragraphs
before the first visual go over a title card built from game.json. A clip shorter than its narration plays once,
then replays at half speed, then holds its last frame; game sound is turned down under the voice. A scene without
narration lasts CARD_S / IMAGE_S, or the clip's own length.

Freeze lines: the clip plays up to that moment, stops, and the paragraphs after the `>` line are narrated over the
frozen frame, which is dimmed except for the marked players (a ring at their feet, arrows, a label); then the clip
plays on. A `>` line on its own resumes the clip at once: the paragraphs after it are read over the running play. 我#17 / 对#25 (or us#17 / them#25) are found in the CV tracks (run/tracks.pkl, --run); x,y fractions of
the frame work without them. In a court diagram the first paragraph goes over the set-up and each further
paragraph starts the next step.

Each paragraph is spoken by edge-tts (needs internet: the text is sent to Microsoft's TTS service) and cached in
<folder>/.film-cache/, so editing one scene only re-speaks that scene. Needs ffmpeg with libass ($FFMPEG and
$FFPROBE override the binaries).

usage: hoop-tape-miner film workspace/teams/<opponent>/<date> [--lang zh en] [--video game.mp4] [--run run/]
       [--height 720] [--crf 23] [--font "Microsoft YaHei"] [--scenes 3-6] [--dry]
--crf trades size for quality (x264: +6 is about half the size; 23 makes ~75 MB for 10 min at 720p).
A full render also writes film.<lang>.jpg, a poster frame from the title card (~1 s).
--dry checks the script and prints the scene list with estimated lengths (no TTS, no rendering).
--scenes renders only those scenes (1-based) into film.<lang>.preview.mp4, for a quick look.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import film_draw as fd
from . import game_config as gc
from .clips import seconds
from .narrate import voices

FPS = 30
CRF = 23                         # x264 quality (--crf): higher = smaller file
POSTER_S = 1.0                   # poster frame time (the title card)
LEAD, TAIL, GAP = 0.3, 0.5, 0.4  # silence before the voice, after it, and between paragraphs (s)
CARD_S, IMAGE_S = 3.0, 4.0       # scene length without narration
SLOW = 0.5                       # replay speed when the narration outlasts a clip
DUCK = 0.2                       # game sound volume under the voice
MAX_CHARS = {"zh": 30, "en": 84}  # one subtitle at most (about two lines at 720p)
FREEZE_S = 2.0                   # a freeze without narration
SLOW_TAG = {"zh": "慢放", "en": "Slow motion"}
FREEZE_TAG = {"zh": "定格", "en": "Paused"}
SPEECH_RATE = {"zh": 5.2, "en": 15.0}  # characters per second, only for --dry estimates
FONT = {"win32": "Microsoft YaHei", "darwin": "PingFang SC"}.get(sys.platform, "Noto Sans CJK SC")
BG = "#14161f"

TIME = r"\d{1,2}:\d{2}(?:\.\d)?"
CLIP_RE = re.compile(rf"^({TIME})-({TIME})$")
TIME_RE = re.compile(rf"^{TIME}$")
VISUAL_RE = re.compile(r"^!\[(.*)\]\((.+)\)$")


@dataclass
class Freeze:
    line: str  # the `> mm:ss marks "label"` line
    paras: list[str] = field(default_factory=list)

    def parts(self):
        return fd.parse_freeze_line(self.line)  # (time text, marks, label, unreadable tokens)

    @property
    def resume(self) -> bool:
        """A bare `>`: the clip plays on, and the paragraphs after it are read over the running play."""
        return self.line.strip() == ">"

    def at(self) -> float | None:
        return None if self.resume else seconds(self.parts()[0])


@dataclass
class Scene:
    kind: str  # title | card | image | clip | stat | court
    text: str  # card title or banner caption
    src: str = ""  # image path, "mm:ss-mm:ss" for a clip, the number for a stat, the play file for a court
    paras: list[str] = field(default_factory=list)
    freezes: list[Freeze] = field(default_factory=list)

    def window(self) -> tuple[float, float]:
        m = CLIP_RE.match(self.src)
        return seconds(m[1]), seconds(m[2])

    def clip_s(self) -> float:
        if self.kind != "clip":
            return 0.0
        t0, t1 = self.window()
        return t1 - t0


def parse_script(text: str) -> list[Scene]:
    scenes: list[Scene] = []
    para: list[str] = []

    def end_para():
        if para:
            if not scenes:
                scenes.append(Scene("title", ""))
            sc = scenes[-1]
            (sc.freezes[-1].paras if sc.freezes else sc.paras).append(" ".join(" ".join(para).split()))
            para.clear()

    for raw in text.splitlines():
        line = raw.strip()
        m = VISUAL_RE.match(line)
        if line.startswith("## ") or m:
            end_para()
            if m:
                cap, target = m[1].strip(), m[2].strip()
                kind = next((k for k in ("clip", "stat", "court") if target.startswith(k + ":")), "image")
                scenes.append(Scene(kind, cap, target[len(kind) + 1:].strip() if kind != "image" else target))
            else:
                scenes.append(Scene("card", line[3:].strip()))
        elif line.startswith(">"):
            end_para()
            if not scenes:
                scenes.append(Scene("title", ""))
            scenes[-1].freezes.append(Freeze(line))
        elif line.startswith("#"):
            continue
        elif not line:
            end_para()
        else:
            para.append(line)
    end_para()
    return scenes


def check(scenes: list[Scene], folder: Path, video: Path | None, video_s: float | None, tracks=None) -> list[str]:
    """Problems that would stop the render (missing pictures, bad clip windows, no video, unreadable freezes)."""
    out = []
    for i, sc in enumerate(scenes, 1):
        if sc.kind == "image" and not (folder / sc.src).is_file():
            out.append(f"scene {i}: picture not found: {folder / sc.src}")
        if sc.kind == "court":
            f = folder / sc.src
            if not f.is_file():
                out.append(f"scene {i}: court diagram not found: {f}")
            else:
                try:
                    out += [f"scene {i} ({sc.src}): {p}" for p in fd.play_problems(fd.load_play(f))]
                except (ValueError, TypeError, AttributeError) as e:
                    out.append(f"scene {i}: cannot read {f}: {e}")
        if sc.freezes and sc.kind != "clip":
            out.append(f"scene {i}: freeze lines (>) only work after a clip line")
        if sc.kind == "clip" and CLIP_RE.match(sc.src):
            t0, t1 = sc.window()
            times = []
            for k, fz in enumerate(sc.freezes):
                if fz.resume:
                    if not k or sc.freezes[k - 1].resume:
                        out.append(f"scene {i}: a `>` line on its own resumes the clip; it only works after a freeze")
                    continue
                t, marks, _, bad = fz.parts()
                if not TIME_RE.match(t):
                    out.append(f"scene {i}: freeze needs a time first (> mm:ss ...), got {fz.line!r}")
                    continue
                times.append(seconds(t))
                if not t0 <= seconds(t) <= t1:
                    out.append(f"scene {i}: freeze {t} is outside the clip {sc.src}")
                out += [f"scene {i}: freeze {t}: cannot read {b!r} (我#17, 对#25, 0.4,0.6, A->B, \"label\")"
                        for b in bad]
                if tracks is None and any(m[0] == "player" for mk in marks for m in points(mk)):
                    out.append(f"scene {i}: freeze {t} marks players but no CV tracks were found; pass --run")
            if times != sorted(times):
                out.append(f"scene {i}: freeze lines must be in time order")
        if sc.kind == "clip":
            if not CLIP_RE.match(sc.src):
                out.append(f"scene {i}: clip window must be mm:ss-mm:ss, got {sc.src!r}")
                continue
            t0, t1 = sc.window()
            if t1 <= t0:
                out.append(f"scene {i}: clip {sc.src} ends before it starts")
            if video is None or not video.is_file():
                out.append(f"scene {i}: clip needs the game video; pass --video or set game.json video")
            elif video_s is not None and t1 > video_s + 0.5:
                out.append(f"scene {i}: clip {sc.src} runs past the end of the video ({video_s:.0f} s)")
    return out


def points(mark) -> tuple:
    """The player / point marks inside a mark (an arrow has two)."""
    return mark[1:] if mark[0] == "arrow" else (mark,)


def freeze_warnings(scenes: list[Scene], tracks) -> list[str]:
    """Marked players the tracks do not have at that moment (their ring is left out)."""
    out = []
    for i, sc in enumerate(scenes, 1):
        for fz in sc.freezes:
            t, marks, _, _ = fz.parts()
            if tracks is None or not TIME_RE.match(t):
                continue
            for m in dict.fromkeys(m for mk in marks for m in points(mk)):
                if m[0] == "player" and fd.mark_box(m, seconds(t), tracks) is None:
                    out.append(f"scene {i}: freeze {t}: {m[1]}#{m[2]} is not in the tracks near that moment; "
                               f"mark them with x,y instead")
    return out


def clip_plan(t0: float, t1: float, freeze_at: list[float | None], voice: list[float]):
    """A clip with freezes. voice[0] = narration before the first freeze, voice[k] = narration on freeze k
    (freeze_at None: a resume, read over the play that follows). Returns (length, segments, narration starts,
    freeze spans): segments are ("play", from, to) in video time or ("hold", at, seconds); starts are scene times
    (None for a group without narration); spans are None for a resume."""
    segs, starts, spans = [], [LEAD if voice[0] else None], []
    s, v, end = 0.0, t0, (LEAD + voice[0]) if voice[0] else 0.0
    for tk, vk in zip(freeze_at, voice[1:]):
        if tk is None:  # the play goes on at once; the voice follows the freeze narration
            ns = max(s + 0.3, end + GAP if end else 0.0) if vk else None
            if vk:
                end = ns + vk
            starts.append(ns)
            spans.append(None)
            continue
        if tk > v:
            segs.append(("play", v, tk))
            s, v = s + tk - v, tk
        if vk:
            ns = max(s + LEAD, end + GAP if end else 0.0)  # the narration before it may still be running
            fe, end = ns + vk + TAIL, ns + vk
        else:
            ns, fe = None, s + FREEZE_S
        starts.append(ns)
        spans.append((s, fe))
        segs.append(("hold", tk, fe - s))
        s = fe
    if t1 > v:
        segs.append(("play", v, t1))
        s += t1 - v
    return max(s, end + TAIL if end else 0.0), segs, starts, spans


def timing(kind: str, voice_s: float, clip_s: float = 0.0) -> tuple[float, float]:
    """(scene length, slow-motion replay length) for a scene with `voice_s` seconds of narration."""
    if kind == "clip":
        if not voice_s:
            return clip_s, 0.0
        need = LEAD + voice_s + TAIL
        if need <= clip_s + 1.0:  # a short overrun just holds the last frame
            return max(clip_s, need), 0.0
        return need, min(clip_s / SLOW, need - clip_s)
    base = CARD_S if kind in ("title", "card", "stat") else IMAGE_S
    return (max(base, LEAD + voice_s + TAIL) if voice_s else base), 0.0


# ---- subtitles ---------------------------------------------------------------------------------------------

def chunks(text: str, max_chars: int) -> list[str]:
    """Split a sentence into subtitle-sized pieces, at commas first, then at spaces or anywhere."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    packed, cur = [], ""
    for piece in re.findall(r"[^，、；：,;:]+[，、；：,;:]?\s*|[，、；：,;:]\s*", text):
        if cur.strip() and len(cur) + len(piece) > max_chars:
            packed.append(cur.strip())
            cur = ""
        cur += piece
    if cur.strip():
        packed.append(cur.strip())
    out = []
    for c in packed:
        while len(c) > max_chars:
            cut = c.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            out.append(c[:cut].strip())
            c = c[cut:].strip()
        if c:
            out.append(c)
    return out


def tidy(t: str) -> str:
    """Subtitles drop trailing commas and full stops (but keep ? and !)."""
    return t.strip().rstrip("，。、；：,;:.").strip()


def cue_split(start: float, end: float, text: str, max_chars: int) -> list[tuple[float, float, str]]:
    parts = chunks(text, max_chars)
    total = sum(len(p) for p in parts) or 1
    out, t = [], start
    for p in parts:
        d = (end - start) * len(p) / total
        out.append((t, t + d, tidy(p)))
        t += d
    return [c for c in out if c[2]]


def ass_time(s: float) -> str:
    cs = int(round(max(s, 0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    sec, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"


def ass_colour(hex_: str, alpha: int = 0) -> str:
    r, g, b = gc.hex_to_rgb(hex_)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def ass_escape(t: str) -> str:
    return t.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def ass_doc(w: int, h: int, font: str, accent: str, events: list[tuple[float, float, str, str]]) -> str:
    """events: (start, end, style, text); text is already escaped and may carry ASS override tags."""
    m = round(h * 0.04)
    side = round(w * 0.08)  # banner keeps clear of broadcast logos in the top corners
    white, box = "&H00FFFFFF", "&H40000000"
    styles = {  # size, primary, outline/box, border style, outline, alignment, margin l/r, margin v, bold
        "Sub": (round(h * 0.057), white, box, 3, round(h * 0.012), 2, m, round(h * 0.05), 0),
        "Banner": (round(h * 0.036), white, ass_colour(accent, 0x30), 3, round(h * 0.012), 8, side, m, 1),
        "Title": (round(h * 0.075), white, "&H00000000", 1, 0, 5, m, 0, 1),
        "Tag": (round(h * 0.04), "&H0000D7FF", box, 3, round(h * 0.01), 9, m, m, 1),
        "Draw": (20, white, "&H00000000", 1, 0, 7, 0, 0, 0),  # telestration shapes (ASS drawings)
        "Mark": (round(h * 0.045), "&H00101010", ass_colour(fd.MARK_HEX), 3, round(h * 0.01), 2, m, 0, 1),
        "Big": (round(h * 0.2), ass_colour(fd.MARK_HEX), "&H00000000", 1, round(h * 0.004), 5, m, 0, 1),
    }
    layer = {"Draw": 0, "Mark": 1}
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 0",
             "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
             "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
             "MarginL, MarginR, MarginV, Encoding"]
    for name, (size, prim, outl, bs, ol, al, ml, mv, bold) in styles.items():
        lines.append(f"Style: {name},{font},{size},{prim},{prim},{outl},{outl},{-bold},0,0,0,100,100,0,0,"
                     f"{bs},{ol},0,{al},{ml},{ml},{mv},1")
    lines += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    lines += [f"Dialogue: {layer.get(st, 2)},{ass_time(s)},{ass_time(e)},{st},,0,0,0,,{t}"
              for s, e, st, t in events if e > s]
    return "\n".join(lines) + "\n"


def scene_events(sc: Scene, length: float, slow: float, clip_s: float, cues, lang: str, title: str, h: int,
                 extra=()):
    """Subtitle events for one scene; cue times count from the start of the voice (LEAD). extra: more events."""
    ev = []
    if sc.kind == "title":
        ev.append((0, length, "Title", title))
    elif sc.kind == "card":  # " · " separates lines; the text grows upwards from just above the accent bar
        lines = "\\N".join(ass_escape(x.strip()) for x in sc.text.split(" · "))
        ev.append((0, length, "Title", f"{{\\an2\\pos({round(h * 8 / 9)},{round(h * 0.555)})}}" + lines))
    elif sc.kind == "stat":
        ev.append((0, length, "Big", f"{ass_escape(sc.src)}\\N{{\\fs{round(h * 0.055)}\\c&HFFFFFF&\\bord0}}"
                   f"{ass_escape(sc.text)}"))
    elif sc.text:
        ev.append((0, length, "Banner", ass_escape(sc.text)))
    if slow:
        ev.append((clip_s, clip_s + slow, "Tag", SLOW_TAG.get(lang, SLOW_TAG["en"])))
    subs = sorted((LEAD + s, LEAD + e, t) for s, e, t in cues)
    for i, (s, e, t) in enumerate(subs):
        if i + 1 < len(subs) and subs[i + 1][0] - e < 0.6:  # no flicker between close subtitles
            e = subs[i + 1][0]
        ev.append((s, min(e, length), "Sub", ass_escape(t)))
    return ev + list(extra)


def title_text(folder: Path, game: dict, h: int) -> str:
    """'<us> vs <them>' plus date and final score (game.json result only) on a smaller second line.
    Training and movement sessions: `title` (else '<name> · training' / '<name> · movement') plus the date."""
    gap = f"\\N{{\\fs{round(h * 0.02)}}} "  # a thin blank line between the title and the date
    if gc.is_personal(game):
        kind = "movement" if gc.is_movement(game) else "training"
        head = game.get("title") or f"{game.get('name') or '#' + str(game.get('player', ''))} · {kind}"
        sub = str(game.get("date") or folder.name)
        return ass_escape(head) + f"{gap}\\N{{\\fs{round(h * 0.045)}\\b0}}{ass_escape(sub)}"
    head = f"{gc.team_name(game, 'us')} vs {gc.team_name(game, 'them')}"
    pm = re.fullmatch(r"player-(\w+)", folder.name)
    if pm:
        head = f"#{pm[1]} · {head}"
    date = next((p for p in reversed(folder.resolve().parts) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p)), "")
    res = game.get("result") or {}
    score = f"{res['us']}–{res['them']}" if isinstance(res.get("us"), int) and isinstance(res.get("them"), int) else ""
    sub = " · ".join(x for x in (date, score) if x)
    return ass_escape(head) + (f"{gap}\\N{{\\fs{round(h * 0.045)}\\b0}}{ass_escape(sub)}" if sub else "")


# ---- speech ------------------------------------------------------------------------------------------------

def ffmpeg(*args: str, cwd: Path | None = None):
    # -nostdin: a backgrounded ffmpeg that reads the terminal can stall or misread keys
    subprocess.run([os.environ.get("FFMPEG", "ffmpeg"), "-nostdin", "-v", "error", "-y", *args], check=True, cwd=cwd)


def duration_s(p: Path) -> float:
    out = subprocess.run([os.environ.get("FFPROBE", "ffprobe"), "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(p)], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def video_size(p: Path) -> tuple[int, int]:
    out = subprocess.run([os.environ.get("FFPROBE", "ffprobe"), "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True).stdout
    w, h = out.strip().split(",")[:2]
    return int(w), int(h)


def has_audio(p: Path) -> bool:
    out = subprocess.run([os.environ.get("FFPROBE", "ffprobe"), "-v", "error", "-select_streams", "a",
                          "-show_entries", "stream=index", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True).stdout
    return bool(out.strip())


async def _tts(text: str, voice: str, rate: str, out: Path) -> list[tuple[float, float, str]]:
    import edge_tts

    cues = []
    with open(out, "wb") as f:
        async for ch in edge_tts.Communicate(text, voice, rate=rate).stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "SentenceBoundary":
                cues.append((ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch["text"]))
    return cues


def spoken(text: str, voice: str, rate: str, cache: Path) -> tuple[Path, float, list]:
    """One paragraph as speech: (wav, seconds, sentence cues), cached by voice + rate + text."""
    key = hashlib.sha1(f"{voice}|{rate}|{text}".encode("utf8")).hexdigest()[:16]
    mp3, meta, wav = cache / f"{key}.mp3", cache / f"{key}.json", cache / f"{key}.wav"
    if mp3.exists() and meta.exists():
        m = json.loads(meta.read_text(encoding="utf8"))
        cues = [tuple(c) for c in m["cues"]]
    else:
        cache.mkdir(parents=True, exist_ok=True)
        cues = asyncio.run(_tts(text, voice, rate, mp3))
        cues = cues or [(0.0, duration_s(mp3), text)]  # no sentence timing from the service: one cue, split later
        meta.write_text(json.dumps({"duration": duration_s(mp3), "cues": cues, "text": text}, ensure_ascii=False),
                        encoding="utf8")
    if not wav.exists():
        # edge-tts ends every clip with ~0.9 s of silence; cut it so scene changes and paragraph gaps stay tight
        ffmpeg("-i", str(mp3), "-af", "areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse",
               "-c:a", "pcm_s16le", str(wav))
    dur = duration_s(wav)
    return wav, dur, [(s, min(e, dur), t) for s, e, t in cues if s < dur]


def voice_track(paras: list[str], voice: str, rate: str, cache: Path, out: Path, max_chars: int):
    """Paragraphs -> one wav with GAP between them: (wav or None, seconds, subtitle cues, paragraph starts)."""
    if not paras:
        return None, 0.0, [], []
    parts, cues, starts, t = [], [], [], 0.0
    for p in paras:
        mp3, dur, pc = spoken(p, voice, rate, cache)
        starts.append(t)
        for s, e, txt in pc:
            cues += cue_split(t + s, t + e, txt, max_chars)
        parts.append(mp3)
        t += dur + GAP
    ins = [x for p in parts for x in ("-i", str(p))]
    pads = "".join(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=mono"
                   f"{f',apad=pad_dur={GAP}' if i < len(parts) - 1 else ''}[p{i}];" for i in range(len(parts)))
    ffmpeg(*ins, "-filter_complex", pads + "".join(f"[p{i}]" for i in range(len(parts))) +
           f"concat=n={len(parts)}:v=0:a=1[a]", "-map", "[a]", "-c:a", "pcm_s16le", str(out))
    return out, duration_s(out), cues, starts


# ---- rendering ---------------------------------------------------------------------------------------------

def scene_cmd(sc: Scene, length: float, slow: float, w: int, h: int, folder: Path, video: Path | None,
              game_audio: bool, voices: list[tuple[Path, float]], ass_name: str, accent: str, out: str, *,
              segs=None, bg: float | None = None, court: str | None = None, crf: int = CRF) -> list[str]:
    """ffmpeg arguments for one scene. voices: (wav, start s) per narration group; segs: a clip's play / hold
    segments (clip_plan); bg: video time of the blurred footage behind a card; court: a diagram's ffconcat list."""
    fit = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
    hold = f"tpad=stop_mode=clone:stop_duration={length:.3f},trim=duration={length:.3f}"
    args, graph, game = [], [], []
    duck = DUCK if voices else 1.0
    if sc.kind == "clip":
        t0, t1 = sc.window()
        segs = segs or [("play", t0, t1)]
        for i, (kind, a, b) in enumerate(segs):  # one input per segment: no frames buffered between them
            if kind == "play":
                args += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(video)]
                v = f"[{i}:v]{fit},setsar=1,fps={FPS},setpts=PTS-STARTPTS"
                if slow and len(segs) == 1:
                    v += (f",split[n][r];[r]setpts=PTS/{SLOW},fps={FPS},trim=duration={slow:.3f}[s];"
                          f"[n][s]concat=n=2:v=1:a=0")
                if game_audio:
                    graph.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=mono,asetpts=PTS-STARTPTS,"
                                 f"apad=whole_dur={b - a:.3f},atrim=duration={b - a:.3f}[g{i}]")
            else:  # a frozen frame: the first frame at that moment, cloned for b seconds, in silence
                args += ["-ss", f"{max(t0, min(a, t1 - 0.2)):.3f}", "-t", "0.2", "-i", str(video)]
                v = (f"[{i}:v]{fit},setsar=1,fps={FPS},setpts=PTS-STARTPTS,trim=end_frame=1,"
                     f"tpad=stop_mode=clone:stop_duration={b:.3f},trim=duration={b:.3f}")
                if game_audio:
                    graph.append(f"aevalsrc=0:c=mono:s=48000:d={b:.3f}[g{i}]")
            graph.append(v + f"[y{i}]")
        graph.append("".join(f"[y{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0,{hold}[c]")
        if game_audio:
            graph.append("".join(f"[g{i}]" for i in range(len(segs))) +
                         f"concat=n={len(segs)}:v=0:a=1,volume={duck}[ga]")
            game = ["[ga]"]
    elif sc.kind == "image":
        args = ["-loop", "1", "-framerate", str(FPS), "-t", f"{length:.3f}", "-i", str((folder / sc.src).resolve())]
        # fitted between the banner and the subtitles, so neither covers a chart's title or axis labels
        top, bottom = round(h * 0.11), round(h * 0.15)
        graph.append(f"[0:v]scale={w}:{h - top - bottom}:force_original_aspect_ratio=decrease,"
                     f"pad={w}:{h}:(ow-iw)/2:{top}+({h - top - bottom}-ih)/2:color=white,setsar=1[c]")
    elif sc.kind == "court":
        args = ["-f", "concat", "-safe", "0", "-i", court]
        graph.append(f"[0:v]scale={w}:{h},setsar=1,fps={FPS},{hold}[c]")
    else:  # title, card, stat: over the game itself, blurred and darkened, when there is footage to use
        if bg is not None and video:
            args = ["-ss", f"{bg:.3f}", "-t", f"{length:.3f}", "-i", str(video)]
            v = (f"[0:v]{fit},setsar=1,fps={FPS},setpts=PTS-STARTPTS,boxblur=20:2,"
                 f"colorlevels=romax=0.4:gomax=0.4:bomax=0.4,{hold}")
        else:
            args = ["-f", "lavfi", "-i", f"color=c=0x{BG[1:]}:s={w}x{h}:r={FPS}:d={length:.3f}"]
            v = "[0:v]null"
        if sc.kind != "stat":
            v += (f",drawbox=x={w // 2 - w // 16}:y={int(h * (0.64 if sc.kind == 'title' else 0.58))}:w={w // 8}:"
                  f"h={max(4, h // 120)}:color=0x{accent[1:]}:t=fill")
        graph.append(v + "[c]")
    graph.append(f"[c]format=yuv420p,ass={ass_name}[v]")

    n, labels = args.count("-i"), list(game)
    for j, (wav, start) in enumerate(voices):
        args += ["-i", str(wav)]
        graph.append(f"[{n + j}:a]aformat=sample_rates=48000:channel_layouts=mono,"
                     f"adelay={int(round(start * 1000))}:all=1[vo{j}]")
        labels.append(f"[vo{j}]")
    if not labels:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"]
        labels.append(f"[{n}:a]")
    mix = labels[0] if len(labels) == 1 else "".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
    # Timestamps rebuilt from the sample count and a finite apad: some game clips came out of amix with broken
    # timestamps, and an open-ended apad then never let atrim / -t stop (ffmpeg ticket #3015 pattern).
    graph.append(f"{mix}asetpts=N/SR/TB,apad=whole_dur={length:.3f},atrim=duration={length:.3f}[a]")
    return [*args, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]", "-t", f"{length:.3f}",
            "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", "-ar", "48000", "-ac", "1", out]


def backdrop(scenes: list[Scene], i: int) -> float | None:
    """Footage behind a card (scene index i, 0-based): the start of the next clip, else of the one before."""
    clips = [sc for sc in scenes[i + 1:] + scenes[:i][::-1] if sc.kind == "clip" and CLIP_RE.match(sc.src)]
    return clips[0].window()[0] if clips else None


def fit_box(src: tuple[int, int], w: int, h: int) -> tuple[float, float, float, float]:
    """Where a src-sized frame sits once fitted into w x h: (x, y, width, height)."""
    k = min(w / src[0], h / src[1])
    return (w - src[0] * k) / 2, (h - src[1] * k) / 2, src[0] * k, src[1] * k


def find_run(run: Path | None, folder: Path, video: Path | None) -> Path | None:
    """The CV run with tracks.pkl: --run, else run/ next to the report or the video."""
    if run:
        if not (run / "tracks.pkl").is_file():
            sys.exit(f"{run}: no tracks.pkl (the CV run folder)")
        return run
    near = [folder / "run"] + ([video.parent / "run", video.parent.parent / "run"] if video else [])
    return next((d for d in near if (d / "tracks.pkl").is_file()), None)


def court_steps(starts: list[float], n: int) -> list[float]:
    """Step start times of a court diagram: paragraph 2, 3, ... start steps 1, 2, ...; extra steps every 2.5 s."""
    st = [LEAD + t for t in starts[1:]][:n]
    while len(st) < n:
        st.append((st[-1] if st else LEAD + 0.5) + 2.5)
    return st


def plan(sc: Scene, voice_s: list[float], para_starts: list[float], n_steps: int = 0):
    """(length, slow, segments, narration starts, freeze spans, court step starts) for one scene."""
    if sc.kind == "clip" and sc.freezes:
        t0, t1 = sc.window()
        length, segs, starts, spans = clip_plan(t0, t1, [fz.at() for fz in sc.freezes], voice_s)
        return length, 0.0, segs, starts, spans, []
    length, slow = timing(sc.kind, voice_s[0], sc.clip_s())
    steps = court_steps(para_starts, n_steps) if sc.kind == "court" else []
    if steps:
        length = max(length, steps[-1] + fd.ANIM + 1.0)
    return length, slow, None, [LEAD], [], steps


def build(folder: Path, lang: str, video: Path | None, height: int, font: str, pick: tuple[int, int] | None = None,
          dry: bool = False, run: Path | None = None, crf: int = CRF) -> Path | None:
    script = folder / f"film.{lang}.md"
    scenes = parse_script(script.read_text(encoding="utf8"))
    if not scenes:
        sys.exit(f"{script}: no scenes")
    game = gc.load_game(folder)
    needs_video = any(sc.kind == "clip" for sc in scenes)
    has_video = bool(video and video.is_file())
    video_s = duration_s(video) if needs_video and has_video else None
    src = video_size(video) if needs_video and has_video else (16, 9)
    tracks = None
    if any(m[0] == "player" for sc in scenes for fz in sc.freezes for mk in fz.parts()[1] for m in points(mk)):
        run_dir = find_run(run, folder, video)
        tracks = fd.Tracks.load(run_dir, *src) if run_dir else None
    problems = check(scenes, folder, video if needs_video else None, video_s, tracks)
    if problems:
        sys.exit(f"{script}:\n  " + "\n  ".join(problems))
    for warn in freeze_warnings(scenes, tracks):
        print(f"warning: {warn}")
    steps = {i: len(fd.load_play(folder / sc.src)["steps"]) for i, sc in enumerate(scenes, 1) if sc.kind == "court"}
    if dry:
        total, rate = 0.0, SPEECH_RATE.get(lang, 15.0)
        for i, sc in enumerate(scenes, 1):
            groups = [sc.paras] + [fz.paras for fz in sc.freezes]
            voice_s = [sum(len(p) / rate for p in g) + GAP * max(0, len(g) - 1) for g in groups]
            starts = [sum(len(p) / rate + GAP for p in sc.paras[:k]) for k in range(len(sc.paras))]
            length, slow, *_ = plan(sc, voice_s, starts, steps.get(i, 0))
            total += length
            extra = f"  {len(sc.freezes)} freeze(s)" if sc.freezes else "  slow replay" if slow else ""
            print(f"{i:3d} {sc.kind:5s} {sc.src or sc.text[:30]:<30s} {sum(len(p) for g in groups for p in g):5d} chars"
                  f" ~{length:5.1f} s{extra}")
        print(f"{len(scenes)} scenes, about {total / 60:.1f} min")
        return None

    w, h = int(round(height * 16 / 9 / 2)) * 2, height
    accent = gc.team_hex(game, "us")
    them_hex = gc.team_hex(game, "them", "#e0e0e0")
    voice, rate = voices(game)[lang]
    title = title_text(folder, game, h)
    cache = folder / ".film-cache"
    game_audio = has_audio(video) if needs_video else False
    fit = fit_box(src, w, h)
    chosen = list(enumerate(scenes, 1))
    if pick:
        chosen = [(i, sc) for i, sc in chosen if pick[0] <= i <= pick[1]]
    out = folder / (f"film.{lang}.preview.mp4" if pick else f"film.{lang}.mp4")
    max_chars = MAX_CHARS.get(lang, 84)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rendered = []
        for i, sc in chosen:
            groups = [sc.paras] + [fz.paras for fz in sc.freezes]
            tracks_ = [voice_track(g, voice, rate, cache, tmp / f"v{i:03d}_{k}.wav", max_chars)
                       for k, g in enumerate(groups)]
            length, slow, segs, starts, spans, step_at = plan(sc, [v[1] for v in tracks_], tracks_[0][3],
                                                              steps.get(i, 0))
            voiced = [(v, st) for v, st in zip(tracks_, starts) if v[0] and st is not None]
            cues = [(a + st - LEAD, b + st - LEAD, txt) for v, st in voiced for a, b, txt in v[2]]
            extra = []
            for fz, span in zip(sc.freezes, spans):
                if span is None:
                    continue
                fs, fe = span
                tt, marks, label, _ = fz.parts()
                extra += fd.freeze_events(marks, ass_escape(label), seconds(tt), tracks, w, h, fit, fs, fe)
                extra.append((fs, fe, "Tag", FREEZE_TAG.get(lang, FREEZE_TAG["en"])))
            ass_name = f"s{i:03d}.ass"
            (tmp / ass_name).write_text(ass_doc(w, h, font, accent, scene_events(sc, length, slow, sc.clip_s(), cues,
                                                                                 lang, title, h, extra)),
                                        encoding="utf8")
            court = None
            if sc.kind == "court":
                court = fd.render_court(fd.load_play(folder / sc.src), w, h, step_at, length, tmp / f"c{i:03d}",
                                        accent, them_hex, FPS).relative_to(tmp).as_posix()
            bg = backdrop(scenes, i - 1) if sc.kind in ("title", "card", "stat") and has_video else None
            seg = f"s{i:03d}.mp4"
            ffmpeg(*scene_cmd(sc, length, slow, w, h, folder, video, game_audio, [(v[0], st) for v, st in voiced],
                              ass_name, accent, seg, segs=segs, bg=bg, court=court, crf=crf), cwd=tmp)
            rendered.append(seg)
            print(f"scene {i}/{len(scenes)} {sc.kind} {length:.1f} s", flush=True)
        (tmp / "list.txt").write_text("".join(f"file '{x}'\n" for x in rendered), encoding="utf8")
        ffmpeg("-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "-movflags", "+faststart",
               str(out.resolve()), cwd=tmp)
    if not pick:
        poster(out, out.with_suffix(".jpg"))
    print(f"wrote {out} {out.stat().st_size / 1e6:.1f} MB, {duration_s(out) / 60:.1f} min")
    return out


def poster(mp4: Path, jpg: Path, at: float = POSTER_S) -> Path:
    """One frame (the title card at ~1 s) as the page player's poster."""
    t = min(at, duration_s(mp4) / 2)
    ffmpeg("-ss", f"{t:.3f}", "-i", str(mp4), "-frames:v", "1", "-q:v", "3", str(jpg))
    return jpg


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # scene titles are often Chinese; a cp1252 console must not crash
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(prog="hoop-tape-miner film", description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", help="report folder with film.<lang>.md")
    ap.add_argument("--lang", nargs="+", help="languages to render (default: every film.<lang>.md in the folder)")
    ap.add_argument("--video", help="our game video (default: game.json video)")
    ap.add_argument("--run", help="CV run folder with tracks.pkl, for 我#17 / 对#25 marks (default: run/ next to the "
                                  "report or the video)")
    ap.add_argument("--height", type=int, default=720, help="video height in pixels (default 720)")
    ap.add_argument("--crf", type=int, default=CRF, help=f"x264 quality, higher = smaller file (default {CRF}; "
                                                          "28 is about half the size)")
    ap.add_argument("--font", default=FONT, help=f"subtitle font, must cover the script's language (default {FONT})")
    ap.add_argument("--scenes", help="render only scenes A-B (1-based) into film.<lang>.preview.mp4")
    ap.add_argument("--dry", action="store_true", help="check the script and print scenes with estimated lengths")
    a = ap.parse_args(argv)
    folder = Path(a.folder)
    langs = a.lang or sorted(p.name.split(".")[1] for p in folder.glob("film.*.md"))
    if not langs:
        sys.exit(f"no film.<lang>.md in {folder}; see prompts/film.md")
    pick = None
    if a.scenes:
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", a.scenes)
        if not m:
            ap.error("--scenes takes A or A-B, e.g. 3-6")
        pick = (int(m[1]), int(m[2] or m[1]))
    # ffmpeg runs in a temp dir: --video is relative to the shell, a game.json path to the folder
    video = Path(a.video).resolve() if a.video else gc.load_game(folder).get("video")
    if video and not Path(video).is_absolute():
        video = (folder / video).resolve()
    for lang in langs:
        build(folder, lang, Path(video) if video else None, a.height, a.font, pick, a.dry,
              Path(a.run) if a.run else None, a.crf)


if __name__ == "__main__":
    main()
