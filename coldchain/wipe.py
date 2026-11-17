"""Remove everything this repo created in the Elastic deployment, to start the setup from scratch.

    python -m coldchain.wipe            # list what would be removed (dry run)
    python -m coldchain.wipe --yes      # remove it

Removes: the Kibana dashboards, detection rules and their alerts, the Agent Builder agent and tools, the hunt workflow, the ML
jobs and datafeeds, the Fleet policy and integration of the collector, the data streams, templates, pipelines and
knowledge-base indices.

Does not remove: the deployment itself, Fleet's own monitoring streams (`logs-elastic_agent*`, `metrics-fleet_server*`),
anything that is not named in this repo's code. The AWS side is `make teardown-aws`. Stop the collector first
(`make collector-down`), or Fleet keeps re-creating its policy's agent.
"""
from __future__ import annotations

import argparse

from elasticsearch import NotFoundError

from . import epilogue, hunt
from .agent import AGENT_ID, TOOLS
from .dashboards import DASHBOARDS, kibana
from .elastic import client
from .fleet import INTEGRATION_NAME, POLICY_NAME
from .prep import STREAMS

OLD_DASHBOARDS = ["coldchain-act1-estate", "coldchain-act4-evidence"]
RULES = ["coldchain-limits", "coldchain-warm-no-defrost", "coldchain-first-seen-peer"]
STREAM_PATTERNS = ["logs-coldchain.*", "metrics-coldchain.*", "logs-netflow.summary-*", "logs-pos.terminal-*", "logs-network_traffic.tls-*"]
TEMPLATE_PREFIXES = ("coldchain", "logs-coldchain", "metrics-coldchain", "logs-netflow.summary", "logs-pos.terminal", "logs-network_traffic.tls")
INDEX_PATTERNS = ["kb-*", "cc-history-audit*", "cc-hunt-findings", "cc-esql-moment", "test-coldchain-*", "zzcheck*"]
PIPELINES = ["coldchain-route", hunt.PIPELINE]
H = {"x-elastic-internal-origin": "Kibana", "elastic-api-version": "2023-10-31"}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="remove (default: list only)")
    yes = ap.parse_args(argv).yes
    es, (url, s) = client(), kibana()
    tag = "removed" if yes else "would remove"

    def kb(method: str, path: str, **kw) -> int:
        return s.request(method, f"{url}{path}", headers=H, timeout=120, **kw).status_code

    def do(what: str, fn=None, exists: bool = True) -> None:
        if not exists:
            return
        print(f"  {tag}: {what}")
        if yes and fn:
            try:
                fn()
            except Exception as e:  # a missing piece is fine, report anything else and carry on
                print(f"    ! {str(e)[:200]}")

    print("Kibana")
    for d in list(DASHBOARDS) + OLD_DASHBOARDS:
        do(f"dashboard {d}", lambda d=d: kb("DELETE", f"/api/dashboards/{d}"), s.get(f"{url}/api/dashboards/{d}", timeout=60).status_code == 200)
    for r in RULES:
        do(f"rule {r}", lambda r=r: s.delete(f"{url}/api/detection_engine/rules", params={"rule_id": r}, timeout=60),
           s.get(f"{url}/api/detection_engine/rules", params={"rule_id": r}, timeout=60).status_code == 200)
    n = es.count(index=".alerts-security.alerts-default", query={"prefix": {"kibana.alert.rule.name": "Cold chain:"}})["count"] \
        if es.indices.exists(index=".alerts-security.alerts-default") else 0
    do(f"{n} alerts of the cold-chain rules", lambda: es.delete_by_query(
        index=".alerts-security.alerts-default", query={"prefix": {"kibana.alert.rule.name": "Cold chain:"}},
        conflicts="proceed", refresh=True), n > 0)
    # the agent first: a tool that an agent still uses cannot be deleted
    do(f"agent {AGENT_ID}", lambda: kb("DELETE", f"/api/agent_builder/agents/{AGENT_ID}"),
       s.get(f"{url}/api/agent_builder/agents/{AGENT_ID}", headers=H, timeout=60).status_code == 200)
    for t in TOOLS:
        do(f"agent tool {t['id']}", lambda t=t: kb("DELETE", f"/api/agent_builder/tools/{t['id']}"),
           s.get(f"{url}/api/agent_builder/tools/{t['id']}", headers=H, timeout=60).status_code == 200)
    wid = hunt._find(s, url)
    do(f"workflow {wid}", lambda: s.delete(f"{url}/api/workflows/workflow/{wid}", timeout=60), wid is not None)

    print("Machine learning")
    for job in list(epilogue.JOBS):
        present = job in [j["job_id"] for j in es.ml.get_jobs(job_id="_all", allow_no_match=True)["jobs"]]

        def drop(job=job) -> None:
            for call, kw in ((es.ml.stop_datafeed, {"datafeed_id": f"datafeed-{job}", "force": True}),
                             (es.ml.delete_datafeed, {"datafeed_id": f"datafeed-{job}", "force": True}),
                             (es.ml.close_job, {"job_id": job, "force": True}),
                             (es.ml.delete_job, {"job_id": job, "force": True, "delete_user_annotations": True})):
                try:
                    call(**kw)
                except Exception:
                    pass
        do(f"ML job and datafeed {job}", drop, present)

    print("Fleet")
    policies = [p for p in s.get(f"{url}/api/fleet/agent_policies?perPage=100", timeout=60).json().get("items", []) if p["name"] == POLICY_NAME]
    for p in policies:
        def drop_policy(p=p) -> None:
            for a in s.get(f"{url}/api/fleet/agents?kuery=policy_id:{p['id']}", timeout=60).json().get("items", []):
                s.post(f"{url}/api/fleet/agents/{a['id']}/unenroll", json={"revoke": True, "force": True}, timeout=60)
                s.delete(f"{url}/api/fleet/agents/{a['id']}", timeout=60)
            pkg = [x for x in s.get(f"{url}/api/fleet/package_policies?perPage=100", timeout=60).json().get("items", []) if x["name"] == INTEGRATION_NAME]
            if pkg:
                s.post(f"{url}/api/fleet/package_policies/delete", json={"packagePolicyIds": [x["id"] for x in pkg], "force": True}, timeout=60)
            s.post(f"{url}/api/fleet/agent_policies/delete", json={"agentPolicyId": p["id"], "force": True}, timeout=60)
        do(f"agent policy {POLICY_NAME}, its integration {INTEGRATION_NAME}, enrolled agents and enrollment keys", drop_policy)

    print("Elasticsearch")
    for pat in STREAM_PATTERNS:
        names = [d["name"] for d in es.indices.get_data_stream(name=pat, expand_wildcards="all").get("data_streams", [])] \
            if es.indices.exists(index=pat) or True else []
        for name in names:
            do(f"data stream {name}", lambda name=name: es.indices.delete_data_stream(name=name))
    for pat in INDEX_PATTERNS:
        try:
            rows = es.cat.indices(index=pat, format="json", h="index", expand_wildcards="all")
        except NotFoundError:
            rows = []
        for row in rows:
            do(f"index {row['index']}", lambda i=row["index"]: es.indices.delete(index=i))
    for t in es.indices.get_index_template(name="*")["index_templates"]:
        if t["name"].startswith(TEMPLATE_PREFIXES):
            do(f"index template {t['name']}", lambda n=t["name"]: es.indices.delete_index_template(name=n))
    do("component template coldchain-mappings", lambda: es.cluster.delete_component_template(name="coldchain-mappings"),
       any(c["name"] == "coldchain-mappings" for c in es.cluster.get_component_template()["component_templates"]))
    existing = es.ingest.get_pipeline()
    for p in PIPELINES:
        do(f"ingest pipeline {p}", lambda p=p: es.ingest.delete_pipeline(id=p), p in existing)
    if not yes:
        print("\ndry run: nothing removed. Run with --yes.")
    else:
        print("\ndone. Streams touched by prep:", ", ".join(STREAMS))


if __name__ == "__main__":
    main()
