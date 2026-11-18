"""The POS scenario (hypothetical): the back-office POS PC of one store is compromised. Generator.

    python -m coldchain.scenario_b --target local --out out-b [--stores S03,S07]
    python -m coldchain.scenario_b --target s3 [--resume]

What it writes (config/scenario_b.yaml; all records carry labels.namespace = "pos"), all to detect/:
  netflow.summary       all 20 stores, 5-minute summaries; S07 adds the nightly download and the internal flows
  pos.terminal          hourly roll-ups (CPU, free disk, transactions per minute) of every POS terminal
  network_traffic.tls   S07 only: the TLS sessions of its POS terminals (server names, JA3)

The nightly download is 96 chunks of 20-60 MB from sync.example-cdn.net over 7 nights, 4.0 GiB in all.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import numpy as np
import yaml

from .chain import CONFIG_DIR, Chain, Store, devices, load_chain
from .network import WINDOW, _flow, flows
from .sink import make_sink, write_chunk, write_records

DAY = 86400


@lru_cache(maxsize=1)
def config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "scenario_b.yaml").read_text())


def epoch(date: str, hhmm: str = "00:00") -> int:
    return int(datetime.fromisoformat(f"{date}T{hhmm}:00+00:00").timestamp())


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def window() -> tuple[int, int]:
    w = config()["window"]
    start = epoch(w["start"])
    return start, start + w["days"] * DAY


# --- the download -----------------------------------------------------------------------------

def chunk_plan(seed: int) -> list[tuple[int, int]]:
    """(epoch, bytes) of every chunk. Sizes are 20-60 MB and sum to the configured total."""
    d = config()["download"]
    n, lo, hi = d["chunks"], d["chunk_mb"][0] * 1e6, d["chunk_mb"][1] * 1e6
    total = d["total_gib"] * 2 ** 30
    rng = np.random.default_rng([seed, 7, 99])
    while True:
        sizes = rng.uniform(lo, hi, n)
        sizes *= total / sizes.sum()
        if sizes.min() >= lo and sizes.max() <= hi:
            break
    sizes = sizes.astype(np.int64)
    sizes[-1] += int(total) - int(sizes.sum())
    nights = d["nights"]
    counts = [n // nights + (1 if i < n % nights else 0) for i in range(nights)]
    first = epoch(d["first_night"], d["night_start_utc"])
    span = d["night_hours"] * 3600
    out, k = [], 0
    for night, c in enumerate(counts):
        base = first + night * DAY
        for i in range(c):
            t = base + int((i + rng.uniform(0.1, 0.9)) * span / c)
            out.append((t, int(sizes[k])))
            k += 1
    return out


# --- records ----------------------------------------------------------------------------------

def tag(rec: dict) -> dict:
    rec["labels"] = {"namespace": config()["namespace"]}
    return rec


def tls_record(flow: dict, server_name: str, ja3: str) -> dict:
    rec = {"@timestamp": flow["@timestamp"],
           "event": {"kind": "event", "category": ["network"], "dataset": "network_traffic.tls"},
           "source": flow["source"], "destination": flow["destination"],
           "network": {"transport": "tcp", "bytes": flow["network"]["bytes"]},
           "tls": {"version": "1.3", "client": {"server_name": server_name, "ja3": ja3}},
           "host": flow["host"], "retail": flow["retail"]}
    return tag(rec)


def store_flows(chain: Chain, store: Store, seed: int):
    """Normal flows for the whole window (summaries for every store), plus S07's story."""
    cfg, (start, end) = config(), window()
    raw, summary = flows(chain, store, start, (end - start) / DAY, seed)
    raw = [(t, tag(r)) for t, r in raw]
    summary = [(t, tag(r)) for t, r in summary]
    if store.id != cfg["store"]:
        return [], summary, []
    devs = devices(chain, store)
    by_role: dict[str, list] = {}
    for d in devs:
        by_role.setdefault(d.role, []).append(d)
    router_ip = by_role["router"][0].ip
    rng = np.random.default_rng([seed, 7, 5])
    bo = by_role["pos-backoffice"][0]
    dl = cfg["download"]

    extra_raw: list[tuple[int, dict]] = []
    sums: dict[tuple[int, str, str], dict] = {}

    def add(ts: int, src, dst_ip: str, port: int, sent: int, recv: int) -> dict:
        rec = tag(_flow(ts, store, src, dst_ip, port, "tcp", sent, recv, router_ip))
        extra_raw.append((ts, rec))
        w = ts - ts % WINDOW
        key = (w, src.name, dst_ip)
        s = sums.get(key)
        if s is None:
            s = tag(_flow(w, store, src, dst_ip, port, "tcp", 0, 0, router_ip, dataset="netflow.summary"))
            s["network"]["packets"], s["network"]["flows"] = 0, 0
            sums[key] = s
        s["source"]["bytes"] += sent
        s["destination"]["bytes"] += recv
        s["network"]["bytes"] += sent + recv
        s["network"]["packets"] += rec["network"]["packets"]
        s["network"]["flows"] += 1
        return rec

    tls: list[tuple[int, dict]] = []
    for ts, size in chunk_plan(seed):
        rec = add(ts, bo, dl["server_ip"], 443, int(rng.integers(2_000, 6_000)), size)
        tls.append((ts, tls_record(rec, dl["server_name"], dl["ja3"])))

    for f in cfg["internal_flows"]:
        name, _, nth = f["src"].partition("-0")  # "pos-lane-02" -> role pos-lane, second device
        src = by_role[name][int(nth) - 1 if nth else 0]
        dsts = by_role[f["dst"]]
        dsts = dsts if len(dsts) < 3 else dsts[:1]
        night = epoch(f["from"], dl["night_start_utc"])
        while night < end:
            for k in range(0, dl["night_hours"] * 3600, f["every_minutes"] * 60):
                for dst in dsts:
                    add(night + k + int(rng.integers(0, 60)), src, dst.ip, f["port"],
                        int(rng.integers(300, 2_000)), int(rng.integers(500, 8_000)))
            night += DAY

    # TLS for the normal 443 flows of S07
    ja3, names = cfg["ja3_normal"], cfg["server_names"]
    for t, r in raw:
        if r["destination"]["port"] == 443 and r["destination"]["ip"] in names:
            tls.append((t, tls_record(r, names[r["destination"]["ip"]], ja3.get(r["retail"]["device"]["role"], ja3["pos-lane"]))))
    raw = sorted(raw + extra_raw, key=lambda x: x[0])
    summary = sorted(summary + [(k[0], v) for k, v in sums.items()], key=lambda x: x[0])
    return raw, summary, sorted(tls, key=lambda x: x[0])


