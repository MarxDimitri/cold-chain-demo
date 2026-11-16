"""Helpers around the Terraform stack in infra/.

    python -m coldchain.infra write-env      # copy Terraform outputs into .env and .secrets/
    python -m coldchain.infra empty-bucket --yes   # delete every version and delete marker (governance bypass)
    python -m coldchain.infra clean-raw --since 2026-11-16T08:50:00Z [--delete] [--force]
        # list (default) or delete the raw/ object versions written since a time: the files of a replay run
    python -m coldchain.infra check          # acceptance checks: store isolation, object lock, collector, federation
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .chain import ROOT

ENV = ROOT / ".env"
SECRETS = ROOT / ".secrets"


def tf_outputs() -> dict:
    out = subprocess.run(["terraform", f"-chdir={ROOT / 'infra'}", "output", "-json"],
                         check=True, capture_output=True, text=True).stdout
    return {k: v["value"] for k, v in json.loads(out).items()}


def _set_env(values: dict[str, str]) -> None:
    src = ENV if ENV.exists() else ROOT / ".env.example"
    lines, seen = src.read_text().splitlines(), set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0]
        if key in values and not line.startswith("#"):
            lines[i], _ = f"{key}={values[key]}", seen.add(key)
    lines += [f"{k}={v}" for k, v in values.items() if k not in seen]
    ENV.write_text("\n".join(lines) + "\n")


def write_env() -> None:
    o = tf_outputs()
    _set_env({"COLDCHAIN_BUCKET": o["bucket"], "AWS_REGION": o["region"],
              "COLDCHAIN_DETECT_QUEUE_URL": o["detect_queue_url"],
              "COLDCHAIN_DETECT_DLQ_URL": o["detect_dlq_url"]})
    SECRETS.mkdir(mode=0o700, exist_ok=True)
    for name in ("collector", "federation"):
        path = SECRETS / f"{name}.json"
        path.write_text(json.dumps(o[f"{name}_credentials"]))
        path.chmod(0o600)
    print(f"bucket {o['bucket']} ({o['region']}); .env updated; credentials in .secrets/ (git-ignored)")


def empty_bucket(yes: bool) -> None:
    import boto3

    bucket = tf_outputs()["bucket"]
    if not yes:
        sys.exit(f"refusing to delete every object version in s3://{bucket} without --yes")
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "eu-central-1"))
    deleted = 0
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
        items = [{"Key": v["Key"], "VersionId": v["VersionId"]}
                 for v in page.get("Versions", []) + page.get("DeleteMarkers", [])]
        for i in range(0, len(items), 1000):
            s3.delete_objects(Bucket=bucket, BypassGovernanceRetention=True,
                              Delete={"Objects": items[i:i + 1000], "Quiet": True})
            deleted += len(items[i:i + 1000])
    print(f"deleted {deleted} versions and delete markers from s3://{bucket}")


MAX_AGE_DAYS = 7


def pick_since(versions: list[dict], since: datetime) -> list[dict]:
    """The object versions in VERSIONS (as listed by S3) written at or after SINCE."""
    return [v for v in versions if v["LastModified"] >= since]


def clean_raw(since: str, delete: bool, force: bool) -> None:
    """Remove the raw/ files a replay run wrote (they are written when the run ends).

    A replay overwrites nothing: its raw files are new keys, so deleting their versions removes them completely and leaves
    the backfilled history alone. Dry run unless --delete. A SINCE older than a week is refused without --force, because
    it would reach the backfill (the history is written once and takes a long time to rebuild).
    """
    import boto3

    t = datetime.fromisoformat(since.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - t > timedelta(days=MAX_AGE_DAYS) and not force:
        sys.exit(f"{since} is more than {MAX_AGE_DAYS} days ago: that could reach the backfilled history. Use --force if you mean it.")
    bucket = os.environ.get("COLDCHAIN_BUCKET") or tf_outputs()["bucket"]
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "eu-central-1"))
    found: list[dict] = []
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix="raw/"):
        found += pick_since(page.get("Versions", []), t)
    by_dataset: dict[str, int] = {}
    for v in found:
        d = v["Key"].split("/")[1]
        by_dataset[d] = by_dataset.get(d, 0) + 1
    print(f"{len(found)} raw/ versions written since {since}:", by_dataset or "none")
    if found:
        print("  oldest write:", min(v["LastModified"] for v in found).isoformat(), "| newest:", max(v["LastModified"] for v in found).isoformat())
    if not delete:
        print("dry run: nothing deleted (add DELETE=1 or --delete)")
        return
    for i in range(0, len(found), 1000):
        batch = [{"Key": v["Key"], "VersionId": v["VersionId"]} for v in found[i:i + 1000]]
        r = s3.delete_objects(Bucket=bucket, BypassGovernanceRetention=True, Delete={"Objects": batch, "Quiet": True})
        if r.get("Errors"):
            sys.exit(f"delete errors: {r['Errors'][:3]}")
    print(f"deleted {len(found)} versions")


def check() -> None:
    import boto3
    from urllib.parse import unquote
    from botocore.exceptions import ClientError

    o = tf_outputs()
    bucket, region = o["bucket"], o["region"]
    keys = json.loads((ROOT / "store-keys.json").read_text())

    def client(service: str, cred: dict):
        return boto3.client(service, region_name=region, aws_access_key_id=cred["access_key_id"],
                            aws_secret_access_key=cred["secret_access_key"])

    results: list[tuple[str, bool]] = []

    def expect(name: str, ok: bool) -> None:
        results.append((name, ok))
        print(f"{'PASS' if ok else 'FAIL'}  {name}", flush=True)

    def allowed(fn) -> bool:
        try:
            fn()
            return True
        except ClientError as e:
            return e.response["Error"]["Code"] not in ("AccessDenied", "AllAccessDisabled", "403")

    def denied(fn) -> bool:
        return not allowed(fn)

    admin = boto3.client("s3", region_name=region)
    lock = admin.get_object_lock_configuration(Bucket=bucket)["ObjectLockConfiguration"]
    expect("object lock enabled, governance default retention",
           lock["ObjectLockEnabled"] == "Enabled" and lock["Rule"]["DefaultRetention"]["Mode"] == "GOVERNANCE")
    expect("versioning enabled", admin.get_bucket_versioning(Bucket=bucket).get("Status") == "Enabled")
    bpa = admin.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
    expect("block public access (all four)", all(bpa.values()))

    stamp = int(time.time())
    own = f"detect/dataset=infra.check/store=S07/dt=check/hh=00/S07-{stamp}-0.ndjson.gz"
    own_raw = f"raw/dataset=infra.check/store=S07/dt=check/hh=00/S07-{stamp}.ndjson.gz"
    other = f"detect/dataset=infra.check/store=S03/dt=check/hh=00/S07-{stamp}-0.ndjson.gz"
    s07 = client("s3", keys["S07"])
    expect("store S07 can write its own detect/ prefix",
           allowed(lambda: s07.put_object(Bucket=bucket, Key=own, Body=b'{"check":true}\n')))
    expect("store S07 can write its own raw/ prefix",
           allowed(lambda: s07.put_object(Bucket=bucket, Key=own_raw, Body=b'{"check":true}\n')))
    expect("store S07 cannot write S03's prefix",
           denied(lambda: s07.put_object(Bucket=bucket, Key=other, Body=b"x")))
    expect("store S07 cannot read", denied(lambda: s07.get_object(Bucket=bucket, Key=own)))
    expect("store S07 cannot list", denied(lambda: s07.list_objects_v2(Bucket=bucket, Prefix="detect/")))
    expect("store S07 cannot delete", denied(lambda: s07.delete_object(Bucket=bucket, Key=own)))

    col = json.loads((SECRETS / "collector.json").read_text())
    c3, sqs = client("s3", col), client("sqs", col)
    expect("collector can read detect/", allowed(lambda: c3.get_object(Bucket=bucket, Key=own)))
    expect("collector can list detect/", allowed(lambda: c3.list_objects_v2(Bucket=bucket, Prefix="detect/", MaxKeys=1)))
    expect("collector cannot read raw/", denied(lambda: c3.get_object(Bucket=bucket, Key=own_raw)))
    expect("collector cannot list raw/", denied(lambda: c3.list_objects_v2(Bucket=bucket, Prefix="raw/", MaxKeys=1)))
    got = []
    for _ in range(4):  # visibility 0, so a running collector would still see the message
        r = sqs.receive_message(QueueUrl=o["detect_queue_url"], MaxNumberOfMessages=10,
                                WaitTimeSeconds=10, VisibilityTimeout=0)
        got += [unquote(m["Body"]) for m in r.get("Messages", [])]  # S3 URL-encodes keys in events
        if any(own in b for b in got):
            break
    expect("S3 event for the detect/ object reached the queue", any(own in b for b in got))
    expect("no queue event for raw/", not any(own_raw in b for b in got))

    fed = json.loads((SECRETS / "federation.json").read_text())
    f3 = client("s3", fed)
    expect("federation can read raw/", allowed(lambda: f3.get_object(Bucket=bucket, Key=own_raw)))
    expect("federation can list raw/", allowed(lambda: f3.list_objects_v2(Bucket=bucket, Prefix="raw/", MaxKeys=1)))
    expect("federation cannot read detect/", denied(lambda: f3.get_object(Bucket=bucket, Key=own)))

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    print("note: check objects under dataset=infra.check stay (object lock); the collector will ingest "
          "the detect/ one once it runs")
    sys.exit(1 if failed else 0)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("write-env")
    e = sub.add_parser("empty-bucket")
    e.add_argument("--yes", action="store_true")
    sub.add_parser("check")
    c = sub.add_parser("clean-raw")
    c.add_argument("--since", required=True, help="ISO time, UTC: raw/ versions written at or after it")
    c.add_argument("--delete", action="store_true")
    c.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "clean-raw":
        return clean_raw(args.since, args.delete, args.force)
    {"write-env": write_env, "check": check}.get(args.cmd, lambda: empty_bucket(args.yes))()


if __name__ == "__main__":
    main()
