"""The agentic SOC (the ending): one Agent Builder agent that hunts across everything and tells one story.

    python -m coldchain.agent push          # create or replace the tools and the agent
    python -m coldchain.agent check         # run every tool query once with sample parameters
    python -m coldchain.agent ask [QUESTION]   # ask the agent (needs an LLM connector on the deployment)
    python -m coldchain.agent delete

Twelve ES|QL tools, one per step of the hunt. They read the indexed streams (the blip, a year of audit history, the POS evidence)
and the knowledge base (what is normal). The agent proposes containment; it does not change anything. Agent Builder is a
preview feature: say so on stage.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import osquery, trucks
from .dashboards import NOMINAL, kibana

ATTACKER = "203.0.113.0/24"

TOOLS = [
    {"id": "cc_recent_changes",
     "description": "Controller parameter changes in the last N minutes (indexed audit), joined to the knowledge base: how many cabinets "
                    "per store, which user and source address, and the verdict (within normal, outside normal, at documented maximum).",
     "params": {"minutes": {"type": "integer", "description": "look back this many minutes"}},
     "query": """FROM logs-coldchain.audit-default
| WHERE event.action == "parameter-change" AND DATE_DIFF("minutes", @timestamp, NOW()) <= ?minutes
| LOOKUP JOIN kb-assets ON device.id
| LOOKUP JOIN kb-controller-limits ON device.model.identifier, coldchain.parameter.code, coldchain.application
| EVAL kb.verdict = CASE(coldchain.parameter.value.new > kb.expected.max OR coldchain.parameter.value.new < kb.expected.min,
        CASE(coldchain.parameter.value.new >= kb.doc.max, "at documented maximum", "outside normal"), "within normal")
| STATS cabinets = COUNT_DISTINCT(device.id), first_seen = MIN(@timestamp), users = VALUES(user.name), sources = VALUES(source.ip)
    BY retail.store.id, coldchain.parameter.code, coldchain.parameter.value.new, kb.verdict
| SORT first_seen
| KEEP retail.store.id, cabinets, coldchain.parameter.code, coldchain.parameter.value.new, kb.verdict, users, sources, first_seen"""},
    {"id": "cc_recent_outside_logins",
     "description": "Indexed audit, live: successful logins in the last N minutes from addresses that are neither the contractor range "
                    "nor a store LAN, per store with the source address. Shows which stores' system managers an outsider has just "
                    "logged in to.",
     "params": {"minutes": {"type": "integer", "description": "look back this many minutes"}},
     "query": """FROM logs-coldchain.audit-default
| WHERE event.action == "logged-in" AND DATE_DIFF("minutes", @timestamp, NOW()) <= ?minutes
| EVAL ip = TO_STRING(source.ip)
| WHERE NOT CIDR_MATCH(TO_IP(ip), "198.51.100.0/24") AND NOT CIDR_MATCH(TO_IP(ip), "10.0.0.0/8")
| STATS logins = COUNT(*), first_seen = MIN(@timestamp) BY retail.store.id, ip
| SORT first_seen"""},
    {"id": "cc_warm_cabinets",
     "description": "Cabinets that are warm right now with no defrost to explain it: more than 2 K above their nominal temperature "
                    "in at least 3 of the last 10 minutes of data, defrost relay off, and no defrost relay reading in the last hour "
                    "(the logic of detection rule 2: a cabinet still recovering from a defrost is not listed). Per store: how many "
                    "cabinets and the largest rise.",
     "params": {},
     "query": f"""FROM metrics-coldchain.case-default
| WHERE @timestamp > NOW() - 1 day AND @timestamp <= NOW()
| INLINE STATS newest = MAX(@timestamp)
| WHERE @timestamp >= newest - 60 minutes
| EVAL rise = coldchain.case.temperature.air - {NOMINAL}
| STATS late_warm = COUNT(*) WHERE @timestamp >= newest - 10 minutes AND rise > 2 AND coldchain.case.defrost.active == false,
        relay_on = COUNT(*) WHERE coldchain.case.defrost.active == true, peak = MAX(rise) BY device.id, retail.store.id
