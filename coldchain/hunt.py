"""The scheduled hunt: the SOC agent keeps looking for abnormal behaviour across the estate (the "AlertZero pattern").

    python -m coldchain.hunt push        # create the findings index and the workflow (scheduled every 30 minutes, also manual)
    python -m coldchain.hunt run         # run it now and wait for the result
    python -m coldchain.hunt findings    # print the findings index
    python -m coldchain.hunt clear       # empty the findings index (before a new demo; the workflow stays)
    python -m coldchain.hunt delete      # remove the workflow and the findings index

AlertZero (Elastic Security's agentic layer) is not offered on this deployment (9.5.6 Elastic Cloud Hosted: no
`securitySolution:enableAlertZero` setting), so the same shape is built from its documented parts: an Elastic Workflow on a
schedule calls an Agent Builder agent (`cc-soc-hunter`, the eight ES|QL tools of `agent.py`) and records what it finds. It
proposes, it never acts. Label it "AlertZero pattern", not the product.
"""
from __future__ import annotations

import argparse
import json
import time

from .agent import AGENT_ID
from .dashboards import kibana
from .elastic import client

INDEX = "cc-hunt-findings"
PIPELINE = "cc-hunt-findings-ts"
NAME = "Cold-chain hunt (AlertZero pattern, preview)"
EVERY = "30m"

MESSAGE = """This is a scheduled hunt. Nobody asked a question: sweep the whole estate for abnormal behaviour and report each
distinct finding once. Every claim must come from a tool result; do not guess and do not repeat a finding in other words.

Check at least these, with your tools:
1. Access from outside: logins or setpoint changes from addresses that are neither a store LAN nor a contractor range, in the
   indexed data, which includes a year of history (a first visit is a finding even when nothing changed).
2. Temperature: cabinets warm for too long with no defrost.
3. Device behaviour: devices talking to servers their profile does not allow, internal peers never seen before, unusual
   volume (compare with what is normal for that device role).
4. Exposure: controllers reachable from the internet that the attacker has not touched yet.
5. Logistics: frozen deliveries heading to a store whose frozen cabinets are not safe to load (ERP plan, truck telemetry and cabinet
   telemetry together).

Stores that an outside address logged in to but did NOT change anything (no setpoint change, no forced defrost, in the live data
or the history) are ONE finding together, key `first-visit:` followed by their ids joined with `+` in order, title like "Unknown address
logged in to 6 stores, no change yet", stores listing all of them, severity high. A first visit to a store where setpoints were changed is
its own finding, with the store id in the key (`first-visit:S07`), because that store was hit.
Report one finding per type and store, never two for the same thing (a first visit seen both live and in the history is one
finding, with the earliest time). The key is exactly `<type>:<store>` with the type from this list and the store id (for a
group of stores use their ids joined with `+`, in order): first-visit, setpoint-change, forced-defrost, warm-cabinets,
pos-download, internal-pivot, exposed-controllers, truck-at-risk (one finding per destination store, entities: truck and ERP delivery ids). Examples: `first-visit:S07`, `setpoint-change:S11`,
`exposed-controllers:S03+S05+S09+S12+S14`. The same finding must get the same key on every run.
List in `tools` the ids of the tools whose results support each finding (for example `cc_history_of_address`).
Keep the text short, it is shown in a dashboard table: title at most 70 characters, proposed_action at most 120,
why_abnormal at most 200 and evidence at most 250 (numbers and times, no sentences repeated from the title).
Severity: critical when something changed a setpoint or a device acts from inside a store, high for a first visit, exposed
controllers sharing a contractor account, or a frozen truck heading into a store in trouble (money and a clock), medium or low otherwise. Propose actions, do not run any. If nothing is abnormal,
return no findings."""

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "Two sentences: what the hunt covered and what it found"},
        "findings": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Stable id of the finding, the same on every run"},
                "title": {"type": "string", "description": "At most 70 characters"},
                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "category": {"type": "string", "enum": ["outside-access", "temperature", "device-behaviour", "exposure", "logistics"]},
                "stores": {"type": "array", "items": {"type": "string"}},
                "tools": {"type": "array", "items": {"type": "string"}, "description": "Ids of the tools whose results support this finding"},
                "entities": {"type": "array", "items": {"type": "string"}, "description": "IP addresses, hosts, devices"},
                "evidence": {"type": "string", "description": "What the tools returned, with numbers and times, at most 250 characters"},
                "why_abnormal": {"type": "string", "description": "At most 200 characters"},
                "proposed_action": {"type": "string", "description": "At most 120 characters"},
            },
            "required": ["key", "title", "severity", "category", "stores", "tools", "evidence", "why_abnormal", "proposed_action"],
        }},
    },
    "required": ["summary", "findings"],
}


def workflow_yaml() -> str:
    schema = json.dumps(SCHEMA)
    message = json.dumps(MESSAGE)
    return f"""version: "1"
name: "{NAME}"
description: "A scheduled hunt by the cold-chain SOC agent over the whole estate. It records findings and proposes actions, it runs none. Synthetic data."
enabled: true
tags: [coldchain, hunt, alertzero-pattern]
triggers:
  - type: manual
  - type: scheduled
    with:
      every: {EVERY}
steps:
  - name: hunt
    type: ai.agent
    agent-id: {AGENT_ID}
    with:
      message: {message}
      schema: {schema}
  - name: record
    type: foreach
    foreach: "{{{{ steps.hunt.output.structured_output.findings | json }}}}"
    steps:
      - name: write_finding
        type: elasticsearch.index
        with:
          index: {INDEX}
          id: "{{{{ foreach.item.key }}}}"
          pipeline: {PIPELINE}
          document:
            key: "{{{{ foreach.item.key }}}}"
            title: "{{{{ foreach.item.title }}}}"
            severity: "{{{{ foreach.item.severity }}}}"
            category: "{{{{ foreach.item.category }}}}"
            stores: "{{{{ foreach.item.stores | json }}}}"
            entities: "{{{{ foreach.item.entities | json }}}}"
            tools: "{{{{ foreach.item.tools | json }}}}"
            evidence: "{{{{ foreach.item.evidence }}}}"
            why_abnormal: "{{{{ foreach.item.why_abnormal }}}}"
            proposed_action: "{{{{ foreach.item.proposed_action }}}}"
            summary: "{{{{ steps.hunt.output.structured_output.summary }}}}"
            status: new
"""


