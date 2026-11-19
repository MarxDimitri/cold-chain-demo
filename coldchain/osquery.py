"""Osquery live-query results (synthetic) and the BSI advisory they are checked against.

    python -m coldchain.osquery run       # the SOC asks the endpoints now: index one set of results (a live query response)
    python -m coldchain.osquery plan      # print who answers and what they run

Elastic Agent with the Osquery Manager integration can answer "which Java runtime runs here, on which CPU, with which JVM flags?" on demand,
also for machines that ship no logs. The stores of this demo are simulated, so the answers are generated here in the shape of Osquery
Manager results (`logs-osquery_manager.result`: `action_id`, `action_data`, `osquery.*`). Hypothetical, synthetic. Which osquery tables
expose the CPU flag on a given POS platform has to be tested on real hardware.

The advisories are data: `config/advisories.yaml`, loaded into `kb-advisories` (the first entry is the BSI warning on OpenJDK "Java4Shell",
BITS-H 2026-306673-1032). Nothing in the agent's prompts names a vulnerability. Only the agent-capable devices answer: the back-office POS PC and the store server of every store (the POS lanes and the system
manager are appliances without an agent). Two stores are offline and do not answer.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import yaml

from .chain import CONFIG_DIR

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
    "software": "SELECT name, version FROM deb_packages / rpm_packages / programs  -- or the release file of a runtime; the installed software of the device",
    "cpu": "SELECT feature FROM cpuid  -- or the flags line of /proc/cpuinfo; platform support to be tested",
    "process": "SELECT name, pid, cmdline FROM processes",
}


def version_num(version: str) -> int:
    """A dotted version (up to four parts) as one number that sorts like the version: 17.0.21.1 -> 17000021001."""
    parts = [int(p) for p in version.split(".")][:4]
    parts += [0] * (4 - len(parts))
    return parts[0] * 10**9 + parts[1] * 10**6 + parts[2] * 10**3 + parts[3]


def advisory_rows() -> list[dict]:
    """`config/advisories.yaml` as rows of kb-advisories: one row per advisory, product and release line (the join keys are osquery.name and osquery.branch)."""
    rows = []
    for adv in yaml.safe_load((CONFIG_DIR / "advisories.yaml").read_text())["advisories"]:
        args = list(adv.get("mitigation_args") or [])[:2] + [None, None]
        for br in adv["branches"]:
            fact = {k: adv[k] for k in ("id", "name", "source", "published", "cvss_v4", "cvss_v31", "criticality", "product", "process", "flaw",
                                        "hardware", "condition", "exploitation", "workaround", "mitigation") if k in adv}
            fact |= {"affected_from": br["affected_from"], "fixed_in": br["fixed_in"],
                     "affected_from_num": version_num(br["affected_from"]), "fixed_in_num": version_num(br["fixed_in"])}
            if adv.get("requires_cpu_flag"):
                fact["requires_cpu_flag"] = adv["requires_cpu_flag"]
            if args[0]:
                fact["mitigation_arg_1"] = args[0]
            if args[1]:
                fact["mitigation_arg_2"] = args[1]
            rows.append({"kb": {"key": f"{adv['id']}:{adv['product']}:{br['branch']}"}, "advisory": fact,
                         "osquery": {"name": adv["product"], "branch": br["branch"]}})
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
    """The answers of one live query run: (store, NDJSON line) for every device that answers. Offline stores stay silent.

    Three generic queries per device: the installed software (name, version), the CPU flags and the process command lines.
    """
    lines = []
    for d in plan():
        if d["store"] in OFFLINE:
            continue
        major, update, sub = _parse(d["version"])
        base = {"@timestamp": ts_iso, "event": {"kind": "event", "dataset": "osquery_manager.result", "category": ["host"]},
                "action_id": action_id, "host": {"name": d["host"]},
                "agent": {"id": f"agent-{d['host'].lower()}", "type": "elastic-agent"},
                "retail": {"store": {"id": d["store"]}, "device": {"role": d["role"]}}, "labels": {"synthetic": "true"}}
        flags = "fpu sse4_2 avx2 bmi2" + (" avx512f avx512bw avx512vbmi" if d["avx512"] else "")
        app = "posclient" if d["role"] == "pos-backoffice" else "storeserver"
        docs = [
            ("software", {"name": "OpenJDK", "version": d["version"], "branch": str(major), "version_num": version_num(d["version"]),
                          "path": f"/usr/lib/jvm/openjdk-{major}/release"}),
            ("cpu", {"cpu_flags": flags}),
            ("process", {"proc": "java", "pid": "2417", "cmdline": f"java -Xmx2g {d['flag']} -jar {app}.jar".replace("  ", " ")}),
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


def list_advisories_query() -> str:
    """The advisories the knowledge base holds, newest first (one row per advisory): id, name, product, published, severity, exploitation, source."""
    return ("FROM kb-advisories | STATS name = MAX(advisory.name), product = MAX(advisory.product), published = MAX(advisory.published), "
            "cvss_v4 = MAX(advisory.cvss_v4), criticality = MAX(advisory.criticality), flaw = MAX(advisory.flaw), "
            "exploitation = MAX(advisory.exploitation), workaround = MAX(advisory.workaround), source = MAX(advisory.source) BY id = advisory.id "
            "| SORT published DESC")


def exposure_query(advisory: str = "?advisory", keep: str = "") -> str:
    """Per answering device: the installed software, CPU flags and process command lines of the latest live query checked against ONE advisory.

    Everything advisory-specific comes from the rows of kb-advisories (product, release line, affected from, fixed in, required CPU flag,
    mitigation arguments); the query names no product. The join key is the advisory id plus the product and release line of the device's software,
    so a device whose software the advisory does not list simply has no row. A device is affected when its software is a product of the advisory, its version is
    in [affected from, fixed in) and, if the advisory requires a CPU flag, the device has it; mitigated when a mitigation argument is on
    a process command line. Devices whose software the advisory does not list are not affected.
    """
    return (f"{LATEST} "
            '| STATS ver = VALUES(osquery.version) WHERE action_data.id == "software", num = MAX(osquery.version_num) WHERE action_data.id == "software", '
            'prod = VALUES(osquery.name) WHERE action_data.id == "software", br = VALUES(osquery.branch) WHERE action_data.id == "software", '
            'flags = VALUES(osquery.cpu_flags) WHERE action_data.id == "cpu", cmds = VALUES(osquery.cmdline) WHERE action_data.id == "process" '
            "BY host = host.name, store = retail.store.id, role = retail.device.role "
            "| EVAL osquery.name = MV_FIRST(prod), osquery.branch = MV_FIRST(br), software = MV_FIRST(ver), cpu = MV_CONCAT(flags, \" \"), cmd = MV_CONCAT(cmds, \" \") "
            f'| EVAL kb.key = CONCAT({advisory}, ":", osquery.name, ":", osquery.branch) | LOOKUP JOIN kb-advisories ON kb.key '

            "| EVAL in_range = num >= advisory.affected_from_num AND num < advisory.fixed_in_num, "
            "cpu_ok = advisory.requires_cpu_flag IS NULL OR CONTAINS(cpu, advisory.requires_cpu_flag), "
            "mitigated = (advisory.mitigation_arg_1 IS NOT NULL AND CONTAINS(cmd, advisory.mitigation_arg_1)) "
            "OR (advisory.mitigation_arg_2 IS NOT NULL AND CONTAINS(cmd, advisory.mitigation_arg_2)) "
            '| EVAL status = CASE(in_range IS NULL OR in_range == false, "not affected: version not in the advisory", cpu_ok == false, '
            '"not affected: CPU condition not met", mitigated, "affected, mitigated", "affected"), '
            'cpu_condition = CASE(advisory.requires_cpu_flag IS NULL, "none", cpu_ok, "met", "not met") '
            + (keep or "| SORT status, store, role | KEEP store, host, role, software, cpu_condition, status"))


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
