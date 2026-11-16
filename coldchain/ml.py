"""Anomaly detection jobs on the indexed telemetry (CLAUDE.md 8.2, 06b section 6).

    python -m coldchain.ml setup                          # create jobs and datafeeds (idempotent)
    python -m coldchain.ml start [--start T] [--end T]    # open jobs, start datafeeds (no --end: real time)
    python -m coldchain.ml status                         # job state, nodes, model memory, anomaly counts
    python -m coldchain.ml stop
    python -m coldchain.ml reset                          # delete jobs and datafeeds (to redefine them)

Both jobs read `metrics-coldchain.case-default`, the alias over the telemetry stream.
"""
from __future__ import annotations

import argparse
import sys

from elasticsearch import ConflictError, Elasticsearch, NotFoundError

from .elastic import client

INDEX = "metrics-coldchain.case-default"
FIELD = "coldchain.case.temperature.rise_5m"

JOBS = {
    # One model per cabinet: a cabinet warming outside its own defrost pattern. The 5-minute bucket is deliberate:
    # with 1-minute buckets about 8% of the cabinets ran away (typical far outside the data, sustained scores of 90+,
    # deterministic per cabinet); 5-minute buckets removed that, 15-minute buckets lost the attack. docs/decisions.md.
    "cc-temp-rise": {
        "description": "Cabinet air temperature rising faster than its own normal (per cabinet)",
        "analysis_config": {
            "bucket_span": "5m",
            "detectors": [{"function": "high_mean", "field_name": FIELD, "partition_field_name": "device.id",
                           "detector_description": "high mean 5-minute temperature rise per cabinet"}],
            "influencers": ["device.id", "retail.store.id"],
        },
        "analysis_limits": {"model_memory_limit": "512mb"},
        "data_description": {"time_field": "@timestamp"},
        "model_plot_config": {"enabled": False},
        "results_index_name": "cc-temp-rise",
        "custom_settings": {"created_by": "coldchain.ml"},
    },
    # One model per application over all cabinets: separates "3 stores at once" from one faulty cabinet.
    "cc-temp-rise-population": {
        "description": "Cabinets warming unlike the rest of their population (frozen or chilled)",
        "analysis_config": {
            "bucket_span": "5m",
            "detectors": [{"function": "high_mean", "field_name": FIELD, "over_field_name": "device.id",
                           "by_field_name": "coldchain.application",
                           "detector_description": "high mean 5-minute rise vs. other cabinets of the same application"}],
            "influencers": ["retail.store.id", "device.id", "coldchain.application"],
        },
        "analysis_limits": {"model_memory_limit": "512mb"},
        "data_description": {"time_field": "@timestamp"},
        "results_index_name": "cc-temp-rise-population",
        "custom_settings": {"created_by": "coldchain.ml"},
    },
}


def datafeed(job: str) -> dict:
    # Per cabinet: a scheduled defrost warms a cabinet by ~25 K, far more than the attack does (+3 K in 10 minutes),
    # so records taken while the defrost relay is on are left out and the model learns the refrigerating state.
    # Population: defrost stays in, it is normal peer behaviour (about a quarter of the frozen cabinets at any time),
    # and the job asks which cabinets differ from their peers right now.
    query = ({"bool": {"must_not": [{"term": {"coldchain.case.defrost.active": True}}]}}
             if job == "cc-temp-rise" else {"match_all": {}})
    return {"job_id": job, "indices": [INDEX],
            "query": query,
            "query_delay": "60s",  # covers collector pickup and indexing; tune after measuring latency
            "frequency": "30s",
            "scroll_size": 5000}


def setup(es: Elasticsearch, _args=None) -> None:
    for job, body in JOBS.items():
        try:
            es.ml.put_job(job_id=job, **body)
            print(f"job {job} created")
        except Exception as e:  # already exists: update the mutable parts
            if "already exists" not in str(e):
                raise
            es.ml.update_job(job_id=job, description=body["description"])
            print(f"job {job} exists (description updated; run `reset` to change detectors)")
        try:
            es.ml.put_datafeed(datafeed_id=f"datafeed-{job}", **{k: v for k, v in datafeed(job).items()})
            print(f"datafeed datafeed-{job} created")
        except Exception as e:
            if "already exists" not in str(e):
                raise
            print(f"datafeed datafeed-{job} exists")


def start(es: Elasticsearch, args) -> None:
    for job in JOBS:
        try:
            es.ml.open_job(job_id=job)
        except ConflictError:
            pass  # already open
        except Exception as e:
            sys.exit(f"open {job}: {str(e)[:500]}")
        kwargs = {"datafeed_id": f"datafeed-{job}", "start": args.start}
        if args.end:
            kwargs["end"] = args.end
        es.ml.start_datafeed(**kwargs)
        print(f"{job}: opened, datafeed started from {args.start}" + (f" to {args.end}" if args.end else " (real time)"))


def stop(es: Elasticsearch, _args=None) -> None:
    for job in JOBS:
        for call, kw in ((es.ml.stop_datafeed, {"datafeed_id": f"datafeed-{job}"}), (es.ml.close_job, {"job_id": job})):
            try:
                call(**kw)
            except (NotFoundError, ConflictError) as e:
                print(f"  skip {job}: {str(e)[:120]}")
        print(f"{job}: stopped")


def reset(es: Elasticsearch, _args=None) -> None:
    stop(es)
    for job in JOBS:
        for call, kw in ((es.ml.delete_datafeed, {"datafeed_id": f"datafeed-{job}", "force": True}),
                         (es.ml.delete_job, {"job_id": job, "force": True, "delete_user_annotations": True})):
            try:
                call(**kw)
            except NotFoundError:
                pass
        print(f"{job}: deleted")


def status(es: Elasticsearch, _args=None) -> None:
    info = es.ml.info()["limits"]
    print(f"ML memory available: {info.get('total_ml_memory')}")
    for job in JOBS:
        try:
            st = es.ml.get_job_stats(job_id=job)["jobs"][0]
        except NotFoundError:
            print(f"{job}: not created")
            continue
        dc = st["data_counts"]
        print(f"{job}: {st['state']}, node={st.get('node', {}).get('name')}, processed={dc['processed_record_count']}, "
              f"buckets={dc['bucket_count']}, memory_status={st['model_size_stats'].get('memory_status')}")
        if st.get("assignment_explanation"):
            print(f"   assignment: {st['assignment_explanation']}")
        try:
            df = es.ml.get_datafeed_stats(datafeed_id=f"datafeed-{job}")["datafeeds"][0]
            print(f"   datafeed: {df['state']}")
        except NotFoundError:
            pass


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["setup", "start", "stop", "status", "reset"])
    ap.add_argument("--start", default="2026-10-08T00:00:00Z", help="datafeed start (default: start of the history)")
    ap.add_argument("--end", help="datafeed end; omit to follow in real time")
    args = ap.parse_args(argv)
    {"setup": setup, "start": start, "stop": stop, "status": status, "reset": reset}[args.cmd](client(), args)


if __name__ == "__main__":
    main()
