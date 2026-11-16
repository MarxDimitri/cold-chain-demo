"""Offline probe: how well does a threshold rule on the cabinet air temperature do, against 35 days of history and
the attack replays in .ml-scoring/out-*? Used to compare with the ML jobs (docs/decisions.md). Not part of the pipeline.

    python coldchain/ruleprobe.py     # run from the repo root
"""
import sys, json, gzip, itertools
sys.path.insert(0, ".")
import numpy as np
from pathlib import Path
from coldchain import mlscore as ms
from coldchain.chain import load_chain, load_attack, cabinets, parse_ts
from coldchain.telemetry import store_series
from coldchain.attack import AttackPlan

chain = load_chain(); cfg = load_attack()
plan = AttackPlan(chain, cfg, ms.epoch(cfg["t0"]), "setpoint")
targets = {c.id for _, c in plan.targets()}
nominal = {c.id: c.setpoint for s in chain.stores for c in cabinets(chain, s)}
t0 = ms.epoch(cfg["t0"])

def episodes(flag):  # rising edges
    f = flag.astype(np.int8); return np.flatnonzero(np.diff(np.concatenate([[0], f])) == 1)

def fires(exc, M, K):  # at least K of the last M minutes in excursion
    c = np.cumsum(np.concatenate([[0], exc.astype(np.int32)]))
    s = c[M:] - c[:-M]
    out = np.zeros(len(exc), bool); out[M - 1:] = s >= K
    return out

# --- history: 35 days, all stores
start = ms.epoch("2026-10-08T00:00:00Z"); minutes = (ms.epoch(ms.HISTORY_END) - start) // 60
hist = {}
for s in chain.stores:
    series, cabs = store_series(chain, s, start, minutes, ms.SEED)
    for c in cabs:
        air, _, dfr = series[c.id]
        hist[c.id] = (air - nominal[c.id], dfr)
print("history built", len(hist), flush=True)

# --- attack runs from the replay output already on disk
def attack_series(scenario):
    docs = []
    for f in sorted(Path(f".ml-scoring/out-{scenario}").glob("detect/dataset=coldchain.case/**/*.ndjson.gz")):
        with gzip.open(f, "rt") as fh: docs += [json.loads(l) for l in fh]
    by = {}
    for d in docs:
        if d["@timestamp"] < ms.HISTORY_END: continue
        by.setdefault(d["device"]["id"], []).append((d["@timestamp"], d["coldchain"]["case"]["temperature"]["air"], d["coldchain"]["case"]["defrost"]["active"]))
    out = {}
    for cab, rows in by.items():
        rows.sort(); out[cab] = (np.array([r[1] for r in rows]) - nominal[cab], np.array([r[2] for r in rows]), rows[0][0])
    return out
att = {sc: attack_series(sc) for sc in ("setpoint", "defrost")}
t_start = ms.epoch(ms.HISTORY_END)


def since_off(dfr, init=10**6):
    """Minutes since the defrost relay was last on (0 while on)."""
    out = np.empty(len(dfr), np.int64); last = -init
    for i, on in enumerate(dfr):
        if on: last = i
        out[i] = i - last
    return out
hist_since = {c: since_off(d) for c, (_, d) in hist.items()}
end_since = {c: int(v[-1]) for c, v in hist_since.items()}
def att_since(cab, dfr):
    out = np.empty(len(dfr), np.int64); cur = end_since[cab] - 1
    for i, on in enumerate(dfr):
        cur = 0 if on else cur + 1; out[i] = cur
    return out

print(f"{'T(K)':>5} {'hold':>5} {'K/M':>6} | hist episodes {'cabs':>5} per-cab-day | setpoint det  median s | defrost det")
for T, X, (K, M) in itertools.product((1.5, 2.0, 2.5), (30, 45, 60, 90), ((3, 5), (5, 5))):
    ep = cabs_hit = 0
    for cab, (dev, dfr) in hist.items():
        exc = (dev > T) & (~dfr) & (hist_since[cab] > X)
        e = episodes(fires(exc, M, K)); ep += len(e); cabs_hit += len(e) > 0
    res = {}
    for sc in ("setpoint", "defrost"):
        det, times = 0, []
        for cab in targets:
            dev, dfr, ts0 = att[sc][cab]
            exc = (dev > T) & (~dfr) & (att_since(cab, dfr) > X)
            idx = np.flatnonzero(fires(exc, M, K))
            if len(idx): det += 1; times.append(t_start + 60 * int(idx[0]) - plan.start)
        res[sc] = (det, int(np.median(times)) if times else None)
    print(f"{T:5.1f} {X:5d} {K:>2}/{M:<3} | {ep:6d} {cabs_hit:5d} {ep/480/35:8.4f} | {res['setpoint'][0]:3d}/46 {res['setpoint'][1]} | {res['defrost'][0]:3d}/46 {res['defrost'][1]}", flush=True)
