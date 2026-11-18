"""The catalog of every source of truth in the demo, measured from the cluster, for the dashboard "Act 0".

    python -m coldchain.sources              # measure every source and load kb-sources (seconds)

`kb-sources` has one row per source: its realm (Security, Observability or Knowledge base), what it holds, how many rows, how far back it reaches and the question it answers.
The dashboard reads it with ES|QL.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from elasticsearch import helpers

from .elastic import client

SECURITY, OBSERVABILITY, KB = "Security realm", "Observability realm", "Knowledge base realm"
TIER_ORDER = {SECURITY: 1, OBSERVABILITY: 2, KB: 3}
# What a SOC already looks at: its alerts, and what the hunting agent adds. Every other source is in the dark.
LIT = {".alerts-security.alerts-default", "cc-hunt-findings"}

# (source as written after FROM, tier, what it holds, has a time field)
SOURCES: list[tuple[str, str, str, bool]] = [
    ("logs-coldchain.audit-default", SECURITY, "Controller logins, setpoint changes, defrost commands: a year of history", True),
    ("logs-netflow.summary-default", SECURITY, "5-minute network summaries per device pair", True),
    ("logs-netflow.summary-pos", SECURITY, "Network summaries around the POS terminals (hypothetical scenario)", True),
    ("logs-network_traffic.tls-pos", SECURITY, "TLS sessions of the S07 back-office POS: server names, fingerprints", True),
    (".alerts-security.alerts-default", SECURITY, "Alerts of the detection rules", True),
    ("cc-hunt-findings", SECURITY, "Findings of the scheduled hunting agent", True),
    ("logs-coldchain.case-default", OBSERVABILITY, "Cabinet telemetry every minute: air, setpoint, defrost relay", True),
    ("logs-coldchain.probe-default", OBSERVABILITY, "Independent temperature probes, every 5 minutes, on their own uplink", True),
    ("logs-pos.terminal-pos", OBSERVABILITY, "POS terminal health: CPU, disk, transactions per minute", True),
    ("logs-logistics.truck-default", OBSERVABILITY, "Delivery trucks: GPS, speed, cargo temperature every minute (hypothetical, live replay)", True),
    ("kb-assets", KB, "Every device: role, model, firmware, exposure, contractor account", False),
    ("kb-assets-by-ip", KB, "The same devices keyed by IP address", False),
    ("kb-controller-limits", KB, "Documented and curated normal setpoints, with manual page references", False),
    ("kb-device-profiles", KB, "Which servers each device role may talk to", False),
    ("kb-manuals", KB, "Short paraphrased controller manual facts", False),
    ("kb-regulations", KB, "Short paraphrased food-temperature and NIS2 facts", False),
    ("kb-erp-deliveries", KB, "The ERP delivery plan: which truck delivers what to which store and when", False),
    ("kb-baselines", KB, "What is normal for the Act 2 tiles, with provenance", False),
]


LABELS = {'logs-coldchain.case-default': 'Cabinet telemetry',
          'logs-coldchain.audit-default': 'Controller audit',
          'logs-coldchain.probe-default': 'Independent probes',
          'logs-netflow.summary-default': 'Network flows',
          'logs-netflow.summary-pos': 'POS network flows',
          'logs-network_traffic.tls-pos': 'POS TLS sessions',
          'logs-pos.terminal-pos': 'POS terminal health',
          'logs-logistics.truck-default': 'Truck telemetry',
          'kb-erp-deliveries': 'ERP deliveries',
          'kb-assets': 'Asset inventory',
          'kb-assets-by-ip': 'Assets by address',
          'kb-controller-limits': 'Controller limits',
          'kb-device-profiles': 'Device profiles',
          'kb-manuals': 'Manual facts',
          'kb-regulations': 'Regulations',
          'kb-baselines': 'Baselines',
          '.alerts-security.alerts-default': 'Alerts',
          'cc-hunt-findings': 'Hunt findings'}


def catalog(es) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for src, tier, what, timed in SOURCES:
        q = f"FROM {src} | STATS rows = COUNT(*)" + (", first_seen = MIN(@timestamp), last_seen = MAX(@timestamp)" if timed else "")
        try:
            vals = es.esql.query(query=q, format="json")["values"]
            vals = vals[0] if vals else [0, None, None]
        except Exception as e:  # a source that does not exist yet is listed as empty
            print(f"  {src}: {str(e)[:100]}", file=sys.stderr)
            vals = [0, None, None]
        n = vals[0]
        first, last = (vals[1], vals[2]) if timed else (None, None)
        days = None
        if first and last:
            days = max(1, round((datetime.fromisoformat(last.replace("Z", "+00:00")) - datetime.fromisoformat(first.replace("Z", "+00:00"))).total_seconds() / 86400))
        rows.append({"source": src, "label": LABELS[src], "zone": "lit" if src in LIT else "dark", "tier": tier, "tier_order": TIER_ORDER[tier], "what": what, "ask_with": f"FROM {src}",
                     "rows": n, "first_seen": first, "last_seen": last, "days": days, "measured_at": now})
        print(f"  {src:36} {n:>12,} rows", flush=True)
    return rows


def load(es, rows: list[dict]) -> None:
    index = "kb-sources"
    if es.indices.exists(index=index):
        es.indices.delete(index=index)
    keyword = {"type": "keyword"}
    es.indices.create(index=index, settings={"index.mode": "lookup"}, mappings={"properties": {
        "measured_at": {"type": "date"}, "source": keyword, "label": keyword, "zone": keyword, "tier": keyword, "tier_order": {"type": "integer"}, "what": keyword,
        "ask_with": keyword, "rows": {"type": "long"}, "first_seen": {"type": "date"}, "last_seen": {"type": "date"},
        "days": {"type": "integer"}}})
    helpers.bulk(es, ({"_index": index, "_source": r} for r in rows), refresh="wait_for")
    print(f"{index}: {len(rows)} rows")


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    es = client()
    load(es, catalog(es))


if __name__ == "__main__":
    main()
