import json

import numpy as np
import pandas as pd
import pytest

from hoop_tape_miner import jersey as js
from hoop_tape_miner import stitch as st

FPS = 10
D = 16


def _look(k, rng, n):
    """n noisy unit embeddings around basis vector k (one player's appearance)."""
    x = np.zeros((n, D))
    x[:, k] = 1
    x += rng.normal(0, 0.05, (n, D))
    return x / np.linalg.norm(x, axis=1, keepdims=True)


def _rows(track, frames, y, look, rng, team="us"):
    """A player walking along x at 1 m/s on line y, one row per frame (frame = 0.1 s)."""
    f = np.asarray(list(frames))
    return pd.DataFrame(dict(frame=f, t=f / FPS, track=track, team=team, colour="navy", cx_s=2.0 + 0.1 * f,
                             cy_s=float(y), x1=0.0, y1=0.0, x2=40.0, y2=100.0)), _look(look, rng, len(f))


def _game(parts):
    """[(track, frames, y, look, team)] -> tracks frame (unique index) and row embeddings."""
    rng = np.random.default_rng(0)
    frames, embs = zip(*[_rows(t, fr, y, lk, rng, team) for t, fr, y, lk, team in parts])
    tr = pd.concat(frames, ignore_index=True)
    tr.index = tr.index + 1000                       # detections.pkl row ids, not positions
    return tr, np.vstack(embs).astype(np.float32)


def _crops(tr, reads):
    """reads: {track: [(frame, number, conf)]} -> crop table on the rows of that track at those frames."""
    rows = []
    for t, rs in reads.items():
        for f, n, c in rs:
            idx = tr.index[(tr.track == t) & (tr.frame == f)][0]
            rows.append(dict(track=t, idx=int(idx), frame=f, read=n, conf=c))
    return pd.DataFrame(rows, columns=["track", "idx", "frame", "read", "conf"])


def _chain_of(out, track, frames):
    return set(out[(out.tracklet == track) & out.frame.isin(frames)].track)


# ---------- jersey helpers

def test_weighted_vote_needs_weight_and_a_majority():
    assert js.weighted_vote([("7", 1), ("7", 1), ("none", 1)]) == ("7", 2.0, 1.0)
    assert js.weighted_vote([("7", 1), ("9", 1)])[0] == "none"
    assert js.weighted_vote([("7", 0.9), ("7", 0.9), ("9", 0.3)])[0] == "7"
    assert js.weighted_vote([("7", 0.6), ("7", 0.6)])[0] == "none"            # 1.2 < 1.5: not sure enough


def test_weighted_vote_ignores_numbers_off_the_roster():
    assert js.weighted_vote([("71", 1), ("71", 1), ("7", 1), ("7", 1)], roster=[7, 9])[0] == "7"


def test_crop_table_reads_crop_records():
    j = {"5": dict(number="7", reads=["7", "7"], crops=[dict(idx=10, frame=3, read="7", conf=0.9),
                                                       dict(idx=11, frame=9, read="7", conf=0.8)]),
         "6": dict(number="none", reads=[])}
    c = js.crop_table(j)
    assert c.track.tolist() == [5, 5] and c.idx.tolist() == [10, 11] and c.conf.tolist() == [0.9, 0.8]
    assert js.crop_table({"1": dict(number="none", reads=["none"])}).empty


def test_legacy_crop_reads_recover_the_detection_behind_each_read():
    tr, _ = _game([(1, range(0, 60), 5, 0, "us"), (2, range(0, 60), 9, 1, "us")])
    tr["x1"] = np.where(tr.track == 1, 0.0, 500.0)       # boxes far apart: no occlusion
    tr["x2"] = tr.x1 + 40
    det = tr.assign(kind="person")
    j = {"1": dict(number="7", reads=["7", "none", "7", "7", "1", "7"]),
         "2": dict(number="9", reads=["9", "9"])}          # 6 crops picked, 2 reads: skipped
    c = js.legacy_crop_reads(tr, det, j)
    assert set(c.track) == {1} and len(c) == 6
    assert c.read.tolist() == j["1"]["reads"] and (c.frame.diff().dropna() > 0).all()
    assert (tr.loc[c.idx, "track"] == 1).all()


