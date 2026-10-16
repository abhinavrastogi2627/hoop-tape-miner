"""No-network tests for the explained-video stage (`hoop-tape-miner film`); the render test fakes the TTS."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hoop_tape_miner import film
from hoop_tape_miner import film_draw as fd

SCRIPT = """# writer's note, never read
Hello team, this is the review.

## Why we lost the run
Two things.
Both fixable.

![#17 loses it to the press](clip:0:02-0:04)
Watch number seventeen.

Again, alone.
### also a note
![Score margin](momentum.png)
"""


def test_parse_script_scenes_and_paragraphs():
    s = film.parse_script(SCRIPT)
    assert [(x.kind, x.text, x.src) for x in s] == [
        ("title", "", ""), ("card", "Why we lost the run", ""), ("clip", "#17 loses it to the press", "0:02-0:04"),
        ("image", "Score margin", "momentum.png")]
    assert s[0].paras == ["Hello team, this is the review."]
    assert s[1].paras == ["Two things. Both fixable."]
    assert s[2].paras == ["Watch number seventeen.", "Again, alone."]
    assert s[3].paras == [] and s[2].window() == (2.0, 4.0) and s[2].clip_s() == 2.0


def test_parse_script_starting_with_a_visual_has_no_title_card():
    assert [x.kind for x in film.parse_script("## Start\nText.\n")] == ["card"]


def test_check_flags_missing_picture_bad_window_and_missing_video(tmp_path):
    scenes = film.parse_script("![a](nope.png)\n![b](clip:0:09-0:05)\n![c](clip:7)\n")
    probs = film.check(scenes, tmp_path, None, None)
    assert any("picture not found" in p for p in probs)
    assert any("ends before it starts" in p for p in probs)
    assert any("mm:ss-mm:ss" in p for p in probs)
    assert any("needs the game video" in p for p in probs)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    assert any("past the end" in p for p in film.check(film.parse_script("![x](clip:0:01-0:30)"), tmp_path, video, 20))


def test_timing_holds_replays_slow_or_plays_clip_through():
    assert film.timing("clip", 0, 10) == (10, 0)                       # no voice: the clip as it is
    assert film.timing("clip", 5, 10) == (10, 0)                       # voice fits: play to the end
    length, slow = film.timing("clip", 9.5, 10)                        # small overrun: hold the last frame
    assert slow == 0 and length == pytest.approx(film.LEAD + 9.5 + film.TAIL)
    length, slow = film.timing("clip", 20, 10)                         # long talk: half-speed replay
    assert length == pytest.approx(film.LEAD + 20 + film.TAIL) and slow == pytest.approx(length - 10)
    assert film.timing("clip", 60, 10)[1] == pytest.approx(10 / film.SLOW)  # replay at most once, then hold
    assert film.timing("card", 0) == (film.CARD_S, 0) and film.timing("image", 0) == (film.IMAGE_S, 0)
    assert film.timing("card", 10)[0] == pytest.approx(film.LEAD + 10 + film.TAIL)


def test_subtitle_chunks_split_at_commas_and_tidy_ends():
    zh = "同一段时间，我们自己的进攻一次挡拆都没有，球一停就一个人往人堆里冲。"
    parts = film.chunks(zh, 20)
    assert all(len(p) <= 20 for p in parts) and "".join(parts) == zh
    cues = film.cue_split(1.0, 4.0, zh, 20)
    assert cues[0][0] == 1.0 and cues[-1][1] == pytest.approx(4.0)
    assert not any(c[2].endswith(("，", "。")) for c in cues)
    assert film.tidy("Really?") == "Really?" and film.tidy("Done.") == "Done"
    long_en = "word " * 40
    assert all(len(p) <= 30 for p in film.chunks(long_en, 30))


def test_ass_doc_and_scene_events():
    sc = film.parse_script("![cap {x}](clip:0:01-0:03)\nA.")[0]
    ev = film.scene_events(sc, 8.0, 3.0, 2.0, [(0.0, 1.0, "A"), (1.2, 2.0, "B")], "zh", "T", 720)
    styles = [e[2] for e in ev]
    assert styles == ["Banner", "Tag", "Sub", "Sub"]
    assert ev[0][3] == "cap (x)" and ev[1][3] == "慢放"
    assert ev[2][1] == pytest.approx(film.LEAD + 1.2)  # short gap closed: no flicker
    doc = film.ass_doc(1280, 720, "Font X", "#6250d6", ev)
    assert "PlayResY: 720" in doc and "Style: Sub,Font X," in doc
    assert "Dialogue: 2,0:00:00.00,0:00:08.00,Banner,,0,0,0,,cap (x)" in doc  # text above drawings (layer 0, 1)
    assert film.ass_time(3725.456) == "1:02:05.46" and film.ass_colour("#6250d6", 0x30) == "&H30D65062"


FREEZE_SCRIPT = """![alone vs the press](clip:07:26-07:38)
Watch the ball.

> 07:28 我#17 对#25 我#17->0.6,0.5 "nobody comes"
Stop here. Nobody comes.

> 07:31.5 0.3,0.6
Now he is trapped.
![fouls](stat:9)
![get back](court:plays/back.json)
Set-up.

Step one.
"""


def test_parse_freeze_lines_stats_and_courts():
    s = film.parse_script(FREEZE_SCRIPT)
    assert [(x.kind, x.src) for x in s] == [("clip", "07:26-07:38"), ("stat", "9"), ("court", "plays/back.json")]
    clip = s[0]
    assert clip.paras == ["Watch the ball."] and [f.paras for f in clip.freezes] == [["Stop here. Nobody comes."],
                                                                                     ["Now he is trapped."]]
    t, marks, label, bad = clip.freezes[0].parts()
    assert t == "07:28" and label == "nobody comes" and not bad
    assert marks == [("player", "us", "17"), ("player", "them", "25"),
                     ("arrow", ("player", "us", "17"), ("point", 0.6, 0.5))]
    assert clip.freezes[1].at() == pytest.approx(451.5) and clip.freezes[1].parts()[1] == [("point", 0.3, 0.6)]
    assert fd.parse_freeze_line('> 1:00 them#3 junk “标签”')[1:] == ([("player", "them", "3")], "标签", ["junk"])


def test_check_flags_bad_freezes_and_court_files(tmp_path):
    (tmp_path / "plays").mkdir()
    (tmp_path / "plays" / "back.json").write_text(json.dumps({"us": {"1": [20, 7]}, "steps": [{"move": {"us:2": [1, 1]}}]}),
                                                  encoding="utf8")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    bad = FREEZE_SCRIPT.replace("07:31.5 0.3,0.6", "07:50 wat") + "## card\n> 0:01 0.1,0.1\n"
    probs = film.check(film.parse_script(bad), tmp_path, video, 2000)
    assert any("outside the clip" in p for p in probs) and any("cannot read 'wat'" in p for p in probs)
    assert any("no CV tracks" in p for p in probs) and any("only work after a clip" in p for p in probs)
    assert any("unknown player us:2" in p for p in probs)


def test_clip_plan_plays_freezes_and_resumes():
    # 12 s clip, freezes at +2 s and +5.5 s; 3 s of talk before the first freeze, 4 s on it, none on the second
    length, segs, starts, spans = film.clip_plan(446, 458, [448, 451.5], [3.0, 4.0, 0.0])
    assert [x[0] for x in segs] == ["play", "hold", "play", "hold", "play"]
    assert segs[0] == ("play", 446, 448) and segs[2] == ("play", 448, 451.5) and segs[4] == ("play", 451.5, 458)
    first = film.LEAD + 3.0 + film.GAP  # the talk before the freeze is still running when the clip reaches it
    assert starts == [film.LEAD, pytest.approx(first), None]
    assert spans[0] == (2.0, pytest.approx(first + 4.0 + film.TAIL))
    assert spans[1][1] - spans[1][0] == pytest.approx(film.FREEZE_S)
    assert length == pytest.approx(12 + segs[1][2] + film.FREEZE_S)


def test_bare_freeze_line_reads_over_the_play_that_follows():
    scenes = film.parse_script("![x](clip:07:26-07:38)\n> 07:28 我#17 \"alone\"\nStop here.\n\n>\nWatch on.\n")
    fz = scenes[0].freezes
    assert [f.resume for f in fz] == [False, True] and fz[1].paras == ["Watch on."] and fz[1].at() is None
    assert not any("only works after" in p for p in film.check(scenes, Path("."), Path("v.mp4"), 3000.0))
    bad = film.parse_script("![x](clip:07:26-07:38)\n>\nToo early.\n")
    assert any("only works after a freeze" in p for p in film.check(bad, Path("."), Path("v.mp4"), 3000.0))
    # 3 s on the freeze at +2 s, then 4 s over the play: the clip runs on right away, the voice after the freeze talk
    length, segs, starts, spans = film.clip_plan(446, 458, [448, None], [0.0, 3.0, 4.0])
    assert segs == [("play", 446, 448), ("hold", 448, pytest.approx(film.LEAD + 3.0 + film.TAIL)), ("play", 448, 458)]
    hold_end = 2.0 + segs[1][2]
    assert spans[1] is None and starts[2] == pytest.approx(max(hold_end + 0.3, 2.0 + film.LEAD + 3.0 + film.GAP))
    assert length == pytest.approx(hold_end + 10)


def test_freeze_events_circle_tracked_players_and_dim_the_rest():
    import pandas as pd

    df = pd.DataFrame([{"t": 448.0, "team": "us", "number": "17", "x1": 370, "y1": 268, "x2": 456, "y2": 412},
                       {"t": 448.1, "team": "them", "number": "25", "x1": 475, "y1": 293, "x2": 529, "y2": 414}])
    tracks = fd.Tracks(df, 1280, 720)
    assert tracks.box("us", "17", 448.05) == pytest.approx((370 / 1280, 268 / 720, 456 / 1280, 412 / 720))
    assert tracks.box("us", "17", 449) is None and tracks.box("them", "17", 448) is None
    marks = fd.parse_freeze_line('> 07:28 我#17 对#25 我#17->对#25 "alone"')[1]
    ev = fd.freeze_events(marks, "alone", 448.0, tracks, 1280, 720, (0, 0, 1280, 720), 2.0, 6.0)
    styles = [e[2] for e in ev]
    assert styles.count("Draw") == 4 and styles[-1] == "Mark"  # dim layer, two rings, one arrow; the label
    assert ev[0][3].count(" m ") == 2 and "\\1a&H78&" in ev[0][3]  # two holes cut in the dim layer
    assert "\\3c&H00D4FF&" in ev[1][3] and all(e[:2] == (2.0, 6.0) for e in ev)
    assert film.freeze_warnings(film.parse_script("![x](clip:07:26-07:38)\n> 07:28 我#9\n"), tracks) == [
        "scene 1: freeze 07:28: us#9 is not in the tracks near that moment; mark them with x,y instead"]


def test_court_diagram_states_and_frames(tmp_path):
    play = {"us": {"1": [20, 7.5], "2": [25, 2]}, "them": {"19": [22, 6]}, "ball": "us:1",
            "steps": [{"dribble": {"us:1": [23, 7]}}, {"pass": ["us:1", "us:2"], "ring": ["them:19"]},
                      {"shot": "us:2"}]}
    f = tmp_path / "p.json"
    f.write_text(json.dumps(play), encoding="utf8")
    play = fd.load_play(f)
    assert fd.play_problems(play) == []
    st = fd.play_states(play)
    assert st[1]["pos"]["us:1"] == (23, 7) and st[2]["ball"] == "us:2" and st[3]["ball"] == "basket:us:2"
    assert film.court_steps([0.0, 3.0], 3) == [film.LEAD + 3.0, film.LEAD + 5.5, film.LEAD + 8.0]
    lst = fd.render_court(play, 320, 180, [1.0, 3.0, 5.0], 7.0, tmp_path / "c", "#6250d6", "#e04040", fps=10)
    lines = lst.read_text(encoding="utf8").splitlines()
    durs = [float(x.split()[1]) for x in lines if x.startswith("duration")]
    assert sum(durs) == pytest.approx(7.0, abs=0.01) and (tmp_path / "c" / "c00000.png").is_file()


def test_title_text_uses_game_json_names_date_and_score(tmp_path):
    folder = tmp_path / "teams" / "x" / "2026-10-14"
    folder.mkdir(parents=True)
    game = {"us": {"team": "A"}, "them": {"team": "B"}, "result": {"us": 30, "them": 38}}
    t = film.title_text(folder, game, 720)
    assert t.startswith("A vs B\\N") and t.endswith("2026-10-14 · 30–38")
    assert film.title_text(folder / "player-17", {}, 720).startswith("#17 · Us vs Them")


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")
def test_film_renders_scenes_with_fake_voice(tmp_path, monkeypatch, capsys):
    def ff(*a):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)

    video = tmp_path / "game.mp4"
    ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=6", "-f", "lavfi", "-i",
       "sine=f=300:d=6", "-pix_fmt", "yuv420p", "-shortest", str(video))
    folder = tmp_path / "2026-10-14"
    folder.mkdir()
    ff("-f", "lavfi", "-i", "color=c=white:s=200x100:d=1", "-frames:v", "1", str(folder / "momentum.png"))
    (folder / "game.json").write_text(json.dumps({"us": {"team": "A"}, "them": {"team": "B"}}), encoding="utf8")
    (folder / "film.en.md").write_text(SCRIPT, encoding="utf8")

    def fake_spoken(text, voice, rate, cache):  # 0.1 s of tone per character stands in for edge-tts
        cache.mkdir(parents=True, exist_ok=True)
        out = cache / f"{abs(hash(text))}.wav"
        ff("-f", "lavfi", "-i", f"sine=f=600:d={len(text) / 10}", str(out))
        return out, len(text) / 10, [(0.0, len(text) / 10, text)]

    monkeypatch.setattr(film, "spoken", fake_spoken)
    film.main([str(folder), "--video", str(video), "--height", "180", "--dry"])
    assert "4 scenes" in capsys.readouterr().out and not (folder / "film.en.mp4").exists()

    out = film.build(folder, "en", video, 180, film.FONT)
    voice = {i: film.LEAD + (sum(len(p) for p in ps) / 10 + film.GAP * (len(ps) - 1)) + film.TAIL
             for i, ps in enumerate(sc.paras for sc in film.parse_script(SCRIPT)) if ps}
    expected = voice[0] + voice[1] + voice[2] + film.IMAGE_S  # clip (2 s) is outlasted by its narration
    assert out == folder / "film.en.mp4"
    assert film.duration_s(out) == pytest.approx(expected, abs=0.5)
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,height", "-of", "csv=p=0",
                              str(out)], capture_output=True, text=True, check=True).stdout
    assert "video,180" in streams and "audio" in streams

    preview = film.build(folder, "en", video, 180, film.FONT, pick=(3, 3))
    assert preview.name == "film.en.preview.mp4" and film.duration_s(preview) == pytest.approx(voice[2], abs=0.3)

    # narration a little longer than the clip: no slow replay, the last frame holds
    (folder / "film.en.md").write_text("![x](clip:0:01-0:03)\nWatch the pass.\n", encoding="utf8")
    assert film.timing("clip", 1.5, 2.0)[1] == 0
    hold = film.build(folder, "en", video, 180, film.FONT)
    assert film.duration_s(hold) == pytest.approx(film.LEAD + 1.5 + film.TAIL, abs=0.2)

    # a card and a stat over blurred footage, a clip that freezes once, an animated court diagram
    (folder / "plays").mkdir()
    (folder / "plays" / "p.json").write_text(json.dumps({"us": {"1": [20, 7.5]}, "steps": [{"move": {"us:1": [24, 4]}}]}),
                                             encoding="utf8")
    (folder / "film.en.md").write_text('## Card\n![x](clip:0:01-0:04)\nGo.\n> 0:02 0.5,0.8 "here"\nLook.\n'
                                       '![n](stat:3)\n![p](court:plays/p.json)\nSet.\n\nMove.\n', encoding="utf8")
    rich = film.build(folder, "en", video, 180, film.FONT)
    clip = film.clip_plan(1, 4, [2], [0.3, 0.5])[0]
    assert clip == pytest.approx(3 + 1.3)  # the 3 s clip plus a 1.3 s freeze
    assert film.duration_s(rich) == pytest.approx(film.CARD_S + clip + film.CARD_S + film.IMAGE_S, abs=0.5)


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")
def test_spoken_cuts_trailing_silence_from_cached_speech(tmp_path):
    import hashlib

    key = hashlib.sha1("v|+0%|Hi.".encode("utf8")).hexdigest()[:16]
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=500:d=1", "-af", "apad=pad_dur=1",
                    str(tmp_path / f"{key}.mp3")], check=True)
    (tmp_path / f"{key}.json").write_text(json.dumps({"duration": 2.0, "cues": [[0.0, 2.0, "Hi."]]}), encoding="utf8")
    wav, dur, cues = film.spoken("Hi.", "v", "+0%", tmp_path)
    assert wav.suffix == ".wav" and dur == pytest.approx(1.0, abs=0.15) and cues == [(0.0, dur, "Hi.")]


def test_card_title_lines_split_at_dots_and_sit_above_the_bar():
    sc = film.Scene("card", "Pressure comes, find a teammate · Two come, pass")
    (ev,) = film.scene_events(sc, 5, 0, 0, [], "en", "", 720)
    assert ev[2] == "Title" and ev[3] == r"{\an2\pos(640,400)}Pressure comes, find a teammate\NTwo come, pass"
