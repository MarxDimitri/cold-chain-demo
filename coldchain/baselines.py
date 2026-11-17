"""kb-baselines: what is normal for the Act 1 tiles, as knowledge-base rows with provenance (like the thresholds).

    python -m coldchain.baselines          # measure from the cluster, write elastic/lookup/kb-baselines.ndjson, load the index

kind "rate": a count per day, scaled to the picker window by the dashboard. kind "level": a count that does not scale.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from elasticsearch import helpers

from .chain import LOOKUP_DIR
from .elastic import CUSTOM_MAPPINGS, client


# When a tile turns amber or red, for a picker window of 24 hours (colour steps are absolute numbers). "up": bad when high; "down": bad
# when low. Parameter changes: amber above 1.5 times the daily mean, red above the largest day seen in the 24 days of history (13).
THRESHOLDS = {
    "parameter-changes": {"direction": "up", "amber": 9, "red": 14},
    "cabinets-reporting": {"direction": "down", "red_below": 480},
    "cabinets-warm": {"direction": "up", "amber": 1, "red": 4},
    "open-alerts": {"direction": "up", "red": 1},
}


def measure(es) -> list[dict]:
    r = es.esql.query(query='''FROM logs-coldchain.audit-default | WHERE event.action == "parameter-change" AND CIDR_MATCH(source.ip, "198.51.100.0/24")
| STATS n = COUNT(*) BY d = BUCKET(@timestamp, 1 day) | STATS days = COUNT(*), per_day = AVG(n), low = MIN(n), high = MAX(n)''',
                      format="json")
    days, per_day, low, high = r["values"][0]
    cabs = es.esql.query(query="FROM kb-assets | WHERE coldchain.application IS NOT NULL | STATS n = COUNT(*)",
                         format="json")["values"][0][0]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def row(key, kind, value, unit, basis, label):
        return {"kb": {"key": key, "label": label,
                       "baseline": {"kind": kind, "value": round(float(value), 1), "unit": unit, "basis": basis, "measured_on": today},
                       "thresholds": THRESHOLDS[key]}}

    return [
        row("parameter-changes", "rate", per_day, "changes per day",
            f"measured: mean of {days} days of indexed audit (range {low} to {high} a day), contractor changes only", "Parameter changes"),
        row("cabinets-reporting", "level", cabs, "cabinets", "kb-assets: 20 stores x 24 cabinets", "Cabinets reporting"),
        row("cabinets-warm", "level", 0, "cabinets",
            "measured: 0 false alarms of the warm-without-defrost logic over the 7 days of indexed telemetry (a measurement of the full version over 34 days: docs/decisions.md)", "Cabinets warm, no defrost"),
        row("open-alerts", "level", 0, "alerts", "design: no alerts in normal operation", "Open alerts"),
    ]


def load(es, rows: list[dict]) -> None:
    path = LOOKUP_DIR / "kb-baselines.ndjson"
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
    if es.indices.exists(index="kb-baselines"):
        es.indices.delete(index="kb-baselines")
    es.indices.create(index="kb-baselines", settings={"index.mode": "lookup"},
                      mappings={"dynamic_templates": CUSTOM_MAPPINGS["dynamic_templates"] + [
                          {"kb_strings": {"path_match": "kb.*", "match_mapping_type": "string", "mapping": {"type": "keyword"}}}]})
    helpers.bulk(es, ({"_index": "kb-baselines", "_source": r} for r in rows), refresh="wait_for")
    for r in rows:
        b = r["kb"]["baseline"]
        print(f"kb-baselines: {r['kb']['key']}: {b['value']} {b['unit']} ({b['kind']}), {b['basis']}")


if __name__ == "__main__":
    es = client()
    load(es, measure(es))
