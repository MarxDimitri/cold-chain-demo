"""ES|QL data federation over the bucket's raw/ prefix (experimental; see CLAUDE.md 4.4).

    python -m coldchain.federation setup            # data source + datasets (idempotent)
    python -m coldchain.federation check            # one query per dataset, with timings
    python -m coldchain.federation query "<ES|QL>"  # run any ES|QL and print timing

The data source uses the read-only federation identity (raw/* only) from .secrets/federation.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "cold-chain-s3"

# dataset name -> dataset in the bucket (resource pattern relative to raw/)
DATASETS = {
    "raw_store_audit": "dataset=coldchain.audit",
    "raw_store_flows": "dataset=netflow.log",
    # Scenario B (hypothetical epilogue), S07 only. raw_edge_metrics of the brief is two datasets here, because the
    # signage and smart-plug files have different columns and one dataset infers one schema.
    "raw_store_tls": "dataset=network_traffic.tls",
    "raw_edge_signage": "dataset=signage.cms",
    "raw_edge_plug": "dataset=power.plug",
    # raw_store_telemetry is optional (raw telemetry is not generated).
}
SETTINGS = {"format": "ndjson"}


def env() -> dict[str, str]:
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)
    return os.environ  # type: ignore[return-value]


class Es:
    def __init__(self) -> None:
        e = env()
        self.url = e["ELASTICSEARCH_URL"].rstrip("/")
        self.bucket = e["COLDCHAIN_BUCKET"]
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"ApiKey {e['ELASTIC_API_KEY']}",
                               "Content-Type": "application/json"})

    def call(self, method: str, path: str, ok_404: bool = False, **kw):
        r = self.s.request(method, f"{self.url}{path}", timeout=300, **kw)
        if r.status_code == 404 and ok_404:
            return None
        if not r.ok:
            sys.exit(f"{method} {path} -> {r.status_code}: {r.text[:800]}")
        return r.json()

    def esql(self, query: str) -> tuple[dict, float]:
        t = time.time()
        res = self.call("POST", "/_query", json={"query": query})
        return res, time.time() - t


def setup() -> None:
    es = Es()
    cred = json.loads((ROOT / ".secrets" / "federation.json").read_text())
    es.call("PUT", f"/_query/data_source/{SOURCE}", json={
        "type": "s3", "description": "Cold-chain raw/ prefix (read-only identity)",
        "settings": {"auth": "static_credentials", "region": env().get("AWS_REGION", "eu-central-1"),
                     "access_key": cred["access_key_id"],
                     "secret_key": cred["secret_access_key"]}})
    print(f"data source {SOURCE}")
    for name, prefix in DATASETS.items():
        es.call("PUT", f"/_query/dataset/{name}", json={
            "data_source": SOURCE,
            "resource": f"s3://{es.bucket}/raw/{prefix}/**/*.ndjson.gz",
            "settings": SETTINGS})
        print(f"dataset {name} -> raw/{prefix}/**/*.ndjson.gz")


def show(res: dict, secs: float, rows: int = 10) -> None:
    cols = [c["name"] for c in res["columns"]]
    print(f"  {len(res['values'])} row(s) in {secs:.1f}s; columns: {', '.join(cols)}")
    for row in res["values"][:rows]:
        print("  ", dict(zip(cols, row)))


def check() -> None:
    es = Es()
    for name in DATASETS:
        res, secs = es.esql(f"FROM {name} | STATS docs = COUNT(*), earliest = MIN(@timestamp), latest = MAX(@timestamp)")
        print(name)
        show(res, secs)


def query(q: str) -> None:
    res, secs = Es().esql(q)
    show(res, secs, rows=50)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["setup", "check", "query"])
    ap.add_argument("esql", nargs="?")
    a = ap.parse_args(argv)
    {"setup": setup, "check": check, "query": lambda: query(a.esql)}[a.cmd]()


if __name__ == "__main__":
    main()
