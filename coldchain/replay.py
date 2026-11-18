"""Replay scenario A in simulated time (speed 1x on stage, 10x in rehearsal).

    python -m coldchain.replay run [--t0 now|config|ISO] [--speed 1] [--restore auto|trigger]
                                   [--scenario setpoint|defrost] [--spoof]
    python -m coldchain.replay trigger     # what the mock response service calls to restore setpoints
    python -m coldchain.replay reset       # clear local replay state

The loop steps one simulated minute at a time and writes 1-minute detect/ files for every store
(normal telemetry and flow summaries for all 20, attack events on top). Raw files are hourly, so
they are written when the run ends. With --s07-mode files, S07's records go to local files (and
optional UDP NetFlow) for the store-in-a-box instead of the sink.
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import shutil
import time
from collections import defaultdict
from datetime import datetime, timezone
from itertools import count
from pathlib import Path

import numpy as np

from .attack import AttackPlan, iso
from .chain import ROOT, load_attack, load_chain, parse_ts
from .netflow import Exporter
from .network import WINDOW, flows
from .sink import make_sink, write_chunk, write_records
from . import trucks
from .telemetry import PROBE_STEP, evaporator_series, probe_line, probe_offsets, store_series, telemetry_line

STATE_DIR = ROOT / ".replay"
TRIGGER = STATE_DIR / "restore.trigger"
S07_DIR = ROOT / "replay" / "s07"
PREROLL = 180  # seconds before T0 (logins land at T0-140s)
TAIL = 300     # seconds of data after the pull-down ends
LAYERS = {"coldchain.case": ("detect",), "coldchain.probe": ("detect",), "coldchain.audit": ("detect",),
          "netflow.summary": ("detect",), "netflow.log": (), "logistics.truck": ("detect",)}  # raw flows are generated for the attack plan but not written


class Replay:
    def __init__(self, args):
        self.args = args
        self.chain, cfg = load_chain(), load_attack()
        now = time.time()
        if args.t0 == "now":
            self.start = math.ceil(now / 60) * 60
            t0 = self.start + PREROLL
            self.wall0 = float(self.start)
        else:
            t0 = int((parse_ts(cfg["t0"]) if args.t0 == "config" else parse_ts(args.t0)).timestamp())
            self.start = t0 - PREROLL
            self.wall0 = now
        # `make demo` pre-rolls normal data up to a minute boundary before the replay starts; the loop begins there and
        # catches up on the minutes before T0-3m without waiting, so the indexed data has no hole.
        self.begin = self.start
        marker = STATE_DIR / "preroll.json"
        if marker.exists():
            filled = json.loads(marker.read_text())["end"]
            marker.unlink()
            if args.t0 == "now" and 0 < self.start - filled <= 1800:
                self.begin = filled
        self.scenario = args.scenario
        self.spoof = bool(args.spoof or cfg.get("telemetry_spoof", {}).get("enabled"))
        self.plan = AttackPlan(self.chain, cfg, t0, self.scenario)
        self.t0 = t0
        self.end = t0 + args.max_minutes * 60
        self.rng = np.random.default_rng(args.seed)
        self.sink = make_sink(args.target, args.out)
        self.exporter = None
        if args.netflow:
            host, port = args.netflow.rsplit(":", 1)
            self.exporter = Exporter(host, int(port))
        self.pending: list = []
        self.tick = count()
        self.detect: dict[tuple, list[str]] = defaultdict(list)
        self.raw: dict[tuple, list[tuple[int, dict]]] = defaultdict(list)
        self.restore_t: int | None = None
        self.stats = defaultdict(int)

    # --- time -----------------------------------------------------------------------------

    def sim_now(self) -> float:
        return self.start + (time.time() - self.wall0) * self.args.speed if self.args.speed > 0 else self.start

    def wait_until(self, sim_t: float) -> None:
        if self.args.speed > 0:
            delay = self.wall0 + (sim_t - self.start) / self.args.speed - time.time()
            if delay > 0:
                time.sleep(delay)

    # --- events ---------------------------------------------------------------------------

    def push(self, emit_ts: int, dataset: str, store: str, rec, ts: int | None = None) -> None:
        heapq.heappush(self.pending, (emit_ts, next(self.tick), dataset, store, rec, ts if ts is not None else emit_ts))

    def push_attack(self) -> None:
        p = self.plan
        first = p.setpoint_events(self.rng) if self.scenario == "setpoint" else p.defrost_events(p.start, self.rng)
        for t, sid, rec in p.login_events() + first:
            self.push(t, "coldchain.audit", sid, rec)
        raw = p.attack_flows()
        for w, sid, rec in p.summarize(raw):
            self.push(w + WINDOW - 1, "netflow.summary", sid, rec, ts=w)

    def push_restore(self, restore_t: int) -> None:
        self.restore_t = restore_t
        for t, sid, rec in self.plan.restore_events(restore_t, self.rng):
            self.push(t, "coldchain.audit", sid, rec)
        STATE_DIR.mkdir(exist_ok=True)
        (STATE_DIR / "state.json").write_text(json.dumps({"t0": iso(self.t0), "restore": iso(restore_t)}))
        print(f"  restore issued at {iso(restore_t)} (T0+{(restore_t - self.t0) / 60:.1f} min)", flush=True)

    def load_erp(self) -> None:
        """Write the delivery plan as the ERP holds it (kb-erp-deliveries) with planned arrivals relative to T0."""
        from .elastic import client
        from elasticsearch import helpers
        es = client()
        rows = trucks.erp_rows(self.t0)
        helpers.bulk(es, ({"_index": "kb-erp-deliveries", "_id": r["kb"]["key"], "_source": r} for r in rows), refresh="wait_for")
        print(f"  ERP: {len(rows)} delivery stops loaded", flush=True)

    def push_trucks(self, fleet, m: int, history: bool = False) -> None:
        """One telemetry record per truck and minute; on the first step also the HISTORY_MIN minutes before, so they are on the road."""
        first = m - trucks.HISTORY_MIN * 60 if history else m
        for mm in range(first, m + 1, 60):
            for tr in fleet:
                line = trucks.telemetry_line(tr, (mm - self.t0) / 60, iso(mm), self.rng)
                if line:
                    self.push(m + 59, "logistics.truck", "LOG", line, ts=mm)

    def push_normal_flows(self, wstart: int) -> None:
        for store in self.chain.stores:
            _, summary = flows(self.chain, store, wstart, 0, self.args.seed, windows=1)
            for ts, rec in summary:
                self.push(wstart + WINDOW - 1, "netflow.summary", store.id, rec, ts=ts)

    # --- output ---------------------------------------------------------------------------

    def route(self, dataset: str, store: str, rec, ts: int) -> None:
        line = rec if isinstance(rec, str) else json.dumps(rec, separators=(",", ":"), ensure_ascii=False)
        self.stats[dataset] += 1
        for layer in LAYERS[dataset]:
            if store == "S07" and self.args.s07_mode == "files":
                if layer == "detect" or dataset == "netflow.log":
                    S07_DIR.mkdir(parents=True, exist_ok=True)
                    with open(S07_DIR / f"{dataset}.ndjson", "a") as fh:
                        fh.write(line + "\n")
                    if dataset == "netflow.log" and self.exporter:
                        self.exporter.send([rec])
                continue
            if layer == "detect":
                self.detect[(dataset, store)].append(line)
            else:
                self.raw[(dataset, store)].append((ts, rec))

    def flush(self, minute: int, until: int) -> None:
        while self.pending and self.pending[0][0] < until:
            _, _, dataset, store, rec, ts = heapq.heappop(self.pending)
            self.route(dataset, store, rec, ts)
        for (dataset, store), lines in self.detect.items():
            write_chunk(self.sink, "detect", dataset, store, minute, lines)
        self.detect.clear()
        self.sink.wait()

    def finish(self) -> None:
        for (dataset, store), recs in self.raw.items():
            write_records(self.sink, "raw", dataset, store, recs, 60)
        self.raw.clear()
        self.sink.wait()

    # --- main loop ------------------------------------------------------------------------

    def run(self) -> None:
        a, p = self.args, self.plan
        STATE_DIR.mkdir(exist_ok=True)
        TRIGGER.unlink(missing_ok=True)
        print(f"replay: T0={iso(self.t0)} scenario={self.scenario}{' +spoof' if self.spoof else ''} "
              f"speed={a.speed}x restore={a.restore} target={a.target}", flush=True)
        if a.target == "s3":
            print(f"afterwards: make reset-demo SINCE={iso(self.start)} DELETE=1   (SINCE keeps the pre-roll, removes the run)", flush=True)

        series_start = self.begin - 600
        minutes = (self.end - series_start) // 60 + 6
        base = {s.id: store_series(self.chain, s, series_start, minutes, a.seed) for s in self.chain.stores}
        air = {cid: arr[0].copy() for _, (series, _) in base.items() for cid, arr in series.items()}
        evap = {s.id: evaporator_series(self.chain, s, series_start, minutes, a.seed) for s in self.chain.stores}
        poff = {s.id: probe_offsets(self.chain, s, series_start, minutes, a.seed) for s in self.chain.stores}
        targets = {c.id for _, c in p.targets()}
        self.wait_until(self.start)
        self.push_attack()
        fleet = trucks.build()
        if a.target == "s3":  # the ERP delivery plan, with planned arrivals relative to this run's T0
            self.load_erp()

        try:
            for step in range((self.end - self.begin) // 60):
                m = self.begin + 60 * step
                if self.restore_t is None:
                    if a.restore == "auto" and m + 60 > self.t0 + p.cfg["restore"]["offset_minutes"] * 60:
                        self.push_restore(self.t0 + p.cfg["restore"]["offset_minutes"] * 60)
                    elif a.restore == "trigger":
                        if TRIGGER.exists():
                            self.push_restore(max(m, int(self.sim_now())))
                        elif m + 60 > self.t0 + a.restore_timeout * 60:
                            self.push_restore(self.t0 + a.restore_timeout * 60)
                if m % WINDOW == 0:
                    self.push_normal_flows(m)
                self.push_trucks(fleet, m, history=step == 0)

                i = (m - series_start) // 60
                for store in self.chain.stores:
                    series, cabs = base[store.id]
                    for cab in cabs:
                        a_series = series[cab.id][0][i]  # what the cabinet would read in normal operation
                        normal_defrost = bool(series[cab.id][2][i])
                        a_true, true_sp = a_series, cab.setpoint
                        attacking = False
                        if cab.id in targets:
                            attacking = p.start <= m and (self.restore_t is None or m < self.restore_t)
                            if attacking and self.scenario == "setpoint":
                                true_sp = p.cfg["setpoint_change"]["new_value"]
                            if p.in_recovery(m, self.restore_t):
                                a_true = cab.setpoint + p.excess(cab.setpoint, m, self.restore_t) \
                                    + float(self.rng.normal(0, 0.08))
                        spoofed = self.spoof and attacking  # the controller reports normal values
                        reported_air = a_series if spoofed else a_true
                        reported_sp = cab.setpoint if spoofed else true_sp
                        # the defrost relay: a forced defrost switches it on, the +50 setpoint does not
                        reported_defrost = normal_defrost or (attacking and self.scenario == "defrost" and not spoofed)
                        # the evaporator follows the air once refrigeration is off (attack, recovery), else normal
                        evap_v = float(evap[store.id][cab.id][i]) if reported_air == a_series else reported_air - 4.0
                        air[cab.id][i] = reported_air
                        rise = reported_air - air[cab.id][i - 5]
                        self.push(m + 59, "coldchain.case", store.id,
                                  telemetry_line(iso(m), store, cab, reported_sp, reported_air, rise, reported_defrost,
                                                 evap_v), ts=m)
                        if (m // 60) % PROBE_STEP == 0:  # independent probe: always the true temperature
                            self.push(m + 59, "coldchain.probe", store.id,
                                      probe_line(iso(m), store, cab, a_true + poff[store.id][cab.id][i]), ts=m)

                if self.scenario == "defrost":  # the attacker keeps re-issuing the forced defrost
                    for t in p.defrost_times(m, m + 60):
                        if self.restore_t is None or t < self.restore_t:
                            for ts, sid, rec in p.defrost_events(t, self.rng):
                                self.push(ts, "coldchain.audit", sid, rec)

                self.wait_until(m + 60)
                self.flush(m, m + 60)
                label = f"T{'+' if m >= self.t0 else '-'}{abs(m - self.t0) // 60}m"
                print(f"  {iso(m)} {label:>5}  files={self.sink.files}", flush=True)

                if self.restore_t is not None and \
                        m >= self.restore_t + p.cfg["restore"]["pulldown_minutes"] * 60 + TAIL:
                    break
        finally:
            self.flush(self.end, self.end + 10**9)
            self.finish()
        print(f"done: {dict(self.stats)}; {self.sink.files} files, {self.sink.bytes / 1e6:.1f} MB", flush=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--t0", default="now", help="now | config | ISO timestamp")
    run.add_argument("--speed", type=float, default=1.0, help="1 on stage, 10 in rehearsal, 0 = no waiting")
    run.add_argument("--restore", choices=["auto", "trigger"], default="auto")
    run.add_argument("--restore-timeout", type=float, default=15, help="minutes after T0 before trigger mode gives up")
    run.add_argument("--max-minutes", type=int, default=70, help="simulated minutes after T0")
    run.add_argument("--target", choices=["local", "s3"], default="local")
    run.add_argument("--out", default="out")
    run.add_argument("--s07-mode", choices=["sink", "files"], default="sink")
    run.add_argument("--netflow", help="host:port for UDP NetFlow v5 of S07's raw flows (with --s07-mode files)")
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--scenario", choices=["setpoint", "defrost"], default="setpoint",
                     help="setpoint: A (+50 C setpoint). defrost: A2 (forced defrost, no setpoint change)")
    run.add_argument("--spoof", action="store_true",
                     help="hypothetical: the controller reports normal values on the targeted cabinets until the restore")
    sub.add_parser("trigger")
    sub.add_parser("reset")
    args = ap.parse_args(argv)

    if args.cmd == "run":
        Replay(args).run()
    elif args.cmd == "trigger":
        STATE_DIR.mkdir(exist_ok=True)
        TRIGGER.write_text(datetime.now(timezone.utc).isoformat())
        print(f"trigger written: {TRIGGER}")
    else:
        shutil.rmtree(STATE_DIR, ignore_errors=True)
        shutil.rmtree(S07_DIR, ignore_errors=True)
        print("local replay state cleared (cluster and bucket data are not touched)")


if __name__ == "__main__":
    main()