# ---------- stitch

def test_fit_reid_separates_teammates_with_lda_when_numbers_are_known():
    rng = np.random.default_rng(1)
    X = np.vstack([_look(k, rng, 50) for k in range(4)]).astype(np.float32)
    labels = np.repeat(["us:1", "us:2", "us:3", ""], 50)
    Z = st.fit_reid(X, np.full(200, "us"), labels)
    assert Z.shape == (200, 2)                            # 3 classes -> 2 LDA directions
    a, b = Z[:50].mean(0), Z[50:100].mean(0)
    assert np.linalg.norm(Z, axis=1) == pytest.approx(1, abs=1e-5)
    assert (Z[:50] @ a).mean() > 0.9 and a @ b / np.linalg.norm(a) / np.linalg.norm(b) < 0.5


def test_fit_reid_falls_back_to_team_centred_embeddings():
    rng = np.random.default_rng(1)
    X = np.vstack([_look(0, rng, 30), _look(1, rng, 30)]).astype(np.float32)
    X[5] = np.nan
    Z = st.fit_reid(X, np.full(60, "us"), np.full(60, ""))
    assert Z.shape == X.shape and np.isnan(Z[5]).all()
    assert Z[:30][~np.isnan(Z[:30, 0])].mean(0) @ Z[30:].mean(0) < 0     # two players opposite once centred


def test_stitch_joins_fragments_by_appearance_when_motion_allows_both():
    # two teammates side by side (1 m apart); both lose their track around frame 50
    tr, Z = _game([(1, range(0, 48), 5, 0, "us"), (2, range(0, 47), 6, 1, "us"),
                   (3, range(52, 100), 6, 0, "us"), (4, range(51, 100), 5, 1, "us")])
    crops = _crops(tr, {1: [(5, "7", 1), (20, "7", 1), (40, "7", 1)], 2: [(10, "9", 1), (30, "9", 1)],
                        3: [(80, "7", 1)]})
    res = st.stitch(tr, Z, crops, {"us": [7, 9]}, FPS)
    out = st.apply_stitch(tr, res)
    assert out.track.nunique() == 2
    assert _chain_of(out, 1, range(100)) == _chain_of(out, 3, range(100))
    assert _chain_of(out, 2, range(100)) == _chain_of(out, 4, range(100))
    nums = {int(k): v["number"] for k, v in res["chains"].items()}
    assert nums[out[out.tracklet == 1].track.iloc[0]] == "7" and nums[out[out.tracklet == 2].track.iloc[0]] == "9"
    assert set(out.tracklet) == {1, 2, 3, 4} and (out.team == "us").all()


def test_stitch_splits_an_identity_switch_and_joins_both_halves():
    # tracklet 1 follows player A (reads 7) and then player B (reads 9) after frame 50
    a = _rows(1, range(0, 50), 5, 0, np.random.default_rng(2))
    b = _rows(1, range(50, 100), 5, 1, np.random.default_rng(3))
    rest, Zr = _game([(2, range(0, 46), 6, 1, "us"), (3, range(53, 100), 6, 0, "us")])
    tr = pd.concat([a[0], b[0], rest], ignore_index=True)
    tr.index = tr.index + 1000
    Z = np.vstack([a[1], b[1], Zr]).astype(np.float32)
    crops = _crops(tr, {1: [(5, "7", 1), (25, "7", 1), (45, "7", 1), (60, "9", 1), (75, "9", 1), (95, "9", 1)],
                        2: [(10, "9", 1), (40, "9", 1)]})
    res = st.stitch(tr, Z, crops, {"us": [7, 9]}, FPS)
    out = st.apply_stitch(tr, res)
    assert res["summary"]["splits"] == 1
    assert _chain_of(out, 1, range(0, 50)) == _chain_of(out, 3, range(100))
    assert _chain_of(out, 1, range(50, 100)) == _chain_of(out, 2, range(100))
    assert out.track.nunique() == 2


