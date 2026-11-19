"""The catalog of every source of truth in the demo, for the dashboard "Act 0".

    python -m coldchain.sources              # load kb-sources (what each source is and which realm it belongs to)

`kb-sources` has one row per source: its realm (Security, Observability or Knowledge base), the label, what it holds and whether the SOC already
watches it ("lit") or not ("dark"). That is the editorial part. The sizes are not stored: the dashboard counts every index live with
`live_query()`, one ES|QL query over all of them, and joins the result to `kb-sources`.
"""
from __future__ import annotations

import argparse

from elasticsearch import helpers

from .elastic import client

SECURITY, OBSERVABILITY, KB = "Security realm", "Observability realm", "Knowledge base realm"
TIER_ORDER = {SECURITY: 1, OBSERVABILITY: 2, KB: 3}
# What the SOC can see under its light: the whole Security realm. Observability and the knowledge base are in the dark until they are switched on.
LIT = {"logs-coldchain.audit-default", "logs-netflow.summary-default", "logs-netflow.summary-pos", "logs-network_traffic.tls-pos",
       ".alerts-security.alerts-default", "cc-hunt-findings"}

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


def catalog() -> list[dict]:
    """What each source is: no measurement, the counts are taken live by the dashboard."""
    return [{"source": src, "label": LABELS[src], "zone": "lit" if src in LIT else "dark", "tier": tier, "tier_order": TIER_ORDER[tier],
             "what": what} for src, tier, what, _ in SOURCES]


def live_query(thousands: str) -> str:
    """ES|QL for Act 0: count every source in the cluster right now (rows, first and last time) and join the editorial `kb-sources`.

    `thousands` formats the count (ES|QL has no number formatting): a template with {col}.
    """
    subs = []
    for src, _, _, timed in SOURCES:
        if timed:
            subs.append(f'(FROM {src} | STATS n = COUNT(*), first_at = MIN(@timestamp), last_at = MAX(@timestamp) | EVAL source = "{src}")')
        else:
            subs.append(f'(FROM {src} | STATS n = COUNT(*) | EVAL source = "{src}", first_at = TO_DATETIME(NULL), last_at = TO_DATETIME(NULL))')
    return (f"FROM {', '.join(subs)} | LOOKUP JOIN kb-sources ON source | SORT tier_order, n DESC "
            f"| EVAL rows_txt = {thousands.format(col='n')} | KEEP tier, zone, label, what, rows_txt")


def load(es, rows: list[dict]) -> None:
    index = "kb-sources"
    if es.indices.exists(index=index):
        es.indices.delete(index=index)
    keyword = {"type": "keyword"}
    es.indices.create(index=index, settings={"index.mode": "lookup"}, mappings={"properties": {
        "source": keyword, "label": keyword, "zone": keyword, "tier": keyword, "tier_order": {"type": "integer"}, "what": keyword}})
    helpers.bulk(es, ({"_index": index, "_source": r} for r in rows), refresh="wait_for")
    print(f"{index}: {len(rows)} rows")


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    es = client()
    load(es, catalog())


if __name__ == "__main__":
    main()
