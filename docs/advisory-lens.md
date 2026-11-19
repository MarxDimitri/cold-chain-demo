# The advisory lens: ask the endpoints (Osquery) and check them against a BSI warning

Hypothetical, synthetic. The advisory is real; the answers of the stores are generated.

## The story in 30 seconds

On 2026-11-18 the BSI warned about a critical flaw in OpenJDK ("Java4Shell", CVE-2026-114938, BITS-H 2026-306673-1032, TLP:CLEAR). Nobody has logs
that say which store runs which Java on which CPU. Elastic Agent is on the machines, so the SOC (or its agent) asks them directly with an Osquery live
query. Within seconds: 14 devices are affected, 2 are mitigated by a JVM flag, 36 of 40 answered and four hosts (S12 and S16) are silent, which means
unknown, not safe. S07 and S11 (hit stores) have an affected device; S19 (also hit) does not. The agent says so: the advisory is an **exposure**,
not the cause. BSI knows of no attacks, and the data does not say how the attacker got in.

## What is in the demo

| Piece | Where |
|---|---|
| The advisory as facts (paraphrased, one row per Java major version) | `kb-advisories`, `coldchain/osquery.py` `advisory_rows()` |
| Live query answers: Java runtime, CPU flag, JVM command line, in the shape of Osquery Manager results | `logs-osquery_manager.result-default` (dataset `osquery_manager.result`) |
| Who answers: the back-office POS PC and the store server of every store (40); the POS lanes and the system managers are appliances without an agent; S12 and S16 are offline | `coldchain/osquery.py` |
| When: the replay answers the live query at T0 + 3 minutes; `make osquery` answers it on demand | `coldchain/replay.py` |
| Agent tools `cc_vulnerable_assets` and `cc_osquery_coverage`; hunt finding `vulnerable-runtime:estate` | `coldchain/agent.py`, `coldchain/hunt.py` |
| Where it shows: the agent (Act 4: tools, finding and its answer); Act 5 has no panel for it | `coldchain/dashboards.py` `pos()` |

A device is **affected** when its Java version is inside the affected range of the advisory row for its major version and its CPU has AVX-512 VBMI;
**mitigated** when a JVM flag of the advisory (`-XX:-UseBASE64Intrinsics`, `-XX:UseAVX=2`) is on its command line. Thresholds come from `kb-advisories`, not from the query.

## Honest limits (say them)

- Osquery live queries need Fleet-managed agents that check in to Fleet Server: a second channel next to the S3 data path. Standalone agents cannot do it.
  Offline agents do not answer; the demo shows the coverage (36 of 40).
- Which osquery table exposes the CPU flag on a given POS platform has to be tested on real hardware. The SQL in the results is illustrative.
- The docs do not confirm an API for the agent to launch a live query on Serverless; here the answers arrive on a schedule (T0 + 3 minutes or `make osquery`).
- Source: BSI BITS-H 2026-306673-1032, version 1.0 of 18.11.2026. Paraphrased; no text of the PDF is stored.
