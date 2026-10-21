"""Shot chart and playlists from the reviewed trips, for the team page and the focus player's page.

Reads the review's coach_part*.json trips (schema v2, see coach_schema) through game.json (`run`, `review_dir`;
default <game>/run/review_v1). Each shot, turnover and foul with a video time becomes an event with one short clip
window; `hoop-tape-miner clips` cuts those windows next to the README clips (same `clips/<from>-<to>.mp4` names, cut
once, shared by the chart and the playlists) and `hoop-tape-miner html` adds two sections to each language:

- Shot chart: a half court (inline SVG) with one dot per reviewed shot in its zone (filled = made, ring = missed,
  dashed ring = make/miss unclear, never guessed), zones shaded by points per shot over the shots whose outcome is
  known, a zone table, filters (team / player / half) and a player under the chart: a dot plays its clip.
- Playlists: per player (their shots and fouls) and per theme (our turnovers, live-ball turnovers when the trips
  carry `turnover_kind`, fouls we gave, their scores, transition defence when they carry `transition`, our offensive
  rebounds), each a list of captioned clips played in sequence in one <video>. At most MAX_PLAYLIST clips per
  playlist (the earliest ones), so a page stays a few dozen clips.

Times: shot.t / foul.t, else the first evidence time of that field; a turnover uses evidence.result. Trips without
a time fall back to the v1 `key_clip` window; with neither they stay on the chart without a clip.
A page with no review (or no game.json run) gets neither section. --share pages (one file) get the chart without
clips and no playlists, so the file stays small; the published page links the clip files.
"""
from __future__ import annotations

import html
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import game_config as gc
from .coach_eval import load_trips
from .timefmt import mmss

MAX_PLAYLIST = 12                 # clips per playlist (earliest first); keeps a published page to a few dozen clips
PAD = {"shot": (6, 2), "turnover": (5, 2), "foul": (4, 2), "oreb": (1, 6)}   # seconds before / after the event
MAX_WINDOW = 12                   # key_clip fallback windows are cut to this many seconds
ZONES = ("rim", "paint_non_rim", "midrange", "three")

UI = {
    "zh": dict(chart="投篮分布", lists="片段合集", team="球队", player="球员", half="半场", all="全部", game="全场",
               half1="上半场", half2="下半场", us="我们", them="对手", made="命中", missed="未进", unknown="进没进看不清",
               unknown_player="号码不明", zone="区域", att="命中 / 出手", unclear_n="不明", pps="每次出手得分",
               no_zone="位置不明", rim="篮下", paint_non_rim="油漆区", midrange="中距离", three="三分",
               clips="段", no_clip="无片段", pick="点一个点看这次出手", embed_note="片段在发布的链接里可以点开看。",
               chart_note="来自复看的每一次出手（不含罚球）。每次出手得分只算看清进没进的出手；看不清的单独标出，不算进也不算没进。",
               shown="显示前 {n} 段，共 {total} 段", lists_note="每个合集连续播放；点任一条跳到那一段。",
               turnover="失误", foul="犯规", fouled="被犯规", shot="出手", by="", now="正在播放",
               t_turnovers="我们的失误", t_live="活球失误", t_fouls="我们的犯规", t_their_scores="对手得分",
               t_transition="转换防守", t_oreb="我们的进攻篮板", p_shots="{p} 的出手", p_fouls="{p} 的犯规",
               open="空位", contested="有干扰", heavily_contested="强干扰",
               layup="上篮", floater="抛投", pullup_mid="急停中投", catch_shoot_mid="接球中投", three_catch="接球三分",
               three_pullup="运球三分", post="背身", putback="补篮"),
    "en": dict(chart="Shot chart", lists="Playlists", team="Team", player="Player", half="Half", all="All", game="Game",
               half1="1st half", half2="2nd half", us="Us", them="Them", made="made", missed="missed",
               unknown="make/miss unclear", unknown_player="number unclear", zone="Zone", att="Made / att",
               unclear_n="Unclear", pps="Points per shot", no_zone="Zone unclear", rim="Rim", paint_non_rim="Paint",
               midrange="Mid-range", three="Three", clips="clips", no_clip="no clip", pick="Tap a dot to watch that shot",
               embed_note="On the published link every dot opens its clip.",
               chart_note="Every reviewed shot (free throws not included). Points per shot counts only shots whose "
                          "make or miss was seen; unclear ones are shown apart, never counted either way.",
               shown="first {n} of {total} clips", lists_note="Each playlist plays straight through; tap a line to jump.",
               turnover="turnover", foul="foul", fouled="fouled", shot="shot", by="by", now="Now playing",
               t_turnovers="Our turnovers", t_live="Live-ball turnovers", t_fouls="Fouls we gave",
               t_their_scores="Their scores", t_transition="Transition defence", t_oreb="Our offensive rebounds",
               p_shots="{p} shots", p_fouls="{p} fouls",
               open="open", contested="contested", heavily_contested="heavily contested",
               layup="layup", floater="floater", pullup_mid="pull-up jumper", catch_shoot_mid="catch-and-shoot jumper",
               three_catch="catch-and-shoot three", three_pullup="pull-up three", post="post-up", putback="putback"),
}


