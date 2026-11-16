"""Experiment: does an ML count job on parameter changes give a better baseline than a constant?

    python -m coldchain.mlcount run       # create and run the 5-minute and 15-minute jobs over history plus the live burst
    python -m coldchain.mlcount score     # burst score and latency, false alarms in history, expected versus actual per day
    python -m coldchain.mlcount reset

Not a product feature: the result is recorded in docs/decisions.md.
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

from elasticsearch import ConflictError, NotFoundError

from .elastic import client

SPANS = {"cc-count-5m": "5m", "cc-count-15m": "15m"}
INDEX = "logs-coldchain.audit-default"
BURST_FROM, BURST_TO = "2026-11-11T14:00:00Z", "2026-11-11T15:00:00Z"
CONSTANT = 5.4  # kb-baselines: parameter-changes per day


def ts(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)


def run(es) -> None:
    first = es.esql.query(query=f'FROM {INDEX} | WHERE event.action == "parameter-change" | STATS a = MIN(@timestamp)',
                          format="json")["values"][0][0]
    for job, span in SPANS.items():
        try:
            es.ml.put_job(job_id=job, description=f"parameter changes per {span}",
                          analysis_config={"bucket_span": span, "detectors": [{"function": "count"}],
                                           "influencers": ["retail.store.id", "source.ip", "user.name"]},
                          analysis_limits={"model_memory_limit": "32mb"}, data_description={"time_field": "@timestamp"},
                          model_plot_config={"enabled": True}, results_index_name=job)
            es.ml.put_datafeed(datafeed_id=f"datafeed-{job}", job_id=job, indices=[INDEX], scroll_size=1000,
                               query={"bool": {"filter": [{"term": {"event.action": "parameter-change"}}]}})
        except Exception as e:
            if "already exists" not in str(e):
                raise
        try:
            es.ml.open_job(job_id=job)
        except ConflictError:
            pass
        es.ml.start_datafeed(datafeed_id=f"datafeed-{job}", start=first, end=BURST_TO)
        print(f"{job}: from {first} to {BURST_TO}")
    for _ in range(120):
        states = [es.ml.get_datafeed_stats(datafeed_id=f"datafeed-{j}")["datafeeds"][0]["state"] for j in SPANS]
        if all(s == "stopped" for s in states):
            break
        time.sleep(3)
    print("datafeeds:", states)


def score(es) -> None:
    attack = ts("2026-11-11T14:11:05Z")
    for job, span in SPANS.items():
        b = es.ml.get_buckets(job_id=job, page={"size": 10000}, sort="timestamp")["buckets"]
        hist = [x for x in b if x["timestamp"] < ts(BURST_FROM)]
        burst = [x for x in b if ts(BURST_FROM) <= x["timestamp"] < ts(BURST_TO)]
        top = max(burst, key=lambda x: x["anomaly_score"]) if burst else None
        span_ms = int(span[:-1]) * 60000
        print(f"\n== {job} ({len(b)} buckets, {len(hist)} before 14:00)")
        if top:
            hit = next((x for x in burst if x["anomaly_score"] >= 75), None)
            print(f"  burst: top score {top['anomaly_score']:.0f} in the bucket at "
                  f"{datetime.fromtimestamp(top['timestamp'] / 1000, timezone.utc):%H:%M}"
                  + (f"; first >= 75 at {datetime.fromtimestamp(hit['timestamp'] / 1000, timezone.utc):%H:%M}, bucket closes "
                     f"{(hit['timestamp'] + span_ms - attack) / 60000:.1f} min after the attack" if hit else "; never >= 75"))
        for thr in (75, 50, 25):
            fa = [x for x in hist if x["anomaly_score"] >= thr]
            print(f"  false alarms in history, score >= {thr}: {len(fa)}"
                  + (f" at {[datetime.fromtimestamp(x['timestamp'] / 1000, timezone.utc).strftime('%m-%d %H:%M') for x in fa[:6]]}" if fa and thr == 75 else ""))
        r = es.search(index=f".ml-anomalies-{job}", size=0, query={"bool": {"filter": [
            {"term": {"result_type": "model_plot"}}, {"range": {"timestamp": {"lt": ts(BURST_FROM)}}}]}},
            aggs={"d": {"date_histogram": {"field": "timestamp", "calendar_interval": "day"},
                        "aggs": {"exp": {"sum": {"field": "model_median"}}, "act": {"sum": {"field": "actual"}}}}})
        days = [(x["key_as_string"][:10], x["exp"]["value"], x["act"]["value"]) for x in r["aggregations"]["d"]["buckets"]]
        days = days[7:]  # skip the first week while the model learns
        if days:
            mae_m = sum(abs(e - a) for _, e, a in days) / len(days)
            mae_c = sum(abs(CONSTANT - a) for _, e, a in days) / len(days)
            print(f"  expected vs actual per day ({len(days)} days after the first week): model error {mae_m:.2f}, "
                  f"constant {CONSTANT} error {mae_c:.2f} (mean absolute, changes per day)")
            print("  sample:", [(d, round(e, 1), int(a)) for d, e, a in days[-6:]])


def reset(es) -> None:
    for job in SPANS:
        for call, kw in ((es.ml.stop_datafeed, {"datafeed_id": f"datafeed-{job}", "force": True}),
                         (es.ml.close_job, {"job_id": job, "force": True}),
                         (es.ml.delete_datafeed, {"datafeed_id": f"datafeed-{job}", "force": True}),
                         (es.ml.delete_job, {"job_id": job, "force": True})):
            try:
                call(**kw)
            except (NotFoundError, ConflictError):
                pass
        print(f"{job}: deleted")


if __name__ == "__main__":
    es = client()
    {"run": run, "score": score, "reset": reset}[sys.argv[1]](es)
