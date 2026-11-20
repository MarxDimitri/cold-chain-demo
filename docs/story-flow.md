# Story flow, simplified version: six acts in 15 minutes

The path: **we search where the light is** (Act 0), a blip in one cabinet (Act 1), the same blip across the estate (Act 2), a year of
history nobody looked at (Act 3), an agent that finds a lead nobody asked for (Act 4), and the POS terminal behind it (Act 5).
Everything is synthetic and fictional. The full version (Hosted, federation, TV-box epilogue) is the git tag `v1-ech-federation-tv`.

| Time | Act | Dashboard id | What the audience sees | Source |
|---|---|---|---|---|
| 0:00 (1.5 min) | **0. The streetlight effect - we search where the light is** | `coldchain-act0-sources` (nine pages) | A dark page with a streetlight. Four switches, in this order: Security realm, Observability realm, Knowledge base realm, the light. Security lights up what a SOC usually watches (audit, flows, TLS, alerts, findings, and Endpoints, Firewalls, Identity); Observability shows cabinet telemetry, probes, POS health, trucks and the endpoint answers in the dark; the knowledge base and the full light come last. One card per source, with its size counted live from the index. | the indices (live counts), `kb-sources` |
| 1:30 (1.5 min) | **1. The blip in the Colmar store** | `coldchain-act1a-cabinet` | One cabinet (S07-C05): its setpoint goes to +50 and the air warms. One odd controller, no pattern, no alert. | indexed `detect/` |
| 3:00 (3 min) | **2. Same blip across the entire estate** | `coldchain-act1b-estate` | A map of the 20 stores (red: setpoints raised; click one to filter the page). 46 changes in 3 stores; S11 and S19 from `203.0.113.47`, **S07 from `10.7.0.41`, an address inside the store**. Rule 1 alerts about 1.5 minutes after T0. **Trucks on the map:** three frozen trucks (about EUR 98,000) are 15 to 40 minutes from the stores whose freezers are warm (`docs/logistics-story.md`). | indexed `detect/`, truck telemetry, ERP plan |
| 5:30 (2.5 min) | **3. The history nobody looked at** | `coldchain-act3-history` | A map: in the last 12 months, which stores did an unknown address (not a contractor, not a store LAN) log in to as `admin`? Red: already hit by the warming attack (S07, S11, S19, with the lead time between the first unknown login and the hit). Amber: visited, nothing changed yet, **might be next** (six stores). Grey: no unknown login. | indexed audit |
| 8:00 (3.5 min) | **4. Let the agent hunt** | `coldchain-hunt-findings` | "Nobody asked, and something is going on." The same map: each store coloured by the worst finding of the agent. Four tiles (critical and high findings, stores named, tools used, last hunt). The findings sit beside the map, grouped by kind (outside access, temperature, device behaviour, **logistics: frozen trucks heading into trouble**, exposure including **advisory exposure**), each with evidence, proposed action and the sources it combined. It proposes, it runs nothing. | `cc-hunt-findings` |
| 11:30 (3 min) | **5. The POS is now having a PhD and nobody watched it** | `coldchain-pos-evidence` | The same page shape: a map of every store's back-office POS PC (S07 red: it reached the refrigeration controller), four cards (4.4 GB received against 137 MB for its peers, CPU, first call to the system manager on 2026-11-09, 7 night downloads), the nightly download chart, CPU and disk against peers, and the evidence tables. Hypothetical, synthetic. The store network is flat: nothing separates the POS from refrigeration. | indexed summaries and TLS |
| 14:30 (0.5 min) | Close | | Rules detect, the agent hunts, the same language everywhere. | |

**Advisory lens (Act 4, `docs/advisory-lens.md`):** advisories are data (`config/advisories.yaml`), the agent's prompts name none. Asked about a security advisory, or during the hunt, the agent lists the advisories in the knowledge base and checks the exposure of the estate from simulated Osquery live-query answers (software, CPU flags, JVM flags; answers at T0 + 3 minutes or `make osquery`). For the current entry, the BSI warning on OpenJDK "Java4Shell": 14 devices affected, 2 mitigated, 36 of 40 answered, S12 and S16 silent (unknown, not safe). S07 and S11 have an affected device, S19 does not: an exposure, never the cause.

## How it connects

- The attacker walked into S07, S11 and S19 months ago (Act 3), reached S07's network through a back-office POS (Act 5), and at T0
  changed setpoints from the internet (S11, S19) and from inside (S07). The blip (Acts 1 and 2) is the effect; Acts 3 and 5 are the
  cause; Act 4 is how an agent connects them.
- The knowledge base ties it together: `kb-controller-limits` says +50 is the documented maximum, `kb-device-profiles` says which
  servers a POS may reach, `kb-assets` knows which controllers face the internet and which contractor account serves them,
  `kb-erp-deliveries` knows which truck brings what to which store, `kb-advisories` knows which software a warning concerns.
- Three systems, one question: the ERP (where is the frozen load going), the truck telemetry (is it still cold, where is it) and the cabinets
  (can the store take it). The agent joins them; Act 2 shows the trucks, Act 4 raises the finding.

## Stage script

1. **Four minutes before you present:** `make demo`. It writes and indexes a 6 hour pre-roll (about 3 minutes), then the replay
   runs: logins at T0 minus 2m20s, 46 setpoint changes at T0 + 5 s, rule 1 alerts about 1.5 minutes later. T0 lands at about minute 2 of the talk.
2. Act 0: "we search where the light is". Switch on the Security realm, then Observability, then Knowledge base, last the light.
3. Acts 1 and 2: open them on "Last 24 hours" with auto-refresh. Point at the two kinds of source address and at the frozen trucks. Click a store or a cabinet to filter the page.
4. Act 3: "a year of store audit, one question". The same address, months ago.
5. Act 4: the findings. Point at the POS, the truck and the advisory findings. Optionally `make agent-ask`, or paste the question into Agent Builder.
6. Act 5: "let's see what the POS terminal is doing." Say "hypothetical, synthetic".
7. `make restore` when you want containment (it restores by itself after 30 minutes). Afterwards the cleanup command that `make demo` printed (`make reset-demo SINCE=...`).

## Agent question

"Something changed temperature setpoints in our stores. What happened, how long has the attacker been in, how did it happen
inside the store, which stores are next, and are any deliveries heading into trouble?"

Advisory question (names no vulnerability): "Which of our devices are exposed to the newest security advisory, and how many did not answer?"