@dataclass
class Event:
    kind: str                     # shot | turnover | foul
    team: str                     # shot / turnover: the offence; foul: the team that fouled
    player: str | None            # shooter or fouler jersey ("13"), None when unclear
    t: float | None               # video seconds of the event
    half: int | None
    window: tuple[str, str] | None  # clip window (mm:ss, mm:ss)
    zone: str | None = None
    made: bool | None = None
    points: int | None = None
    type: str | None = None
    contested: str | None = None
    on: str | None = None         # foul: the player fouled
    tags: set = field(default_factory=set)
    pid: object = None

    @property
    def pts(self) -> int:
        """Points this shot scored (0 when missed or unclear)."""
        if self.made is not True:
            return 0
        return self.points or (3 if self.zone == "three" else 2)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _first(*vals):
    for v in vals:
        if isinstance(v, list):
            v = next((x for x in v if _num(x)), None)
        if _num(v):
            return float(v)
    return None


def _window(t: float | None, kind: str, key_clip) -> tuple[str, str] | None:
    if t is not None:
        before, after = PAD[kind]
        return mmss(math.floor(max(0.0, t - before))), mmss(math.ceil(t + after))
    if isinstance(key_clip, dict) and _num(key_clip.get("t0")) and _num(key_clip.get("t1")) and key_clip["t1"] > key_clip["t0"]:
        a = max(0.0, key_clip["t0"] - 1)
        return mmss(math.floor(a)), mmss(math.ceil(min(key_clip["t1"] + 1, a + MAX_WINDOW)))
    return None


