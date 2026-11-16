"""Backfill: write synthetic history to raw/ and detect/ in the bucket layout.

Backfill files use coarser rotation than live traffic (default 60 min for detect/) so 35 days of
history is about 50k objects instead of millions. Live replay uses 1-minute files.
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
    ap.add_argument("--detect-days", type=int, default=35, help="indexed history (telemetry, audit, summaries)")
    ap.add_argument("--raw-days", type=int, default=365, help="raw audit history")
    ap.add_argument("--flow-days", type=int, default=7, help="raw flows and summaries")
    ap.add_argument("--raw-telemetry-days", type=int, default=0, help="optional raw telemetry at 5-min resolution")
    ap.add_argument("--detect-rotation", type=int, default=60, help="minutes per detect/ file")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--raw-audit-rotation", type=int, default=1440,
                    help="minutes per raw audit file; daily keeps 12 months under the federation limit of 10,000 files")
    ap.add_argument("--only", help="comma-separated parts to write: telemetry,probe,audit,audit-raw,flows (default: all; audit-raw skips the indexed copy)")
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
            counts["telemetry"] = write_telemetry(sink, chain, store, "detect", d_epoch, minutes, 1,
                                                  args.detect_rotation, args.seed)
        if "probe" in only:
            counts["probe"] = write_probe(sink, chain, store, "detect", d_epoch, minutes,
                                          args.detect_rotation, args.seed)
        if args.raw_telemetry_days and "telemetry" in only:
            r_epoch = int((end - timedelta(days=args.raw_telemetry_days)).timestamp()) // 60 * 60
            counts["raw telemetry"] = write_telemetry(
                sink, chain, store, "raw", r_epoch, int((end.timestamp() - r_epoch) // 60), 5, 60, args.seed)

        if "audit" in only or "audit-raw" in only:
            audit = audit_history(chain, store, end - timedelta(days=args.raw_days), end, args.seed, probes, t0)
            counts["audit raw"] = write_records(sink, "raw", "coldchain.audit", store.id, audit,
                                                args.raw_audit_rotation)
            if "audit" in only:
                recent = [(e, r) for e, r in audit if e >= int(d_start.timestamp())]
                counts["audit detect"] = write_records(sink, "detect", "coldchain.audit", store.id, recent,
                                                       args.detect_rotation)

        if args.flow_days and "flows" in only:
            f_epoch = int((end - timedelta(days=args.flow_days)).timestamp()) // 300 * 300
            raw, summary = flows(chain, store, f_epoch, args.flow_days, args.seed)
            counts["flows raw"] = write_records(sink, "raw", "netflow.log", store.id, raw, 60)
            counts["flows summary"] = write_records(sink, "detect", "netflow.summary", store.id, summary,
                                                    args.detect_rotation)
        print(f"{store.id}: {counts} in {time.time() - started:.1f}s", flush=True)

    print(f"done: {sink.files} files, {sink.bytes / 1e6:.1f} MB"
          + (f", {sink.skipped} already present" if getattr(sink, "skipped", 0) else ""))


if __name__ == "__main__":
    main()
