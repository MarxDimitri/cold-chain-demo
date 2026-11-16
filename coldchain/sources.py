"""The catalog of every source of truth in the demo, measured from the cluster, and the "one question, three places" timings.

    python -m coldchain.sources              # measure everything, load kb-sources and cc-esql-moment (about 5 minutes)
    python -m coldchain.sources catalog      # only the catalog
    python -m coldchain.sources moment       # only the timings

`kb-sources` feeds the dashboard "CC Act 0": one row per source with its tier, what it holds, how big it is and how far back it
reaches. The raw files are counted in place by federation, so the rows are measured once (`measured_at`), not live.
`cc-esql-moment` holds the same question asked of three places with only the FROM changed (live index, frozen tier, raw files in
S3), with the seconds each took: the "one language" proof of Acts 3a and 3b.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from elasticsearch import helpers

from .elastic import client
from .federation import Es

INDEXED, FROZEN, RAW, KB, PRODUCED = "Indexed", "Frozen tier", "Raw in S3", "Knowledge base", "Produced"
TIER_ORDER = {INDEXED: 1, FROZEN: 2, RAW: 3, KB: 4, PRODUCED: 5}

# (source as written after FROM, tier, what it holds, has a time field)
SOURCES: list[tuple[str, str, str, bool]] = [
    ("logs-coldchain.case-default", INDEXED, "Cabinet telemetry every minute: air, setpoint, defrost relay (35 days)", True),
    ("logs-coldchain.audit-default", INDEXED, "Controller logins, setpoint changes, defrost commands (35 days)", True),
    ("logs-coldchain.probe-default", INDEXED, "Independent temperature probes, every 5 minutes, own uplink (35 days)", True),
    ("logs-netflow.summary-default", INDEXED, "5-minute network summaries per device pair (7 days)", True),
    ("logs-netflow.summary-epilogue", INDEXED, "Scenario B: flow summaries, the TV box (hypothetical, 21 days)", True),
    ("logs-signage.cms-epilogue", INDEXED, "Scenario B: signage CPU and storage (hypothetical)", True),
    ("logs-power.plug-epilogue", INDEXED, "Scenario B: TV box smart-plug power (hypothetical)", True),
    ("cc-history-audit", FROZEN, "The 12-month store audit, ingested once, kept on the frozen tier", True),
    ("raw_store_audit", RAW, "12 months of store audit, never ingested, one file per store per day", True),
    ("raw_store_flows", RAW, "Full network flows, 7 days (S07's window is scenario B)", True),
    ("raw_store_tls", RAW, "S07 TLS sessions: server names and JA3 (hypothetical)", True),
    ("raw_edge_signage", RAW, "S07 signage player CPU and storage (hypothetical)", True),
    ("raw_edge_plug", RAW, "S07 TV box smart-plug watts (hypothetical)", True),
    ("kb-assets", KB, "Every device: role, model, firmware, exposure, contractor account", False),
    ("kb-assets-by-ip", KB, "The same devices keyed by IP address", False),
    ("kb-controller-limits", KB, "Documented and curated normal setpoints, with manual page references", False),
    ("kb-device-profiles", KB, "Which servers each device role may talk to", False),
    ("kb-manuals", KB, "Short paraphrased controller manual facts", False),
    ("kb-regulations", KB, "Short paraphrased food-temperature and NIS2 facts", False),
    ("kb-baselines", KB, "What is normal for the Act 2 tiles, with provenance", False),
    (".alerts-security.alerts-default", PRODUCED, "Alerts of the two detection rules", True),
    ("cc-hunt-findings", PRODUCED, "Findings of the scheduled hunting agent", True),
]

# The Act 3 question, word for word the same for every place: only the FROM changes.
QUESTION = ('FROM {src} | WHERE event.action == "logged-in" AND CIDR_MATCH(TO_IP(source.ip), "203.0.113.0/24") '
            "| STATS first_seen = MIN(@timestamp), logins = COUNT(*) BY store = retail.store.id | SORT first_seen | LIMIT 20")
PLACES = [("Live index", INDEXED, "logs-coldchain.audit-default"), ("Frozen tier", FROZEN, "cc-history-audit"),
          ("Raw files in S3", RAW, "raw_store_audit")]


def _ts(v):
    return v if v else None


def catalog(fed: Es) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for src, tier, what, timed in SOURCES:
        q = f"FROM {src} | STATS rows = COUNT(*)" + (", first_seen = MIN(@timestamp), last_seen = MAX(@timestamp)" if timed else "")
        t = time.time()
        try:
            res, _ = fed.esql(q)
            vals = res["values"][0] if res["values"] else [0, None, None]
        except SystemExit as e:  # a source that does not exist yet is listed as empty, not fatal
            print(f"  {src}: {str(e)[:120]}", file=sys.stderr)
            vals = [0, None, None]
        n, first, last = vals[0], (vals[1] if timed else None), (vals[2] if timed else None)
        days = None
        if first and last:
            days = max(1, round((datetime.fromisoformat(last.replace("Z", "+00:00")) - datetime.fromisoformat(first.replace("Z", "+00:00"))).total_seconds() / 86400))
        rows.append({"source": src, "tier": tier, "tier_order": TIER_ORDER[tier], "what": what, "ask_with": f"FROM {src}",
                     "rows": n, "first_seen": _ts(first), "last_seen": _ts(last), "days": days, "measured_at": now})
        print(f"  {src:36} {n:>12,} rows in {time.time() - t:5.1f} s", flush=True)
    return rows


def moment(fed: Es) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for i, (place, tier, src) in enumerate(PLACES):
        res, secs = fed.esql(QUESTION.format(src=src))
        stores = [str(r[2]) for r in res["values"]]  # columns: first_seen, logins, store
        rows.append({"order": i + 1, "place": place, "tier": tier, "ask_with": f"FROM {src}", "seconds": round(secs, 2),
                     "stores_found": len(res["values"]), "answer": ", ".join(stores) if stores else "nothing: the history is not here",
                     "measured_at": now})
        print(f"  {place:16} {secs:6.1f} s  {len(res['values'])} stores {stores}", flush=True)
    return rows


def load(es, index: str, rows: list[dict], lookup: bool) -> None:
    if es.indices.exists(index=index):
        es.indices.delete(index=index)
    keyword = {"type": "keyword"}
    props = {"measured_at": {"type": "date"}}
    if index == "kb-sources":
        props |= {"source": keyword, "tier": keyword, "tier_order": {"type": "integer"}, "what": keyword, "ask_with": keyword,
                  "rows": {"type": "long"}, "first_seen": {"type": "date"}, "last_seen": {"type": "date"}, "days": {"type": "integer"}}
    else:
        props |= {"order": {"type": "integer"}, "place": keyword, "tier": keyword, "ask_with": keyword, "seconds": {"type": "float"},
                  "stores_found": {"type": "integer"}, "answer": keyword}
    es.indices.create(index=index, settings={"index.mode": "lookup"} if lookup else {}, mappings={"properties": props})
    helpers.bulk(es, ({"_index": index, "_source": r} for r in rows), refresh="wait_for")
    print(f"{index}: {len(rows)} rows")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="?", choices=["all", "catalog", "moment"], default="all")
    what = ap.parse_args(argv).what
    es, fed = client(), Es()
    if what in ("all", "catalog"):
        print("catalog:")
        load(es, "kb-sources", catalog(fed), lookup=True)
    if what in ("all", "moment"):
        print("the same question, three places:")
        load(es, "cc-esql-moment", moment(fed), lookup=False)


if __name__ == "__main__":
    main()