| WHERE late_warm >= 3 AND relay_on == 0
| STATS warm_cabinets = COUNT(*), largest_rise_k = ROUND(MAX(peak), 1) BY retail.store.id
| SORT warm_cabinets DESC"""},
    {"id": "cc_history_of_address",
     "description": "A year of indexed store audit: every successful login from one address, per store, with first and last time. "
                    "Use it to find when an attacker first visited each store.",
     "params": {"ip": {"type": "string", "description": "source address, for example 203.0.113.47"}},
     "query": """FROM logs-coldchain.audit-default
| WHERE event.action == "logged-in"
| EVAL ip = TO_STRING(source.ip)
| WHERE ip == ?ip
| STATS visits = COUNT(*), first_visit = MIN(@timestamp), last_visit = MAX(@timestamp) BY store = retail.store.id
| SORT first_visit"""},
    {"id": "cc_estate_footprint",
     "description": "Indexed network flow summaries that touch the attacker address range, per store: which stores the attacker "
                    "has reached or called back to.",
     "params": {},
     "query": f"""FROM logs-netflow.summary-default
| WHERE CIDR_MATCH(source.ip, "{ATTACKER}") OR CIDR_MATCH(destination.ip, "{ATTACKER}")
| STATS flows = COUNT(*), first_seen = MIN(@timestamp), last_seen = MAX(@timestamp) BY store = retail.store.id
| SORT first_seen"""},
    {"id": "cc_exposed_controllers",
     "description": "Knowledge base: system managers that face the internet, with firmware, owner and the contractor's vendor-cloud "
                    "account. Compare it with the stores already touched to find the stores still at risk.",
     "params": {},
     "query": """FROM kb-assets
| WHERE coldchain.exposure.internet == true
| KEEP retail.store.id, retail.owner.id, coldchain.controller.firmware, contractor.account.id
| SORT retail.store.id"""},
    {"id": "cc_device_evidence",
     "description": "TLS records for one store: devices talking to servers their device profile does not allow, with the server name, "
                    "gigabytes received, chunks, nights and the TLS fingerprint (JA3). Hypothetical POS scenario.",
     "params": {"store": {"type": "string", "description": "store id, for example S07"}},
     "query": """FROM logs-network_traffic.tls-pos
| EVAL store = TO_STRING(retail.store.id), host.ip = TO_STRING(source.ip), tls.client.server_name = TO_STRING(tls.client.server_name)
| WHERE store == ?store
| LOOKUP JOIN kb-assets-by-ip ON host.ip
| LOOKUP JOIN kb-device-profiles ON retail.device.role, tls.client.server_name
| WHERE profile.allowed IS NULL
| STATS received = SUM(destination.bytes), chunks = COUNT(*), nights = COUNT_DISTINCT(DATE_TRUNC(1 day, @timestamp)),
        first_seen = MIN(@timestamp), last_seen = MAX(@timestamp), ja3 = VALUES(tls.client.ja3) BY host.name, tls.client.server_name
| EVAL received_gb = ROUND(received / 1073741824.0, 2)
| SORT received DESC
| KEEP host.name, tls.client.server_name, received_gb, chunks, nights, first_seen, last_seen, ja3
| LIMIT 10"""},
    {"id": "cc_internal_movement",
     "description": "Indexed flow summaries (hypothetical POS scenario): first-seen flows between devices inside one store, "
                    "newest first. Shows how a compromised device moved sideways, for example a back-office POS reaching the system manager.",
     "params": {"store": {"type": "string", "description": "store id, for example S07"}},
     "query": """FROM logs-netflow.summary-pos
