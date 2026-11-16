"""Offline probe: duration rules on the cabinet air temperature against the slow-warming scenario (config/attack.yaml
`slow_warming`) and 35 days of history. Compares a count rule with a rolling-mean rule (docs/decisions.md).

    python coldchain/ruleprobe_duration.py     # run from the repo root
"""
import sys, itertools
sys.path.insert(0, ".")
import numpy as np
from coldchain import mlscore as ms
from coldchain.chain import load_chain, load_attack, cabinets
from coldchain.telemetry import store_series
chain = load_chain(); cfg = load_attack(); sw = cfg["slow_warming"]
targets = ms.slow_targets()
start = ms.epoch("2026-10-08T00:00:00Z"); hist_end = ms.epoch(ms.HISTORY_END)
total = (hist_end - start) // 60 + ms.CONTROL_MINUTES
t_start = ms.epoch(cfg["t0"]) + sw["offset_seconds"]
n_hist = (hist_end - start) // 60
def since_off(dfr):
    out = np.empty(len(dfr), np.int64); last = -10**6
    for i, on in enumerate(dfr):
        if on: last = i
        out[i] = i - last
    return out
def frac_rule(dev, dfr, ss, T, M, K, X):
    exc = ((dev > T) & ~dfr & (ss > X)).astype(np.int32)
    c = np.cumsum(np.concatenate([[0], exc])); s = c[M:] - c[:-M]
    out = np.zeros(len(dev), bool); out[M - 1:] = s >= K
    return out
data = {}
for s in chain.stores:
    series, cabs = store_series(chain, s, start, total, ms.SEED)
    for c in cabs:
        air, _, dfr = series[c.id]; dev = air - c.setpoint
        slow = dev.copy()
        if c.id in targets:
            for i in range(n_hist, total):
                slow[i] += ms.slow_excess(sw, (start + 60 * i - t_start) / 60)
        data[c.id] = (dev, slow, dfr, since_off(dfr))
print("built", flush=True)

def mean_rule(dev, dfr, ss, T, M, X):
    ok = (~dfr) & (ss > X)
    v = np.where(ok, dev, 0.0)
    c = np.cumsum(np.concatenate([[0.0], v])); n = np.cumsum(np.concatenate([[0], ok.astype(np.int32)]))
    sm = (c[M:] - c[:-M]) / M; cnt = n[M:] - n[:-M]
    out = np.zeros(len(dev), bool); out[M - 1:] = (cnt == M) & (sm > T)
    return out
print(f"{'meanT':>5} {'M':>3} | FP episodes | slow detected, median min after start, max normal 30-min mean")
for T, M in itertools.product((0.3, 0.4, 0.5, 0.6, 0.8), (20, 30)):
    fp = 0; det = []; mx = 0
    for cab, (dev, slow, dfr, ss) in data.items():
        if cab in targets:
            f = mean_rule(slow, dfr, ss, T, M, 30)
            idx = np.flatnonzero(f[n_hist:])
            if len(idx): det.append(idx[0] - ((t_start - hist_end) / 60))
            f0 = f[:n_hist]
        else:
            f0 = mean_rule(dev, dfr, ss, T, M, 30)
        fp += int(np.sum(np.diff(np.concatenate([[0], f0.astype(int)])) == 1))
    print(f"{T:5.1f} {M:3d} | {fp:8d} | {len(det):2d}/12 {int(np.median(det)) if det else None}", flush=True)
# distribution of the normal 30-minute mean (valid windows only)
vals = []
for cab, (dev, slow, dfr, ss) in list(data.items())[:60]:
    ok = (~dfr) & (ss > 30); v = np.where(ok, dev, 0.0)
    c = np.cumsum(np.concatenate([[0.0], v])); n = np.cumsum(np.concatenate([[0], ok.astype(int)]))
    m = (c[30:] - c[:-30]) / 30; full = (n[30:] - n[:-30]) == 30
    vals.append(m[full][:n_hist])
v = np.concatenate(vals); print("normal 30-min mean of dev: p99.9", round(float(np.percentile(v, 99.9)), 2), "max", round(float(v.max()), 2))
