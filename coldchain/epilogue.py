"""Scenario B (epilogue, hypothetical): ML jobs, the new-terms rule and the scoring on the indexed epilogue streams.

    python -m coldchain.epilogue setup      # ML jobs + datafeeds (idempotent), federation datasets for the raw side
    python -m coldchain.epilogue start      # open jobs and run the datafeeds over the epilogue window
    python -m coldchain.epilogue status
    python -m coldchain.epilogue score      # which hosts each job flagged, when, and whether a peer was flagged
    python -m coldchain.epilogue rule       # create the new-terms rule (disabled) and preview it over the window
    python -m coldchain.epilogue reset      # delete jobs and datafeeds

The data is in the `epilogue` namespace (logs-netflow.summary-epilogue, logs-signage.cms-epilogue, logs-power.plug-epilogue),
so it never mixes with the main demo's streams. All jobs are population jobs: a device is compared with its peers.
"""
from __future__ import annotations

import argparse
import json
import sys

import requests
from elasticsearch import ConflictError, NotFoundError

from . import scenario_b
from .elastic import client
from .federation import env

SUMMARY = "logs-netflow.summary-epilogue"
SIGNAGE = "logs-signage.cms-epilogue"
PLUG = "logs-power.plug-epilogue"

EXPECTED = {  # job -> the one host the story is about
    "edge-inbound-population": "S07-TVBOX-01",
    "edge-signage-cpu": "S07-SIG-02",
    "edge-signage-storage": "S07-SIG-02",
    "edge-plug-power": "S07-PLUG-01",
}


def _job(desc: str, detector: dict, influencers: list[str], index: str) -> dict:
    return {"description": desc,
            "analysis_config": {"bucket_span": "1h", "detectors": [detector], "influencers": influencers},
            "analysis_limits": {"model_memory_limit": "256mb"},
            "data_description": {"time_field": "@timestamp"},
            "results_index_name": "", "custom_settings": {"created_by": "coldchain.epilogue", "index": index}}


JOBS = {
    # Bytes received per device in an hour against the other devices of the same role. A TV box that pulls 20-60 MB
    # chunks every night stands out from 19 peers that receive about 35 MB a week in all.
    "edge-inbound-population": _job(
        "Bytes received per hour, compared with the devices of the same role",
        {"function": "high_sum", "field_name": "destination.bytes", "over_field_name": "host.name",
         "by_field_name": "retail.device.role",
         "detector_description": "high bytes received per device vs. peers of the same role"},
        ["host.name", "retail.device.role", "retail.store.id"], SUMMARY),
    "edge-signage-cpu": _job(
        "Signage player CPU compared with the other players",
        {"function": "high_mean", "field_name": "host.cpu.usage", "over_field_name": "host.name",
         "detector_description": "high mean CPU per signage player vs. peers"},
        ["host.name", "retail.store.id"], SIGNAGE),
    "edge-signage-storage": _job(
        "Signage player free storage compared with the other players",
        {"function": "low_mean", "field_name": "coldchain.edge.storage.free_pct", "over_field_name": "host.name",
         "detector_description": "low mean free storage per signage player vs. peers"},
        ["host.name", "retail.store.id"], SIGNAGE),
    "edge-plug-power": _job(
        "TV box power draw compared with the other boxes",
        {"function": "high_mean", "field_name": "coldchain.edge.power.watts", "over_field_name": "host.name",
         "detector_description": "high mean power draw per smart plug vs. peers"},
        ["host.name", "retail.store.id"], PLUG),
}


def setup(es) -> None:
    for job, body in JOBS.items():
        body = {k: v for k, v in body.items() if k != "results_index_name"} | {"results_index_name": job}
        index = body["custom_settings"]["index"]
        try:
            es.ml.put_job(job_id=job, **body)
            print(f"job {job} created")
        except Exception as e:
            if "already exists" not in str(e):
                raise
            print(f"job {job} exists")
        try:
            es.ml.put_datafeed(datafeed_id=f"datafeed-{job}", job_id=job, indices=[index],
                               query={"match_all": {}}, query_delay="60s", frequency="30s", scroll_size=5000)
            print(f"datafeed datafeed-{job} created")
        except Exception as e:
            if "already exists" not in str(e):
                raise


def start(es) -> None:
    w0, w1 = scenario_b.window()
    for job in JOBS:
        try:
            es.ml.open_job(job_id=job)
        except ConflictError:
            pass
        es.ml.start_datafeed(datafeed_id=f"datafeed-{job}", start=scenario_b.iso(w0), end=scenario_b.iso(w1))
        print(f"{job}: datafeed {scenario_b.iso(w0)} -> {scenario_b.iso(w1)}")


