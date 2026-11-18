"""Writers for gzip NDJSON files in the bucket layout (local directory or S3).

detect/dataset=<d>/store=<S>/dt=<date>/hh=<HH>/<S>-<epoch>-<seq>.ndjson.gz
raw/dataset=<d>/store=<S>/dt=<date>/hh=<HH>/<S>-<epoch>.ndjson.gz
"""
from __future__ import annotations

import gzip
import json
import os
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def object_key(layer: str, dataset: str, store: str, chunk_epoch: int, seq: int = 0) -> str:
    t = datetime.fromtimestamp(chunk_epoch, tz=timezone.utc)
    name = f"{store}-{chunk_epoch}" + (f"-{seq}" if layer == "detect" else "") + ".ndjson.gz"
    return (f"{layer}/dataset={dataset}/store={store}/"
            f"dt={t:%Y-%m-%d}/hh={t:%H}/{name}")


class LocalSink:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.files = 0
        self.bytes = 0

    def put(self, key: str, store: str, body: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        self.files += 1
        self.bytes += len(body)

    def wait(self) -> None:
        """Nothing to wait for: local writes are synchronous."""


class S3Sink:
    """Each store writes with its own write-only credentials (COLDCHAIN_STORE_KEYS_FILE).

    Uploads run in a thread pool (a PUT takes 0.1 to 0.5 s from a laptop, and a pre-roll is thousands of small files); call
    `wait()` before relying on the objects being there.
    """

    def __init__(self, bucket: str, region: str, keys_file: str | None = None, resume: bool = False):
        import boto3  # imported lazily so local runs don't need AWS
        from botocore.config import Config

        self.bucket, self.region = bucket, region
        self._config = Config(retries={"max_attempts": 10, "mode": "adaptive"})
        self.skipped = 0
        self.existing: set[str] = set()
        if resume:  # list what is already there with the operator's credentials (stores cannot list)
            pager = boto3.client("s3", region_name=region, config=self._config).get_paginator("list_objects_v2")
            self.existing = {o["Key"] for prefix in ("detect/", "raw/")
                             for page in pager.paginate(Bucket=bucket, Prefix=prefix)
                             for o in page.get("Contents", [])}
            print(f"resume: {len(self.existing)} objects already in s3://{bucket}", flush=True)
        self.keys = json.loads(Path(keys_file).read_text()) if keys_file and Path(keys_file).exists() else {}
        self._boto3 = boto3
        self._clients: dict[str, object] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=int(os.environ.get("COLDCHAIN_UPLOAD_THREADS", "16")))
        self._pending: list = []
        self.files = 0
        self.bytes = 0

    def _client(self, store: str):
        with self._lock:
            if store not in self._clients:
                cred = self.keys.get(store)
                kwargs = {"region_name": self.region, "config": self._config}
                if cred:
                    kwargs |= {"aws_access_key_id": cred["access_key_id"],
                               "aws_secret_access_key": cred["secret_access_key"]}
                self._clients[store] = self._boto3.client("s3", **kwargs)
            return self._clients[store]

    def put(self, key: str, store: str, body: bytes) -> None:
        if key in self.existing:
            self.skipped += 1
            return
        client = self._client(store)

        def upload() -> None:
            client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType="application/x-ndjson", ContentEncoding="gzip")
            with self._lock:
                self.files += 1
                self.bytes += len(body)
        self._pending.append(self._pool.submit(upload))
        if len(self._pending) >= 2000:  # bound the memory held by queued bodies
            self.wait()

    def wait(self) -> None:
        """Wait for every queued upload; raise the first error."""
        pending, self._pending = self._pending, []
        for f in pending:
            f.result()


def make_sink(target: str, out: str = "out", resume: bool = False):
    if target == "local":
        return LocalSink(out)
    return S3Sink(os.environ["COLDCHAIN_BUCKET"], os.environ.get("AWS_REGION", "eu-central-1"),
                  os.environ.get("COLDCHAIN_STORE_KEYS_FILE"), resume)


def _gz(lines: Iterable[str]) -> bytes:
    return gzip.compress(("\n".join(lines) + "\n").encode(), compresslevel=1, mtime=0)


def write_chunk(sink, layer: str, dataset: str, store: str, chunk_epoch: int,
                lines: list[str], seq: int = 0) -> None:
    if lines:
        sink.put(object_key(layer, dataset, store, chunk_epoch, seq), store, _gz(lines))


def write_records(sink, layer: str, dataset: str, store: str,
                  records: Iterable[tuple[int, dict]], rotation_minutes: int) -> int:
    """Group (epoch_seconds, record) pairs into rotation-aligned files. Returns record count."""
    span = rotation_minutes * 60
    groups: dict[int, list[tuple[int, str]]] = defaultdict(list)
    n = 0
    for epoch, rec in records:
        groups[epoch - epoch % span].append((epoch, json.dumps(rec, separators=(",", ":"), ensure_ascii=False)))
        n += 1
    for chunk_epoch, items in groups.items():
        items.sort(key=lambda x: x[0])
        write_chunk(sink, layer, dataset, store, chunk_epoch, [s for _, s in items])
    return n
