"""fetch stage: Glory League game -> league/*.json, game.json, run/official.json. No network: _open is mocked."""
import io
import json
from pathlib import Path

import pytest

from hoop_tape_miner import fetch, workspace

FIX = Path(__file__).parent / "fixtures" / "glory"
URL = "https://my.gloryleague.basketball/game/RkFLRUdBTUU=/overview"
TOKEN = "fake.jwt.token-value"


def fixture(op):
    return json.loads((FIX / f"{op}.json").read_text(encoding="utf8"))


class Resp(io.BytesIO):
    def __init__(self, body=b"", status=200, headers=None):
        super().__init__(body)
        self.status, self.headers = status, headers or {}


class Fake:
    """Stands in for urllib: GraphQL POSTs answered from fixtures, video URL served from `video` bytes."""

    def __init__(self, video=b"", deny=(), login_errors=None, honour_range=True, overrides=None):
        self.video, self.deny, self.login_errors, self.honour_range = video, set(deny), login_errors, honour_range
        self.overrides = overrides or {}
        self.bodies, self.ranges = [], []

    def __call__(self, req, timeout=60):
        if req.full_url == fetch.API:
            body = json.loads(req.data)
            self.bodies.append(body)
            if "operationName" not in body:
                if self.login_errors:
                    return Resp(json.dumps({"errors": [{"message": self.login_errors}], "data": None}).encode())
                return Resp(json.dumps({"data": {"login": {"authToken": TOKEN}}}).encode())
            op = body["operationName"]
            assert body["extensions"]["authToken"] == TOKEN and body["variables"] == {"gameId": "RkFLRUdBTUU="}
            if op in self.deny:
                return Resp(json.dumps({"errors": [{"message": f"Access Denied for field {op}"}],
                                        "data": {"game": None}}).encode())
            return Resp(json.dumps(self.overrides.get(op) or fixture(op)).encode())
        if req.get_method() == "HEAD":
            return Resp(headers={"Content-Length": str(len(self.video))})
        rng = req.headers.get("Range")
        self.ranges.append(rng)
        start = int(rng.split("=")[1].rstrip("-")) if rng and self.honour_range else 0
        return Resp(self.video[start:], 206 if start else 200, {"Content-Length": str(len(self.video) - start)})


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "team.json").write_text(json.dumps({
        "_comment": {"about": "x"}, "team": "night owls", "label": "Dark jerseys", "hex": "#123456",
        "focus_player": 17, "media_root": str(tmp_path / "media"),
        "league": {"kind": "glory", "secrets": str(tmp_path / "glory.env")}}), encoding="utf8")
    (tmp_path / "glory.env").write_text("# comment\nGLORY_EMAIL=coach@example.invalid\nexport GLORY_PASSWORD='s3cret-PW'\n",
                                        encoding="utf8")
    monkeypatch.setenv("HOOP_WORKSPACE", str(root))
    monkeypatch.delenv("GLORY_EMAIL", raising=False)
    monkeypatch.delenv("GLORY_PASSWORD", raising=False)
    monkeypatch.setattr(fetch, "video_length", lambda p: 1200.0 if Path(p).exists() else None)
    return tmp_path


def test_game_id_keeps_padding():
    assert fetch.game_id(URL) == "RkFLRUdBTUU="
    assert fetch.game_id("https://my.gloryleague.basketball/game/ab_C-d==/video?x=1#t") == "ab_C-d=="
    with pytest.raises(SystemExit):
        fetch.game_id("https://my.gloryleague.basketball/games")


def test_credentials_env_then_file(tmp_path, monkeypatch):
    f = tmp_path / "s.env"
    f.write_text('GLORY_EMAIL="a@example.invalid"\nGLORY_PASSWORD=p=q\n', encoding="utf8")
    monkeypatch.delenv("GLORY_EMAIL", raising=False)
    monkeypatch.delenv("GLORY_PASSWORD", raising=False)
    assert fetch.credentials(f) == ("a@example.invalid", "p=q")
    monkeypatch.setenv("GLORY_EMAIL", "env@example.invalid")
    monkeypatch.setenv("GLORY_PASSWORD", "envpw")
    assert fetch.credentials(f) == ("env@example.invalid", "envpw")
    monkeypatch.delenv("GLORY_PASSWORD")
    with pytest.raises(SystemExit, match="login missing"):
        fetch.credentials(tmp_path / "missing.env")


def test_login_error_and_access_denied(monkeypatch):
    monkeypatch.setattr(fetch, "_open", Fake(login_errors="Invalid email or password"))
    with pytest.raises(fetch.GloryError, match="login failed: Invalid email"):
        fetch.login("a@example.invalid", "secret-pw")
    fake = Fake(deny={"PointChart"})
    monkeypatch.setattr(fetch, "_open", fake)
    token = fetch.login("a@example.invalid", "secret-pw")
    with pytest.raises(fetch.GloryError, match="PointChart failed: Access Denied") as e:
        fetch.fetch_all("RkFLRUdBTUU=", token)
    assert TOKEN not in str(e.value) and "secret-pw" not in str(e.value)
    assert "Authorization" not in str(fake.bodies)   # auth goes in the body, not a header


