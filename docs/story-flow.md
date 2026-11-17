# Story flow v3: blip, history, the TV box, the agentic SOC (2026-11-11)

The main path is four beats. The earlier acts 2, 3, 6 and 7 stay built and become an optional appendix (detection by rules, the
hunt for the next stores, the response). The evidence dashboard (old Act 4) was removed. Dashboard names are "CC Act 1" to "CC Act 5". Everything is synthetic and fictional.

| Beat | Screen | What the audience sees | Source |
|---|---|---|---|
| Act 0. The realms you usually do not watch | `coldchain-act0-sources` | The opener: every dataset in five tiers (live index, frozen tier, raw files in S3, knowledge base, what the demo produces), how big and how far back each goes, and the same `FROM` line for each. The point: one platform, one language (ES\|QL), so you can ask questions nobody modelled in advance. | catalog `kb-sources` |
| Act 1. One cabinet, the contractor's view | `coldchain-act1a-cabinet` (S07-C05), picker "Last 24 hours" | What a contractor sees: one cabinet, its air temperature and setpoint, its changes. The setpoint jumps to +50 and the cabinet warms: one odd controller, no pattern, no alert. Same indexed data as 1b, filtered to one device. | indexed `detect/` |
| Act 2. The same blip across the whole estate | `coldchain-act1b-estate`, picker "Last 24 hours", live `make demo` | Central IT's view of the same moment, plus an inventory of what it knows (cabinets, signage, TV boxes, cameras, routers; only some report live). Every tile is green, then 46 setpoint changes in 3 stores and nobody alerted. In the table: S11 and S19 changed from `203.0.113.47`, **S07 from `10.7.0.41`, an address inside the store**. | indexed `detect/` |
| Act 3a. The history nobody ingested | `coldchain-act5a-history` | A year of raw audit read in place (about 700k events, never ingested). The same internet address logged in to **S07 126 days ago, S11 84 days ago, S19 49 days ago**: success, no changes. They are the three stores hit at T0. | federation (experimental), `raw/` |
| Act 3b. The history ingested at a predictable price (with "one question, three places") | `coldchain-act5b-history-frozen` | The same year of audit ingested once into an index kept on the frozen tier (searchable snapshot): about 1 s the first query, 0.1 s after, against about 75 s in place. You choose: read in place (nothing ingested) or go faster on a fixed-size frozen node. | indexed, frozen tier |
| Act 4. Edge devices on no one's radar (epilogue) | `coldchain-epilogue-edge`, picker 2026-10-22 to 2026-11-11 | In the three weeks before the blip a TV box in the S07 staff room pulled 4.6 GB over 9 nights from `models.example-hub.net`, signage CPU and storage changed, the plug power doubled, and from 2026-11-09 the TV box called the system manager on tcp/80 for the first time. At T0 that same box writes S07's setpoints. | indexed summaries + federated TLS (hypothetical) |
| Act 5. Hunting agent, the agent that keeps looking | `coldchain-hunt-findings` (AlertZero pattern, preview) | Without anyone asking, a workflow runs the SOC agent every 30 minutes over live data, the raw history, device profiles and exposure, and records findings with evidence and a proposed action. This is the bridge to the security product: rules detect, the agent hunts, and Elastic's AlertZero Watches do the same on a deployment that offers them. | `cc-hunt-findings` |
| Act 5 (asked). The agentic SOC | Kibana > Agent Builder, agent "Cold-chain SOC agent (preview)" | One question, one agent, eight tools. It tells the story in order (blip, history, store, next stores), names the 7 stores still at risk and the shared contractor account, and proposes containment. It runs nothing. | all of the above |

## How it connects

- The attacker walked into S07, S11 and S19 months ago (history), reached S07's LAN through a TV box (epilogue), and at T0 changed
  setpoints from the internet (S11, S19) and from inside (S07). The blip is the effect; beats 2 and 3 are the cause.
- The knowledge base ties it together: `kb-controller-limits` says +50 is the documented maximum and far outside normal,
  `kb-device-profiles` says a TV box may not talk to the model hub, `kb-assets` knows which controllers face the internet.

## Stage script

1. `make demo` (live, real clock, uploads to S3, waits for `make restore`). It first writes and indexes a day of normal data so the dashboards start with context (about a minute), then prints `T0=...`. Open Act 1 on "Last 24 hours" with auto-refresh.
2. Acts 1 and 2: green, then the blip about 4 minutes in. Point at the two kinds of source address.
3. Act 3a (and 3b): open the history dashboard. "A year of raw store data, never ingested, one query." Say "experimental".
4. Epilogue: open the dashboard on 2026-10-22 to 2026-11-11. Say "hypothetical, synthetic".
5. Agent: ask the scripted question (`make agent-ask`, or paste it in Agent Builder). Show the tool calls, then the answer.
6. `make demo` has already enabled the rules: rule 1 alerts appear about a minute after the blip, rule 2 and the warm tile about 10 minutes after. `make restore` when you want containment (it restores by itself after 30 minutes). Afterwards `make clean-run SINCE=<start time>`.

## Agent question

"Something changed temperature setpoints in our stores. What happened, how long has the attacker been in, how did it happen
inside the store, and which stores are next?"
