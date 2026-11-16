"""Re-trigger `detect/` objects whose records are missing (or partial) in Elasticsearch.

    python -m coldchain.reingest telemetry [--dry-run]

Compares the indexed telemetry per store and hour against the expected 24 cabinets x 60 minutes. Hours with no
documents are re-triggered; partial hours are cleared first (delete by query) so nothing is indexed twice.
A re-trigger copies the object onto itself with a metadata change, which makes S3 send a fresh
`ObjectCreated:Copy` event to the queue. Needs operator AWS credentials (stores cannot read or copy).
"""
from __future__ import annotations

import argparse
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .chain import load_chain
from .elastic import client

FULL_HOUR = 24 * 60  # cabinets x minutes
STREAM = "logs-coldchain.case-default"
KEY_RE = re.compile(r"detect/dataset=coldchain\.case/store=(S\d+)/dt=([\d-]+)/hh=(\d+)/")


def present_hours(es, store: str) -> dict[str, int]:
    res = es.esql.query(query=f"""FROM {STREAM}
        | WHERE retail.store.id == "{store}"
        | EVAL hour = DATE_FORMAT("yyyy-MM-dd'T'HH", @timestamp)
        | STATS docs = COUNT(*) BY hour
        | LIMIT 5000""", format="json")
    return {h: n for n, h in res["values"]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["telemetry"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    import boto3
    bucket, region = os.environ["COLDCHAIN_BUCKET"], os.environ.get("AWS_REGION", "eu-central-1")
    s3 = boto3.client("s3", region_name=region)
    es = client()

    keys: dict[tuple[str, str], str] = {}  # (store, "YYYY-MM-DDTHH") -> key
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="detect/dataset=coldchain.case/"):
        for o in page.get("Contents", []):
            m = KEY_RE.match(o["Key"])
            if m:
                keys[(m[1], f"{m[2]}T{m[3]}")] = o["Key"]
    print(f"{len(keys)} telemetry objects in the bucket")

    retrigger: list[str] = []
    partial: list[tuple[str, str]] = []
    for store in (s.id for s in load_chain().stores):
        have = present_hours(es, store)
        hours = sorted(h for (st, h) in keys if st == store)
        edges = {hours[0], hours[-1]}  # the window starts and ends mid-hour, so these are partial by design
        for (st, hour), key in keys.items():
            if st != store:
                continue
            n = have.get(hour, 0)
            if n >= FULL_HOUR or (n > 0 and hour in edges):
                continue
            retrigger.append(key)
            if n > 0:
                partial.append((store, hour))
        print(f"  {store}: {sum(1 for h in hours if have.get(h, 0) < FULL_HOUR and not (have.get(h, 0) > 0 and h in edges))} hours to re-trigger", flush=True)
    print(f"re-trigger {len(retrigger)} objects; clear {len(partial)} partial hours first")
    if args.dry_run or not retrigger:
        return

    for store, hour in partial:
        start = datetime.strptime(hour, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
        es.delete_by_query(index=STREAM, refresh=True, conflicts="proceed", query={"bool": {"filter": [
            {"term": {"retail.store.id": store}},
            {"range": {"@timestamp": {"gte": start.isoformat(), "lt": (start + timedelta(hours=1)).isoformat()}}}]}})
    for i, key in enumerate(retrigger, 1):
        s3.copy_object(Bucket=bucket, Key=key, CopySource={"Bucket": bucket, "Key": key},
                       MetadataDirective="REPLACE", ContentType="application/x-ndjson", ContentEncoding="gzip",
                       Metadata={"retrigger": "1"})
        if i % 500 == 0:
            print(f"  re-triggered {i}/{len(retrigger)}", flush=True)
    print("done; the collector will re-ingest them")


if __name__ == "__main__":
    main()
