"""Experiment: which feature lets per-cabinet ML see the +50 attack? Throw-away jobs on a subset of cabinets.

    python -m coldchain.mlexp train       # create exp jobs, train on the history of stores S07, S17, S18
    python -m coldchain.mlexp score       # revert, replay control / setpoint / defrost, print the results
    python -m coldchain.mlexp cleanup     # delete the exp jobs, datafeeds and the test index

Production jobs and indices are not touched; results indices are `exp-*`.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from elasticsearch import helpers

from . import mlscore as ms
from .attack import AttackPlan
from .chain import load_attack, load_chain
from .elastic import client
from .ml import INDEX

STORES = ["S05", "S14", "S15", "S09"]  # S05 and S14 hold the slow-warming cabinets  # S15-C20 and S09-C01 ran away in the production training
FIELDS = {"air": "coldchain.case.temperature.air", "rise": "coldchain.case.temperature.rise_5m"}
WARM = {"source": ("double nom = doc['coldchain.application'].value == 'frozen' ? -24.0 : 2.0;"
                   "boolean relay = doc['coldchain.case.defrost.active'].size() > 0 && doc['coldchain.case.defrost.active'].value;"
                   "return (doc['coldchain.case.temperature.air'].value - nom > 2.0 && !relay) ? 1.0 : 0.0;"),
        "lang": "painless"}
DEV = {"source": ("double nom = doc['coldchain.application'].value == 'frozen' ? -24.0 : 2.0;"
                  "return doc['coldchain.case.temperature.air'].value - nom;"), "lang": "painless"}
# name -> (field, bucket span, population?, relay filter on the datafeed?)
VARIANTS = {"exp-dev-30m": ("dev", "30m", False, True), "exp-dev-pop-30m": ("dev", "30m", True, True)}


def create(es) -> None:
    for job, (f, span, population, relay_filter) in VARIANTS.items():
        det = {"function": "high_mean", "field_name": f}
        det.update({"over_field_name": "device.id", "by_field_name": "coldchain.application"} if population
                   else {"partition_field_name": "device.id"})
        feed = {"job_id": job, "indices": [INDEX], "scroll_size": 5000, "query_delay": "60s",
                "query": {"bool": {"filter": [{"terms": {"retail.store.id": STORES}}],
                                   "must_not": ([{"term": {"coldchain.case.defrost.active": True}}] if relay_filter else [])}}}
        if f in ("warm", "dev"):
            feed["script_fields"] = {f: {"script": WARM if f == "warm" else DEV}}
        try:
            es.ml.put_job(job_id=job, analysis_config={
                "bucket_span": span, "influencers": ["device.id", "retail.store.id"], "detectors": [det]},
                analysis_limits={"model_memory_limit": "512mb"}, data_description={"time_field": "@timestamp"},
                results_index_name=job)
            es.ml.put_datafeed(datafeed_id=f"datafeed-{job}", **feed)
        except Exception as e:
            if "already exists" not in str(e):
                raise


def wait(es, jobs) -> None:
    deadline = time.time() + 3000
    while time.time() < deadline:
        if all(es.ml.get_datafeed_stats(datafeed_id=f"datafeed-{j}")["datafeeds"][0]["state"] == "stopped" for j in jobs):
            return
        time.sleep(10)
    sys.exit("training did not finish")


def train(es) -> None:
    create(es)
    for job in VARIANTS:
        es.ml.open_job(job_id=job)
        es.ml.start_datafeed(datafeed_id=f"datafeed-{job}", start="2026-10-08T00:00:00Z", end=ms.HISTORY_END)
    t = time.time()
    wait(es, VARIANTS)
    out = {}
    for job in VARIANTS:
        es.ml.close_job(job_id=job)
        snaps = sorted(es.ml.get_model_snapshots(job_id=job)["model_snapshots"], key=lambda s: s["timestamp"])
        out[job] = snaps[-1]["snapshot_id"]
        es.ml.update_model_snapshot(job_id=job, snapshot_id=out[job], retain=True)
        print(job, "trained, snapshot", out[job], "latest record", snaps[-1].get("latest_record_time_stamp"))
    (ms.WORK / "exp-baseline.json").write_text(json.dumps(out))
    print(f"training took {time.time() - t:.0f}s")


def score(es) -> None:
    base = json.loads((ms.WORK / "exp-baseline.json").read_text())
    cfg, chain = load_attack(), load_chain()
    plan = AttackPlan(chain, cfg, ms.epoch(cfg["t0"]), "setpoint")
    targets = {c.id for _, c in plan.targets() if c.id[:3] in STORES}
    restore_t = plan.t0 + cfg["restore"]["offset_minutes"] * 60
    allres = {}
    for scenario in ("control", "setpoint", "defrost"):
        if scenario == "control":
            docs = ms.control_docs(ms.epoch(ms.HISTORY_END), ms.CONTROL_MINUTES)
        else:
            docs = ms.replay_docs(scenario, ms.WORK / f"out-{scenario}")
        docs = [d for d in docs if d["@timestamp"] >= ms.HISTORY_END and d["retail"]["store"]["id"] in STORES]
        end = ms.iso(ms.epoch(max(d["@timestamp"] for d in docs)) + 60)
        ms.create_test_index(es)
        helpers.bulk(es, ({"_index": ms.TEST_INDEX, "_source": d} for d in docs), chunk_size=5000)
        es.indices.refresh(index=ms.TEST_INDEX)
        for job, snap in base.items():
            es.ml.revert_model_snapshot(job_id=job, snapshot_id=snap, delete_intervening_results=True)
            es.ml.update_datafeed(datafeed_id=f"datafeed-{job}", indices=[ms.TEST_INDEX], query={"match_all": {}})  # scoring feeds everything; script_fields stay
            es.ml.open_job(job_id=job)
            es.ml.start_datafeed(datafeed_id=f"datafeed-{job}", start=ms.HISTORY_END, end=end)
        wait(es, base)
        for job in base:
            es.ml.close_job(job_id=job)
        res = ms.analyse(scenario, es, ms.HISTORY_END, targets, plan.start, restore_t, jobs=list(base))
        allres[scenario] = res
        print(f"=== {scenario}: {len(docs)} docs", flush=True)
        for job in base:
            for thr in (50, 75):
                r = res[f"{job}@{thr}"]
                print(f"  {job}@{thr}: targets flagged {r['target_cabinets_flagged']}/{r['of']}, first {r['first_target_record_bucket']} "
                      f"(+{r['seconds_after_attack_start']}s), false-positive cabinets {r['false_positive_cabinets']} "
                      f"records {r['false_positive_records']}, before attack {r['records_on_targets_before_attack']}; "
                      f"top FP {r['top_false_positives'][:2]}", flush=True)
            print(f"  {job}: max record score {res[f'{job}:max_record_score']}", flush=True)
    (ms.WORK / "exp-results.json").write_text(json.dumps(allres, indent=1, default=str))


def score_slow(es) -> None:
    """Control and slow warming (config/attack.yaml `slow_warming`) through the experiment jobs."""
    base = json.loads((ms.WORK / "exp-baseline.json").read_text())
    cfg = load_attack()
    sw = cfg["slow_warming"]
    targets = ms.slow_targets() & {c for c in ms.slow_targets() if c[:3] in STORES}
    t_start = ms.epoch(cfg["t0"]) + sw["offset_seconds"]
    end_t = t_start + sw["duration_minutes"] * 60
    out = {}
    for scenario in ("control", "slow"):
        start = ms.epoch(ms.HISTORY_END)
        docs = (ms.control_docs if scenario == "control" else ms.slow_docs)(start, ms.CONTROL_MINUTES)
        docs = [d for d in docs if d["@timestamp"] >= ms.HISTORY_END and d["retail"]["store"]["id"] in STORES]
        end = ms.iso(ms.epoch(max(d["@timestamp"] for d in docs)) + 60)
        ms.create_test_index(es)
        helpers.bulk(es, ({"_index": ms.TEST_INDEX, "_source": d} for d in docs), chunk_size=5000)
        es.indices.refresh(index=ms.TEST_INDEX)
        for job, snap in base.items():
            es.ml.revert_model_snapshot(job_id=job, snapshot_id=snap, delete_intervening_results=True)
            es.ml.update_datafeed(datafeed_id=f"datafeed-{job}", indices=[ms.TEST_INDEX], query={"match_all": {}})
            es.ml.open_job(job_id=job)
            es.ml.start_datafeed(datafeed_id=f"datafeed-{job}", start=ms.HISTORY_END, end=end)
        wait(es, base)
        for job in base:
            es.ml.close_job(job_id=job)
        res = ms.analyse(scenario, es, ms.HISTORY_END, targets, t_start, end_t, jobs=list(base))
        out[scenario] = res
        print(f"=== {scenario}: {len(docs)} docs, {len(targets)} slow-warming cabinets in the subset", flush=True)
        for job in base:
            for thr in (50, 75):
                r = res[f"{job}@{thr}"]
                print(f"  {job}@{thr}: targets flagged {r['target_cabinets_flagged']}/{r['of']}, first +{r['seconds_after_attack_start']}s, "
                      f"false-positive cabinets {r['false_positive_cabinets']} records {r['false_positive_records']}, "
                      f"top FP {r['top_false_positives'][:2]}", flush=True)
            print(f"  {job}: max record score {res[f'{job}:max_record_score']}", flush=True)
    (ms.WORK / "exp-slow-results.json").write_text(json.dumps(out, indent=1, default=str))


def stability(es) -> None:
    """Records at score 75+ in the last 5 weeks of training, per variant (steady state, after the warm-up)."""
    for job in VARIANTS:
        q = {"bool": {"filter": [{"term": {"job_id": job}}, {"term": {"result_type": "record"}},
                                 {"range": {"record_score": {"gte": 75}}}, {"range": {"timestamp": {"gte": "2026-10-20"}}}]}}
        a = es.search(index=".ml-anomalies-*", size=0, query=q,
                      aggs={"c": {"terms": {"field": "partition_field_value", "size": 5}}})
        top = [(b["key"], b["doc_count"]) for b in a["aggregations"]["c"]["buckets"]]
        print(f"{job}: {a['hits']['total']['value']} records >=75 since 10-20; top {top}")


def cleanup(es) -> None:
    for job in VARIANTS:
        for call, kw in ((es.ml.stop_datafeed, {"datafeed_id": f"datafeed-{job}"}), (es.ml.close_job, {"job_id": job}),
                         (es.ml.delete_datafeed, {"datafeed_id": f"datafeed-{job}", "force": True}),
                         (es.ml.delete_job, {"job_id": job, "force": True, "delete_user_annotations": True})):
            try:
                call(**kw)
            except Exception:
                pass
    if es.indices.exists(index=ms.TEST_INDEX):
        es.indices.delete(index=ms.TEST_INDEX)
    print("experiment jobs and test index removed")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["train", "score", "score-slow", "stability", "cleanup"])
    {"train": train, "score": score, "score-slow": score_slow, "stability": stability, "cleanup": cleanup}[ap.parse_args(argv).cmd](client())


if __name__ == "__main__":
    main()