# --- POS terminal metrics ----------------------------------------------------------------------

def pos_series(store: Store, chain: Chain, seed: int, step: int) -> list[tuple[int, dict]]:
    """Records at `step` seconds for every POS terminal of the store. S07's back-office PC tells the story."""
    cfg = config()
    p, dl, (start, end) = cfg["pos"], cfg["download"], window()
    devs = [d for d in devices(chain, store) if d.role in ("pos-lane", "pos-backoffice")]
    story = store.id == cfg["store"]
    first_night = epoch(dl["first_night"], dl["night_start_utc"])
    ts = np.arange(start, end, step)
    hour = (ts % DAY) / 3600
    daylight = np.sin(np.pi * (hour - 6) / 16).clip(0) * ((hour >= 6) & (hour < 22))
    out: list[tuple[int, dict]] = []
    for i, d in enumerate(devs):
        rng = np.random.default_rng([seed, 7, store.number, 20 + i])
        lane = d.role == "pos-lane"
        cpu = (0.07 + 0.12 * daylight if lane else 0.05 + 0.08 * daylight) + rng.normal(0, 0.012, len(ts))
        free = 64 + rng.normal(0, 0.3, len(ts))
        tx = np.clip(5.0 * daylight + rng.normal(0, 0.4, len(ts)), 0, None) if lane else np.zeros(len(ts))
        if story and not lane:
            k, within = (ts - first_night) // DAY, (ts - first_night) % DAY
            night = (ts >= first_night) & (k < dl["nights"]) & (within < dl["night_hours"] * 3600)
            cpu = np.where(night, p["cpu_busy"] + rng.normal(0, 0.02, len(ts)), cpu)
            frac = np.clip((ts - first_night) / (end - first_night), 0, 1)
            free = np.where(ts >= first_night, p["disk_free_start_pct"] + (p["disk_free_end_pct"] - p["disk_free_start_pct"]) * frac
                            + rng.normal(0, 0.3, len(ts)), free)
        for t, c, f, x in zip(ts, cpu, free, tx):
            out.append((int(t), tag({
                "@timestamp": iso(int(t)), "event": {"kind": "metric", "category": ["host"], "dataset": "pos.terminal"},
                "host": {"name": d.name, "cpu": {"usage": round(float(np.clip(c, 0, 1)), 3)}},
                "retail": {"store": {"id": store.id}, "device": {"role": d.role}},
                "coldchain": {"pos": {"disk_free_pct": round(float(f), 1), "tx_per_min": round(float(x), 2)}}})))
    return out


# --- writing ------------------------------------------------------------------------------------


def roll_up(records: list[tuple[int, dict]], step: int, fields: list[tuple[str, ...]]) -> list[tuple[int, dict]]:
    """Hourly mean per host of the numeric fields (paths in `fields`)."""
    groups: dict[tuple[int, str], list[dict]] = {}
    for t, r in records:
        groups.setdefault((t - t % 3600, r["host"]["name"]), []).append(r)
    out = []
    for (h, _), rs in sorted(groups.items()):
        rec = json.loads(json.dumps(rs[0]))
        rec["@timestamp"] = iso(h)
        for path in fields:
            vals = []
            for r in rs:
                v = r
                for p in path:
                    v = v[p]
                vals.append(v)
            node = rec
            for p in path[:-1]:
                node = node[p]
            node[path[-1]] = round(float(np.mean(vals)), 3)
        out.append((h, rec))
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", choices=["local", "s3"], default="local")
    ap.add_argument("--out", default="out-b")
    ap.add_argument("--stores", help="comma-separated store ids (default: all)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args(argv)

    chain = load_chain()
    sink = make_sink(args.target, args.out, args.resume)
    stores = [chain.store(s) for s in args.stores.split(",")] if args.stores else chain.stores
    for store in stores:
        started, counts = time.time(), {}
        _, summary, tls = store_flows(chain, store, args.seed)
        pos5 = pos_series(store, chain, args.seed, 300)
        counts["summary"] = write_records(sink, "detect", "netflow.summary", store.id, summary, 60)
        counts["pos"] = write_records(sink, "detect", "pos.terminal", store.id, roll_up(
            pos5, 300, [("host", "cpu", "usage"), ("coldchain", "pos", "disk_free_pct"), ("coldchain", "pos", "tx_per_min")]), 60)
        if store.id == config()["store"]:
            counts["tls"] = write_records(sink, "detect", "network_traffic.tls", store.id, tls, 60)
        sink.wait()
        print(f"{store.id}: {counts} in {time.time() - started:.1f}s", flush=True)
    print(f"done: {sink.files} files, {sink.bytes / 1e6:.1f} MB"
          + (f", {sink.skipped} already present" if getattr(sink, "skipped", 0) else ""))


if __name__ == "__main__":
    main()
