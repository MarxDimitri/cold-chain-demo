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
| **The advisories as data** (paraphrased, with source): one entry per advisory, with release lines, affected-from and fixed-in versions, an optional CPU condition and mitigation arguments | `config/advisories.yaml`, loaded by `make lookups` into `kb-advisories` |
| Live query answers: installed software (name, version), CPU flags, process command lines, in the shape of Osquery Manager results | `logs-osquery_manager.result-default` (dataset `osquery_manager.result`) |
| Who answers: the back-office POS PC and the store server of every store (40); the POS lanes and the system managers are appliances without an agent; S12 and S16 are offline | `coldchain/osquery.py` |
| When: the replay answers the live query at T0 + 3 minutes; `make osquery` answers it on demand | `coldchain/replay.py` |
| Agent tools `cc_list_advisories`, `cc_advisory_exposure` (parameter: the advisory id) and `cc_osquery_coverage`; hunt finding `advisory-exposure:<id>` | `coldchain/agent.py`, `coldchain/hunt.py` |

## Open to any new advisory

The prompts of the agent and of the hunt workflow name no vulnerability, product or version (a test checks this). They say: list the advisories, check
the exposure for the ones that matter, report what the tools return. The tools read everything advisory-specific from `kb-advisories`. To add a new
one: add an entry to `config/advisories.yaml` and run `make lookups` (or `python -m coldchain.elastic lookups`). The next question and the next hunt pick it up.
A second advisory for the same software works with no change at all; an advisory for new software also needs the live query to collect that
software (the answers carry name and version of the installed software, CPU flags and process command lines). In a real estate a feed (CERT-Bund,
NVD, vendor advisories) would write the rows; the file is the demo's stand-in.

A device is **affected** when its software is a product of the advisory, its version is in [affected from, fixed in) and, if the advisory requires a
CPU flag, it has it; **mitigated** when a mitigation argument is on a process command line; devices whose software the advisory does not list are not affected.

## Honest limits (say them)

- Osquery live queries need Fleet-managed agents that check in to Fleet Server: a second channel next to the S3 data path. Standalone agents cannot do it.
  Offline agents do not answer; the demo shows the coverage (36 of 40).
- Which osquery table exposes the CPU flag on a given POS platform has to be tested on real hardware. The SQL in the results is illustrative.
- The docs do not confirm an API for the agent to launch a live query on Serverless; here the answers arrive on a schedule (T0 + 3 minutes or `make osquery`).
- Source: BSI BITS-H 2026-306673-1032, version 1.0 of 18.11.2026. Paraphrased; no text of the PDF is stored.
