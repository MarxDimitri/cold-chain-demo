"""Score the trained ML jobs against synthetic attack runs, without touching the production indices.

    python -m coldchain.mlscore baseline                 # record the trained snapshot (once, before any run)
    python -m coldchain.mlscore run control|setpoint|defrost|spoof [--tag NAME]
    python -m coldchain.mlscore restore                  # revert both jobs to the baseline, delete test artefacts

How it works: the trained models (35 days, ending 2026-11-12 02:47) are frozen as a snapshot. Each run reverts both
jobs to that snapshot, writes the scenario's telemetry to a throw-away index (`test-coldchain-case-ml`), points the
datafeeds at it, replays 02:47 onward, and reads the anomaly records. `control` is the same clock with no attack
(it runs through the 05:00 UTC scheduled defrost). The attack runs use the real replay generator.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import io
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from elasticsearch import helpers

from . import replay
from .attack import AttackPlan, iso
from .chain import ROOT, cabinets, load_attack, load_chain, parse_ts
from .elastic import client
from .ml import INDEX, JOBS
from .telemetry import store_series, telemetry_line

TEST_INDEX = "test-coldchain-case-ml"
WORK = ROOT / ".ml-scoring"
HISTORY_END = "2026-11-12T02:47:00Z"
SEED = 42
CONTROL_MINUTES = 253  # 02:47 -> 07:00, includes the 05:00 UTC scheduled defrost


def epoch(ts: str) -> int:
    return int(parse_ts(ts).timestamp())


# --- data ------------------------------------------------------------------------------------

def control_docs(start: int, minutes: int) -> list[dict]:
    """The same generator as the replay with no attack: what the cabinets would normally report."""
    chain = load_chain()
    series_start = start - 600
    total = (minutes * 60 + 600) // 60 + 6
    out = []
    for store in chain.stores:
        series, cabs = store_series(chain, store, series_start, total, SEED)
        for cab in cabs:
            air, _, dfr = series[cab.id]
            for k in range(minutes):
                i = (start - series_start) // 60 + k
                out.append(json.loads(telemetry_line(iso(start + 60 * k), store, cab, cab.setpoint,
                                                     float(air[i]), float(air[i] - air[i - 5]), bool(dfr[i]))))
    return out


def slow_excess(cfg: dict, minutes_since_start: float) -> float:
    """Kelvin above nominal at a time after the slow warming started (config/attack.yaml `slow_warming`)."""
    import math
    t = minutes_since_start
    if t < 0:
        return 0.0
    rise = lambda m: cfg["plateau_c"] * (1 - math.exp(-m / cfg["tau_minutes"]))
    end = cfg["duration_minutes"]
    if t < end:
        return rise(t)
    return rise(end) * math.exp(-3.5 * (t - end) / cfg["pulldown_minutes"])


def slow_targets() -> set[str]:
    cfg = load_attack()["slow_warming"]
    out = set()
    for sid, rng in cfg["cabinets"].items():
        lo, hi = int(rng["from"][1:]), int(rng["to"][1:])
        out |= {c.id for c in cabinets(load_chain(), load_chain().store(sid)) if lo <= int(c.id[-2:]) <= hi}
    return out


def slow_docs(start: int, minutes: int) -> list[dict]:
    """Control telemetry with the slow warming added to the air temperature of the target cabinets."""
    cfg, targets = load_attack()["slow_warming"], slow_targets()
    t_start = epoch(load_attack()["t0"]) + cfg["offset_seconds"]
    docs = control_docs(start, minutes)
    for d in docs:
        if d["device"]["id"] in targets:
            e = slow_excess(cfg, (epoch(d["@timestamp"]) - t_start) / 60)
            t = d["coldchain"]["case"]["temperature"]
            t["air"] = round(t["air"] + e, 2)  # rise_5m is left as generated: the slow warming is meant to be gradual
    return docs


def replay_docs(scenario: str, tmp: Path) -> list[dict]:
    replay.PREROLL = 300  # start the run at 02:47, where the training history ends
    args = ["run", "--t0", "config", "--speed", "0", "--restore", "auto", "--target", "local", "--out", str(tmp),
            "--seed", str(SEED)]
    if scenario == "defrost":
        args += ["--scenario", "defrost"]
    if scenario == "spoof":
        args += ["--spoof"]
    with contextlib.redirect_stdout(io.StringIO()):
        replay.main(args)
    docs = []
    for f in sorted(tmp.glob("detect/dataset=coldchain.case/**/*.ndjson.gz")):
        with gzip.open(f, "rt") as fh:
            docs += [json.loads(line) for line in fh]
    return docs


def create_test_index(es) -> None:
    if es.indices.exists(index=TEST_INDEX):
        es.indices.delete(index=TEST_INDEX)
    kw = {"type": "keyword"}
    es.indices.create(index=TEST_INDEX, mappings={"properties": {
        "@timestamp": {"type": "date"}, "device": {"properties": {"id": kw}},
        "retail": {"properties": {"store": {"properties": {"id": kw}}}},
        "coldchain": {"properties": {"application": kw, "case": {"properties": {
            "setpoint": {"type": "float"},
            "temperature": {"properties": {"air": {"type": "float"}, "rise_5m": {"type": "float"}}}}}}}}})


# --- ML plumbing -----------------------------------------------------------------------------

def baselines(es) -> dict[str, str]:
    path = WORK / "baseline.json"
    if not path.exists():
        sys.exit("no baseline recorded: run `python -m coldchain.mlscore baseline` first")
    return json.loads(path.read_text())


def record_baseline(es) -> None:
    WORK.mkdir(exist_ok=True)
    out = {}
    for job in JOBS:
        st = es.ml.get_job_stats(job_id=job)["jobs"][0]
        if st["state"] != "closed":
            sys.exit(f"{job} is {st['state']}: close it first")
        snaps = es.ml.get_model_snapshots(job_id=job)["model_snapshots"]
        snaps.sort(key=lambda s: s["timestamp"])
        cur = snaps[-1]
        es.ml.update_model_snapshot(job_id=job, snapshot_id=cur["snapshot_id"], retain=True)  # keep it safe
        out[job] = cur["snapshot_id"]
        print(f"{job}: baseline snapshot {cur['snapshot_id']} (latest record {cur.get('latest_record_time_stamp')}, "
              f"created {cur['timestamp']}), retained")
    (WORK / "baseline.json").write_text(json.dumps(out))


def revert(es, base: dict[str, str]) -> None:
    for job, snap in base.items():
        es.ml.revert_model_snapshot(job_id=job, snapshot_id=snap, delete_intervening_results=True)


def point_datafeeds(es, index: str) -> None:
    for job in JOBS:
        es.ml.update_datafeed(datafeed_id=f"datafeed-{job}", indices=[index])


def run_feed(es, start: str, end: str) -> None:
    for job in JOBS:
        es.ml.open_job(job_id=job)
        es.ml.start_datafeed(datafeed_id=f"datafeed-{job}", start=start, end=end)
    deadline = time.time() + 1500
    while time.time() < deadline:
        states = [es.ml.get_datafeed_stats(datafeed_id=f"datafeed-{j}")["datafeeds"][0]["state"] for j in JOBS]
        if all(s == "stopped" for s in states):
            break
        time.sleep(5)
    else:
        sys.exit("datafeeds did not finish in 25 minutes")
    for job in JOBS:
        es.ml.close_job(job_id=job)


def fetch(es, job: str, since: str) -> tuple[list[dict], list[dict]]:
    base = [{"term": {"job_id": job}}, {"range": {"timestamp": {"gte": since}}}]
    recs = helpers.scan(es, index=".ml-anomalies-*", query={"query": {"bool": {"filter": base + [
        {"term": {"result_type": "record"}}, {"range": {"record_score": {"gte": 1}}}]}}})
    buckets = helpers.scan(es, index=".ml-anomalies-*", query={"query": {"bool": {"filter": base + [
        {"term": {"result_type": "bucket"}}]}}})
    return [r["_source"] for r in recs], [b["_source"] for b in buckets]


# --- analysis --------------------------------------------------------------------------------

def ms(t) -> str:
    return datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime("%H:%M:%S")


def analyse(scenario: str, es, since: str, targets: set[str], attack_start: int, restore_t: int,
            jobs=JOBS) -> dict:
    res = {"scenario": scenario}
    stores_t = {c[:3] for c in targets}
    for job in jobs:
        recs, buckets = fetch(es, job, since)
        dev = lambda r: r.get("partition_field_value") or r.get("over_field_value") or ""
        for thr in (50, 75):
            hit = [r for r in recs if r["record_score"] >= thr]
            on = {dev(r) for r in hit if dev(r) in targets}
            off = [r for r in hit if dev(r) not in targets]
            pre = [r for r in hit if dev(r) in targets and r["timestamp"] < attack_start * 1000]
            first = min((r["timestamp"] for r in hit if dev(r) in targets and r["timestamp"] >= attack_start * 1000),
                        default=None)
            res[f"{job}@{thr}"] = {
                "target_cabinets_flagged": len(on), "of": len(targets),
                "first_target_record_bucket": ms(first) if first else None,
                "seconds_after_attack_start": (first // 1000 - attack_start) if first else None,
                "stores_flagged": sorted({dev(r)[:3] for r in hit}),
                "target_stores_flagged": sorted({d[:3] for d in on}),
                "false_positive_records": len(off), "false_positive_cabinets": len({dev(r) for r in off}),
                "records_on_targets_before_attack": len(pre),
                "top_false_positives": [(dev(r), ms(r["timestamp"]), round(r["record_score"], 1))
                                        for r in sorted(off, key=lambda r: -r["record_score"])[:5]],
            }
        sc = [(b["timestamp"], b["anomaly_score"]) for b in buckets]
        for thr in (50, 75):
            first = min((t for t, s in sc if s >= thr and t >= attack_start * 1000), default=None)
            res[f"{job}:bucket@{thr}"] = {"first_bucket": ms(first) if first else None,
                                          "buckets_at_or_above": sum(1 for _, s in sc if s >= thr),
                                          "before_attack": sum(1 for t, s in sc if s >= thr and t < attack_start * 1000)}
        res[f"{job}:max_record_score"] = round(max((r["record_score"] for r in recs), default=0), 1)
        (WORK / f"{scenario}-{job}-records.json").write_text(json.dumps(
            [r for r in recs if r["record_score"] >= 25], default=str))
    return res


def run(es, scenario: str, tag: str) -> dict:
    WORK.mkdir(exist_ok=True)
    base = baselines(es)
    cfg, chain = load_attack(), load_chain()
    start = epoch(HISTORY_END)
    plan = AttackPlan(chain, cfg, epoch(cfg["t0"]), "defrost" if scenario == "defrost" else "setpoint")
    targets = {c.id for _, c in plan.targets()}
    restore_t = plan.t0 + cfg["restore"]["offset_minutes"] * 60

    docs = control_docs(start, CONTROL_MINUTES) if scenario == "control" else replay_docs(scenario, WORK / f"out-{scenario}")
    docs = [d for d in docs if d["@timestamp"] >= HISTORY_END]
    last = max(d["@timestamp"] for d in docs)
    end = iso(epoch(last) + 60)
    print(f"[{scenario}] {len(docs)} telemetry docs, {HISTORY_END} -> {end}", flush=True)

    create_test_index(es)
    helpers.bulk(es, ({"_index": TEST_INDEX, "_source": d} for d in docs), chunk_size=5000, request_timeout=120)
    es.indices.refresh(index=TEST_INDEX)
    assert es.count(index=TEST_INDEX)["count"] == len(docs)

    revert(es, base)
    point_datafeeds(es, TEST_INDEX)
    t = time.time()
    run_feed(es, HISTORY_END, end)
    print(f"[{scenario}] datafeeds finished in {time.time() - t:.0f}s", flush=True)
    res = analyse(scenario, es, HISTORY_END, targets, plan.start, restore_t)
    res["tag"] = tag
    (WORK / f"{scenario}{'-' + tag if tag else ''}.json").write_text(json.dumps(res, indent=1))
    return res


def restore(es) -> None:
    base = baselines(es)
    for job in JOBS:
        for call, kw in ((es.ml.stop_datafeed, {"datafeed_id": f"datafeed-{job}"}), (es.ml.close_job, {"job_id": job})):
            try:
                call(**kw)
            except Exception:
                pass
    revert(es, base)
    point_datafeeds(es, INDEX)
    for job, snap in base.items():  # drop the snapshots the test runs created
        snaps = es.ml.get_model_snapshots(job_id=job)["model_snapshots"]
        cur_ts = next(s["timestamp"] for s in snaps if s["snapshot_id"] == snap)
        for s in snaps:
            if s["timestamp"] > cur_ts:
                es.ml.delete_model_snapshot(job_id=job, snapshot_id=s["snapshot_id"])
        print(f"{job}: reverted to {snap}, datafeed back on {INDEX}")
    if es.indices.exists(index=TEST_INDEX):
        es.indices.delete(index=TEST_INDEX)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["baseline", "run", "restore"])
    ap.add_argument("scenario", nargs="?", choices=["control", "setpoint", "defrost", "spoof"])
    ap.add_argument("--tag", default="")
    args = ap.parse_args(argv)
    es = client()
    if args.cmd == "baseline":
        record_baseline(es)
    elif args.cmd == "restore":
        restore(es)
    else:
        if not args.scenario:
            sys.exit("run needs a scenario")
        print(json.dumps(run(es, args.scenario, args.tag), indent=1, default=str))


if __name__ == "__main__":
    main()
