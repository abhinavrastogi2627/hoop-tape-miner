"""CLI: split and join tracklets into player chains (GTA-style global tracklet association), offline on tracks.pkl.

Reads RUN/tracks.pkl, RUN/embeddings.npz (SigLIP, from `embed`), RUN/jersey.json (crop reads; older runs are
re-picked from detections.pkl) and --game rosters. Writes RUN/stitch.json; `analyze` applies it (track = chain,
the original id kept as `tracklet`) and takes the chain's pooled jersey number.

1. Re-ID space: an LDA fitted per game on the detections of tracklets whose jersey vote is clear (team + number
   as the class), so teammates in the same kit become separable; plain team-centred SigLIP when too few numbers.
2. Split a tracklet where its jersey reads change number (A A .. B B), where its team changes, or where its
   re-ID appearance jumps (binary segmentation, each side at least --min-seg rows).
3. Join segments of one team that do not overlap in time, reachable in court space (<= --vmax m/s over the gap),
   with similar appearance and no conflicting jersey number; greedy by score, checked chain against chain.
4. At most 5 chains per team on court: short chains that are mostly the sixth (or later) of their team in a frame
   are marked "extra" (bench, coaches, duplicates) and leave the team.
5. Jersey reads pooled per chain (confidence-weighted vote, roster-gated); per (team, number) at most one chain
   at a time, the one with more weight keeps it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from .jersey import weighted_vote

TEAMS = ("us", "them")
DEFAULTS = dict(min_seg=20, split_app=0.5, split_team=0.6, max_gap=6.0, short_gap=2.0, vmax=7.0, slack=1.5,
                link_short=0.9, link_long=0.95, link_chain=0.95, one_link=0, motion_w=0.1, max_per_team=5,
                extra_len_s=5.0, conflict_s=1.0)


# ---------- inputs

def base_tracks(tr: pd.DataFrame) -> pd.DataFrame:
    """tracks.pkl as written by `tracks` (undo an earlier stitch that `analyze` saved: tracklet / team_raw)."""
    tr = tr.copy()
    if "tracklet" in tr:
        tr["track"] = tr["tracklet"]
    if "team_raw" in tr:
        tr["team"] = tr["team_raw"]
    return tr.drop(columns=[c for c in ("tracklet", "team_raw", "number") if c in tr])


def tracks_key(tr: pd.DataFrame) -> str:
    """Fingerprint of the tracklets a stitch was computed on (ids, first frame, length)."""
    g = tr.groupby("track").frame.agg(["min", "size"]).sort_index()
    return hashlib.sha1(g.reset_index().to_numpy(np.int64).tobytes()).hexdigest()[:16]


def row_embeddings(tr: pd.DataFrame, e) -> np.ndarray:
    """embeddings.npz rows aligned to tr (unit length), NaN where a row has no embedding."""
    pos = pd.Series(np.arange(len(e["idx"])), index=np.asarray(e["idx"], int))
    have = tr.index.isin(pos.index)
    out = np.full((len(tr), e["emb"].shape[1]), np.nan, np.float32)
    x = e["emb"][pos.loc[tr.index[have]].to_numpy()].astype(np.float32)
    out[have] = x / np.linalg.norm(x, axis=1, keepdims=True)
    return out


def _unit(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return np.where(n > 0, x / np.where(n > 0, n, 1), np.nan)


# ---------- 1. re-ID space

def fit_reid(X: np.ndarray, team: np.ndarray, labels: np.ndarray, min_classes: int = 3, dims: int = 32,
             per_class: int = 400, seed: int = 0) -> np.ndarray:
    """Rows in the space appearance is compared in (unit length; NaN where X is NaN). X: unit embeddings, team and
    labels ("" = unknown, else e.g. "us:17") per row. With >= min_classes labelled classes an LDA (shrinkage) fitted
    on the labelled rows, so teammates in one kit separate; else the embeddings centred per team."""
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    ok = ~np.isnan(X).any(1)
    lab = ok & (labels != "")
    classes = pd.Series(labels[lab]).value_counts()
    classes = classes[classes >= 2]
    if len(classes) >= min_classes:
        rng = np.random.default_rng(seed)
        idx = np.concatenate([rng.permutation(np.flatnonzero(lab & (labels == c)))[:per_class]
                              for c in classes.index])
        lda = LinearDiscriminantAnalysis(solver="eigen", shrinkage="auto",
                                         n_components=min(dims, len(classes) - 1)).fit(X[idx], labels[idx])
        out = np.full((len(X), lda.n_components), np.nan, np.float32)
        out[ok] = _unit(lda.transform(X[ok]))
        return out
    out = np.full(X.shape, np.nan, np.float32)
    for t in set(team[ok]):
        m = ok & (team == t)
        out[m] = _unit(X[m] - X[m].mean(0))
    return out


# ---------- 2. split

def _strong_runs(frames: np.ndarray, reads: np.ndarray, conf: np.ndarray, min_weight: float = 1.5):
    """Time-ordered reads -> [(number, first frame, last frame)] of the numbers read with weight >= min_weight,
    when each such number forms one run (A A B B); [] when they interleave (A B A: misreads, not a switch)."""
    w = Counter()
    for r, c in zip(reads, conf):
        if r != "none":
            w[r] += c
    strong = {n for n, x in w.items() if x >= min_weight}
    if len(strong) < 2:
        return []
    seq = [(f, r) for f, r in sorted(zip(frames, reads)) if r in strong]
    runs = []
    for f, r in seq:
        if runs and runs[-1][0] == r:
            runs[-1][2] = f
        else:
            runs.append([r, f, f])
    if len(runs) != len(strong):
        return []
    return [tuple(x) for x in runs]


def _best_cut(F: np.ndarray, min_len: int, kind: str) -> tuple[int, float]:
    """Best single cut of rows F (n x d, no NaN) into [:k] and [k:]. kind "cos": 1 - cosine of the side means;
    "team": side means of class probabilities, score = the smaller side's top probability when the top classes
    differ, else 0."""
    n = len(F)
    if n < 2 * min_len:
        return -1, 0.0
    cs = np.cumsum(F, 0)
    ks = np.arange(min_len, n - min_len + 1)
    left = cs[ks - 1] / ks[:, None]
    right = (cs[-1] - cs[ks - 1]) / (n - ks)[:, None]
    if kind == "cos":
        s = 1 - (left * right).sum(1) / (np.linalg.norm(left, axis=1) * np.linalg.norm(right, axis=1) + 1e-9)
    else:
        diff = left.argmax(1) != right.argmax(1)
        s = np.where(diff, np.minimum(left.max(1), right.max(1)), 0.0)
    i = int(np.argmax(s))
    return int(ks[i]), float(s[i])


def _refine_cut(z: np.ndarray, lo: int, hi: int) -> int:
    """Cut position in [lo, hi] (rows between the last read of one number and the first of the next) where the
    appearance before and after differs most; the middle when the rows have no embeddings."""
    ok = ~np.isnan(z).any(1)
    if hi <= lo or ok.sum() < 2:
        return (lo + hi) // 2
    x = np.where(ok[:, None], z, 0)
    cs, cn = np.cumsum(x, 0), np.cumsum(ok)
    ks = np.arange(max(lo, 1), min(hi, len(z) - 1) + 1)
    if not len(ks):
        return (lo + hi) // 2
    left = cs[ks - 1] / np.maximum(cn[ks - 1], 1)[:, None]
    right = (cs[-1] - cs[ks - 1]) / np.maximum(cn[-1] - cn[ks - 1], 1)[:, None]
    s = (left * right).sum(1) / (np.linalg.norm(left, axis=1) * np.linalg.norm(right, axis=1) + 1e-9)
    return int(ks[np.argmin(s)])


def _segment(F: np.ndarray, min_len: int, thr: float, kind: str, depth: int = 4) -> list[int]:
    """Cut positions (binary segmentation) where the score exceeds thr."""
    k, s = _best_cut(F, min_len, kind)
    if k < 0 or s <= thr or depth == 0:
        return []
    return _segment(F[:k], min_len, thr, kind, depth - 1) + [k] + \
        [k + c for c in _segment(F[k:], min_len, thr, kind, depth - 1)]


def split_tracklets(tr: pd.DataFrame, Z: np.ndarray, crops: pd.DataFrame, min_seg: int = 20,
                    split_app: float = 0.5, split_team: float = 0.6) -> np.ndarray:
    """Segment id per row of tr (any order). Cuts: jersey number runs, team-probability change, appearance jump."""
    order = np.lexsort((tr.frame.to_numpy(), tr.track.to_numpy()))
    seg = np.empty(len(tr), int)
    prob_cols = [c for c in tr.columns if c.startswith("prob_")]
    P = tr[prob_cols].to_numpy(float) if prob_cols else None
    cr = crops.set_index("idx") if len(crops) else None
    tracks = tr.track.to_numpy()[order]
    starts = np.r_[0, np.flatnonzero(np.diff(tracks)) + 1, len(order)]
    next_id = 0
    for a, b in zip(starts[:-1], starts[1:]):
        rows = order[a:b]
        frames = tr.frame.to_numpy()[rows]
        cuts = set()
        if cr is not None:
            have = tr.index[rows][tr.index[rows].isin(cr.index)]
            if len(have) >= 4:
                c = cr.loc[have]
                runs = _strong_runs(c.frame.to_numpy(), c.read.astype(str).to_numpy(), c.conf.to_numpy(float))
                for (_, _, last), (_, first, _) in zip(runs[:-1], runs[1:]):
                    lo_k, hi_k = np.searchsorted(frames, [last + 1, first])
                    cuts.add(_refine_cut(Z[rows], int(lo_k), int(hi_k)))
        bounds = [0] + sorted(cuts) + [len(rows)]
        for lo, hi in zip(bounds[:-1], bounds[1:]):
            sub = []
            if P is not None:
                sub += [lo + k for k in _segment(P[rows[lo:hi]], min_seg, split_team, "team")]
            parts = [lo] + sorted(sub) + [hi]
            final = []
            for plo, phi in zip(parts[:-1], parts[1:]):
                z = Z[rows[plo:phi]]
                ok = ~np.isnan(z).any(1)
                if ok.sum() >= 2 * min_seg:
                    pos = np.flatnonzero(ok)
                    final += [plo + pos[k] for k in _segment(z[ok], min_seg, split_app, "cos")]
            cut_all = sorted(set(sub) | set(final))
            edges = [lo] + cut_all + [hi]
            for elo, ehi in zip(edges[:-1], edges[1:]):
                seg[rows[elo:ehi]] = next_id
                next_id += 1
    return seg


def segment_table(tr: pd.DataFrame, seg: np.ndarray, Z: np.ndarray, teams_of_prob: dict | None = None,
                  ends: int = 3) -> tuple[pd.DataFrame, np.ndarray]:
    """Per segment: tracklet, team, f0, f1, t0, t1, n, court position at start / end (median of `ends` rows), and
    the mean re-ID vector (unit; NaN when no row has one)."""
    d = tr.assign(seg=seg, _row=np.arange(len(tr))).sort_values(["seg", "frame"])
    g = d.groupby("seg")
    S = pd.DataFrame(dict(tracklet=g.track.first(), team=g.team.agg(lambda s: s.value_counts().index[0]),
                          f0=g.frame.first(), f1=g.frame.last(), t0=g.t.first(), t1=g.t.last(), n=g.size(),
                          x0=g.cx_s.agg(lambda s: s.iloc[:ends].median()),
                          y0=g.cy_s.agg(lambda s: s.iloc[:ends].median()),
                          x1=g.cx_s.agg(lambda s: s.iloc[-ends:].median()),
                          y1=g.cy_s.agg(lambda s: s.iloc[-ends:].median())))
    prob_cols = [c for c in tr.columns if c.startswith("prob_")]
    if prob_cols and teams_of_prob:
        m = g[prob_cols].mean()
        lab = m.idxmax(axis=1).str[5:].map(teams_of_prob)
        S["team"] = lab.where(m.max(axis=1) >= 0.5, "unk").fillna("unk")
    M = np.full((len(S), Z.shape[1]), np.nan, np.float32)
    zs = pd.DataFrame(Z[d._row.to_numpy()]).groupby(d.seg.to_numpy()).mean()   # NaN rows skipped
    M[S.index.get_indexer(zs.index)] = zs.to_numpy()
    return S, _unit(M)


# ---------- 3. join

class _Chains:
    def __init__(self, S: pd.DataFrame, M: np.ndarray, reads: dict, p: dict):
        self.S, self.M, self.p = S, M, p
        self.f0, self.f1, self.t0, self.t1 = (S[c].to_numpy() for c in ("f0", "f1", "t0", "t1"))
        self.x0, self.y0, self.x1, self.y1 = (S[c].to_numpy(float) for c in ("x0", "y0", "x1", "y1"))
        self.parent = list(range(len(S)))
        self.members = {i: [i] for i in range(len(S))}
        self.reads = {i: Counter(reads.get(i, {})) for i in range(len(S))}
        self.vec = {i: (M[i] * S.n.iloc[i] if not np.isnan(M[i]).any() else None) for i in range(len(S))}

    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def _number(self, c):
        w = self.reads[c]
        return weighted_vote(list(w.items()), min_weight=1.5)[0] if w else "none"

    def compatible(self, a, b) -> bool:
        p = self.p
        ms = np.array(self.members[a] + self.members[b])
        ms = ms[np.argsort(self.f0[ms], kind="stable")]
        u, v = ms[:-1], ms[1:]
        if (self.f0[v] <= self.f1[u]).any():
            return False
        d = np.hypot(self.x0[v] - self.x1[u], self.y0[v] - self.y1[u])
        if (d > p["vmax"] * (self.t0[v] - self.t1[u]) + p["slack"]).any():
            return False
        na, nb = self._number(a), self._number(b)
        if na != "none" and nb != "none" and na != nb:
            return False
        both = self.reads[a] + self.reads[b]
        strong = [n for n, w in both.items() if w >= 1.5]
        if len(strong) >= 2:
            return False
        va, vb = self.vec[a], self.vec[b]
        if va is not None and vb is not None:
            sim = float(va @ vb / (np.linalg.norm(va) * np.linalg.norm(vb)))
            if sim < p["link_chain"]:
                return False
        return True

    def union(self, a, b):
        self.parent[b] = a
        self.members[a] += self.members.pop(b)
        self.reads[a] += self.reads.pop(b)
        va, vb = self.vec[a], self.vec.pop(b)
        self.vec[a] = vb if va is None else (va if vb is None else va + vb)


def link_segments(S: pd.DataFrame, M: np.ndarray, seg_reads: dict, links: list | None = None,
                  **params) -> np.ndarray:
    """Chain id per segment (row of S). seg_reads: segment row -> {number: weight}. links (optional) collects the
    accepted joins as [segment a, segment b, gap s, similarity, score]."""
    p = {**DEFAULTS, **params}
    t0, t1 = S.t0.to_numpy(), S.t1.to_numpy()
    f0, f1 = S.f0.to_numpy(), S.f1.to_numpy()
    x0, y0, x1, y1 = (S[c].to_numpy() for c in ("x0", "y0", "x1", "y1"))
    team = S.team.to_numpy()
    has = ~np.isnan(M).any(1)
    cand = []
    for a in range(len(S)):
        if team[a] not in TEAMS:
            continue
        gap = t0 - t1[a]
        d = np.hypot(x0 - x1[a], y0 - y1[a])
        ok = (f0 > f1[a]) & (gap <= p["max_gap"]) & (team == team[a]) & (d <= p["vmax"] * gap + p["slack"])
        for b in np.flatnonzero(ok):
            sim = float(M[a] @ M[b]) if has[a] and has[b] else p["link_short"]
            score = sim - p["motion_w"] * d[b] / (p["vmax"] * gap[b] + p["slack"])
            need = p["link_short"] if gap[b] <= p["short_gap"] else p["link_long"]
            if score >= need:
                cand.append((score, a, b, sim, gap[b]))
    cand.sort(reverse=True)
    ch = _Chains(S, M, seg_reads, p)
    has_next, has_prev = set(), set()
    for score, a, b, sim, g in cand:
        if p["one_link"] and (a in has_next or b in has_prev):
            continue
        ra, rb = ch.find(a), ch.find(b)
        if ra != rb and ch.compatible(ra, rb):
            ch.union(ra, rb)
            has_next.add(a)
            has_prev.add(b)
            if links is not None:
                links.append([int(a), int(b), round(float(g), 2), round(sim, 3), round(float(score), 3)])
    roots = np.array([ch.find(i) for i in range(len(S))])
    return pd.factorize(roots)[0]


# ---------- 4. five per team

def extra_chains(tr: pd.DataFrame, fps: float, max_per_team: int = 5, extra_len_s: float = 5.0) -> set:
    """Chains (tr.track) that are mostly beyond the max_per_team longest of their team in their frames and shorter
    than extra_len_s: not one of the players on court."""
    p = tr[tr.team.isin(TEAMS)]
    size = p.groupby("track").size()
    d = p[["frame", "team", "track"]].drop_duplicates().assign(n=lambda x: x.track.map(size))
    d = d.sort_values(["frame", "team", "n"], ascending=[True, True, False])
    d["rank"] = d.groupby(["frame", "team"]).cumcount()
    over = d[d["rank"] >= max_per_team].groupby("track").size()
    share = over / size.reindex(over.index)
    return {int(t) for t in share.index if share[t] >= 0.5 and size[t] < extra_len_s * fps}


# ---------- 5. numbers per chain

def chain_numbers(tr: pd.DataFrame, crops: pd.DataFrame, rosters: dict, fps: float, conflict_s: float = 1.0,
                  min_weight: float = 1.5) -> dict:
    """chain -> {number, weight, share, reads}: pooled confidence-weighted vote over the chain's crops, roster
    gated; when two chains of a team hold one number at the same time (>= conflict_s), the heavier keeps it."""
    rows = tr[["track", "team", "frame"]]
    c = crops.merge(rows, left_on="idx", right_index=True, how="inner", suffixes=("_c", "")) if len(crops) else None
    out = {}
    for t, team in tr.groupby("track").team.first().items():
        g = c[c.track == t].sort_values("frame") if c is not None else None
        reads = list(zip(g.read.astype(str), g.conf.astype(float))) if g is not None else []
        n, w, s = weighted_vote(reads, min_weight=min_weight, roster=(rosters or {}).get(team))
        out[int(t)] = dict(team=team, number=n, weight=round(w, 3), share=round(s, 3), reads=[r for r, _ in reads])
    frames = rows.groupby("track").frame.agg(set)
    for team in TEAMS:
        by_num = {}
        for t, v in out.items():
            if v["team"] == team and v["number"] != "none":
                by_num.setdefault(v["number"], []).append(t)
        for n, ts in by_num.items():
            kept = []
            for t in sorted(ts, key=lambda t: -out[t]["weight"]):
                if any(len(frames[t] & frames[k]) >= conflict_s * fps for k in kept):
                    out[t]["number"] = "none"
                    out[t]["lost"] = n
                else:
                    kept.append(t)
    return out


# ---------- driver

def stitch(tr: pd.DataFrame, Z_raw: np.ndarray, crops: pd.DataFrame, rosters: dict, fps: float,
           teams_of_prob: dict | None = None, **params) -> dict:
    """Base tracks (+ row embeddings, crop reads) -> stitch.json content."""
    p = {**DEFAULTS, **params}
    tr = base_tracks(tr)
    # 1. re-ID labels: tracklets with a clear pooled vote
    lab_of = {}
    if len(crops):
        cr = crops.merge(tr[["track", "team"]], left_on="idx", right_index=True, suffixes=("_c", ""))
        for (t, team), g in cr.groupby(["track", "team"]):
            n = weighted_vote(list(zip(g.read.astype(str), g.conf)), roster=(rosters or {}).get(team))[0]
            if n != "none" and team in TEAMS:
                lab_of[t] = f"{team}:{n}"
    labels = tr.track.map(lab_of).fillna("").to_numpy().astype(str)
    Z = fit_reid(Z_raw, tr.team.to_numpy(), labels)
    # 2. split
    seg = split_tracklets(tr, Z, crops, p["min_seg"], p["split_app"], p["split_team"])
    S, M = segment_table(tr, seg, Z, teams_of_prob)
    # 3. join
    seg_reads = {}
    if len(crops):
        row_of = pd.Series(np.arange(len(tr)), index=tr.index)
        c = crops[crops.idx.isin(tr.index)]
        segs = seg[row_of.loc[c.idx].to_numpy()]
        srow = S.index.get_indexer(segs)
        for i, r, w in zip(srow, c.read.astype(str), c.conf.astype(float)):
            if r != "none":
                seg_reads.setdefault(i, Counter())[r] += w
    links = []
    S["chain"] = link_segments(S, M, seg_reads, links, **{k: p[k] for k in DEFAULTS})
    out = tr.assign(track=S.chain.reindex(seg).to_numpy(), team=S.team.reindex(seg).to_numpy())
    # 4. five per team
    extra = extra_chains(out, fps, p["max_per_team"], p["extra_len_s"])
    out.loc[out.track.isin(extra), "team"] = "extra"
    # 5. numbers
    nums = chain_numbers(out, crops, rosters, fps, p["conflict_s"])
    segs = [[int(r.tracklet), int(r.f0), int(r.f1), int(r.chain)] for r in S.itertuples()]
    for t in extra:
        nums.setdefault(int(t), {})["extra"] = True
    return dict(version=1, key=tracks_key(tr), params=p, segments=segs, links=links,
                chains={str(k): v for k, v in nums.items()},
                summary=dict(tracklets=int(tr.track.nunique()), segments=len(S), chains=int(S.chain.nunique()),
                             extra=len(extra), splits=int(len(S) - tr.track.nunique())))


def apply_stitch(tr: pd.DataFrame, st: dict) -> pd.DataFrame:
    """tracks.pkl rows -> track = chain, team = chain team ("extra" for non-players), tracklet / team_raw kept.
    Raises ValueError when the stitch was computed on other tracklets."""
    base = base_tracks(tr)
    if tracks_key(base) != st["key"]:
        raise ValueError("stitch.json belongs to another tracks.pkl (run `stitch` again after `tracks`)")
    seg = pd.DataFrame(st["segments"], columns=["track", "f0", "f1", "chain"]).sort_values("f0")
    b = base.assign(_i=np.arange(len(base))).sort_values("frame")
    m = pd.merge_asof(b[["frame", "track", "_i"]], seg, left_on="frame", right_on="f0", by="track")
    m = m.sort_values("_i")
    out = base.assign(tracklet=base.track, team_raw=base.team, track=m.chain.to_numpy().astype(int))
    chains = st["chains"]
    team = out.track.map(lambda c: "extra" if chains[str(c)].get("extra") else chains[str(c)]["team"])
    return out.assign(team=team.to_numpy())


def stitched_jersey(st: dict) -> dict:
    """stitch.json chains -> the jersey dict analyze.identities reads (numbered chains only, so no one-read
    fallback re-adds a number the conflict check removed)."""
    return {k: dict(number=v["number"], reads=[v["number"]]) for k, v in st["chains"].items()
            if v.get("number", "none") != "none" and not v.get("extra")}


def main(argv=None):
    from .camera import sampled_fps
    from .jersey import crop_table, legacy_crop_reads
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--game", default=None, help="game.json (rosters gate the jersey votes)")
    ap.add_argument("--tracks", default=None, help="tracks pickle (default RUN/tracks.pkl)")
    ap.add_argument("--jersey", default=None, help="jersey reads (default RUN/jersey.json)")
    ap.add_argument("--out", default=None, help="output (default RUN/stitch.json)")
    for k, v in DEFAULTS.items():
        ap.add_argument("--" + k.replace("_", "-"), type=type(v), default=v)
    args = ap.parse_args(argv)
    run = Path(args.run)
    tr = base_tracks(pd.read_pickle(args.tracks or run / "tracks.pkl"))
    jp = Path(args.jersey) if args.jersey else run / "jersey.json"
    jersey = json.loads(jp.read_text()) if jp.exists() else {}
    crops = crop_table(jersey)
    if jersey and crops.empty:
        print("jersey.json has no crop records (older run): picking the crops again", flush=True)
        crops = legacy_crop_reads(tr, pd.read_pickle(run / "detections.pkl"), jersey)
    rosters = {}
    if args.game:
        rosters = json.loads(Path(args.game).read_text(encoding="utf8")).get("rosters") or {}
    teams_of_prob = None
    if any(c.startswith("prob_") for c in tr.columns):
        teams_of_prob = tr.assign(lab=tr.colour).groupby("lab").team.first().to_dict()
    Z = row_embeddings(tr, np.load(run / "embeddings.npz"))
    params = {k: getattr(args, k) for k in DEFAULTS}
    st = stitch(tr, Z, crops, rosters, sampled_fps(run), teams_of_prob, **params)
    out = Path(args.out) if args.out else run / "stitch.json"
    out.write_text(json.dumps(st))
    print(f"{out}: {st['summary']}")


if __name__ == "__main__":
    main()
