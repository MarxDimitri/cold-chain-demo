"""Scenario B (epilogue, hypothetical): a payload on an in-store TV box. Generator.

    python -m coldchain.scenario_b --target local --out out-b [--stores S03,S07]
    python -m coldchain.scenario_b --target s3 [--resume]

What it writes (config/scenario_b.yaml; all records carry labels.namespace = "epilogue"):
  detect/  netflow.summary   all 20 stores, 5-minute summaries; S07 adds the nightly download and the internal flows
           signage.cms       hourly roll-ups (CPU, storage) of every signage player
           power.plug        hourly roll-ups of every TV box's smart plug
  raw/     netflow.log, network_traffic.tls, signage.cms, power.plug     S07 only, hourly files

The nightly download is 123 chunks of 20-60 MB from models.example-hub.net over 9 nights, 4.6 GiB in all. One night S07 is
offline for 48 minutes: its files for that window are uploaded after it is back, with event.ingested set to the upload time.
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


def offline_span() -> tuple[int, int, int]:
    o = config()["offline"]
    return epoch(o["night"], o["from_utc"]), epoch(o["night"], o["to_utc"]), epoch(o["night"], o["upload_utc"])


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
    tv = by_role["tv-box"][0]
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
        rec = add(ts, tv, dl["server_ip"], 443, int(rng.integers(2_000, 6_000)), size)
        tls.append((ts, tls_record(rec, dl["server_name"], dl["ja3"])))

    for f in cfg["internal_flows"]:
        name, _, nth = f["src"].partition("-0")  # "signage-player-02" -> role signage-player, second device
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
            tls.append((t, tls_record(r, names[r["destination"]["ip"]], ja3.get(r["retail"]["device"]["role"], ja3["tv-box"]))))
    raw = sorted(raw + extra_raw, key=lambda x: x[0])
    summary = sorted(summary + [(k[0], v) for k, v in sums.items()], key=lambda x: x[0])
    return raw, summary, sorted(tls, key=lambda x: x[0])


# --- edge metrics -----------------------------------------------------------------------------

def edge_series(store: Store, chain: Chain, seed: int, step: int):
    """(signage records, plug records) at `step` seconds. S07's SIG-02 and TV box tell the story."""
    cfg = config()
    e, (start, end) = cfg["edge"], window()
    devs = devices(chain, store)
    sigs = [d for d in devs if d.role == "signage-player"]
    tv = next(d for d in devs if d.role == "tv-box")
    story = store.id == cfg["store"]
    busy_from = epoch(e["signage_busy_from"])
    first_night = epoch(cfg["download"]["first_night"], cfg["download"]["night_start_utc"])
    ts = np.arange(start, end, step)
    sig_out, plug_out = [], []
    for i, d in enumerate(sigs):
        rng = np.random.default_rng([seed, 7, store.number, 20 + i])
        hour = (ts % DAY) / 3600
        cpu = 0.28 + 0.10 * np.sin(np.pi * (hour - 6) / 16).clip(0) + rng.normal(0, 0.02, len(ts))
        free = 62 + rng.normal(0, 0.4, len(ts))
        if story and d.name.endswith("SIG-02"):
            on = ts >= busy_from
            cpu = np.where(on, e["signage_cpu_busy"] + rng.normal(0, 0.008, len(ts)), cpu)
            frac = np.clip((ts - busy_from) / (end - busy_from), 0, 1)
            free = np.where(on, e["storage_free_start_pct"] + (e["storage_free_end_pct"] - e["storage_free_start_pct"]) * frac
                            + rng.normal(0, 0.3, len(ts)), free)
        for t, c, f in zip(ts, cpu, free):
            sig_out.append((int(t), tag({
                "@timestamp": iso(int(t)), "event": {"kind": "metric", "category": ["host"], "dataset": "signage.cms"},
                "host": {"name": d.name, "cpu": {"usage": round(float(np.clip(c, 0, 1)), 3)}},
                "retail": {"store": {"id": store.id}, "device": {"role": "signage-player"}},
                "coldchain": {"edge": {"storage": {"free_pct": round(float(f), 1)}}}})))
    rng = np.random.default_rng([seed, 7, store.number, 30])
    watts = 3.0 + 0.4 * np.sin(np.pi * (((ts % DAY) / 3600) - 6) / 16).clip(0) + rng.normal(0, 0.12, len(ts))
    if story:
        watts = np.where(ts >= first_night, e["plug_watts_busy"] + rng.normal(0, 0.25, len(ts)), watts)
    for t, w in zip(ts, watts):
        plug_out.append((int(t), tag({
            "@timestamp": iso(int(t)), "event": {"kind": "metric", "category": ["host"], "dataset": "power.plug"},
            "host": {"name": f"{store.id}-PLUG-01"},
            "retail": {"store": {"id": store.id}, "device": {"role": "smart-plug"}},
            "coldchain": {"edge": {"attached_to": tv.name, "power": {"watts": round(float(max(w, 0.5)), 2)}}}})))
    return sig_out, plug_out


