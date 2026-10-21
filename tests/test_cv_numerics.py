"""CV numerics without video: sampling rate, attack direction, roster types, embedding cache, camera loss, slugs."""
import numpy as np
import pandas as pd
import pytest

from hoop_tape_miner import analyze, camera, workspace
from hoop_tape_miner.possessions import frame_table


# ---- sampling rate ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("vfps, step", [(60, 6), (29.97, 3), (30, 3), (25, 3), (50, 5), (15, 2), (24, 2), (5, 1)])
def test_sample_step_is_closest_to_the_target(vfps, step):
    assert camera.sample_step(vfps, 10.0) == step


def test_sampled_fps_read_from_camera_npz_with_fallback(tmp_path):
    np.savez(tmp_path / "camera.npz", frame=np.arange(3), fps=np.float64(25 / 3))
    assert camera.sampled_fps(tmp_path) == pytest.approx(8.3333, abs=1e-3)
    old = tmp_path / "old"
    old.mkdir()
    np.savez(old / "camera.npz", frame=np.arange(3))
    assert camera.sampled_fps(old) == 10.0
    assert camera.sampled_fps(tmp_path / "missing") == 10.0


# ---- attack direction -----------------------------------------------------------------------------------------

def _frames(frame0, n, t0, us_x, them_x, fps=10):
    rows = []
    for i in range(n):
        f = frame0 + i
        for k in range(5):
            rows.append(dict(frame=f, t=t0 + i / fps, team="us", track=k, cx=us_x, cy=3.0 + 2 * k))
            rows.append(dict(frame=f, t=t0 + i / fps, team="them", track=10 + k, cx=them_x, cy=3.0 + 2 * k))
    return rows


def _table(rows, periods):
    tr = pd.DataFrame(rows)
    ft = frame_table(tr)
    ft["period"] = 0
    for i, (a, b) in enumerate(periods, 1):
        ft.loc[ft.t.between(a, b), "period"] = i
    live = (ft.period > 0) & (ft.n_us + ft.n_them >= 6)
    return tr, ft, live


def test_halves_follow_the_basket_switch():
    assert analyze.halves(4) == [[1, 2], [3, 4]]
    assert analyze.halves(5) == [[1, 2], [3, 4, 5]]
    assert analyze.halves(2) == [[1], [2]]
    assert analyze.halves(1) == [[1]]


def test_attack_direction_is_pooled_per_half(capsys):
    periods = [[0, 100], [100, 200], [200, 300], [300, 400]]
    # first half: play only on the right half, us further from the right basket = us attacking right
    # period 3 has no live frames at all; period 4: play on the left half, us attacking left
    rows = _frames(0, 50, 10, us_x=18.0, them_x=25.0) + _frames(1000, 50, 110, us_x=18.0, them_x=25.0) \
        + _frames(3000, 50, 310, us_x=10.0, them_x=3.0)
    tr, ft, live = _table(rows, periods)
    att = analyze.attack_directions(tr, ft, live, analyze.halves(4))
    assert att[(1, "us")] == att[(2, "us")] == "right" and att[(1, "them")] == "left"
    assert att[(3, "us")] == att[(4, "us")] == "left" and att[(3, "them")] == "right"


def test_attack_direction_half_without_signal_uses_the_other_half_and_warns(capsys):
    periods = [[0, 100], [100, 200]]
    tr, ft, live = _table(_frames(0, 50, 10, us_x=18.0, them_x=25.0), periods)
    att = analyze.attack_directions(tr, ft, live, analyze.halves(2))
    assert att[(1, "us")] == "right" and att[(2, "us")] == "left"   # baskets switch at half time
    assert "warning" in capsys.readouterr().out.lower()


def test_attack_direction_without_any_signal_fails_loudly():
    periods = [[0, 100], [100, 200]]
    tr, ft, live = _table(_frames(0, 50, 500, us_x=18.0, them_x=25.0), periods)   # nothing inside the periods
    with pytest.raises(SystemExit, match="attack direction"):
        analyze.attack_directions(tr, ft, live, analyze.halves(2))


# ---- roster types ---------------------------------------------------------------------------------------------

def test_identities_accept_integer_rosters():
    tr = pd.DataFrame(dict(track=[1, 2], team=["us", "them"]))
    jersey = {"1": dict(number="17", reads=["17", "17"]), "2": dict(number="none", reads=["9"])}
    assert analyze.identities(tr, jersey, {"us": [4, 17], "them": [9]}) == {1: "17", 2: "9"}


# ---- embedding cache ------------------------------------------------------------------------------------------

def test_embedding_cache_rows_from_another_extract_are_stale(tmp_path):
    from hoop_tape_miner import embed
    det = pd.DataFrame(dict(frame=[0, 0, 6, 6], x1=[10.0, 50.0, 12.0, 52.0], y1=[20.0, 20.0, 21.0, 21.0]))
    emb = np.ones((4, 3), np.float16)
    embed.save_cache(tmp_path / "embeddings.npz", det.index.to_numpy(), emb, det)
    e = np.load(tmp_path / "embeddings.npz")
    assert embed.fresh_rows(e, det).all()
    redo = pd.DataFrame(dict(frame=[0, 6, 6, 12, 12], x1=[10.0, 12.0, 52.0, 9.0, 40.0], y1=[20.0, 21.0, 21.0, 5.0, 5.0]))
    assert embed.fresh_rows(e, redo).tolist() == [True, False, False, False]   # same index, other detections
    sub = det.iloc[[0, 2]]                                                      # filtered subset of the same extract
    assert embed.fresh_rows(e, sub).tolist() == [True, False, True, False]
    assert embed.fresh_rows(e, sub, missing_ok=True).all()
    np.savez(tmp_path / "old.npz", idx=np.arange(4), emb=emb)                   # cache from before fingerprints
    assert embed.fresh_rows(np.load(tmp_path / "old.npz"), det).all()


# ---- camera loss ----------------------------------------------------------------------------------------------

class _NoMatchBank:
    frames = [object()]

    def localise(self, gray, mask=None):
        return None, 0


def test_lost_camera_returns_no_homography_instead_of_the_last_one():
    tr = camera.CourtCameraTracker(_NoMatchBank())
    tr.H = np.eye(3)                                  # a pose from an earlier frame
    blank = np.zeros((48, 64, 3), np.uint8)           # featureless: no flow, no keyframe match
    for _ in range(2):
        H, q, how = tr.update(blank)
        assert H is None and how == "none"
    assert tr.lost == 2


# ---- slugs ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, slug", [("Red Foxes", "red-foxes"), ("Bulls/Bears", "bulls-bears"),
                                        ("A:B", "a-b"), ('What?* <Now>|"', "what-now"), ("Team. ", "team"),
                                        ("St. Kilda", "st-kilda"), ("CON", "con-team"), ("???", "team")])
def test_slug_is_a_safe_windows_folder_name(name, slug):
    assert workspace.slug(name) == slug


def test_existing_legacy_slug_folder_is_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOP_WORKSPACE", str(tmp_path))
    (tmp_path / "teams" / "st.-kilda").mkdir(parents=True)
    assert workspace.team_dir("St. Kilda") == tmp_path / "teams" / "st.-kilda"
    assert workspace.team_dir("Red Foxes") == tmp_path / "teams" / "red-foxes"
