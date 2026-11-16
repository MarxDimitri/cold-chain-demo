"""Act 5b: the same 12 months of raw store audit, ingested and kept on the frozen tier.

    python -m coldchain.frozen load        # read raw/ audit from S3, index it, snapshot it, mount it as a frozen index
    python -m coldchain.frozen check       # count and time the Act 5 question on the frozen index
    python -m coldchain.frozen delete      # remove the mounted index and its snapshot

Act 5a reads the bucket in place with federation (nothing ingested, every query scans the files). Act 5b ingests the history
once into an index, snapshots it into the deployment's `found-snapshots` repository (object storage) and mounts it as a
partially mounted searchable snapshot on the frozen tier: storage stays at object-storage prices, the queries are served from a
small local cache, and the spend is fixed by the size of the frozen node. Needs operator AWS credentials (read on raw/).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

from elasticsearch import helpers

from .elastic import client

INDEX = "cc-history-audit"
SOURCE = f"{INDEX}-src"
SNAPSHOT = "cc-history-audit"
REPO = "found-snapshots"
PREFIX = "raw/dataset=coldchain.audit/"

MAPPINGS = {"dynamic": True, "properties": {
    "@timestamp": {"type": "date"},
    "source": {"properties": {"ip": {"type": "ip"}}},
    "destination": {"properties": {"ip": {"type": "ip"}}},
    "event": {"properties": {"action": {"type": "keyword"}, "dataset": {"type": "keyword"}, "outcome": {"type": "keyword"}}},
    "retail": {"properties": {"store": {"properties": {"id": {"type": "keyword"}}}}},
    "user": {"properties": {"name": {"type": "keyword"}}},
    "device": {"properties": {"id": {"type": "keyword"}}},
    "host": {"properties": {"name": {"type": "keyword"}}},
}}

# The Act 5 question on the indexed copy: the same answer as HISTORY in dashboards.py, from the frozen index.
QUESTION = """FROM cc-history-audit
| WHERE event.action == "logged-in" AND NOT CIDR_MATCH(source.ip, "198.51.100.0/24") AND NOT CIDR_MATCH(source.ip, "10.0.0.0/8")
| STATS first_seen = MIN(@timestamp) BY store = retail.store.id
| SORT first_seen"""


def _read(s3, bucket: str, key: str) -> list[dict]:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return [json.loads(line) for line in gzip.decompress(body).splitlines() if line.strip()]


def load() -> None:
    import boto3
    es = client()
    bucket, region = os.environ["COLDCHAIN_BUCKET"], os.environ.get("AWS_REGION", "eu-central-1")
    s3 = boto3.client("s3", region_name=region)
    keys = [o["Key"] for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=PREFIX)
            for o in page.get("Contents", [])]
    print(f"{len(keys)} raw audit files")
    delete(quiet=True)
    es.indices.create(index=SOURCE, mappings=MAPPINGS, settings={"number_of_shards": 1, "number_of_replicas": 0})

    t0 = time.time()
    total = 0
    with ThreadPoolExecutor(16) as pool:
        batch: list[dict] = []
        for docs in pool.map(lambda k: _read(s3, bucket, k), keys):
            batch += docs
            if len(batch) >= 20000:
                helpers.bulk(es, ({"_index": SOURCE, "_source": d} for d in batch), chunk_size=5000)
                total += len(batch)
                batch = []
                print(f"  {total} documents")
        if batch:
            helpers.bulk(es, ({"_index": SOURCE, "_source": d} for d in batch), chunk_size=5000)
            total += len(batch)
    es.indices.refresh(index=SOURCE)
    es.indices.forcemerge(index=SOURCE, max_num_segments=1)
    print(f"indexed {total} documents in {time.time() - t0:.0f} s")

    es.snapshot.create(repository=REPO, snapshot=SNAPSHOT, indices=SOURCE, include_global_state=False, wait_for_completion=True)
    es.indices.delete(index=SOURCE)
    es.searchable_snapshots.mount(repository=REPO, snapshot=SNAPSHOT, index=SOURCE, renamed_index=INDEX, storage="shared_cache",
                                  wait_for_completion=True)
    print(f"mounted {INDEX} as a frozen (partially mounted) searchable snapshot")


def delete(quiet: bool = False) -> None:
    es = client()
    for idx in (INDEX, SOURCE):
        if es.indices.exists(index=idx):
            es.indices.delete(index=idx)
    try:
        es.snapshot.delete(repository=REPO, snapshot=SNAPSHOT)
    except Exception:
        pass
    if not quiet:
        print("deleted the frozen index and its snapshot")


def check() -> None:
    es = client()
    st = es.indices.get_settings(index=INDEX)[INDEX]["settings"]["index"]
    print("store type:", st.get("store", {}).get("type"), "| tier preference:", st.get("routing", {}).get("allocation", {}).get("include", {}))
    print("documents:", es.count(index=INDEX)["count"])
    for i in (1, 2):
        t = time.time()
        r = es.esql.query(query=QUESTION, format="json")
        print(f"run {i}: {time.time() - t:.1f} s", r["values"])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["load", "check", "delete"])
    a = ap.parse_args(argv)
    {"load": load, "check": check, "delete": delete}[a.cmd]()


if __name__ == "__main__":
    main()