def setup_index() -> None:
    es = client()
    # The workflow renders the agent's arrays as JSON text; the pipeline turns them back into arrays and stamps the time.
    es.ingest.put_pipeline(id=PIPELINE, processors=[
        {"set": {"field": "@timestamp", "value": "{{_ingest.timestamp}}", "if": "ctx['@timestamp'] == null"}},
        {"json": {"field": "stores", "target_field": "stores", "ignore_failure": True}},
        {"json": {"field": "entities", "target_field": "entities", "ignore_failure": True}},
        {"json": {"field": "tools", "target_field": "tools", "ignore_failure": True}},
        {"script": {"lang": "painless", "ignore_failure": True, "source":
                    "ctx.risk = ctx.severity == 'critical' ? 95 : ctx.severity == 'high' ? 75 : ctx.severity == 'medium' ? 50 : 25"}}])
    if es.indices.exists(index=INDEX):
        es.indices.put_mapping(index=INDEX, properties={"risk": {"type": "integer"}, "tools": {"type": "keyword"}})
    else:
        es.indices.create(index=INDEX, settings={"index.default_pipeline": PIPELINE}, mappings={"properties": {
            "@timestamp": {"type": "date"}, "key": {"type": "keyword"}, "title": {"type": "text"},
            "severity": {"type": "keyword"}, "category": {"type": "keyword"}, "stores": {"type": "keyword"},
            "entities": {"type": "keyword"}, "evidence": {"type": "text"}, "why_abnormal": {"type": "text"},
            "proposed_action": {"type": "text"}, "summary": {"type": "text"}, "status": {"type": "keyword"}, "risk": {"type": "integer"}, "tools": {"type": "keyword"}}})


def _find(s, url) -> str | None:
    for w in s.get(f"{url}/api/workflows", params={"size": 100}, timeout=60).json().get("results", []):
        if w.get("name") == NAME:
            return w["id"]
    return None


def push() -> str:
    setup_index()
    url, s = kibana()
    wid = _find(s, url)
    body = {"yaml": workflow_yaml()}
    r = s.put(f"{url}/api/workflows/workflow/{wid}", json=body, timeout=60) if wid else \
        s.post(f"{url}/api/workflows", json={"workflows": [body]}, timeout=60)
    print("workflow", "updated" if wid else "created", r.status_code, r.text[:600])
    r.raise_for_status()
    if not wid:
        d = r.json()
        wid = (d.get("created") or d.get("workflows") or [{}])[0].get("id") if isinstance(d, dict) else None
        wid = wid or _find(s, url)
    print("id:", wid)
    return wid


def run() -> None:
    url, s = kibana()
    wid = _find(s, url) or push()
    # The Workflows run endpoint is not a public REST route on 9.5.6; Agent Builder's workflow tools start and poll it.
    h = {"x-elastic-internal-origin": "Kibana", "elastic-api-version": "2023-10-31"}

    def tool(name: str, params: dict) -> dict:
        r = s.post(f"{url}/api/agent_builder/tools/_execute", headers=h, json={"tool_id": name, "tool_params": params}, timeout=300)
        r.raise_for_status()
        return r.json()["results"][0]["data"]["execution"]

    eid = tool("platform.core.execute_workflow", {"workflowId": wid, "inputs": {}})["execution_id"]
    print("execution", eid)
    t = time.time()
    while time.time() - t < 900:
        time.sleep(20)
        e = tool("platform.core.get_workflow_execution_status", {"executionId": eid})
        print(f"  {time.time() - t:4.0f} s {e['status']}", flush=True)
        if e["status"] not in ("running", "pending", "waiting"):
            if e.get("error"):
                print("  error:", str(e["error"])[:500])
            return


def findings() -> None:
    es = client()
    es.indices.refresh(index=INDEX)
    r = es.search(index=INDEX, size=50, sort=[{"@timestamp": "desc"}])
    print(r["hits"]["total"]["value"], "findings")
    for h in r["hits"]["hits"]:
        d = h["_source"]
        print(f"- [{d.get('severity')}] {d.get('key')}: {d.get('title')} | stores={d.get('stores')} | {d.get('@timestamp')}")


def clear() -> None:
    es = client()
    if es.indices.exists(index=INDEX):
        print("cleared", es.delete_by_query(index=INDEX, query={"match_all": {}}, refresh=True, conflicts="proceed")["deleted"], "findings")


def delete() -> None:
    url, s = kibana()
    wid = _find(s, url)
    if wid:
        print("workflow", s.delete(f"{url}/api/workflows/workflow/{wid}", timeout=60).status_code)
    es = client()
    es.indices.delete(index=INDEX, ignore_unavailable=True)
    es.ingest.delete_pipeline(id=PIPELINE, ignore=[404])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["push", "run", "findings", "clear", "delete"])
    a = ap.parse_args(argv)
    {"push": push, "run": run, "findings": findings, "clear": clear, "delete": delete}[a.cmd]()


if __name__ == "__main__":
    main()