def test_stitch_does_not_join_two_numbers_or_overlapping_tracklets():
    tr, Z = _game([(1, range(0, 40), 5, 0, "us"), (2, range(42, 90), 5, 0, "us"), (3, range(30, 80), 9, 0, "us")])
    crops = _crops(tr, {1: [(5, "7", 1), (20, "7", 1)], 2: [(50, "9", 1), (70, "9", 1)]})
    out = st.apply_stitch(tr, st.stitch(tr, Z, crops, {"us": [7, 9]}, FPS))
    assert out.groupby("tracklet").track.first().nunique() == 3


def test_extra_chains_are_short_sixth_players():
    parts = [(t, range(0, 100), t, 0, "us") for t in range(1, 6)] + [(6, range(0, 20), 12, 0, "us"),
                                                                     (7, range(0, 100), 12, 0, "them")]
    tr, _ = _game(parts)
    assert st.extra_chains(tr, FPS) == {6}


def test_chain_numbers_one_number_per_team_at_a_time():
    tr, _ = _game([(1, range(0, 60), 5, 0, "us"), (2, range(0, 60), 8, 0, "us"), (3, range(70, 90), 8, 0, "us")])
    crops = _crops(tr, {1: [(5, "7", 1), (20, "7", 1), (40, "7", 1)], 2: [(5, "7", 1), (20, "7", 1)],
                        3: [(75, "7", 1), (80, "7", 1)]})
    n = st.chain_numbers(tr, crops, {"us": ["7"]}, FPS)
    assert n[1]["number"] == "7" and n[2]["number"] == "none" and n[2]["lost"] == "7"
    assert n[3]["number"] == "7"                          # not at the same time as chain 1


def test_apply_stitch_is_idempotent_and_refuses_other_tracks():
    tr, Z = _game([(1, range(0, 48), 5, 0, "us"), (3, range(52, 100), 5, 0, "us"), (2, range(0, 100), 9, 1, "us")])
    res = st.stitch(tr, Z, _crops(tr, {}), {}, FPS)
    once = st.apply_stitch(tr, res)
    twice = st.apply_stitch(once, res)
    pd.testing.assert_frame_equal(once, twice)
    assert once.track.nunique() == 2 and set(once.columns) >= {"tracklet", "team_raw"}
    assert _chain_of(once, 1, range(100)) == _chain_of(once, 3, range(100))
    with pytest.raises(ValueError):
        st.apply_stitch(tr[tr.frame != 60], res)
    assert json.loads(json.dumps(res))["key"] == res["key"]


def test_analyze_uses_a_matching_stitch_and_ignores_a_stale_one(tmp_path, capsys):
    from hoop_tape_miner.analyze import identities, stitched_tracks
    tr, Z = _game([(1, range(0, 48), 5, 0, "us"), (3, range(52, 100), 5, 0, "us"), (2, range(0, 100), 9, 1, "us")])
    crops = _crops(tr, {1: [(5, "7", 1), (20, "7", 1)]})
    jersey = {"1": dict(number="7", reads=["7", "7"])}
    assert stitched_tracks(tmp_path, tr, jersey) == (tr, jersey)            # no stitch.json: unchanged
    (tmp_path / "stitch.json").write_text(json.dumps(st.stitch(tr, Z, crops, {"us": [7]}, FPS)))
    out, j = stitched_tracks(tmp_path, tr, jersey)
    nums = identities(out, j, {"us": [7]})
    assert set(out[out.track.map(nums) == "7"].tracklet) == {1, 3}       # the number covers the joined fragment
    stale, j2 = stitched_tracks(tmp_path, tr[tr.frame != 60], jersey)
    assert j2 == jersey and "tracklet" not in stale and "ignored" in capsys.readouterr().out


def test_stitched_jersey_keeps_numbered_player_chains():
    res = dict(chains={"0": dict(team="us", number="7"), "1": dict(team="us", number="none"),
                       "2": dict(team="extra", number="4", extra=True)})
    assert st.stitched_jersey(res) == {"0": dict(number="7", reads=["7"])}
