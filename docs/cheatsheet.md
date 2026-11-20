# Cheat-sheet: run the demo (15 minutes)

## 0. Set up from scratch (once, about 1 hour, mostly waiting)
You need: Python 3.11+, Docker, Terraform 1.5+, AWS CLI v2, `make`; an AWS account (profile that can create an S3 bucket, an SQS queue and about 22 IAM users);
an **Elastic Cloud Serverless Security project** with an API key, Fleet, ML, Agent Builder, Workflows and an LLM connector. All data is synthetic.
```bash
git clone https://github.com/<your-org>/cold-chain-demo.git && cd cold-chain-demo
make install && make test                       # a virtualenv in .venv, then the offline tests (about 40 seconds)
cp .env.example .env                            # set AWS_PROFILE and the three ELASTIC_CLOUD_SERVERLESS_* values (Elasticsearch URL, Kibana URL, API key)
cp infra/terraform.tfvars.example infra/terraform.tfvars   # your resource tags (the AWS sandbox policy needs them)
aws login                                       # or: aws sso login --profile <p>
make setup                                      # AWS (Terraform), the Elastic side, the collector container
make backfill                                   # a year of audit, a week of telemetry: about 30 minutes, about 15,000 S3 objects
make backfill-pos                               # the POS scenario (hypothetical)
make baselines epilogue                         # after the collector has drained: what is normal, the POS ML jobs
make sources content                            # Act 0 catalog; the dashboards, rules, agent and the 30-minute hunt
make verify                                     # every query and tool answers
```
`.env`, `infra/terraform.tfvars` and `store-keys.json` are git-ignored: never commit them. `make content` also starts the hunt schedule (it uses the LLM every
30 minutes: stop it with `python -m coldchain.hunt delete`). Dry run: `make rehearse`, then clean up as in section 4. More in `README.md`.

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

Findings empty in Act 4? `make hunt-run` (about 20 seconds, uses the LLM). The simulated Osquery answers (what the agent uses for advisory exposure) arrive by themselves 3 minutes after T0; `make osquery` repeats them.

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