def test_side_matching_and_facts():
    data = {op: fixture(op) for op in fetch.OPS}
    assert fetch.pick_side(data["GameOverviewPage"], " NIGHT owls ") == "away"
    assert fetch.pick_side(data["GameOverviewPage"], "Red Foxes") == "home"
    with pytest.raises(SystemExit, match="'Red Foxes'.*'Night Owls'"):
        fetch.pick_side(data["GameOverviewPage"], "Blue Herons")
    f = fetch.league_facts(data, "Night Owls")
    assert (f["us"], f["them"], f["us_side"], f["them_side"]) == ("Night Owls", "Red Foxes", "away", "home")
    assert f["score"] == {"us": 16, "them": 20}
    assert f["halftime"] == {"us": 6, "them": 12}           # basket logged 10 s after H1 finish still counts
    assert f["periods"] == [[0, 600], [600, 1200]]
    assert f["rosters"] == {"us": ["5", "8", "17", "30"], "them": ["4", "7", "11", "22"]}
    assert f["date"] == "2026-03-01"                        # +13:00 instant, Sydney (+11:00) calendar date


def test_game_date_timezone():
    assert fetch.game_date("2026-10-15T00:02:04+13:00", "Australia/Sydney") == "2026-10-14"
    assert fetch.game_date("2026-10-15T00:02:04+13:00") == "2026-10-15"
    assert fetch.game_date("2026-10-15T00:02:04+13:00", "Not/AZone") == "2026-10-15"


def test_halftime_four_quarters():
    pc = fixture("PointChart")
    pc["data"]["game"]["pointChart"]["periods"] = [
        {"name": f"Q{i + 1}", "startTimeString": f"{i * 5:02d}:00", "finishTimeString": f"{i * 5 + 5:02d}:00"}
        for i in range(4)]
    assert fetch.periods(pc) == [[0, 300], [300, 600], [600, 900], [900, 1200]]
    assert fetch.halftime(pc, us_is_home=True) == {"us": 12, "them": 6}


def test_fetch_end_to_end_no_video(ws, monkeypatch, capsys):
    monkeypatch.setattr(fetch, "_open", Fake())
    folder = fetch.main([URL, "--no-video"])
    assert folder == workspace.game_dir("Red Foxes", "2026-03-01")
    out = capsys.readouterr().out
    assert out.strip().splitlines()[-1] == str(folder)
    assert "16-20" in out and TOKEN not in out and "s3cret-PW" not in out and "Test Person" not in out
    media = ws / "media" / "teams" / "red-foxes" / "2026-03-01"
    assert sorted(p.name for p in (media / "league").iterdir()) == sorted(f"{op}.json" for op in fetch.OPS)
    assert not (folder / "run").exists() and not (folder.parent / "README.md").exists()
    game = json.loads((folder / "game.json").read_text(encoding="utf8"))
    assert game["us"] == {"team": "Night Owls", "colour": "us", "hex": "#123456", "label": "Dark jerseys",
                          "focus_player": "17"}
    assert game["them"]["team"] == "Red Foxes" and game["name"] == "2026-03-01 vs Red Foxes"
    assert game["result"] == {"us": 16, "them": 20, "us_side": "away", "them_side": "home",
                              "halftime": {"us": 6, "them": 12}}
    assert game["periods"] == [[0, 600], [600, 1200]] and game["rosters"]["us"] == ["5", "8", "17", "30"]
    assert game["periods_checked"] is False
    assert game["league"] == {"kind": "glory", "game_id": "RkFLRUdBTUU=", "url": URL}
    assert Path(game["run"]) == (media / "run").resolve() and game["video"] == ""
    off = json.loads((media / "run" / "official.json").read_text(encoding="utf8"))
    assert off["video_alignment"]["segments"] == [{"official_from": 0, "official_to": fetch.UNKNOWN_LEN,
                                                    "offset_s": 0, "corr": 1.0}]
    assert all(e["our_video_t"] == e["official_t"] for e in off["score_flow"])
    assert off["final"]["us"]["pts"] == 16 and "17" in off["players"]["us"]
    for p in (folder / "game.json", media / "run" / "official.json"):
        assert "Test Person" not in p.read_text(encoding="utf8")


def test_fetch_keeps_user_edits_unless_force(ws, monkeypatch):
    monkeypatch.setattr(fetch, "_open", Fake())
    folder = fetch.main([URL, "--no-video"])
    gj = folder / "game.json"
    game = json.loads(gj.read_text(encoding="utf8"))
    game["periods"] = [[5, 590], [700, 1190]]
    game["us"]["label"] = "Purple"
    game["result"]["halftime"] = {"us": None, "them": None}
    game["rosters"]["them"] = []
    gj.write_text(json.dumps(game), encoding="utf8")
    fetch.main([URL, "--no-video"])
    game = json.loads(gj.read_text(encoding="utf8"))
    assert game["periods"] == [[5, 590], [700, 1190]] and game["us"]["label"] == "Purple"
    assert game["result"]["halftime"] == {"us": 6, "them": 12} and game["rosters"]["them"] == ["4", "7", "11", "22"]
    fetch.main([URL, "--no-video", "--force"])
    game = json.loads(gj.read_text(encoding="utf8"))
    assert game["periods"] == [[0, 600], [600, 1200]] and game["us"]["label"] == "Dark jerseys"


