"""Detection rules for Act 2 (CLAUDE.md 8.2): ES|QL rules over the indexed streams, thresholds from the knowledge base.

    python -m coldchain.rules push [--enable]     # create or replace (disabled unless --enable)
    python -m coldchain.rules preview RULE_ID END [N]   # dry-run N executions ending at END (ISO time), one per minute
    python -m coldchain.rules delete

Rule 1 reads the documented maximum and the curated normal from `kb-controller-limits` (a join, not a constant).
Rule 2 compares the air with the nominal setpoint of the cabinet type. That nominal is the chain's -24 / +2 C, still
a constant here until `kb-thresholds` exists (CLAUDE.md 8.2, not built). Rules 3 to 5 are not built.

Alerts are grouped by store so each carries `retail.store.id` (the Act 3 timeline joins on it).
"""
from __future__ import annotations

import argparse
import json
import sys

from .dashboards import NOMINAL, kibana

RULES = {
    "coldchain-limits": {
        "name": "Cold chain: controller setting outside documented normal",
        "description": "A parameter change outside the curated normal range in kb-controller-limits; the documented maximum "
                       "is a stronger verdict. Synthetic data.",
        "query": """FROM logs-coldchain.audit-*
| WHERE event.action == "parameter-change"
| LOOKUP JOIN kb-assets ON device.id
| LOOKUP JOIN kb-controller-limits ON device.model.identifier, coldchain.parameter.code, coldchain.application
| WHERE coldchain.parameter.value.new > kb.expected.max OR coldchain.parameter.value.new < kb.expected.min
| EVAL kb.verdict = CASE(coldchain.parameter.value.new >= kb.doc.max, "at documented maximum", "outside normal")
| STATS cabinets = COUNT_DISTINCT(device.id), first_seen = MIN(@timestamp), sources = VALUES(source.ip), users = VALUES(user.name),
        refs = VALUES(kb.doc.ref)
    BY retail.store.id, coldchain.parameter.code, coldchain.parameter.value.new, kb.verdict""",
        "interval": "1m", "from": "now-6m", "risk_score": 99, "severity": "critical",
        "tags": ["coldchain", "act2", "synthetic"],
    },
    "coldchain-warm-no-defrost": {
        "name": "Cold chain: cabinet warm for too long, no defrost",
        "description": "At least 3 of the last 10 minutes more than 2 K above the nominal temperature, defrost relay off, no "
                       "relay in the last hour. The net for causes the setpoint rule does not see. Synthetic data.",
        "query": f"""FROM metrics-coldchain.case-*
| EVAL warm = coldchain.case.temperature.air - {NOMINAL}
| STATS late_warm = COUNT(*) WHERE @timestamp >= NOW() - 10 minutes AND warm > 2 AND coldchain.case.defrost.active == false,
        relay_on = COUNT(*) WHERE coldchain.case.defrost.active == true,
        peak = MAX(warm) BY device.id, retail.store.id
| WHERE late_warm >= 3 AND relay_on == 0
| STATS cabinets = COUNT(*), warmest = ROUND(MAX(peak), 1), devices = VALUES(device.id) BY retail.store.id""",
        "interval": "1m", "from": "now-1h", "risk_score": 73, "severity": "high",
        "tags": ["coldchain", "act2", "synthetic"],
    },
}


def body(rule_id: str, enabled: bool) -> dict:
    r = RULES[rule_id]
    # One alert per store for 15 minutes, not one per minute while the lookback still sees the same change.
    suppress = {"group_by": ["retail.store.id"], "duration": {"value": 15, "unit": "m"}, "missing_fields_strategy": "suppress"}
    return {"rule_id": rule_id, "type": "esql", "language": "esql", "enabled": enabled, "to": "now", "threat": [],
            "alert_suppression": suppress, **r}


def push(enable: bool) -> None:
    url, s = kibana()
    for rid in RULES:
        r = s.post(f"{url}/api/detection_engine/rules", json=body(rid, enable), timeout=60)
        if r.status_code == 409:
            r = s.put(f"{url}/api/detection_engine/rules", json=body(rid, enable), timeout=60)
        print(rid, r.status_code, r.text[:200] if r.status_code >= 400 else "ok")


def preview(rid: str, end: str, n: int) -> None:
    url, s = kibana()
    b = body(rid, True)
    b.pop("enabled")
    r = s.post(f"{url}/api/detection_engine/rules/preview", json={**b, "invocationCount": n, "timeframeEnd": end}, timeout=600)
    d = r.json()
    print(rid, r.status_code, "alerts:", len(d.get("alerts", []) or []) if isinstance(d, dict) else d)
    for log in d.get("logs", []):
        for k in ("errors", "warnings"):
            for m in log.get(k, []):
                print(" ", k, m[:300])
    if r.status_code >= 400:
        print(r.text[:800])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["push", "preview", "delete"])
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--enable", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "push":
        return push(a.enable)
    if a.cmd == "preview":
        return preview(a.rest[0], a.rest[1], int(a.rest[2]) if len(a.rest) > 2 else 1)
    url, s = kibana()
    for rid in RULES:
        print(rid, s.delete(f"{url}/api/detection_engine/rules", params={"rule_id": rid}, timeout=60).status_code)


if __name__ == "__main__":
    main()