# --- writing, with the offline window ----------------------------------------------------------

def write_late(sink, store: Store, layer: str, dataset: str, records: list[tuple[int, dict]], rotation: int) -> int:
    """Write records; those inside S07's offline window go in one file uploaded after it, with event.ingested set."""
    a, b, up = offline_span()
    late = [(t, r) for t, r in records if store.id == config()["store"] and a <= t <= b]
    normal = [(t, r) for t, r in records if not (store.id == config()["store"] and a <= t <= b)]
    n = write_records(sink, layer, dataset, store.id, normal, rotation)
    if late:
        for i, (t, r) in enumerate(late):
            r["event"]["ingested"] = iso(up + 20 + i % 30)
        late.sort(key=lambda x: x[0])
        write_chunk(sink, layer, dataset, store.id, up,
                    [json.dumps(r, separators=(",", ":")) for _, r in late], seq=1)
        n += len(late)
    return n


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
    ap.add_argument("--raw-only", action="store_true",
                    help="write only the raw/ files of S07 (rewrites them; the indexed detect/ files are not uploaded again)")
    args = ap.parse_args(argv)

    chain = load_chain()
    sink = make_sink(args.target, args.out, args.resume)
    stores = [chain.store(s) for s in args.stores.split(",")] if args.stores else chain.stores
    for store in stores:
        started, counts = time.time(), {}
        raw, summary, tls = store_flows(chain, store, args.seed)
        sig5, plug5 = edge_series(store, chain, args.seed, 300)
        if not args.raw_only:
            counts["summary"] = write_late(sink, store, "detect", "netflow.summary", summary, 60)
            counts["signage"] = write_late(sink, store, "detect", "signage.cms",
                                           roll_up(sig5, 300, [("host", "cpu", "usage"), ("coldchain", "edge", "storage", "free_pct")]), 60)
            counts["plug"] = write_late(sink, store, "detect", "power.plug",
                                        roll_up(plug5, 300, [("coldchain", "edge", "power", "watts")]), 60)
        if store.id == config()["store"]:
            counts["flows raw"] = write_late(sink, store, "raw", "netflow.log", raw, 60)
            counts["tls raw"] = write_late(sink, store, "raw", "network_traffic.tls", tls, 60)
            counts["signage raw"] = write_late(sink, store, "raw", "signage.cms", sig5, 60)
            counts["plug raw"] = write_late(sink, store, "raw", "power.plug", plug5, 60)
        print(f"{store.id}: {counts} in {time.time() - started:.1f}s", flush=True)
    print(f"done: {sink.files} files, {sink.bytes / 1e6:.1f} MB"
          + (f", {sink.skipped} already present" if getattr(sink, "skipped", 0) else ""))


if __name__ == "__main__":
    main()