| WHERE retail.store.id == ?store AND CIDR_MATCH(source.ip, "10.0.0.0/8") AND CIDR_MATCH(destination.ip, "10.0.0.0/8")
| STATS first_seen = MIN(@timestamp), flows = COUNT(*) BY host.name, source.ip, destination.ip, destination.port
| SORT first_seen DESC
| LIMIT 10"""},
    {"id": "cc_trucks_at_risk",
     "description": "Logistics, live: frozen deliveries on their way to a store whose frozen cabinets are not safe to load right now "
                    "(at least 8 frozen cabinets with the setpoint raised or the air above -18 C and no defrost). One query over three "
                    "sources: the cabinet telemetry, the truck telemetry (position, cargo temperature) and the ERP delivery plan. "
                    "Returns per truck and stop: the store, how many frozen cabinets are bad, kilometres to go, minutes to the planned "
                    "arrival, the ERP delivery id, pallets, cargo value in euros and the cargo temperature. The truck itself is cold: the risk is the store. "
                    "truck_status is what the truck is doing now, which may be unloading at an EARLIER stop; only at_destination = true means it is at this store.",
     "params": {},
     "query": trucks.at_risk_query()},
    {"id": "cc_vulnerable_assets",
     "description": "Advisory lens, from the endpoints themselves: the latest Osquery live query answers (Java runtime and version, CPU with or without "
                    "AVX-512 VBMI, JVM flags) of every agent-capable device (back-office POS PC and store server per store), checked against the BSI "
                    "warning on OpenJDK Java4Shell (CVE-2026-114938, published 2026-11-18) in kb-advisories. Per device: store, host, role, Java "
                    "version, AVX-512 yes or no, and a status: affected, affected mitigated by a JVM flag, not affected (Java version), "
                    "not affected (CPU). Affected is an exposure, not evidence of compromise: BSI says no attacks are known. Synthetic data.",
     "params": {},
     "query": osquery.vulnerable_query()},
    {"id": "cc_osquery_coverage",
     "description": "How many of the 40 agent-capable devices (back-office POS PC and store server of each store) answered the latest Osquery live "
                    "query, and which hosts are silent (offline agents). Always call it with cc_vulnerable_assets: a silent host is unknown, not safe. "
                    "The POS lanes and the system managers are appliances without an agent and are not part of this.",
     "params": {},
     "query": osquery.coverage_query()},
    {"id": "cc_what_is_normal",
     "description": "Knowledge base: the documented range and the curated normal range of a controller parameter, with the manual page.",
     "params": {"code": {"type": "string", "description": "parameter code: setpoint, A13, A03"}},
     "query": """FROM kb-controller-limits
| WHERE coldchain.parameter.code == ?code
| KEEP coldchain.parameter.code, coldchain.application, kb.doc.min, kb.doc.max, kb.expected.min, kb.expected.max, kb.doc.ref"""},
]

AGENT_ID = "cc-soc-hunter"
INSTRUCTIONS = """You are the SOC agent of a fictional retail chain (20 stores on the Upper Rhine, synthetic data). You hunt across
the live detections, a year of audit history and the in-store network, and you answer in ONE narrative, in this order:

1. THE BLIP. Call cc_recent_changes (for example 60 minutes), cc_recent_outside_logins and cc_warm_cabinets. Say which stores, how many cabinets, who changed
   them, from where, and what the knowledge base says is normal. Notice the two kinds of source address: the internet address and
   an address inside the store.
2. THE HISTORY. Call cc_history_of_address with the internet address, and cc_estate_footprint. Say when the attacker first visited
   each store (months ago, before any alert could exist), from a year of history that nobody was looking at.
3. THE STORE. For the store whose change came from inside, call cc_internal_movement and cc_device_evidence. Say which device
   it was (a back-office POS PC), what it downloaded and from which server, over how many nights, and how it reached the system
   manager. A POS device reaching the refrigeration controller means nothing separates the two on that store network: say so.
4. THE TRUCKS. Call cc_trucks_at_risk. The ERP says which frozen deliveries are planned for which store, the truck telemetry says
   where each truck is and that its cargo is still cold, and the cabinet telemetry says the destination's frozen cabinets are not safe to load.
   Say which trucks (id, ERP delivery id), to which store, how many minutes to the planned arrival and how many kilometres to go,
   the pallets and value in euros, and that the cargo is cold but the store is not. Propose: hold or reroute the delivery, or unload into the
   store's cold room instead of the cabinets; the logistics team decides. If the tool returns nothing, say no frozen delivery is heading to a store in trouble.
5. THE ADVISORY LENS. Call cc_vulnerable_assets and cc_osquery_coverage. The BSI warned on 2026-11-18 about OpenJDK "Java4Shell". The endpoints were asked
   directly (Osquery), also those that ship no logs. Say how many devices are affected (Java inside the affected range and a CPU with AVX-512 VBMI), how
   many are mitigated by a JVM flag, how many answered of 40 and which hosts are silent (unknown, not safe). Name which of the hit stores (S07, S11, S19) have an
   affected device and which do not (a hit store without an affected device shows that this advisory does not explain every hit). This is an exposure, never the cause: the BSI knows of no attacks and
   the data does not say how the attacker got in. Propose: the JVM workaround (-XX:-UseBASE64Intrinsics or -XX:UseAVX=2) and a restart, then patching, first on affected devices in
   stores with an outside login or a hit and on internet-reachable ones; ask the owners of silent hosts to check by hand.