def test_fetch_downloads_league_video_as_our_video(ws, monkeypatch):
    video = bytes(range(256)) * 400
    monkeypatch.setattr(fetch, "_open", Fake(video=video))
    monkeypatch.setattr(fetch, "CHUNK", 10_000)
    folder = fetch.main([URL, "--us-team", "Night Owls"])
    media = ws / "media" / "teams" / "red-foxes" / "2026-03-01"
    assert (media / "video" / "league.mp4").read_bytes() == video
    game = json.loads((folder / "game.json").read_text(encoding="utf8"))
    assert Path(game["video"]) == (media / "video" / "league.mp4").resolve()
    off = json.loads((media / "run" / "official.json").read_text(encoding="utf8"))
    assert off["video_alignment"]["segments"][0]["official_to"] == 1200.0


def test_fetch_video_not_available(ws, monkeypatch):
    ov = fixture("GameOverviewPage")
    ov["data"]["game"]["videoProcessing"] = True
    monkeypatch.setattr(fetch, "_open", Fake(overrides={"GameOverviewPage": ov}))
    with pytest.raises(SystemExit, match="league video not available.*processing=True"):
        fetch.main([URL])


def test_download_resumes_and_skips(tmp_path, monkeypatch):
    video = bytes(range(256)) * 1000
    fake = Fake(video=video)
    monkeypatch.setattr(fetch, "_open", fake)
    monkeypatch.setattr(fetch, "CHUNK", 7_000)
    dest = tmp_path / "v" / "league.mp4"
    log = []
    part = fetch.download("https://video.example.invalid/x.mp4", dest, max_bytes=100_000, log=log.append)
    assert part.name == "league.mp4.part" and part.stat().st_size == 100_000 and not dest.exists()
    fetch.download("https://video.example.invalid/x.mp4", dest, log=log.append)
    assert dest.read_bytes() == video and not part.exists()
    assert fake.ranges == [None, "bytes=100000-"]
    pct = [line for line in log if line.endswith(" MB") and "%" in line]
    assert 5 <= len(pct) <= 11                                   # about one line per 10 %
    fetch.download("https://video.example.invalid/x.mp4", dest, log=log.append)
    assert "kept" in log[-1] and len(fake.ranges) == 2           # complete file: no GET at all


def test_download_restarts_when_range_ignored(tmp_path, monkeypatch):
    video = b"abcdefghij" * 1000
    monkeypatch.setattr(fetch, "_open", Fake(video=video, honour_range=False))
    dest = tmp_path / "league.mp4"
    (tmp_path / "league.mp4.part").write_bytes(b"XXXX")
    fetch.download("https://video.example.invalid/x.mp4", dest, log=lambda s: None)
    assert dest.read_bytes() == video


def test_identity_alignment_maps_every_event():
    off = fetch.official.load_glory(fixture("BoxScore"), fixture("PointChart"), False,
                                    fetch.identity_alignment(1200.0), 1200.0)
    assert off["score_flow"] and all(e["our_video_t"] == e["official_t"] for e in off["score_flow"])


def test_queries_packaged():
    q = fetch.queries()
    assert set(fetch.OPS) <= set(q) and all(f"query {op}(" in q[op] for op in fetch.OPS)


def test_refetch_without_video_keeps_own_video_alignment(ws, monkeypatch):
    """A game aligned to our own video keeps that alignment when fetched again without --video (unless --force)."""
    video = bytes(range(256)) * 40
    monkeypatch.setattr(fetch, "_open", Fake(video=video))
    own = ws / "own.mp4"
    own.write_bytes(b"own")
    segs = [{"official_from": 0, "official_to": 1200.0, "offset_s": 78.5, "corr": 0.9}]
    monkeypatch.setattr(fetch.official, "align_videos", lambda a, b: segs)
    folder = fetch.main([URL, "--video", str(own)])
    off_path = Path(json.loads((folder / "game.json").read_text(encoding="utf8"))["run"]) / "official.json"
    first = json.loads(off_path.read_text(encoding="utf8"))
    assert first["video_alignment"]["segments"] == segs

    fetch.main([URL])                                            # the run loop re-entering with the url
    again = json.loads(off_path.read_text(encoding="utf8"))
    assert again["video_alignment"] == first["video_alignment"]
    assert [e["our_video_t"] for e in again["score_flow"]] == [e["our_video_t"] for e in first["score_flow"]]

    fetch.main([URL, "--force"])
    forced = json.loads(off_path.read_text(encoding="utf8"))
    assert forced["video_alignment"]["segments"][0]["offset_s"] == 0
