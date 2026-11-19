# Cheat-sheet: run the demo (15 minutes)

## 1. Before (day of the demo)
```bash
aws login                      # the session expires; "LoginRefreshRequired" means this
docker ps                      # coldchain-collector must be Up   (make collector-up if not)
set -a; . ./.env; set +a; .venv/bin/python -m coldchain.prep 60 --preroll-hours 40   # only if the last demo was more than 6 hours ago (fills the gap)
```
Open the dashboards in a browser (hard reload with Cmd+Shift+R after any change), time range "Last 24 hours".

## 2. Start (4 minutes before you present)
```bash
make demo                      # writes a 6 hour pre-roll, then the attack lands about 3 minutes later (T0)
make restore                   # second terminal: the "go" for containment (otherwise it restores itself after 30 minutes)
```
Note the line `afterwards: make reset-demo SINCE=...` that `make demo` prints.

## 3. The story
| Min | Act | Say |
|---|---|---|
| 0:00 | **0** the streetlight | We search where the light is. Switch on Security, Observability, Knowledge base, then the light. |
| 1:30 | **1** store 07 | One cabinet, one odd change, no alert. Click a cabinet number for its page. |
| 3:00 | **2** the estate | The same blip in 3 stores, one from inside the store. Trucks on the map: frozen goods heading into trouble. Click a store. |
| 5:30 | **3** the history | Who logged in as admin from an unknown address? Red: hit. Amber: might be next. |
| 8:00 | **4** the agent | Nobody asked. The agent combined audit, network, cabinets, trucks and the ERP. It proposes, it runs nothing. |
| 11:30 | **5** the POS | A 4 GB night-time download from a server the POS must not reach, then the controller. Say "hypothetical". |
| 14:30 | close | Rules detect, the agent hunts, one language everywhere. |

Findings empty in Act 4? `make hunt-run` (about 20 seconds, uses the LLM). The Osquery answers (Act 5 Java4Shell card, Act 4 agent) arrive by themselves 3 minutes after T0; `make osquery` repeats them.

## 4. After
```bash
make reset-demo SINCE=<the time printed by make demo> DELETE=1
python -m coldchain.hunt delete      # stop the 30-minute hunt if you do not want it running
```

## 5. If something breaks
| Symptom | Fix |
|---|---|
| Nothing indexes during the run | collector down: `make collector-up`, then `make collector-logs` |
| `LoginRefreshRequired` | `aws login` |
| A dashboard looks old | Cmd+Shift+R, or open it in a private window |
| Start over completely | `python -m coldchain.wipe --yes`, then the README setup |

Details: `README.md`, `docs/story-flow.md`, `docs/logistics-story.md`.
