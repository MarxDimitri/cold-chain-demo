# Story flow, simplified version: six acts in 15 minutes

The path: **we search where the light is** (Act 0), a blip in one cabinet (Act 1), the same blip across the estate (Act 2), a year of
history nobody looked at (Act 3), an agent that finds a lead nobody asked for (Act 4), and the POS terminal behind it (Act 5).
Everything is synthetic and fictional. The full version (Hosted, federation, TV-box epilogue) is the git tag `v1-ech-federation-tv`.

| Time | Act | Dashboard id | What the audience sees | Source |
|---|---|---|---|---|
| 0:00 (1.5 min) | **0. The realms you usually do not watch** | `coldchain-act0-sources` | A streetlight over endpoints, firewalls and identity: what you usually watch. In the dark: cabinet telemetry, controller audit, independent probes, network flows, POS terminals, a year of history. One card per source, with its size. A "Switch on the light" toggle opens `coldchain-act0-lit`: the same sources, all in the light ("Switch off" goes back). | indexed data, `kb-sources` |
| 1:30 (1.5 min) | **1. Store 07, Colmar, from above - what each system says** | `coldchain-act1a-cabinet` | One cabinet (S07-C05): its setpoint goes to +50 and the air warms. One odd controller, no pattern, no alert. | indexed `detect/` |
| 3:00 (3 min) | **2. The same blip across the whole estate** | `coldchain-act1b-estate` | A map of the 20 stores (red: setpoints raised; click one to filter the page). 46 changes in 3 stores; S11 and S19 from `203.0.113.47`, **S07 from `10.7.0.41`, an address inside the store**. Rule 1 alerts about 1.5 minutes after T0. **Trucks on the map:** three frozen trucks (about EUR 98,000) are 15 to 40 minutes from the stores whose freezers are warm (`docs/logistics-story.md`). | indexed `detect/`, truck telemetry, ERP plan |
| 5:30 (2.5 min) | **3. The history nobody looked at** | `coldchain-act3-history` | A map: where `admin` logged in over the last 12 months, one bubble per store sized by the number of logins, red where an outside address logged in. The same address visited **S07 126 days ago, S11 84 days ago, S19 49 days ago** (success, no changes): the three stores hit at T0. Brush the weekly chart to narrow the period. | indexed audit |
| 8:00 (3.5 min) | **4. Hunting agent** | `coldchain-hunt-findings` | "Nobody asked, and something is going on." The agent's findings as cards: first visits, setpoint changes, exposed controllers on one contractor account, and **a back-office POS PC talking to the system manager**. It proposes, it runs nothing. | `cc-hunt-findings` |
| 11:30 (3 min) | **5. The POS that nobody watched** | `coldchain-pos-evidence` | The evidence, hypothetical and synthetic: a 4 GB download at night from `sync.example-cdn.net` (not in the device profile, an unusual JA3), CPU at 88% while the store is closed, the disk filling, and from 2026-11-09 the first call to the system manager. The store network is flat: nothing separates the POS from refrigeration. | indexed summaries and TLS |
| 14:30 (0.5 min) | Close | | Rules detect, the agent hunts, the same language everywhere. | |

## How it connects

- The attacker walked into S07, S11 and S19 months ago (Act 3), reached S07's network through a back-office POS (Act 5), and at T0
  changed setpoints from the internet (S11, S19) and from inside (S07). The blip (Acts 1 and 2) is the effect; Acts 3 and 5 are the
  cause; Act 4 is how an agent connects them.
- The knowledge base ties it together: `kb-controller-limits` says +50 is the documented maximum, `kb-device-profiles` says which
  servers a POS may reach, `kb-assets` knows which controllers face the internet and which contractor account serves them.

## Stage script

1. **Four minutes before you present:** `make demo`. It writes and indexes a 6 hour pre-roll (about 3 minutes), then the replay
   runs: logins at T0 minus 2m20s, 46 setpoint changes at T0 + 5 s, rule 1 alerts about 1.5 minutes later. T0 lands at about minute 2 of the talk.
2. Act 0: "we search where the light is".
3. Acts 1 and 2: open them on "Last 24 hours" with auto-refresh. Point at the two kinds of source address.
4. Act 3: "a year of store audit, one question". The same address, months ago.
5. Act 4: the findings. Point at the POS finding. Optionally `make agent-ask`, or paste the question into Agent Builder.
6. Act 5: "let's see what the POS terminal is doing." Say "hypothetical, synthetic".
7. `make restore` when you want containment (it restores by itself after 30 minutes). Afterwards the cleanup command that `make demo` printed (`make reset-demo SINCE=...`).

## Agent question

"Something changed temperature setpoints in our stores. What happened, how long has the attacker been in, how did it happen
inside the store, and which stores are next?"