def half_of(t: float | None, periods) -> int | None:
    """1 or 2 from game.json periods (2 halves, or 4 quarters); the nearest period when t is in a break."""
    if t is None or not periods:
        return None
    try:
        spans = [(float(a), float(b)) for a, b in periods]
    except (TypeError, ValueError):
        return None
    i = min(range(len(spans)), key=lambda k: 0 if spans[k][0] <= t <= spans[k][1]
            else min(abs(t - spans[k][0]), abs(t - spans[k][1])))
    return 1 if i < max(1, len(spans) // 2) else 2


def _jersey(v) -> str | None:
    return str(v) if v is not None and re.fullmatch(r"\d{1,2}", str(v)) else None


def events(trips: list[dict], periods=None) -> list[Event]:
    """Shots, turnovers and fouls of the trips, in video order."""
    out = []
    for x in trips:
        if not isinstance(x, dict):
            continue
        ev = x.get("evidence") if isinstance(x.get("evidence"), dict) else {}
        off, kc = x.get("offence"), x.get("key_clip")
        tags = set()
        if x.get("transition") is True:
            tags.add("transition")
        oreb = x.get("oreb_crash") if isinstance(x.get("oreb_crash"), dict) else {}
        if off == "us" and "us" in (oreb.get("got"), oreb.get("rebound")):
            tags.add("oreb")
        shot = x.get("shot") if isinstance(x.get("shot"), dict) else None
        if shot and off in gc.SIDES:
            t = _first(shot.get("t"), ev.get("shot"))
            out.append(Event("shot", off, _jersey(shot.get("shooter")), t, half_of(t, periods), _window(t, "shot", kc),
                             zone=shot.get("zone") if shot.get("zone") in ZONES else None,
                             made=shot.get("made") if shot.get("made") in (True, False) else None,
                             points=shot.get("points") if shot.get("points") in (2, 3) else None,
                             type=shot.get("type"), contested=shot.get("contested"), tags=set(tags), pid=x.get("pid")))
            if "oreb" in tags:
                out.append(Event("oreb", off, None, t, half_of(t, periods), _window(t, "oreb", kc), pid=x.get("pid")))
        if x.get("result") == "turnover" and off in gc.SIDES:
            t = _first(ev.get("result"))
            if x.get("turnover_kind") in ("live", "dead"):
                tags.add(x["turnover_kind"])
            out.append(Event("turnover", off, _jersey(x.get("turnover_by")), t, half_of(t, periods),
                             _window(t, "turnover", kc), tags=set(tags), pid=x.get("pid")))
        foul = x.get("foul") if isinstance(x.get("foul"), dict) else None
        if foul and foul.get("by_team") in gc.SIDES:
            t = _first(foul.get("t"), ev.get("foul"))
            out.append(Event("foul", foul["by_team"], _jersey(foul.get("by")), t, half_of(t, periods),
                             _window(t, "foul", None if shot else kc), type=foul.get("type"),
                             on=_jersey(foul.get("on")), tags=set(tags), pid=x.get("pid")))
    return sorted(out, key=lambda e: (e.t is None, e.t or 0))


# ---- which events a report folder shows -------------------------------------------------------------------------

def run_dir(folder: Path) -> Path | None:
    """The run folder (game.json `run`, default <game>/run) of the game this report belongs to, or None."""
    gj = gc.find_up(folder)
    if gj is None:
        return None
    game = json.loads(gj.read_text(encoding="utf8"))
    if gc.is_personal(game):
        return None
    run = Path(game["run"]) if game.get("run") else gj.parent / "run"
    return run if run.is_absolute() else gj.parent / run


def review_dir(folder: Path) -> Path | None:
    """The review folder of the game this report belongs to, or None."""
    run = run_dir(folder)
    if run is None:
        return None
    review_name = gc.load_game(folder).get("review_dir")
    review = run / review_name if review_name else run / "review_v1"
    return review if review.is_dir() else None


def focus_of(folder: Path) -> str | None:
    m = re.fullmatch(r"player-(\w+)", Path(folder).name)
    return m.group(1) if m else None


@dataclass
class Playlist:
    key: str
    title: dict                   # lang -> title
    items: list                   # Events with a window, video order, capped
    total: int                    # before the cap


def _title(key: str, p: str | None = None) -> dict:
    return {c: UI[c][key].format(p=f"#{p}") for c in UI}


def _playlist(key, title, evs) -> Playlist | None:
    evs = [e for e in evs if e.window]
    return Playlist(key, title, evs[:MAX_PLAYLIST], len(evs)) if evs else None


def index(folder: Path) -> dict | None:
    """{"shots": [Event], "playlists": [Playlist], "focus": jersey|None} for the report folder; None without trips."""
    review = review_dir(folder) if Path(folder).is_dir() else None
    if review is None:
        return None
    trips = load_trips(review)
    if not trips:
        return None
    game = gc.load_game(folder)
    evs = events(trips, game.get("periods"))
    focus = focus_of(folder)
    shots = [e for e in evs if e.kind == "shot"]
    lists = []
    if focus:
        shots = [e for e in shots if e.team == "us" and e.player == focus]
        lists.append(_playlist("p-shots", _title("p_shots", focus), shots))
        lists.append(_playlist("p-fouls", _title("p_fouls", focus),
                               [e for e in evs if e.kind == "foul" and ((e.team == "us" and e.player == focus)
                                                                         or (e.team == "them" and e.on == focus))]))
    else:
        roster = [str(n) for n in (game.get("rosters") or {}).get("us", [])]
        seen = {e.player for e in evs if e.team == "us" and e.player and e.kind in ("shot", "foul")}
        for p in roster + sorted(seen - set(roster), key=lambda s: int(s)):
            if p in seen:
                lists.append(_playlist(f"p{p}", {c: f"#{p}" for c in UI},
                                       [e for e in evs if e.team == "us" and e.player == p and e.kind in ("shot", "foul")]))
        tos = [e for e in evs if e.kind == "turnover" and e.team == "us"]
        if any("live" in e.tags or "dead" in e.tags for e in tos):
            lists.append(_playlist("live", _title("t_live"), [e for e in tos if "live" in e.tags]))
        lists.append(_playlist("turnovers", _title("t_turnovers"), tos))
        lists.append(_playlist("fouls", _title("t_fouls"), [e for e in evs if e.kind == "foul" and e.team == "us"]))
        lists.append(_playlist("transition", _title("t_transition"),
                               [e for e in evs if e.kind == "shot" and e.team == "them" and "transition" in e.tags]))
        lists.append(_playlist("their-scores", _title("t_their_scores"),
                               [e for e in evs if e.kind == "shot" and e.team == "them" and e.made is True]))
        lists.append(_playlist("oreb", _title("t_oreb"), [e for e in evs if e.kind == "oreb"]))
    return {"shots": shots, "playlists": [p for p in lists if p], "focus": focus}


def windows(folder: Path) -> list[tuple[str, str]]:
    """Clip windows the shot chart and playlists of this folder need (each once, video order)."""
    try:
        ix = index(folder)
    except (OSError, ValueError, KeyError) as ex:  # a half-written review must not stop the README clips
        print(f"warning: no shot chart / playlist clips for {folder} ({ex})")
        return []
    if not ix:
        return []
    seen = {}
    for e in ix["shots"] + [e for p in ix["playlists"] for e in p.items]:
        if e.window:
            seen.setdefault(e.window, None)
    return list(seen)


# ---- HTML ---------------------------------------------------------------------------------------------------------

def caption(e: Event, lang: str, team_names: dict | None = None) -> str:
    u = UI[lang]
    who = f"#{e.player}" if e.player else u["unknown_player"]
    when = mmss(e.t) if e.t is not None else ""
    side = (team_names or {}).get(e.team) or u[e.team]
    sep = "，" if lang == "zh" else ", "
    if e.kind == "shot":
        bits = [u.get(e.zone, u["no_zone"]) if e.zone else u["no_zone"]]
        if e.type in u:
            bits.append(u[e.type])
        if e.contested in u:
            bits.append(u[e.contested])
        res = u["made"] if e.made is True else u["missed"] if e.made is False else u["unknown"]
        if e.made is True:
            res += f" +{e.pts}"
        text = f"{side} {who} {' '.join(bits) if lang == 'en' else ''.join(bits)}{sep}{res}"
    elif e.kind == "turnover":
        text = f"{side} {u['turnover']}" + (f" {who}" if e.player else "")
    elif e.kind == "oreb":
        text = UI[lang]["t_oreb"]
    else:
        on = f"{sep}{u['fouled']} #{e.on}" if e.on else ""
        text = f"{side} {who} {u['foul']}{on}"
    return f"{when} · {text}" if when else text


# Half court in decimetres (FIBA): 150 wide, baseline at y=0, basket centre 15.75 from it, 3-point arc r=67.5
# meeting the corner lines 9 from each sideline, paint 49 wide x 58 deep, "rim" zone = 2 m around the basket.
COURT_W, COURT_H = 150, 140
ARC_IN = "M9 0 L9 29.9 A67.5 67.5 0 1 0 141 29.9 L141 0 Z"
PAINT = "M50.5 0 H99.5 V58 H50.5 Z"
RIM_ZONE = "M62.67 0 A20 20 0 1 0 87.33 0 Z"
ZONE_PATHS = {"three": f"M0 0 H150 V140 H0 Z {ARC_IN}", "midrange": f"{ARC_IN} {PAINT}",
              "paint_non_rim": f"{PAINT} {RIM_ZONE}", "rim": RIM_ZONE}
LINES = (f'<path d="M0 0 H150 V140 H0 Z"/><path d="{PAINT}"/><path d="M9 0 L9 29.9 A67.5 67.5 0 1 0 141 29.9 L141 0"/>'
         '<path d="M57 58 A18 18 0 0 0 93 58"/><path d="M66 12 H84"/><circle cx="75" cy="15.75" r="2.25"/>')
# dot grid per zone: centre x, first row y, dots per row (the script lays out the visible dots the same way)
ANCHORS = {"rim": (75, 21, 7), "paint_non_rim": (75, 42, 9), "midrange": (75, 64, 11), "three": (75, 92, 15)}
STEP, DOT_R = 4.6, 1.8


def layout(zone: str, i: int) -> tuple[float, float]:
    cx, y0, cols = ANCHORS[zone]
    row, col = divmod(i, cols)
    n_row = cols
    return round(cx + (col - (n_row - 1) / 2) * STEP, 2), round(y0 + row * STEP, 2)


def zone_stats(shots: list[Event]) -> dict:
    """zone -> {att, made, missed, unknown, pts, pps}; pps over shots with a known outcome (None when none)."""
    out = {}
    for z in (*ZONES, None):
        s = [e for e in shots if e.zone == z]
        made = sum(e.made is True for e in s)
        missed = sum(e.made is False for e in s)
        pts = sum(e.pts for e in s)
        out[z] = dict(att=len(s), made=made, missed=missed, unknown=len(s) - made - missed, pts=pts,
                      pps=round(pts / (made + missed), 2) if made + missed else None)
    return out


def _clip_attrs(e: Event, folder: Path | None, embed: bool, lang: str, names: dict) -> tuple[str, str]:
    """(href attrs, caption) for an event: data-src / data-poster when its clip file exists and pages link files."""
    cap = caption(e, lang, names)
    if embed or not e.window or folder is None:
        return "", cap
    from .clips import clip_path, poster_of
    mp4 = clip_path(folder, *e.window)
    if not mp4.exists():
        return "", cap
    rel = f"clips/{mp4.name}"
    jpg = poster_of(mp4)
    poster = f' data-poster="clips/{jpg.name}"' if jpg.exists() else ""
    return f' href="{rel}" data-src="{rel}"{poster}', cap


def chart_html(ix: dict, folder: Path | None, lang: str, embed: bool, hid: str, names: dict) -> str:
    u = UI[lang]
    shots, focus = ix["shots"], ix["focus"]
    default_team = "us"
    dots, counts = [], {}
    for e in shots:
        attrs, cap = _clip_attrs(e, folder, embed, lang, names)
        z = e.zone or "none"
        shown = e.team == default_team
        made = "1" if e.made is True else "0" if e.made is False else "u"
        if z != "none" and shown:
            i = counts[z] = counts.get(z, -1) + 1
            x, y = layout(z, i)
        else:
            x, y = -10, -10
        cls = f"fi-dot {e.team} m{made}" + ("" if shown else " fi-off") + ("" if attrs else " noclip")
        data = (f'data-team="{e.team}" data-player="{e.player or ""}" data-half="{e.half or ""}" data-zone="{z}" '
                f'data-made="{made}" data-pts="{e.pts}" data-cap="{html.escape(cap)}"')
        mark = f'<circle cx="{x}" cy="{y}" r="{DOT_R}"/><title>{html.escape(cap)}</title>'
        if z == "none":
            dots.append(("none", f'<a class="{cls}" {data}{attrs}><svg viewBox="-3 -3 6 6" aria-hidden="true">'
                                 f'<circle r="{DOT_R}"/></svg><span>{html.escape(cap)}</span></a>'))
        else:
            dots.append((z, f'<a class="{cls}" {data}{attrs}>{mark}</a>'))
    st = zone_stats([e for e in shots if e.team == default_team])
    zones = "".join(f'<path class="fi-zone {default_team}" data-zone="{z}" fill-rule="evenodd" d="{ZONE_PATHS[z]}" '
                    f'style="fill-opacity:{_shade(st[z]["pps"])}"><title>{u[z]}</title></path>' for z in reversed(ZONES))
    svg = (f'<svg class="fi-court" viewBox="-2 -2 154 144" role="img" aria-label="{u["chart"]}">'
           f'{zones}<g class="fi-lines">{LINES}</g><g class="fi-dots">{"".join(d for z, d in dots if z != "none")}</g></svg>')
    unzoned = "".join(d for z, d in dots if z == "none")
    rows = "".join(f'<tr data-zone="{z or "none"}"><td>{u[z] if z else u["no_zone"]}</td><td>{_ma(st[z])}</td>'
                   f'<td>{st[z]["unknown"] or "–"}</td><td>{_pps(st[z]["pps"])}</td></tr>' for z in (*ZONES, None))
    table = (f'<div class="table-wrap"><table class="fi-table"><thead><tr><th>{u["zone"]}</th><th>{u["att"]}</th>'
             f'<th>{u["unclear_n"]}</th><th>{u["pps"]}</th></tr></thead><tbody>{rows}</tbody></table></div>')
    filters = []
    if not focus:
        filters.append(f'<label>{u["team"]} <select data-f="team"><option value="us">{html.escape(names.get("us") or u["us"])}'
                       f'</option><option value="them">{html.escape(names.get("them") or u["them"])}</option></select></label>')
        opts = "".join(f'<option value="{t}:{p}"{"" if t == default_team else " hidden"}>#{p}</option>'
                       for t, p in sorted({(e.team, e.player) for e in shots if e.player},
                                          key=lambda tp: (tp[0] != "us", int(tp[1]))))
        filters.append(f'<label>{u["player"]} <select data-f="player"><option value="">{u["all"]}</option>{opts}</select></label>')
    if any(e.half for e in shots):
        filters.append(f'<label>{u["half"]} <select data-f="half"><option value="">{u["game"]}</option>'
                       f'<option value="1">{u["half1"]}</option><option value="2">{u["half2"]}</option></select></label>')
    legend = (f'<p class="fi-legend"><span class="k m1"></span>{u["made"]} <span class="k m0"></span>{u["missed"]} '
              f'<span class="k mu"></span>{u["unknown"]}</p>')
    player = ("" if embed else f'<figure class="fi-player clip"><video controls playsinline preload="none"></video>'
                               f'<div class="clip-bar"><figcaption>{u["pick"]}</figcaption></div></figure>')
    note = u["chart_note"] + (" " + u["embed_note"] if embed else "")
    return (f'<h2 id="{hid}">{u["chart"]}</h2><div class="film-index" data-film-chart data-lang-code="{lang}">'
            f'<p class="fi-note">{note}</p><div class="fi-filters">{"".join(filters)}</div>{legend}{svg}'
            f'<div class="fi-unzoned"><b>{u["no_zone"]}</b>{unzoned}</div>{table}{player}</div>')


def _shade(pps) -> float:
    return 0.05 if pps is None else round(0.1 + 0.5 * min(pps / 1.5, 1.0), 2)


def _ma(s: dict) -> str:
    return f'{s["made"]}/{s["made"] + s["missed"]}' if s["att"] else "–"


def _pps(v) -> str:
    return "–" if v is None else f"{v:.2f}"


def playlists_html(ix: dict, folder: Path, lang: str, hid: str, names: dict) -> str:
    u = UI[lang]
    blocks = []
    for pl in ix["playlists"]:
        items = []
        for e in pl.items:
            attrs, cap = _clip_attrs(e, folder, False, lang, names)
            if attrs:
                items.append(f'<li><a{attrs}>{html.escape(cap)}</a></li>')
        if not items:
            continue
        more = f' · {u["shown"].format(n=len(items), total=pl.total)}' if pl.total > len(pl.items) else ""
        blocks.append(f'<div class="fi-list" id="{lang}-pl-{pl.key}"><h3>{html.escape(pl.title[lang])} '
                      f'<small>{len(items)} {u["clips"]}{more}</small></h3>'
                      f'<figure class="clip"><video controls playsinline preload="none"></video>'
                      f'<div class="clip-bar"><figcaption class="fi-now"></figcaption></div></figure>'
                      f'<ol>{"".join(items)}</ol></div>')
    if not blocks:
        return ""
    return (f'<h2 id="{hid}">{u["lists"]}</h2><div class="film-lists" data-film-lists>'
            f'<p class="fi-note">{u["lists_note"]}</p>{"".join(blocks)}</div>')


def sections(folder: Path, lang: str, embed: bool, first: int) -> tuple[str, list[str]]:
    """(HTML, h2 titles) of the shot chart and playlists for one language; h2 ids continue at <lang>-s<first>."""
    try:
        ix = index(folder)
    except (OSError, ValueError, KeyError) as ex:
        print(f"warning: no shot chart / playlists ({ex})")
        return "", []
    if not ix:
        return "", []
    game = gc.load_game(folder)
    names = {s: gc.team(game, s).get("team") for s in gc.SIDES}
    out, heads = [], []
    if ix["shots"]:
        out.append(chart_html(ix, folder, lang, embed, f"{lang}-s{first + len(heads)}", names))
        heads.append(UI[lang]["chart"])
    if not embed:
        pl = playlists_html(ix, folder, lang, f"{lang}-s{first + len(heads)}", names)
        if pl:
            out.append(pl)
            heads.append(UI[lang]["lists"])
    return "".join(out), heads


ASSETS = """<style>
.film-index, .film-lists { max-width: 42rem; }
.fi-note { color: var(--muted); font-size: .9rem; }
.fi-filters { display: flex; flex-wrap: wrap; gap: .5rem 1rem; margin: .75rem 0; font-size: .9rem; }
.fi-filters select { font: inherit; padding: .3rem .5rem; border: 1px solid var(--rule); border-radius: 6px; background: #fff; }
.fi-legend { font-size: .85rem; color: var(--ink-soft); display: flex; align-items: center; gap: .35rem; flex-wrap: wrap; }
.fi-legend .k { display: inline-block; width: .8rem; height: .8rem; border-radius: 50%; border: 2px solid var(--us); margin-left: .6rem; }
.fi-legend .k.m1 { background: var(--us); }
.fi-legend .k.mu { border-style: dashed; border-color: var(--muted); }
.fi-court { display: block; width: 100%; height: auto; background: var(--sheet); border: 1px solid var(--rule); border-radius: 6px; }
.fi-zone.us { fill: var(--us); }
.fi-zone.them { fill: var(--them); }
.fi-lines { fill: none; stroke: var(--ink-soft); stroke-width: .5; }
.fi-dot circle { stroke-width: .7; }
.fi-dot.us circle { fill: var(--us); stroke: #fff; }
.fi-dot.them circle { fill: var(--them); stroke: #fff; }
.fi-dot.m0 circle { fill: #fff; }
.fi-dot.us.m0 circle { stroke: var(--us); }
.fi-dot.them.m0 circle { stroke: var(--them); }
.fi-dot.mu circle { fill: #fff; stroke: var(--muted); stroke-dasharray: 1 .7; }
.fi-dot[href] { cursor: pointer; }
.fi-dot[href]:hover circle, .fi-dot.on circle { stroke: var(--ink); stroke-width: 1; }
.fi-off { display: none; }
.fi-unzoned { font-size: .85rem; margin: .5rem 0; display: flex; flex-wrap: wrap; gap: .25rem .75rem; align-items: center; }
.fi-unzoned:not(:has(a:not(.fi-off))) { display: none; }
.fi-unzoned a { display: inline-flex; align-items: center; gap: .3rem; color: inherit; text-decoration: none; }
.fi-unzoned a svg { width: 1rem; height: 1rem; }
.fi-unzoned a span { display: none; }
.fi-player { margin-top: 1rem; }
.fi-list h3 small { color: var(--muted); font-weight: 400; margin-left: .4rem; }
.fi-list ol { font-size: .9rem; padding-left: 1.6rem; }
.fi-list li a { color: var(--ink-soft); text-decoration: none; }
.fi-list li.on a { color: var(--us); font-weight: 700; }
</style>
<script>
(() => {
  const anchors = __ANCHORS__, step = __STEP__;
  const filmVideos = () => document.querySelectorAll(".fi-player video, .fi-list video");
  const pauseOthers = v => document.querySelectorAll("video, audio").forEach(o => { if (o !== v) o.pause(); });
  document.addEventListener("play", ev => {
    const v = ev.target;
    if (v.closest && v.closest(".fi-player, .fi-list")) pauseOthers(v);
    else filmVideos().forEach(o => o.pause());
  }, true);
  document.querySelectorAll("[data-set-lang]").forEach(b => b.addEventListener("click", () => filmVideos().forEach(v => v.pause())));
  function load(video, a, cap) {
    video.src = a.dataset.src;
    if (a.dataset.poster) video.poster = a.dataset.poster;
    if (cap) cap.textContent = a.dataset.cap || a.textContent;
  }
  document.querySelectorAll("[data-film-chart]").forEach(box => {
    const video = box.querySelector(".fi-player video"), cap = box.querySelector(".fi-player figcaption");
    const sel = k => box.querySelector(`[data-f="${k}"]`);
    const dots = [...box.querySelectorAll(".fi-dot")];
    function apply() {
      const team = sel("team") ? sel("team").value : "us", pl = sel("player")?.value || "", half = sel("half")?.value || "";
      if (sel("player")) sel("player").querySelectorAll("option[value*=':']").forEach(o => { o.hidden = !o.value.startsWith(team + ":"); });
      if (pl && !pl.startsWith(team + ":")) sel("player").value = "";
      const p = sel("player")?.value || "";
      const n = {}, st = {};
      dots.forEach(d => {
        const on = (!sel("team") || d.dataset.team === team) && (!p || p === d.dataset.team + ":" + d.dataset.player)
          && (!half || d.dataset.half === half);
        d.classList.toggle("fi-off", !on);
        if (!on) return;
        const z = d.dataset.zone, s = st[z] = st[z] || { made: 0, missed: 0, u: 0, pts: 0 };
        if (d.dataset.made === "1") s.made++; else if (d.dataset.made === "0") s.missed++; else s.u++;
        s.pts += Number(d.dataset.pts);
        if (z === "none") return;
        const i = n[z] = (n[z] ?? -1) + 1, [cx, y0, cols] = anchors[z], c = d.querySelector("circle");
        c.setAttribute("cx", (cx + (i % cols - (cols - 1) / 2) * step).toFixed(2));
        c.setAttribute("cy", (y0 + Math.floor(i / cols) * step).toFixed(2));
      });
      box.querySelectorAll(".fi-zone").forEach(z => {
        const s = st[z.dataset.zone], known = s ? s.made + s.missed : 0;
        z.setAttribute("class", "fi-zone " + team);
        z.style.fillOpacity = known ? (0.1 + 0.5 * Math.min(s.pts / known / 1.5, 1)).toFixed(2) : 0.05;
      });
      box.querySelectorAll(".fi-table tbody tr").forEach(r => {
        const s = st[r.dataset.zone], known = s ? s.made + s.missed : 0, c = r.children;
        c[1].textContent = s ? s.made + "/" + known : "–";
        c[2].textContent = s && s.u ? s.u : "–";
        c[3].textContent = known ? (s.pts / known).toFixed(2) : "–";
      });
    }
    box.querySelectorAll("select").forEach(s => s.addEventListener("change", apply));
    if (video) dots.forEach(d => d.addEventListener("click", ev => {
      if (!d.dataset.src) return;
      ev.preventDefault();
      dots.forEach(o => o.classList.toggle("on", o === d));
      load(video, d, cap);
      video.play().catch(() => {});
      video.scrollIntoView({ block: "nearest" });
    }));
    apply();
  });
  document.querySelectorAll("[data-film-lists] .fi-list").forEach(list => {
    const video = list.querySelector("video"), cap = list.querySelector(".fi-now");
    const links = [...list.querySelectorAll("a[data-src]")];
    let cur = 0;
    function go(i, play) {
      cur = i;
      links.forEach((a, k) => a.parentElement.classList.toggle("on", k === i));
      load(video, links[i], cap);
      if (play) video.play().catch(() => {});
    }
    links.forEach((a, i) => a.addEventListener("click", ev => { ev.preventDefault(); go(i, true); }));
    video.addEventListener("ended", () => { if (cur + 1 < links.length) go(cur + 1, true); });
    if (links.length) go(0, false);
  });
})();
</script>
""".replace("__ANCHORS__", json.dumps(ANCHORS)).replace("__STEP__", str(STEP))
