"""Osquery live-query results (synthetic) and the BSI advisory they are checked against.

    python -m coldchain.osquery run       # the SOC asks the endpoints now: index one set of results (a live query response)
    python -m coldchain.osquery plan      # print who answers and what they run

Elastic Agent with the Osquery Manager integration can answer "which Java runtime runs here, on which CPU, with which JVM flags?" on demand,
also for machines that ship no logs. The stores of this demo are simulated, so the answers are generated here in the shape of Osquery
Manager results (`logs-osquery_manager.result`: `action_id`, `action_data`, `osquery.*`). Hypothetical, synthetic. Which osquery tables
expose the CPU flag on a given POS platform has to be tested on real hardware.

The advisory is BSI BITS-H 2026-306673-1032 (18.11.2026, TLP:CLEAR) on OpenJDK "Java4Shell", CVE-2026-114938, paraphrased in `advisory_rows()`.
Only the agent-capable devices answer: the back-office POS PC and the store server of every store (the POS lanes and the system
manager are appliances without an agent). Two stores are offline and do not answer.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

SOURCE = "BSI BITS-H 2026-306673-1032, 18.11.2026 (TLP:CLEAR), paraphrased"
OFFLINE = {"S12", "S16"}  # their agents do not check in

# Back-office POS PC: Java version of the POS client; AVX-512 VBMI present?; JVM flag set?
BO = {
    "affected": {"S01": "21.0.5", "S03": "17.0.10", "S05": "17.0.8", "S07": "17.0.8", "S09": "17.0.10", "S11": "17.0.12", "S14": "21.0.5"},
    "mitigated": {"S18": "17.0.8"},            # affected version and CPU, but -XX:UseAVX=2 is set
    "patched": {"S02": "17.0.21.1", "S06": "21.0.13.1"},   # AVX-512, fixed Java
    "no_avx512": {"S04": "17.0.8", "S08": "17.0.10", "S10": "21.0.5", "S13": "17.0.8", "S15": "17.0.10", "S17": "17.0.8", "S19": "17.0.12", "S20": "11.0.22"},
    "offline": {"S12": "17.0.8", "S16": "17.0.8"},   # the agent does not check in: not known
}
# Store server (a Java application server): same four groups
SRV = {
    "affected": {"S02": "17.0.9", "S04": "17.0.9", "S07": "17.0.9", "S08": "17.0.9", "S10": "17.0.9", "S15": "17.0.9", "S17": "17.0.9"},
    "mitigated": {"S13": "17.0.9"},            # -XX:-UseBASE64Intrinsics
    "patched": {"S01": "17.0.21.1", "S05": "21.0.13.1"},
    "no_avx512": {"S03": "17.0.9", "S06": "17.0.9", "S09": "17.0.9", "S11": "17.0.9", "S14": "17.0.9", "S18": "17.0.9", "S19": "17.0.9", "S20": "11.0.22"},
    "offline": {"S12": "17.0.9", "S16": "17.0.9"},
}

QUERIES = {
    "java_runtime": "SELECT name, version, path FROM file JOIN (parsed from the JDK release file) WHERE path LIKE '%/jvm/%/release'  -- or deb_packages / rpm_packages / programs",
    "cpu_avx512": "SELECT feature, value FROM cpuid WHERE feature = 'avx512vbmi'  -- platform support to be tested",
    "jvm_cmdline": "SELECT pid, cmdline FROM processes WHERE name = 'java'",
}


def advisory_rows() -> list[dict]:
    """The advisory as facts, one row per Java major version (affected from, fixed in), paraphrased from the BSI warning."""
    common = {"kb": {"source": SOURCE}, "advisory": {
        "id": "CVE-2026-114938", "name": "Java4Shell", "cvss_v4": 9.2, "cvss_v31": 8.1, "criticality": "2 / yellow",
        "published": "2026-11-18",
        "flaw": "memory corruption in the optimised Base64 decoder of OpenJDK (negative length on padding)",
        "hardware": "only x86-64 with AVX-512 VBMI (Intel Xeon Ice Lake and later, AMD Zen 4 and later); ARM64 is not affected",
        "condition": "the application passes attacker-controlled Base64 input to the decoder, for example HTTP Basic or SAML tokens",
        "exploitation": "denial of service is easy, remote code execution is hard; no public exploit and no known attack, first attempts seen by Greynoise",
        "workaround": "start the JVM with -XX:-UseBASE64Intrinsics or -XX:UseAVX=2, then restart it",
        "mitigation": "update to a fixed OpenJDK and restart the Java processes; restrict access to Java applications reachable from the internet"}}
    rows = []
    for major, min_update, fixed_update, fixed_sub in ((17, 6, 21, 1), (21, 0, 13, 1), (25, 0, 5, 1), (27, 0, 1, 1)):
        r = json.loads(json.dumps(common))
        r["kb"]["key"] = f"CVE-2026-114938:{major}"
        r["osquery"] = {"major": major}
        r["advisory"].update({"affected_min_update": min_update, "fixed_update": fixed_update, "fixed_sub": fixed_sub,
                              "fixed_version": f"{major}.0.{fixed_update}.{fixed_sub}"})
        rows.append(r)
    return rows


def _parse(version: str) -> tuple[int, int, int]:
    parts = [int(p) for p in version.split(".")]
    return parts[0], parts[2] if len(parts) > 2 else 0, parts[3] if len(parts) > 3 else 0


def plan() -> list[dict]:
    """Per device: store, host, role, java version, avx512, mitigation flag (empty for offline stores)."""
    out = []
    for role, host_suffix, table in (("pos-backoffice", "POS-BO-01", BO), ("store-server", "SRV", SRV)):
        for group, stores in table.items():
            for sid, version in stores.items():
                out.append({"store": sid, "host": f"{sid}-{host_suffix}", "role": role, "version": version, "group": group,
                            "avx512": group in ("affected", "mitigated", "patched"),
                            "flag": {"mitigated": "-XX:UseAVX=2" if role == "pos-backoffice" else "-XX:-UseBASE64Intrinsics"}.get(group, "")})
    return sorted(out, key=lambda d: (d["store"], d["role"]))


def results(ts_iso: str, action_id: str) -> list[tuple[str, str]]:
    """The answers of one live query run: (store, NDJSON line) for every device that answers. Offline stores stay silent."""
    lines = []
    for d in plan():
        if d["store"] in OFFLINE:
            continue
        major, update, sub = _parse(d["version"])
        base = {"@timestamp": ts_iso, "event": {"kind": "event", "dataset": "osquery_manager.result", "category": ["host"]},
                "action_id": action_id, "host": {"name": d["host"]},
                "agent": {"id": f"agent-{d['host'].lower()}", "type": "elastic-agent"},
                "retail": {"store": {"id": d["store"]}, "device": {"role": d["role"]}}, "labels": {"synthetic": "true"}}
        docs = [
            ("java_runtime", {"name": "OpenJDK", "version": d["version"], "path": f"/usr/lib/jvm/openjdk-{major}/release",
                              "major": major, "update": update, "sub": sub}),
            ("cpu_avx512", {"feature": "avx512vbmi", "value": "1" if d["avx512"] else "0", "avx512vbmi": 1 if d["avx512"] else 0}),
            ("jvm_cmdline", {"pid": "2417", "cmdline": f"java -Xmx2g {d['flag']} -jar {'posclient' if d['role'] == 'pos-backoffice' else 'storeserver'}.jar".replace("  ", " ")}),
        ]
        for qid, cols in docs:
            doc = {**base, "action_data": {"id": qid, "query": QUERIES[qid]}, "osquery": cols}
            lines.append((d["store"], json.dumps(doc, separators=(",", ":"))))
    return lines


def run() -> None:
    """Index one set of results through the ingest pipeline: the response to a live query launched now."""
    from elasticsearch import helpers

    from .elastic import PIPELINE, client
    es = client()
    now = datetime.now(timezone.utc)
    action_id = f"live-{now:%Y%m%d%H%M%S}"
    docs = [{"_op_type": "create", "_index": "logs-osquery_manager.result-default", "pipeline": PIPELINE, "_source": json.loads(line)}
            for _, line in results(now.strftime("%Y-%m-%dT%H:%M:%SZ"), action_id)]
    n, _ = helpers.bulk(es, docs, refresh="wait_for")
    asked = len([d for d in plan()])
    answered = len({json.loads(line)["host"]["name"] for _, line in results(now.isoformat(), action_id)})
    print(f"live query {action_id}: {answered} of {asked} agent-capable devices answered ({n} result rows); offline: {sorted(OFFLINE)}")


# --- ES|QL over the answers and the advisory -----------------------------------------------------------------------------------

LATEST = ("FROM logs-osquery_manager.result-default | INLINE STATS newest = MAX(@timestamp) "
          "| WHERE @timestamp >= newest - 30 minutes")  # the most recent live query run


def vulnerable_query(keep: str = "") -> str:
    """Per answering device: its Java runtime, CPU and JVM flags checked against the advisory (rows of kb-advisories).

    A device is affected when its Java is inside the affected range of the advisory for its major version (from the advisory row, not a
    constant) and its CPU has AVX-512 VBMI; it is mitigated when a JVM flag of the advisory is set. Java versions the advisory does not
    list (for example 11) are not affected.
    """
    return (f"{LATEST} "
            '| STATS major = MAX(osquery.major) WHERE action_data.id == "java_runtime", upd = MAX(osquery.update) WHERE action_data.id == "java_runtime", '
            'sub = MAX(osquery.sub) WHERE action_data.id == "java_runtime", vers = VALUES(osquery.version) WHERE action_data.id == "java_runtime", '
            'avx = MAX(osquery.avx512vbmi) WHERE action_data.id == "cpu_avx512", '
            'flagged = COUNT(*) WHERE action_data.id == "jvm_cmdline" AND (osquery.cmdline LIKE "*-XX:-UseBASE64Intrinsics*" OR osquery.cmdline LIKE "*-XX:UseAVX=2*") '
            "BY host = host.name, store = retail.store.id, role = retail.device.role "
            "| EVAL osquery.major = major | LOOKUP JOIN kb-advisories ON osquery.major "
            "| EVAL in_range = upd >= advisory.affected_min_update AND (upd < advisory.fixed_update OR (upd == advisory.fixed_update AND sub < advisory.fixed_sub)), "
            "java = MV_FIRST(vers) "
            '| EVAL status = CASE(in_range IS NULL OR in_range == false, "not affected: Java version", avx == 0, "not affected: CPU without AVX-512 VBMI", '
            'flagged > 0, "affected, mitigated by a JVM flag", "affected"), '
            'avx512 = CASE(avx == 1, "yes", "no") '
            + (keep or "| SORT status, store, role | KEEP store, host, role, java, avx512, status"))


def coverage_query() -> str:
    """How many of the agent-capable devices (back-office POS PC and store server of every store) answered the last live query, and who is silent."""
    return (f"FROM ({LATEST} | STATS rows = COUNT(*) BY host = host.name | EVAL answered = 1), "
            '(FROM kb-assets | WHERE retail.device.role IN ("pos-backoffice", "store-server") | EVAL host = device.id, expected = 1 | KEEP host, expected) '
            "| STATS answered = MAX(answered), expected = MAX(expected) BY host "
            "| STATS expected_hosts = COUNT(*), answered_hosts = COUNT(*) WHERE answered == 1, silent = VALUES(host) WHERE answered IS NULL "
            '| EVAL silent_hosts = MV_CONCAT(MV_SORT(silent), ", ")')


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if cmd == "run":
        run()
        return
    for d in plan():
        silent = " (offline)" if d["store"] in OFFLINE else ""
        print(f"{d['host']:16} {d['role']:15} java {d['version']:10} avx512={int(d['avx512'])} {d['group']:10} {d['flag']}{silent}")


if __name__ == "__main__":
    main()
