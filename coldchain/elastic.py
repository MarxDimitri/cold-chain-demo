"""Elastic side of the detection path: templates, ingest pipelines, lookup indices.

    python -m coldchain.elastic setup     # idempotent: PUTs everything below
    python -m coldchain.elastic lookups   # (re)load the kb-* lookup indices from elastic/lookup/
    python -m coldchain.elastic check     # simulate the pipeline on one record per dataset

Everything is ECS-first: built-in `ecs@mappings` plus `logs@*` / `metrics@*` components, custom fields
only under `coldchain.*`, `retail.*` and `kb.*`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from elasticsearch import Elasticsearch, NotFoundError, helpers

from .envfile import load_env

ROOT = Path(__file__).resolve().parent.parent
ECS_VERSION = "9.4.0"  # assumption: confirm against https://github.com/elastic/ecs/releases
RETENTION = "90d"
RETENTION_BY_DATASET = {"coldchain.audit": "400d"}  # the year of store audit is indexed too
PIPELINE = "coldchain-route"

# The collector's API key (Fleet, Custom AWS Logs integration) can only write logs-*-*, and Fleet blocks
# overriding that. Telemetry is therefore stored in a logs-type stream and exposed under the name the
# data model uses (`metrics-coldchain.case-default`) through an alias. See docs/decisions.md.
ALIASES = {"coldchain.case": "metrics-coldchain.case-default",
           "coldchain.probe": "metrics-coldchain.probe-default"}

# dataset -> (data stream type, event.type)
DATASETS = {
    "coldchain.audit": ("logs", None),  # the generator already sets event.type
    "coldchain.case": ("logs", ["info"]),
    "coldchain.probe": ("logs", ["info"]),  # independent temperature loggers, outside the controller's trust
    "netflow.summary": ("logs", ["connection", "info"]),
    "pos.terminal": ("logs", ["info"]),  # POS scenario: hourly roll-ups per POS terminal (CPU, disk, transactions per minute)
    "osquery_manager.result": ("logs", ["info"]),  # live query answers of the endpoints (synthetic, Osquery Manager shape)
    "logistics.truck": ("logs", ["info"]),  # truck telemetry: GPS, speed, cargo temperature (destination is in the ERP)
    "network_traffic.tls": ("logs", ["connection", "info"]),  # POS scenario: TLS sessions of the S07 back-office POS
}


def client() -> Elasticsearch:
    env = load_env()
    return Elasticsearch(env["ELASTICSEARCH_URL"], api_key=env["ELASTIC_API_KEY"], request_timeout=300)


def kw(**extra):
    return {"type": "keyword", **extra}


CUSTOM_MAPPINGS = {
    "dynamic_templates": [
        # Unknown strings in our namespaces are keywords, not text + keyword.
        {"cc_strings": {"path_match": "coldchain.*", "match_mapping_type": "string",
                        "mapping": {"type": "keyword"}}},
        {"retail_strings": {"path_match": "retail.*", "match_mapping_type": "string",
                            "mapping": {"type": "keyword"}}},
        {"osquery_strings": {"path_match": "osquery.*", "match_mapping_type": "string", "mapping": {"type": "keyword"}}},
        {"action_strings": {"path_match": "action_data.*", "match_mapping_type": "string", "mapping": {"type": "keyword"}}},
    ],
    "properties": {
        "event": {"properties": {"ingested": {"type": "date"}}},  # ECS date; scenario B compares it with @timestamp
        "retail": {"properties": {
            "store": {"properties": {"id": kw()}},
            "owner": {"properties": {"id": kw()}},
            "device": {"properties": {"role": kw()}},
        }},
        "coldchain": {"properties": {
            "application": kw(),
            "parameter": {"properties": {
                "code": kw(), "name": kw(), "unit": kw(),
                "value": {"properties": {"old": {"type": "float"}, "new": {"type": "float"}}},
            }},
            "case": {"properties": {
                "setpoint": {"type": "float"},
                "defrost": {"properties": {"active": {"type": "boolean"}}},
                "temperature": {"properties": {"air": {"type": "float"}, "rise_5m": {"type": "float"},
                                               "evaporator": {"type": "float"}}},
            }},
            "netflow": {"properties": {"flows": {"type": "long"}}},
            "probe": {"properties": {"temperature": {"type": "float"}}},
            "pos": {"properties": {
                "disk_free_pct": {"type": "float"},
                "tx_per_min": {"type": "float"},
            }},
            "independent": {"type": "boolean"},
            "truck": {"properties": {"id": kw(), "cargo": kw(), "status": kw(), "speed_kmh": {"type": "float"}, "heading": {"type": "integer"},
                                     "cargo_temp": {"type": "float"}, "reefer_setpoint": {"type": "float"}}},
        }},
    },
}


def pipeline_body() -> dict:
    """Normalise to ECS, then reroute each record to its data stream by event.dataset."""
    procs: list[dict] = [
        {"json": {"field": "message", "add_to_root": True, "ignore_failure": True,
                  "if": "ctx.message instanceof String && ctx.message.startsWith('{')"}},
        {"remove": {"field": "message", "ignore_missing": True,
                    "if": "ctx.event?.dataset != null"}},
        {"set": {"field": "ecs.version", "value": ECS_VERSION}},
        # Scenario B: files uploaded after an offline window carry the upload time already; keep it.
        {"set": {"field": "event.ingested", "copy_from": "_ingest.timestamp", "if": "ctx.event?.ingested == null"}},
        # Store id from the device name (Sxx-...) when the record lacks it.
        {"grok": {"field": "host.name", "patterns": ["^%{DATA:retail.store.id}-.*"],
                  "if": "ctx.retail?.store?.id == null && ctx.host?.name != null",
                  "ignore_failure": True}},
        # network.flows is not an ECS field: move it into our namespace.
        {"rename": {"field": "network.flows", "target_field": "coldchain.netflow.flows",
                    "ignore_missing": True}},
    ]
    for dataset, (stream_type, event_type) in DATASETS.items():
        cond = f"ctx.event?.dataset == '{dataset}'"
        procs.append({"set": {"field": "data_stream.type", "value": stream_type, "if": cond}})
        if event_type:
            procs.append({"set": {"field": "event.type", "value": event_type,
                                  "if": f"{cond} && ctx.event?.type == null"}})
    procs += [
        {"set": {"field": "data_stream.type", "value": "logs",
                 "if": "ctx.data_stream?.type == null || ctx.event?.dataset == null"}},
        # labels.namespace routes the POS scenario into its own streams (…-pos); default otherwise.
        {"reroute": {"dataset": "{{event.dataset}}", "namespace": ["{{labels.namespace}}", "default"],
                     "if": "ctx.event?.dataset != null"}},
    ]
    return {"description": "cold-chain: ECS normalisation and routing by event.dataset", "processors": procs,
            "meta": {"managed_by": "coldchain.elastic"}}


def index_template(pattern: str, stream_type: str, retention: str = RETENTION) -> dict:
    return {
        "template": {"lifecycle": {"data_retention": retention}},
        "index_patterns": [pattern],
        "data_stream": {},
        "priority": 250,  # above the built-in logs-*-* / metrics-*-* templates (100)
        "composed_of": [f"{stream_type}@mappings", "data-streams@mappings", f"{stream_type}@settings",
                        f"{stream_type}@custom", "ecs@mappings", "coldchain-mappings"],
        "ignore_missing_component_templates": [f"{stream_type}@custom"],
        "meta": {"managed_by": "coldchain.elastic"},
    }


def setup(es: Elasticsearch) -> None:
    es.cluster.put_component_template(name="coldchain-mappings", template={"mappings": CUSTOM_MAPPINGS},
                                      meta={"managed_by": "coldchain.elastic"})
    print("component template coldchain-mappings")
    es.ingest.put_pipeline(id=PIPELINE, **pipeline_body())
    print(f"ingest pipeline {PIPELINE}")
    try:  # earlier versions of this setup created a metrics-type template for telemetry
        es.indices.delete_index_template(name="metrics-coldchain.case")
    except NotFoundError:
        pass
    for dataset, (stream_type, _) in DATASETS.items():
        es.indices.put_index_template(name=f"{stream_type}-{dataset}", **index_template(
            f"{stream_type}-{dataset}-*", stream_type, RETENTION_BY_DATASET.get(dataset, RETENTION)))
        print(f"index template {stream_type}-{dataset}-*")
        if dataset in ALIASES:  # templates cannot carry data stream aliases: create the stream, then alias it
            stream = f"{stream_type}-{dataset}-default"
            if not es.indices.exists(index=stream):
                es.indices.create_data_stream(name=stream)
            es.indices.update_aliases(actions=[{"add": {"index": stream, "alias": ALIASES[dataset]}}])
            print(f"data stream alias {ALIASES[dataset]} -> {stream}")
    lookups(es)


LOOKUP_FILES = ["kb-assets", "kb-assets-by-ip", "kb-controller-limits", "kb-device-profiles", "kb-manuals",
                "kb-regulations", "kb-baselines", "kb-erp-deliveries", "kb-advisories"]


LOOKUP_PROPERTIES = {
    "kb-erp-deliveries": {
        "kb": {"properties": {"key": kw()}},
        "coldchain": {"properties": {"truck": {"properties": {"id": kw()}}}},
        "retail": {"properties": {"store": {"properties": {"id": kw()}}}},
        "erp": {"properties": {
            "system": kw(),
            "delivery": {"properties": {"id": kw(), "stop": {"type": "long"}, "planned_arrival": {"type": "date"}, "town": kw(),
                                        "lon": {"type": "double"}, "lat": {"type": "double"}}},
            "cargo": {"properties": {"type": kw(), "pallets": {"type": "long"}, "value_eur": {"type": "long"}}}}},
    },
}


def lookups(es: Elasticsearch) -> None:
    for name in LOOKUP_FILES:
        path = ROOT / "elastic" / "lookup" / f"{name}.ndjson"
        if not path.exists():
            sys.exit(f"{path} missing: run `make lookups` first")
        docs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if es.indices.exists(index=name):
            es.indices.delete(index=name)
        # Join keys must be keyword: a federated dataset reads strings as text, so it casts with TO_STRING and the
        # lookup side has to be keyword too. Free-text indices (manuals, regulations) keep the default.
        join_keys = [] if name in ("kb-manuals", "kb-regulations") else [
            {"all_strings": {"match_mapping_type": "string", "mapping": {"type": "keyword"}}}]
        mappings = {"dynamic_templates": CUSTOM_MAPPINGS["dynamic_templates"] + [
            {"kb_strings": {"path_match": "kb.*", "match_mapping_type": "string", "mapping": {"type": "keyword"}}}] + join_keys}
        if name in LOOKUP_PROPERTIES:  # an index that starts empty (filled by the replay) still needs its fields for the joins
            mappings["properties"] = LOOKUP_PROPERTIES[name]
        es.indices.create(index=name, settings={"index.mode": "lookup"}, mappings=mappings)
        helpers.bulk(es, ({"_index": name, "_source": d} for d in docs), refresh="wait_for")
        print(f"lookup index {name}: {len(docs)} docs")


SAMPLES = {
    "coldchain.audit": {"@timestamp": "2026-11-12T02:52:05Z", "event": {"kind": "event", "dataset": "coldchain.audit",
                        "action": "parameter-change", "category": ["configuration"], "type": ["change"]},
                        "host": {"name": "S07-SM800"}, "source": {"ip": "203.0.113.47"}},
    "coldchain.case": {"@timestamp": "2026-11-12T02:52:00Z", "event": {"kind": "metric", "dataset": "coldchain.case",
                       "category": ["host"]}, "host": {"name": "S07-SM800"}, "device": {"id": "S07-C01"}},
    "coldchain.probe": {"@timestamp": "2026-11-12T02:52:00Z", "event": {"kind": "metric", "dataset": "coldchain.probe",
                        "category": ["host"]}, "host": {"name": "S07-LOGGER"}, "device": {"id": "S07-C01"}},
    "netflow.summary": {"@timestamp": "2026-11-12T02:50:00Z", "event": {"kind": "event", "dataset": "netflow.summary",
                        "category": ["network"]}, "host": {"name": "S07-SM800"},
                        "network": {"bytes": 10, "flows": 2, "transport": "tcp"}},
}


def check(es: Elasticsearch) -> None:
    ok = True
    for dataset, doc in SAMPLES.items():
        res = es.ingest.simulate(id=PIPELINE, docs=[{"_index": "logs-generic-default", "_source": doc}])["docs"][0]
        if "error" in res:
            print("FAIL", dataset, res["error"])
            ok = False
            continue
        src, index = res["doc"]["_source"], res["doc"]["_index"]
        want = f"{DATASETS[dataset][0]}-{dataset}-default"
        good = (index == want and src["ecs"]["version"] == ECS_VERSION and src["retail"]["store"]["id"] == "S07"
                and "event_ingested" not in src and src["event"].get("type") and "flows" not in src.get("network", {}))
        print("PASS" if good else "FAIL", f"{dataset} -> {index}")
        ok &= bool(good)
    sys.exit(0 if ok else 1)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["setup", "lookups", "check"])
    args = ap.parse_args(argv)
    es = client()
    {"setup": setup, "lookups": lookups, "check": check}[args.cmd](es)


if __name__ == "__main__":
    main()