def reset(es) -> None:
    for job in JOBS:
        for call, kw in ((es.ml.stop_datafeed, {"datafeed_id": f"datafeed-{job}", "force": True}),
                         (es.ml.close_job, {"job_id": job, "force": True}),
                         (es.ml.delete_datafeed, {"datafeed_id": f"datafeed-{job}", "force": True}),
                         (es.ml.delete_job, {"job_id": job, "force": True, "delete_user_annotations": True})):
            try:
                call(**kw)
            except (NotFoundError, ConflictError):
                pass
        print(f"{job}: deleted")


def status(es) -> None:
    for job in JOBS:
        try:
            st = es.ml.get_job_stats(job_id=job)["jobs"][0]
            df = es.ml.get_datafeed_stats(datafeed_id=f"datafeed-{job}")["datafeeds"][0]["state"]
        except NotFoundError:
            print(f"{job}: not created")
            continue
        dc = st["data_counts"]
        print(f"{job}: {st['state']}, datafeed {df}, processed={dc['processed_record_count']}, buckets={dc['bucket_count']}")


def records(es, job: str, min_score: float = 75) -> list[dict]:
    res = es.ml.get_records(job_id=job, record_score=min_score, sort="timestamp", desc=False, page={"size": 1000})
    return res["records"]


def score(es) -> dict:
    story = scenario_b.epoch(scenario_b.config()["download"]["first_night"])
    out = {}
    for job, expected in EXPECTED.items():
        hits = {}
        for thr in (75, 50):
            recs = records(es, job, thr)
            by = {}
            for r in recs:
                host = r.get("over_field_value") or r.get("partition_field_value")
                d = by.setdefault(host, {"first": r["timestamp"], "max": 0.0, "n": 0})
                d["max"] = max(d["max"], r["record_score"])
                d["n"] += 1
                d["first"] = min(d["first"], r["timestamp"])
            hits[thr] = by
        first = hits[75].get(expected, {}).get("first")
        out[job] = {"expected": expected, "flagged_75": sorted(hits[75]), "flagged_50": sorted(hits[50]),
                    "expected_first_75": scenario_b.iso(first // 1000) if first else None,
                    "expected_max_75": hits[75].get(expected, {}).get("max"),
                    "peers_flagged_75": [h for h in hits[75] if h != expected],
                    "flagged_before_story": [h for h, d in hits[50].items() if d["first"] // 1000 < story - 3600]}
        print(json.dumps({job: out[job]}, indent=1))
    return out


# --- the new-terms rule ------------------------------------------------------------------------

RULE = {
    "name": "First-seen internal peer (hypothetical epilogue)",
    "description": "A device talks to an address it never talked to in the last 14 days. Scenario B: a TV box reaching the "
                   "system manager. Hypothetical scenario; synthetic data.",
    "type": "new_terms", "language": "kuery", "query": "labels.namespace : epilogue",
    "index": ["logs-netflow.summary-*"], "new_terms_fields": ["source.ip", "destination.ip"],
    "history_window_start": "now-14d", "interval": "1d", "from": "now-1d", "to": "now",
    "risk_score": 47, "severity": "medium", "enabled": False,
    "tags": ["coldchain", "epilogue", "hypothetical"],
    "threat": [],
}


def kibana() -> tuple[str, requests.Session]:
    e = env()
    s = requests.Session()
    s.headers.update({"Authorization": f"ApiKey {e['ELASTIC_API_KEY']}", "kbn-xsrf": "true",
                      "Content-Type": "application/json", "elastic-api-version": "2023-10-31"})
    return e["KIBANA_URL"].rstrip("/"), s


def rule() -> None:
    url, s = kibana()
    r = s.post(f"{url}/api/detection_engine/rules", json={**RULE, "rule_id": "coldchain-first-seen-peer"}, timeout=60)
    if r.status_code == 409:
        r = s.put(f"{url}/api/detection_engine/rules", json={**RULE, "rule_id": "coldchain-first-seen-peer"}, timeout=60)
    print("rule:", r.status_code, r.text[:300])
    w0, w1 = scenario_b.window()
    prev = s.post(f"{url}/api/detection_engine/rules/preview", timeout=300, json={
        **{k: v for k, v in RULE.items() if k not in ("enabled",)},
        "invocationCount": 8, "timeframeEnd": scenario_b.iso(w1 - 86400 * 2)})
    print("preview:", prev.status_code, prev.text[:1500])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["setup", "start", "status", "score", "rule", "reset"])
    args = ap.parse_args(argv)
    if args.cmd == "rule":
        return rule()
    es = client()
    {"setup": setup, "start": start, "status": status, "score": score, "reset": reset}[args.cmd](es)


if __name__ == "__main__":
    main()