6. WHAT IS NEXT. Call cc_exposed_controllers and subtract the stores already touched: every store with an outside login
   (cc_recent_outside_logins, live) or in cc_history_of_address or cc_estate_footprint (history, may lag a running attack). Name the stores still at risk and the
   shared contractor account. Propose containment (block the address, isolate the device, review the account, restore setpoints
   after the contractor approves). You never run containment yourself.

Rules: use the tools, never guess numbers or causes (do not name how the attacker got the credentials or what a device
"beacons"; say what the data shows and what is not known); show times in UTC; say "hypothetical, synthetic" for the POS scenario; quote counts per store exactly as the tools return them; keep the answer short, one section per step, ending with a one-line verdict. Write the final answer directly: never
announce that you are about to answer and never describe your plan."""

DEFAULT_QUESTION = ("Something changed temperature setpoints in our stores. What happened, how long has the attacker been in, "
                    "how did it happen inside the store, which stores are next, and are any deliveries heading into trouble?")

SAMPLE = {"minutes": 100000, "ip": "203.0.113.47", "store": "S07", "code": "setpoint"}


def tool_body(t: dict) -> dict:
    return {"id": t["id"], "type": "esql", "description": t["description"], "tags": ["coldchain"],
            "configuration": {"query": t["query"], "params": t["params"]}}


def agent_body() -> dict:
    return {"id": AGENT_ID, "name": "Cold-chain SOC agent (preview)",
            "description": "Hunts across detections, a year of history and the in-store network and tells one story. Synthetic data.",
            "configuration": {"instructions": INSTRUCTIONS, "tools": [{"tool_ids": [t["id"] for t in TOOLS]}]}}


def push() -> None:
    url, s = kibana()
    for t in TOOLS:
        r = s.post(f"{url}/api/agent_builder/tools", json=tool_body(t), timeout=60)
        if r.status_code == 409 or "already exists" in r.text:
            b = tool_body(t)
            b.pop("id"), b.pop("type")
            r = s.put(f"{url}/api/agent_builder/tools/{t['id']}", json=b, timeout=60)
        print("tool", t["id"], r.status_code, r.text[:200] if r.status_code >= 400 else "ok")
    r = s.post(f"{url}/api/agent_builder/agents", json=agent_body(), timeout=60)
    if r.status_code == 409 or "already exists" in r.text:
        b = agent_body()
        b.pop("id")
        r = s.put(f"{url}/api/agent_builder/agents/{AGENT_ID}", json=b, timeout=60)
    print("agent", AGENT_ID, r.status_code, r.text[:300] if r.status_code >= 400 else "ok")


def check() -> None:
    from .elastic import client
    es = client()
    bad = 0
    for t in TOOLS:
        params = [{k: SAMPLE[k]} for k in t["params"]]
        try:
            r = es.esql.query(query=t["query"], params=params, format="json")
            print(f"  ok   {len(r['values']):4d} rows  {t['id']}  {r['values'][0] if r['values'] else ''}"[:230])
        except Exception as e:
            bad += 1
            print(f"  FAIL {t['id']}: {str(e)[:300]}")
    sys.exit(1 if bad else 0)


def ask(question: str) -> None:
    url, s = kibana()
    r = s.post(f"{url}/api/agent_builder/converse", json={"input": question, "agent_id": AGENT_ID}, timeout=600)
    print(r.status_code)
    d = r.json()
    for step in d.get("steps", []):
        if step.get("type") == "tool_call":
            print("  tool:", step.get("tool_id"), json.dumps(step.get("params"))[:100])
    print(d.get("response", {}).get("message", r.text[:1500]))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["push", "check", "ask", "delete"])
    ap.add_argument("rest", nargs="*")
    a = ap.parse_args(argv)
    if a.cmd == "push":
        return push()
    if a.cmd == "check":
        return check()
    if a.cmd == "ask":
        return ask(" ".join(a.rest) or DEFAULT_QUESTION)
    url, s = kibana()
    print("agent", s.delete(f"{url}/api/agent_builder/agents/{AGENT_ID}").status_code)
    for t in TOOLS:
        print("tool", t["id"], s.delete(f"{url}/api/agent_builder/tools/{t['id']}").status_code)


if __name__ == "__main__":
    main()
