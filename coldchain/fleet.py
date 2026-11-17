"""Fleet side of the detection path: the collector's agent policy and its AWS S3 (SQS) integration.

    python -m coldchain.fleet setup     # idempotent: policy + Custom AWS Logs integration + enrollment token
    python -m coldchain.fleet status    # enrolled agents and policy health

The collector Agent reads the SQS queue, fetches each `detect/` object and sends the decoded NDJSON records
to `logs-coldchain.ingest-default` with the `coldchain-route` pipeline, which reroutes by event.dataset.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

from .envfile import load_env

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / ".secrets"
POLICY_NAME = "cold-chain-collector"
INTEGRATION_NAME = "cold-chain-detect-s3"
PACKAGE, PACKAGE_VERSION = "aws_logs", "1.8.3"
INGEST_DATASET = "coldchain.ingest"
PIPELINE = "coldchain-route"


class Kibana:
    def __init__(self) -> None:
        env = load_env()
        self.url = env["KIBANA_URL"].rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"ApiKey {env['ELASTIC_API_KEY']}", "kbn-xsrf": "true",
                               "Content-Type": "application/json"})

    def call(self, method: str, path: str, **kw):
        r = self.s.request(method, f"{self.url}{path}", timeout=60, **kw)
        if not r.ok:
            sys.exit(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
        return r.json()


def find(items: list[dict], name: str) -> dict | None:
    return next((i for i in items if i["name"] == name), None)


def integration_body(policy_id: str, env: dict[str, str], cred: dict[str, str]) -> dict:
    stream_vars = {
        "queue_url": env["COLDCHAIN_DETECT_QUEUE_URL"],
        "data_stream.dataset": INGEST_DATASET,
        "pipeline": PIPELINE,
        "number_of_workers": 5,
        "max_number_of_messages": 10,
        "parsers": '- ndjson:\n    target: ""\n    add_error_key: true\n',
        "tags": ["forwarded"],
        "preserve_original_event": False,
    }
    return {  # Fleet "simplified" format: plain values, keyed by input and stream id
        "name": INTEGRATION_NAME,
        "namespace": "default",
        "policy_ids": [policy_id],
        "package": {"name": PACKAGE, "version": PACKAGE_VERSION},
        "vars": {"access_key_id": cred["access_key_id"], "secret_access_key": cred["secret_access_key"],
                 "default_region": env.get("AWS_REGION", "eu-central-1")},
        "inputs": {"aws_logs-aws-s3": {"enabled": True, "streams": {
            "aws_logs.generic": {"enabled": True, "vars": stream_vars}}},
            "aws_logs-aws-cloudwatch": {"enabled": False, "streams": {}}},
    }


def setup() -> None:
    env = load_env()
    for key in ("COLDCHAIN_DETECT_QUEUE_URL", "KIBANA_URL", "ELASTIC_API_KEY"):
        if not env.get(key):
            sys.exit(f"{key} is not set in .env")
    cred = json.loads((SECRETS / "collector.json").read_text())
    kb = Kibana()
    kb.call("POST", f"/api/fleet/epm/packages/{PACKAGE}/{PACKAGE_VERSION}", json={"force": False})

    policy = find(kb.call("GET", "/api/fleet/agent_policies?perPage=100")["items"], POLICY_NAME)
    if not policy:
        policy = kb.call("POST", "/api/fleet/agent_policies", json={
            "name": POLICY_NAME, "namespace": "default", "monitoring_enabled": ["logs", "metrics"],
            "description": "Central collector: SQS -> detect/ objects -> coldchain-route"})["item"]
    print(f"agent policy {POLICY_NAME} ({policy['id']})")

    body = integration_body(policy["id"], env, cred)
    existing = find(kb.call("GET", "/api/fleet/package_policies?perPage=100")["items"], INTEGRATION_NAME)
    if existing:
        kb.call("PUT", f"/api/fleet/package_policies/{existing['id']}?format=simplified", json=body)
        print(f"integration {INTEGRATION_NAME} updated")
    else:
        kb.call("POST", "/api/fleet/package_policies?format=simplified", json=body)
        print(f"integration {INTEGRATION_NAME} created")

    keys = kb.call("GET", f"/api/fleet/enrollment_api_keys?perPage=100&kuery=policy_id:{policy['id']}")["items"]
    key = next((k for k in keys if k.get("active", True)), None) or kb.call(
        "POST", "/api/fleet/enrollment_api_keys", json={"policy_id": policy["id"]})["item"]
    hosts = kb.call("GET", "/api/fleet/fleet_server_hosts")["items"]
    fleet_url = next(h for h in hosts if h.get("is_default"))["host_urls"][0]
    SECRETS.mkdir(mode=0o700, exist_ok=True)
    path = SECRETS / "fleet.json"
    path.write_text(json.dumps({"fleet_url": fleet_url, "enrollment_token": key["api_key"],
                                "policy_id": policy["id"]}))
    path.chmod(0o600)
    env_path = SECRETS / "collector.env"  # read by compose/collector/docker-compose.yml
    env_path.write_text(f"FLEET_URL={fleet_url}\nFLEET_ENROLLMENT_TOKEN={key['api_key']}\n")
    env_path.chmod(0o600)
    print(f"enrollment token and Fleet URL saved to .secrets/fleet.json and .secrets/collector.env (git-ignored)")


def status() -> None:
    kb = Kibana()
    policy = find(kb.call("GET", "/api/fleet/agent_policies?perPage=100")["items"], POLICY_NAME)
    if not policy:
        sys.exit("policy not found: run `python -m coldchain.fleet setup`")
    agents = kb.call("GET", f"/api/fleet/agents?kuery=policy_id:{policy['id']}")["items"]
    print(f"{POLICY_NAME}: {len(agents)} agent(s)")
    for a in agents:
        print(f"  {a['id']} {a['status']} v{a.get('agent', {}).get('version')} {a.get('local_metadata', {}).get('host', {}).get('hostname')}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["setup", "status"])
    {"setup": setup, "status": status}[ap.parse_args(argv).cmd]()


if __name__ == "__main__":
    main()
