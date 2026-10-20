"""Render a bilingual report folder (README.md = 中文, README.en.md = English) into one HTML page with
a 中文 / EN switch. Images are inlined; if listen.zh.mp3 / listen.en.mp3 sit next to the READMEs
(`hoop-tape-miner narrate` makes them) the page gets a play button that reads the report aloud. Clip markers
`![caption](clip:07:24-07:33)` become numbered video players (cut them first with `hoop-tape-miner clips`).

usage: hoop-tape-miner html workspace/teams/<opponent>/<date> [--out index.html]
       hoop-tape-miner html workspace/teams/<opponent>/<date>/player-<number>
       hoop-tape-miner html workspace/teams/<opponent>/<date> --share --out /somewhere/Us_vs_Them_<date>.html
game.json (team names, optional us.hex / them.hex colours, result incl. halftime) is read from the folder or
its parent. --share drops repo links and local paths and embeds the audio, so the single file can be sent to
anyone, clips included. `hoop-tape-miner publish` uses the same clean-up but keeps audio and clips as files
(page(..., share=True, embed=False)) for a hosted copy.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import os
import re
import subprocess
import sys
from pathlib import Path

from markdown_it import MarkdownIt

from . import clips as clipmod
from . import game_config as gc

MD = MarkdownIt("commonmark", {"html": True}).enable("table")
LANGS = [("zh", "zh-CN", "中文", "README.md"), ("en", "en", "EN", "README.en.md")]
UI = {
    "zh": dict(us="我们", them="对手", half1="上半场", half2="下半场", final="终场", contents="目录", switch="切换语言",
               listen="听报告", listen_sub="约 {m} 分钟，可以边看边听", play="播放 / 暂停", seek="播放进度", speed="播放速度",
               clip="片段", slow="慢放", missing="（片段还没剪：运行 hoop-tape-miner clips）",
               training="个人训练", made="命中 / 出手", shots="投篮", finishes="终结", dribble="运球",
               targets="目标达成", vs_last="对比上次", minutes="分钟", unclear="无法判断",
               movement="运动模式", segments="片段", seen="看到的问题", hypotheses="待侧拍验证", good="保持的优点",
               measured="测量值"),
    "en": dict(us="Us", them="Them", half1="1st half", half2="2nd half", final="Final", contents="Contents", switch="Switch language",
               listen="Listen to the report", listen_sub="About {m} min. Read along or just listen.", play="Play / pause",
               seek="Playback position", speed="Playback speed",
               clip="Clip", slow="Slow-mo", missing="(clip not cut yet: run hoop-tape-miner clips)",
               training="Training", made="Made / attempts", shots="Shots", finishes="Finishes", dribble="Dribbling",
               targets="Targets met", vs_last="vs last session", minutes="min", unclear="unclear",
               movement="Movement", segments="Segments", seen="Findings seen", hypotheses="To test (side re-shoot)",
               good="Good habits", measured="Measured"),
}
PLAY_ICON = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path class="i-play" d="M8 5.5v13l10.5-6.5z"/>'
             '<path class="i-pause" d="M7 5h3.6v14H7zM13.4 5H17v14h-3.6z"/></svg>')


# Page colours when game.json has no us.hex / them.hex: (main, light variant for the dark score band).
DEFAULT_COLOURS = {"us": ("#5b4bd1", "#b9b0ff"), "them": ("#11907b", "#6fe0c9")}


def find_up(folder: Path, name: str) -> Path:
    p = gc.find_up(folder, name)
    if p is None:
        raise FileNotFoundError(f"{name} not found in {folder} or its parent")
    return p


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def scoreboard(folder: Path):
    """Team names, colours and score from game.json; scores are None while the result is not filled in."""
    game = gc.load_game(folder)
    if not game:
        raise FileNotFoundError(f"game.json / session.json not found in {folder} or its parent")
    if gc.is_personal(game):
        return training_scoreboard(folder, game)
    res = game.get("result") or {}
    fin = (_num(res.get("us")), _num(res.get("them")))
    ht = res.get("halftime") or {}
    h1 = (_num(ht.get("us")), _num(ht.get("them")))
    h2 = (fin[0] - h1[0], fin[1] - h1[1]) if None not in fin + h1 else (None, None)
    colours = {}
    for side in gc.SIDES:
        h = gc.team(game, side).get("hex")
        colours[side] = (h, gc.mix(h, "#ffffff", 0.55)) if gc.is_hex(h) else DEFAULT_COLOURS[side]
    return dict(us=gc.team_name(game, "us"), them=gc.team_name(game, "them"), final=fin, h1=h1, h2=h2, colours=colours)


BOARD = """<div class="score" data-result="{result}">
      <div class="team us"><span class="name">{us_name}</span><span class="side">{us_label}</span></div>
      <div class="pts" aria-label="{us_pts}–{them_pts}"><span class="{us_cls}">{us_pts}</span><span class="dash">–</span><span class="{them_cls}">{them_pts}</span></div>
      <div class="team them"><span class="name">{them_name}</span><span class="side">{them_label}</span></div>
    </div>
    <div class="halves">{halves}</div>"""


def training_scoreboard(folder: Path, s: dict) -> dict:
    """Session band: the player, made / attempts and % over all reviewed reps (summary.json `headline`)."""
    p = folder / "summary.json"
    summ = json.loads(p.read_text(encoding="utf8")) if p.exists() else {}
    h = s.get("hex")
    colours = dict(DEFAULT_COLOURS)
    if gc.is_hex(h):
        colours["us"] = (h, gc.mix(h, "#ffffff", 0.55))
    name = s.get("name") or f"#{s.get('player', '')}"
    return dict(training=True, movement=gc.is_movement(s), us=name, them="", date=s.get("date") or folder.name,
                summary=summ, colours=colours)


def _pct(t: dict | None) -> str:
    return f"{round(100 * t['pct'])}%" if t and t.get("pct") is not None else "–"


def training_board(sb: dict, lab) -> str:
    summ = sb["summary"]
    tot = (summ.get("totals") or {})
    allr = tot.get("all") or {}
    stats = []
    for key, t in (("shots", tot.get("shot")), ("finishes", tot.get("finish"))):
        if t and (t.get("att") or t.get("unclear")):
            got = f'{t["made"]}/{t["att"]} · {_pct(t)}' if t.get("att") else "–"
            more = f' +{t["unclear"]} {lab("unclear")}' if t.get("unclear") else ""
            stats.append(f'<span>{lab(key)}<b>{got}</b>{more}</span>')
    drib = summ.get("dribble") or {}
    if drib.get("seconds"):
        stats.append(f'<span>{lab("dribble")}<b>{drib["seconds"] / 60:.1f}</b> {lab("minutes")}</span>')
    tg = summ.get("targets") or []
    if tg:
        stats.append(f'<span>{lab("targets")}<b>{sum(t["status"] == "met" for t in tg)}/{len(tg)}</b></span>')
    d = (summ.get("previous") or {}).get("delta_pct")
    if d is not None:
        stats.append(f'<span>{lab("vs_last")}<b>{"+" if d >= 0 else "−"}{abs(round(100 * d))}</b> pp</span>')
    made = f'{allr["made"]}/{allr["att"]}' if allr.get("att") else "–"
    return f"""<div class="score" data-result="training">
      <div class="team us"><span class="name">{html.escape(sb["us"])}</span><span class="side">{lab("training")} · {html.escape(str(sb["date"]))}</span></div>
      <div class="pts" aria-label="{_pct(allr)}"><span>{_pct(allr)}</span></div>
      <div class="team them"><span class="name">{made}</span><span class="side">{lab("made")}</span></div>
    </div>
    <div class="halves">{"".join(stats)}</div>"""


def movement_board(sb: dict, lab) -> str:
    """Movement band: the player, film findings seen / to test / good habits and measured metrics (headline)."""
    h = sb["summary"].get("headline") or {}
    stats = [f'<span>{lab(k)}<b>{h[k]}</b></span>' for k in ("segments", "hypotheses", "good") if h.get(k) is not None]
    if h.get("shown_metrics"):
        stats.append(f'<span>{lab("measured")}<b>{h["shown_metrics"]}</b></span>')
    seen = h.get("seen")
    return f"""<div class="score" data-result="training">
      <div class="team us"><span class="name">{html.escape(sb["us"])}</span><span class="side">{lab("movement")} · {html.escape(str(sb["date"]))}</span></div>
      <div class="pts" aria-label="{seen if seen is not None else '–'}"><span>{seen if seen is not None else '–'}</span></div>
      <div class="team them"><span class="name"></span><span class="side">{lab("seen")}</span></div>
    </div>
    <div class="halves">{"".join(stats)}</div>"""


def data_uri(p: Path) -> str:
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def inline_images(body: str, folder: Path) -> str:
    def sub(m):
        src = m.group(1)
        p = folder / src
        if src.startswith(("http:", "https:", "data:")) or src.endswith(".mp4") or not p.exists():
            return m.group(0)
        return f'src="{data_uri(p)}"'
    return re.sub(r'src="([^"]+)"', sub, body)


def duration_s(p: Path) -> float:
    out = subprocess.run([os.environ.get("FFPROBE", "ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def for_sharing(md_text: str) -> str:
    """Drop top-level list items that point at repo files or local paths (they break once the page is
    sent on); keep everything else, nested items included."""
    out, skipping = [], False
    for line in md_text.splitlines():
        if line.startswith(("- ", "* ")):
            skipping = bool(re.search(r"\]\((?!https?:|#|clip:)[^)]+\)|`[^`]*[\\/][^`]*`", line))
        elif not line.startswith(" "):
            skipping = False
        if not skipping:
            out.append(line)
    text = "\n".join(out) + "\n"
    return re.sub(r"`[^`]*[\\/][^`]*`(?:[，,]\s*)?", "", text)  # inline local paths, e.g. (`gem-work\...`, each trip ...)


CLIP_IMG = re.compile(r'(<p>)?<img src="clips/([0-9_]+-[0-9_]+)\.mp4" alt="([^"]*)"\s*/?>(?(1)</p>)')


def clip_players(body: str, folder: Path | None, lang: str, embed: bool, windows: dict) -> str:
    """Clip images (from `clip:` markers) -> numbered <figure> with a video player, poster and slow-mo button.
    Paths stay relative in index.html (clips/ sits next to it); embed (--share) inlines them."""
    n = 0

    def sub(m):
        nonlocal n
        n += 1
        name, alt = m.group(2), m.group(3)
        start, end = windows.get(name, ("", ""))
        mp4 = folder / "clips" / f"{name}.mp4" if folder else None
        cap = (f'<figcaption><span class="clip-no">{UI[lang]["clip"]} {n} · {start}–{end}</span>{alt}</figcaption>')
        if mp4 is None or not mp4.exists():
            print(f"warning: clips/{name}.mp4 missing; run `hoop-tape-miner clips {folder}`", file=sys.stderr)
            return f'<figure class="clip missing" id="{lang}-clip-{name}">{cap}<p>{UI[lang]["missing"]}</p></figure>'
        poster = mp4.with_suffix(".jpg")
        src = data_uri(mp4) if embed else f"clips/{mp4.name}"
        post = f' poster="{data_uri(poster) if embed else "clips/" + poster.name}"' if poster.exists() else ""
        return (f'<figure class="clip" id="{lang}-clip-{name}"><video controls playsinline preload="none"{post} src="{src}"></video>'
                f'<div class="clip-bar">{cap}<button type="button" class="slow" data-slow aria-pressed="false">'
                f'{UI[lang]["slow"]} ½×</button></div></figure>')
    body = CLIP_IMG.sub(sub, body)
    return body.replace('href="#clip-', f'href="#{lang}-clip-')  # [▶ 07:24](#clip-0724-0733) jumps to the player


def render(md_text: str, lang: str, share: bool = False, folder: Path | None = None, embed: bool | None = None):
    md_text = re.sub(r"^# .*\n", "", md_text, count=1)  # H1 becomes the page header
    if share:
        md_text = for_sharing(md_text)
    windows = {}

    def clip_md(m):  # markdown-it would mangle "clip:07:24-07:33" as a URL, so hand it a plain relative path
        name = clipmod.clip_name(*m.groups())
        windows[name] = m.groups()
        return f"](clips/{name}.mp4)"
    md_text = clipmod.CLIP_RE.sub(clip_md, md_text)
    body = MD.render(md_text)  # CommonMark: lists need no blank line before them, 2-space nesting works
    body = clip_players(body, folder, lang, share if embed is None else embed, windows)
    if share:  # any repo-relative link left would be dead for the recipient
        body = re.sub(r'<a href="(?!https?:|#)[^"]*">(.*?)</a>', r"\1", body)
    heads = []

    def h2(m):
        heads.append(re.sub(r"<[^>]+>", "", m.group(1)))
        return f'<h2 id="{lang}-s{len(heads)}">{m.group(1)}</h2>'
    body = re.sub(r"<h2>(.*?)</h2>", h2, body)
    body = re.sub(r"<table>", '<div class="table-wrap"><table>', body).replace("</table>", "</table></div>")
    body = re.sub(r"<p>(<img [^>]+>)</p>", r'<div class="figure">\1</div>', body)
    return body, heads


def hide(code: str) -> str:
    return "" if code == "zh" else " hidden"


def listen_block(folder: Path, embed: bool):
    """Big play button + progress for the narration, or empty strings when there is no audio yet."""
    files = {c: folder / f"listen.{c}.mp3" for c, *_ in LANGS}
    if not all(p.exists() for p in files.values()):
        return "", ""
    audios, labels = [], []
    for c, attr, *_ in LANGS:
        src = data_uri(files[c]) if embed else files[c].name
        # native controls stay visible when scripts are blocked (WeChat / mail file previews); the script hides them
        audios.append(f'<audio id="audio-{c}" class="native" data-lang="{c}"{hide(c)} controls preload="metadata" src="{src}"></audio>')
        m = max(1, round(duration_s(files[c]) / 60))
        labels.append(f'<span data-lang="{c}" lang="{attr}"{hide(c)}><b>{UI[c]["listen"]}</b>'
                      f'<small>{UI[c]["listen_sub"].format(m=m)}</small></span>')
    block = f"""<div class="listen">
      <button type="button" class="play big" data-play aria-label="{UI['zh']['play']}">{PLAY_ICON}</button>
      <div class="listen-body">
        <div class="listen-label">{''.join(labels)}</div>
        <div class="listen-track">
          <input type="range" class="seek" min="0" max="100" step="1" value="0" aria-label="{UI['zh']['seek']}">
          <span class="clock">0:00</span>
          <button type="button" class="speed" aria-label="{UI['zh']['speed']}">1×</button>
        </div>
      </div>
      {''.join(audios)}
    </div>"""
    mini = f'<button type="button" class="play mini" data-play aria-label="{UI["zh"]["play"]}">{PLAY_ICON}</button>'
    return block, mini


def page(folder: Path, share: bool = False, embed: bool | None = None) -> str:
    """share: drop repo links and local paths; embed (default: same as share): inline audio and clips."""
    embed = share if embed is None else embed
    sb = scoreboard(folder)
    arts, tocs, titles = [], [], {}
    for code, attr, _, fname in LANGS:
        text = (folder / fname).read_text(encoding="utf8")
        titles[code] = re.match(r"# (.*)", text).group(1).strip()
        body, heads = render(text, code, share, folder, embed)
        arts.append(f'<article class="report" data-lang="{code}" lang="{attr}"{hide(code)}>{inline_images(body, folder)}</article>')
        links = "".join(f'<li><a href="#{code}-s{i}">{html.escape(h)}</a></li>' for i, h in enumerate(heads, 1))
        tocs.append(f'<nav class="toc" data-lang="{code}" lang="{attr}" aria-label="{UI[code]["contents"]}"{hide(code)}>'
                    f'<p class="toc-title">{UI[code]["contents"]}</p><ol>{links}</ol></nav>')

    def lab(key):
        return "".join(f'<span data-lang="{c}"{hide(c)}>{UI[c][key]}</span>' for c, *_ in LANGS)

    def title_spans():
        return "".join(f'<span data-lang="{c}"{hide(c)}>{html.escape(titles[c])}</span>' for c, *_ in LANGS)
    if sb.get("movement"):
        board = movement_board(sb, lab)
    elif sb.get("training"):
        board = training_board(sb, lab)
    else:
        us, them = sb["final"]
        known = None not in (us, them)
        result = ("win" if us > them else "loss" if us < them else "tie") if known else "unknown"
        halves = [f'<span>{lab(key)}<b>{a}–{b}</b></span>'
                  for key, (a, b) in (("half1", sb["h1"]), ("half2", sb["h2"])) if None not in (a, b)]
        if known:
            halves.append(f'<span>{lab("final")}<b>{us}–{them}</b></span>')
        board = BOARD.format(
            result=result, us_cls="" if not known or us >= them else "lose", them_cls="" if not known or them >= us else "lose",
            us_name=html.escape(sb["us"]), them_name=html.escape(sb["them"]), us_label=lab("us"), them_label=lab("them"),
            us_pts=us if known else "", them_pts=them if known else "", halves="".join(halves))
    (us_hex, us_light), (them_hex, them_light) = sb["colours"]["us"], sb["colours"]["them"]
    buttons = "".join(f'<button type="button" data-set-lang="{c}" lang="{a}" aria-pressed="{str(c == "zh").lower()}">{n}</button>' for c, a, n, _ in LANGS)
    listen, mini = listen_block(folder, embed)
    ui_js = {c: {k: UI[c][k] for k in ("play", "seek", "speed", "switch")} for c, *_ in LANGS}
    return TEMPLATE.format(
        page_title=html.escape(titles["zh"]), titles_js=json.dumps(json.dumps(titles, ensure_ascii=False)).replace("</", "<\\/"),
        ui_js=json.dumps(json.dumps(ui_js, ensure_ascii=False)),
        buttons=buttons, switch=UI["zh"]["switch"], heading=title_spans(), board=board,
        us_hex=us_hex, them_hex=them_hex, us_light=us_light, them_light=them_light,
        us_light_rgb=", ".join(map(str, gc.hex_to_rgb(us_light))),
        listen=listen, mini=mini, tocs="".join(tocs), articles="".join(arts),
    )


TEMPLATE = """<!doctype html>
<html lang="zh-CN" class="no-js">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{page_title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root {{
  --ink: #221f45;        /* page ink + score band */
  --ink-soft: #4a4868;
  --muted: #6c6b84;
  --paper: #f5f5f8;
  --sheet: #ffffff;
  --rule: #dcdce6;
  --us: {us_hex};         /* game.json us.hex */
  --them: {them_hex};       /* game.json them.hex */
  --us-light: {us_light};   /* lighter twins on the dark score band */
  --them-light: {them_light};
  --us-light-rgb: {us_light_rgb};
  --whistle: #c9343f;    /* points we gave away */
  --display: "Barlow Condensed", "Arial Narrow", sans-serif;
  --body: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-padding-top: 4.5rem; }}
body {{ margin: 0; background: var(--paper); color: var(--ink); font: 16px/1.75 var(--body); }}
[hidden] {{ display: none !important; }}

/* sticky title bar with the language switch, then the scoreboard band */
.topbar {{ position: sticky; top: 0; z-index: 10; background: var(--ink); border-bottom: 1px solid #34315c; }}
.bar {{ max-width: 72rem; margin: 0 auto; padding: .6rem 1.25rem; display: flex; align-items: center; gap: .75rem; }}
.bar h1 {{ margin: 0 auto 0 0; font: 500 .95rem/1.4 var(--body); color: #c9c7e6; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }}
.board {{ background: var(--ink); color: #fff; }}
.board-inner {{ max-width: 72rem; margin: 0 auto; padding: .5rem 1.25rem 1.75rem; }}
.lang {{ display: inline-flex; border: 1px solid #5c5a86; border-radius: 999px; padding: 2px; flex: none; }}
.lang button {{ font: 600 0.95rem/1 var(--display); letter-spacing: .02em; color: #c9c7e6; background: none; border: 0;
  border-radius: 999px; padding: .45rem .9rem; cursor: pointer; }}
.lang button[aria-pressed="true"] {{ background: #fff; color: var(--ink); }}
button:focus-visible, a:focus-visible, input:focus-visible {{ outline: 3px solid #f2c94c; outline-offset: 2px; }}
.score {{ display: grid; grid-template-columns: 1fr auto 1fr; align-items: end; gap: 1rem; margin-top: 1.5rem; }}
.team {{ display: flex; flex-direction: column; gap: .15rem; }}
.team.them {{ text-align: right; }}
.team .name {{ font: 600 clamp(1.1rem, 2.6vw, 1.6rem)/1.1 var(--display); }}
.team .side {{ font-size: .8rem; color: #a9a7cc; }}
.team.us .name {{ color: var(--us-light); }}
.team.them .name {{ color: var(--them-light); }}
.pts {{ font: 700 clamp(4rem, 13vw, 8.5rem)/.85 var(--display); font-variant-numeric: tabular-nums; display: flex; gap: .35em; }}
.pts .dash {{ color: #5c5a86; font-weight: 500; }}
.pts .lose {{ color: #8f8db3; }}
.halves {{ display: flex; justify-content: center; gap: 1.75rem; margin-top: .9rem; font-size: .85rem; color: #a9a7cc; }}
.halves b {{ font: 600 1.15rem var(--display); color: #fff; margin-left: .35rem; font-variant-numeric: tabular-nums; }}

/* narration: one big button under the score, a small twin in the sticky bar */
.play {{ flex: none; display: grid; place-items: center; border: 0; border-radius: 50%; cursor: pointer; padding: 0; }}
.play svg {{ fill: currentColor; }}
.play .i-pause, .play.playing .i-play {{ display: none; }}
.play.playing .i-pause {{ display: inline; }}
.play.big {{ width: 5.5rem; height: 5.5rem; background: #fff; color: var(--us); box-shadow: 0 0 0 6px rgba(var(--us-light-rgb), .25); }}
.play.big svg {{ width: 2.6rem; height: 2.6rem; }}
.play.big:hover {{ box-shadow: 0 0 0 9px rgba(var(--us-light-rgb), .35); }}
.play.big.playing {{ background: var(--us-light); color: var(--ink); }}
.play.mini {{ width: 2.1rem; height: 2.1rem; background: #fff; color: var(--us); }}
.play.mini svg {{ width: 1.1rem; height: 1.1rem; }}
.listen {{ display: flex; align-items: center; gap: 1.25rem; max-width: 38rem; margin: 1.75rem auto 0; padding: 1rem 1.25rem;
  border: 1px solid #3d3a6b; border-radius: 1.25rem; background: #2b2856; }}
.listen-body {{ flex: 1; min-width: 0; }}
.listen-label b {{ display: block; font-size: 1.15rem; }}
.listen-label small {{ color: #a9a7cc; font-size: .85rem; }}
.listen-track {{ display: flex; align-items: center; gap: .75rem; margin-top: .5rem; }}
.listen {{ flex-wrap: wrap; }}
.listen audio[controls] {{ flex-basis: 100%; width: 100%; }}
.no-js .play, .no-js .listen-track {{ display: none; }}
.seek {{ flex: 1; min-width: 0; accent-color: var(--us-light); }}
.clock {{ font: 600 1rem var(--display); font-variant-numeric: tabular-nums; color: #c9c7e6; min-width: 3.2rem; text-align: right; }}
.speed {{ font: 600 .95rem/1 var(--display); color: #c9c7e6; background: none; border: 1px solid #5c5a86; border-radius: 999px;
  padding: .35rem .6rem; cursor: pointer; min-width: 3.2rem; }}

/* body */
.layout {{ max-width: 72rem; margin: 0 auto; padding: 0 1.25rem 4rem; display: grid; grid-template-columns: 1fr; gap: 2rem; }}
@media (min-width: 1080px) {{ .layout {{ grid-template-columns: 14rem minmax(0, 46rem); justify-content: center; }} }}
.toc {{ display: none; }}
@media (min-width: 1080px) {{
  .toc {{ display: block; position: sticky; top: 4.5rem; align-self: start; margin-top: 2.5rem; font-size: .88rem; }}
  .toc[hidden] {{ display: none; }}
}}
.toc-title {{ color: var(--muted); margin: 0 0 .5rem; }}
.toc ol {{ list-style: none; margin: 0; padding: 0; border-left: 2px solid var(--rule); }}
.toc a {{ display: block; padding: .3rem 0 .3rem .9rem; color: var(--ink-soft); text-decoration: none; margin-left: -2px; border-left: 2px solid transparent; }}
.toc a:hover {{ color: var(--us); border-left-color: var(--us); }}

.layout > main {{ min-width: 0; }}
.report {{ padding-top: 2rem; min-width: 0; }}
.report > p:first-child {{ color: var(--muted); font-size: .92rem; }}
.report > p:nth-child(2) {{ font-size: 1.12rem; line-height: 1.8; border-left: 4px solid var(--whistle); padding: .2rem 0 .2rem 1.1rem; margin: 1.5rem 0; }}
.report h2 {{ font: 700 clamp(1.5rem, 3.2vw, 2rem)/1.2 var(--display); letter-spacing: .01em; margin: 3.25rem 0 1rem;
  padding-top: 1.25rem; border-top: 3px solid var(--ink); }}
.report[lang="zh-CN"] h2 {{ font-family: var(--body); font-weight: 700; font-size: clamp(1.3rem, 2.8vw, 1.65rem); }}
.report h3 {{ font-size: 1.08rem; margin: 2rem 0 .6rem; color: var(--ink); }}
.report p, .report li {{ max-width: 42rem; }}
.report ul, .report ol {{ padding-left: 1.3rem; }}
.report li {{ margin: .3rem 0; }}
.report li::marker {{ color: var(--us); font-weight: 700; }}
.report strong {{ color: var(--ink); font-weight: 700; }}
.report a {{ color: var(--us); text-underline-offset: 3px; }}
.report code {{ font-size: .85em; background: #ebebf2; padding: .1em .35em; border-radius: 4px; word-break: break-all; }}
.report hr {{ display: none; }}
.figure {{ margin: 1.5rem 0; overflow-x: auto; background: #fff; border: 1px solid var(--rule); border-radius: 6px; }}
.figure img {{ display: block; width: 100%; height: auto; }}

/* film clips next to the analysis */
.clip {{ margin: 1.25rem 0 1.75rem; background: #000; border-radius: 6px; overflow: hidden; max-width: 42rem; }}
.clip video {{ display: block; width: 100%; aspect-ratio: 16 / 9; background: #000; }}
.clip-bar {{ display: flex; align-items: flex-start; gap: .75rem; padding: .6rem .8rem; background: var(--ink); color: #e6e5f5; }}
.clip figcaption {{ flex: 1; min-width: 0; font-size: .9rem; line-height: 1.55; }}
.clip-no {{ display: block; font: 600 .95rem/1.3 var(--display); letter-spacing: .03em; color: var(--us-light); font-variant-numeric: tabular-nums; }}
.slow {{ flex: none; font: 600 .85rem/1 var(--body); color: #c9c7e6; background: none; border: 1px solid #5c5a86; border-radius: 999px;
  padding: .4rem .7rem; cursor: pointer; }}
.slow[aria-pressed="true"] {{ background: var(--us-light); color: var(--ink); border-color: var(--us-light); }}
.no-js .slow {{ display: none; }}
.clip.missing {{ background: #fff4f4; border: 1px dashed var(--whistle); padding: .6rem .8rem; }}
.clip.missing .clip-no {{ color: var(--whistle); }}
.clip.missing p {{ margin: .3rem 0 0; color: var(--whistle); font-size: .85rem; }}
td .clip {{ min-width: 16rem; margin: .25rem 0; }}

.table-wrap {{ overflow-x: auto; margin: 1.25rem 0; background: var(--sheet); border: 1px solid var(--rule); border-radius: 6px; }}
table {{ border-collapse: collapse; width: 100%; font-size: .9rem; line-height: 1.55; }}
th, td {{ text-align: left; vertical-align: top; padding: .55rem .75rem; border-bottom: 1px solid var(--rule); }}
th {{ font-weight: 700; color: var(--ink-soft); background: #f0f0f5; white-space: nowrap; }}
tr:last-child td {{ border-bottom: 0; }}
td:first-child {{ white-space: nowrap; font-variant-numeric: tabular-nums; }}
td strong {{ color: var(--whistle); }}

@media (max-width: 560px) {{
  body {{ font-size: 15px; }}
  .halves {{ gap: 1rem; flex-wrap: wrap; }}
  .figure img {{ width: 760px; max-width: none; }}  /* chart text stays readable; swipe sideways */
  .listen {{ gap: .9rem; padding: .85rem; }}
  .play.big {{ width: 4.5rem; height: 4.5rem; }}
}}
@media (prefers-reduced-motion: no-preference) {{
  .play.big {{ transition: box-shadow .2s, background-color .2s; }}
}}
@media print {{
  .lang, .toc, .listen, .play, .slow {{ display: none !important; }}
  .board {{ background: none; color: var(--ink); }}
  .team.us .name, .team.them .name, .halves b {{ color: var(--ink); }}
}}
</style>
</head>
<body>
<div class="topbar">
  <div class="bar">
    <h1>{heading}</h1>
    {mini}
    <div class="lang" role="group" aria-label="{switch}">{buttons}</div>
  </div>
</div>
<header class="board">
  <div class="board-inner">
    {board}
    {listen}
  </div>
</header>
<div class="layout">
  {tocs}
  <main>{articles}</main>
</div>
<script>
(() => {{
  const titles = JSON.parse({titles_js});
  const ui = JSON.parse({ui_js});
  const buttons = document.querySelectorAll("[data-set-lang]");
  const playBtns = document.querySelectorAll("[data-play]");
  const seek = document.querySelector(".seek"), clock = document.querySelector(".clock"), speedBtn = document.querySelector(".speed");
  const audios = {{ zh: document.getElementById("audio-zh"), en: document.getElementById("audio-en") }};
  const speeds = [1, 1.25, 1.5];
  let lang = "zh", speed = 0;
  const fmt = s => Math.floor(s / 60) + ":" + String(Math.floor(s % 60)).padStart(2, "0");
  document.documentElement.classList.remove("no-js");

  // Embedded audio: a Blob URL seeks and reports duration more reliably than a multi-MB data: URI in in-app webviews.
  function toBlob(a, type) {{
    const s = a.getAttribute("src") || "";
    if (!s.startsWith("data:")) return;
    try {{
      const bin = atob(s.slice(s.indexOf(",") + 1)), buf = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
      a.src = URL.createObjectURL(new Blob([buf], {{ type: type || "audio/mpeg" }}));
    }} catch (e) {{}}
  }}
  function showNative(a) {{ a.controls = true; a.classList.add("fallback"); }}
  Object.values(audios).forEach(a => {{ if (a) {{ a.controls = false; toBlob(a); }} }});

  function syncAudio() {{
    const a = audios[lang];
    if (!a) return;
    playBtns.forEach(b => b.classList.toggle("playing", !a.paused));
    if (isFinite(a.duration)) seek.max = Math.floor(a.duration);
    seek.value = Math.floor(a.currentTime);
    clock.textContent = fmt(a.paused && !a.currentTime && isFinite(a.duration) ? a.duration : a.currentTime);
  }}
  Object.values(audios).forEach(a => a && ["play", "pause", "timeupdate", "loadedmetadata", "ended"].forEach(ev => a.addEventListener(ev, syncAudio)));
  playBtns.forEach(b => b.addEventListener("click", () => {{
    const a = audios[lang];
    if (!a) return;
    if (!a.paused) return a.pause();
    const p = a.play();
    if (p && p.catch) p.catch(() => showNative(a));  // blocked custom player: fall back to the browser's own controls
  }}));
  Object.values(audios).forEach(a => a && a.addEventListener("error", () => showNative(a)));

  // clips: one thing plays at a time (narration or one clip); the slow-mo button halves the speed
  const videos = document.querySelectorAll(".clip video");
  videos.forEach(v => {{
    toBlob(v, "video/mp4");
    v.addEventListener("play", () => {{
      Object.values(audios).forEach(a => a && a.pause());
      videos.forEach(o => {{ if (o !== v) o.pause(); }});
    }});
  }});
  Object.values(audios).forEach(a => a && a.addEventListener("play", () => videos.forEach(v => v.pause())));
  document.querySelectorAll("[data-slow]").forEach(b => b.addEventListener("click", () => {{
    const v = b.closest(".clip").querySelector("video"), on = b.getAttribute("aria-pressed") !== "true";
    v.defaultPlaybackRate = v.playbackRate = on ? 0.5 : 1;  // default survives the first load of a preload="none" video
    b.setAttribute("aria-pressed", String(on));
  }}));
  seek?.addEventListener("input", () => {{ audios[lang].currentTime = Number(seek.value); }});
  speedBtn?.addEventListener("click", () => {{
    speed = (speed + 1) % speeds.length;
    Object.values(audios).forEach(a => {{ if (a) a.playbackRate = speeds[speed]; }});
    speedBtn.textContent = speeds[speed] + "×";
  }});

  function currentSection() {{
    const heads = document.querySelectorAll('.report:not([hidden]) h2');
    let idx = 0;
    heads.forEach((h, i) => {{ if (h.getBoundingClientRect().top < 120) idx = i + 1; }});
    return idx;
  }}
  function setLang(next, keepPlace) {{
    if (!titles[next]) next = "zh";
    const section = keepPlace ? currentSection() : 0;
    if (next !== lang && audios[lang]) audios[lang].pause();  // the two narrations are different scripts
    document.querySelectorAll(".clip video").forEach(v => v.pause());
    lang = next;
    document.querySelectorAll("[data-lang]").forEach(el => {{ el.hidden = el.dataset.lang !== lang; }});
    buttons.forEach(b => b.setAttribute("aria-pressed", String(b.dataset.setLang === lang)));
    playBtns.forEach(b => b.setAttribute("aria-label", ui[lang].play));
    seek?.setAttribute("aria-label", ui[lang].seek);
    speedBtn?.setAttribute("aria-label", ui[lang].speed);
    document.querySelector(".lang").setAttribute("aria-label", ui[lang].switch);
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    document.title = titles[lang];
    try {{ localStorage.setItem("report-lang", lang); }} catch (e) {{}}
    const url = new URL(location.href); url.searchParams.set("lang", lang);
    if (keepPlace && /^#(zh|en)-s\\d+$/.test(url.hash)) url.hash = section ? lang + "-s" + section : "";
    history.replaceState(null, "", url);
    if (section) document.getElementById(lang + "-s" + section)?.scrollIntoView();
    syncAudio();
  }}
  buttons.forEach(b => b.addEventListener("click", () => setLang(b.dataset.setLang, true)));
  const fromHash = location.hash.match(/^#(zh|en)-s\\d+$/);
  let start = fromHash ? fromHash[1] : new URLSearchParams(location.search).get("lang");
  if (!start) {{ try {{ start = localStorage.getItem("report-lang"); }} catch (e) {{}} }}
  if (!start && !/^zh/i.test(navigator.language || "")) start = "en";
  setLang(start || "zh", false);
  if (fromHash) document.querySelector(location.hash)?.scrollIntoView();  // target was hidden at load
  const clipHash = location.hash.match(/^#clip-([0-9_-]+)$/);  // language-free link to a clip
  if (clipHash) document.getElementById(lang + "-clip-" + clipHash[1])?.scrollIntoView();
}})();
</script>
</body>
</html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out", default="index.html", help="file name in the folder, or an absolute path")
    ap.add_argument("--share", action="store_true", help="copy to send to others: drop repo links and local paths, embed audio and clips")
    a = ap.parse_args(argv)
    folder = Path(a.folder)
    out = folder / a.out
    out.write_text(page(folder, a.share), encoding="utf8")
    print("wrote", out, f"{out.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
