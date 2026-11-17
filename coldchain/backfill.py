"""Backfill: write synthetic history to detect/ in the bucket layout, for the collector to index.

Everything is indexed (there is no raw/ side any more): a year of store audit, and a short window of telemetry, probes and
flow summaries (default 7 days: the demo needs context, not a month). Backfill files use coarser rotation than live traffic
(60 minutes for telemetry, one file per store and day for the audit) so the history stays a few thousand objects. Live replay
uses 1-minute files.
"""
from __future__ import annotations

import argparse
import time
from datetime import timedelta

from .audit import audit_history
from .chain import load_attack, load_chain, parse_ts
from .network import flows
from .sink import make_sink, write_records
from .telemetry import write_probe, write_telemetry

HISTORY_GAP = timedelta(minutes=5)  # history ends this long before T0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", choices=["local", "s3"], default="local")
    ap.add_argument("--out", default="out")
    ap.add_argument("--stores", help="comma-separated store ids (default: all)")
    ap.add_argument("--detect-days", type=int, default=7, help="telemetry, probes and flow summaries")
    ap.add_argument("--audit-days", type=int, default=365, help="store audit history")
    ap.add_argument("--detect-rotation", type=int, default=60, help="minutes per detect/ file (telemetry, probes, summaries)")
    ap.add_argument("--audit-rotation", type=int, default=1440, help="minutes per audit file (one a day keeps a year to 7,300 objects)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--only", help="comma-separated parts to write: telemetry,probe,audit,flows (default: all)")
    ap.add_argument("--resume", action="store_true",
                    help="s3 only: skip objects already in the bucket (needs operator credentials to list)")
    args = ap.parse_args(argv)

    chain, attack = load_chain(), load_attack()
    t0 = parse_ts(attack["t0"])
    end = t0 - HISTORY_GAP
    probes = [{**p, "attacker_ip": attack["attacker_ip"]} for p in attack["probes"]]
    sink = make_sink(args.target, args.out, args.resume)
    stores = [chain.store(s) for s in args.stores.split(",")] if args.stores else chain.stores

    only = set(args.only.split(",")) if args.only else {"telemetry", "probe", "audit", "flows"}
    for store in stores:
        started, counts = time.time(), {}
        d_start = end - timedelta(days=args.detect_days)
        d_epoch = int(d_start.timestamp()) // 60 * 60
        minutes = int((end.timestamp() - d_epoch) // 60)
        if "telemetry" in only:
            counts["telemetry"] = write_telemetry(sink, chain, store, "detect", d_epoch, minutes, 1, args.detect_rotation, args.seed)
        if "probe" in only:
            counts["probe"] = write_probe(sink, chain, store, "detect", d_epoch, minutes, args.detect_rotation, args.seed)
        if "audit" in only:
            audit = audit_history(chain, store, end - timedelta(days=args.audit_days), end, args.seed, probes, t0)
            counts["audit"] = write_records(sink, "detect", "coldchain.audit", store.id, audit, args.audit_rotation)
        if "flows" in only:
            f_epoch = int(d_start.timestamp()) // 300 * 300
            _, summary = flows(chain, store, f_epoch, args.detect_days, args.seed)
            counts["flows summary"] = write_records(sink, "detect", "netflow.summary", store.id, summary, args.detect_rotation)
        print(f"{store.id}: {counts} in {time.time() - started:.1f}s", flush=True)

    print(f"done: {sink.files} files, {sink.bytes / 1e6:.1f} MB"
          + (f", {sink.skipped} already present" if getattr(sink, "skipped", 0) else ""))


if __name__ == "__main__":
    main()
