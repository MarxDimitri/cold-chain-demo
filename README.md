# Cold-chain demo: one platform, one language, an agent that keeps looking (15 minutes)

A reproducible Elastic demo with **synthetic data**: a fictional retail chain (20 stores on the Upper Rhine, 480 refrigeration
cabinets) is attacked, and a security team finds out how, how long ago, and what is next. Everything is invented. Nothing here is a
real retailer, store, person or customer.

This is the **simplified** version (branch `simplified-serverless`): Elastic Cloud **Serverless**, no data federation, one indexed
history, **POS systems** instead of the TV boxes, six acts built with Serverless **custom panels** (HTML, SVG maps on Natural Earth data) and native charts, 15 minutes. The full
version (Elastic Cloud Hosted, federation, frozen tier, TV-box epilogue) is preserved as the git tag `v1-ech-federation-tv`.

- Stores only **write to an S3 bucket**. Nothing runs in a store.
- A collector reads the bucket's queue and indexes everything into the Serverless project.
- Rules detect, an **agent** (Agent Builder plus an Elastic Workflow) keeps looking without being asked, and ES|QL is the one
  language over every source.
- Two stories ride on the attack: **delivery trucks** carrying frozen goods to stores whose freezers are warm (truck telemetry plus an ERP plan,
  `docs/logistics-story.md`), and an **advisory lens**: the agent asks the endpoints (simulated Osquery answers) which devices a new security
  advisory concerns, with prompts that name no vulnerability (`docs/advisory-lens.md`).

## The story in 15 minutes

| Time | Dashboard (Kibana) | What the audience sees |
|---|---|---|
| 0:00 | **Act 0 · The streetlight effect - we search where the light is** | A streetlight with four switches (Security, Observability, Knowledge base, the light): what a SOC watches and what stays in the dark. Sizes counted live from the indices. |
| 1:30 | **Act 1 · The blip in the Colmar store** | The store from above, with its state tiles: one cabinet, one odd change, no alert. Click a cabinet for its page. |
| 3:00 | **Act 2 · Same blip across the entire estate** | A map of the 20 stores with delivery trucks moving on it, tiles with their normals, a zoomable chart and the logins: 46 setpoint changes in 3 stores, one of them from inside the store, and three frozen trucks heading for them. Click a store. |
| 5:30 | **Act 3 · The history nobody looked at** | Which stores an unknown address logged in to as admin in 12 months: red = already hit, amber = might be next. |
| 8:00 | **Act 4 · Let the agent hunt** | Nobody asked, and something is going on: a map by worst finding, tiles and the findings by kind with evidence and proposed action, including trucks heading into trouble and advisory exposure. |
| 11:30 | **Act 5 · The POS is now having a PhD and nobody watched it** | A map of every store's back-office POS PC (S07 reached the controller), four cards, charts against its peers and the evidence: a 4 GB night-time download, CPU, disk, the first call to the controller. Hypothetical. |
| 14:30 | | Rules detect, the agent hunts, the same language everywhere. |

`docs/cheatsheet.md` is the one-page runbook (set up from scratch, run, reset), `docs/story-flow.md` the stage script, `docs/plan-simplified.md` and
`docs/decisions.md` the decisions behind this version.

## 1. What you need

**On your machine:** Python 3.11+, Docker (for the collector), Terraform 1.5+, AWS CLI v2, `make`.

**AWS:** an account and a CLI profile that can create an S3 bucket (versioning and Object Lock), an SQS queue with a dead-letter
queue, and about 22 IAM users. The collector reads the queue; the generator and replay write with per-store keys.

**An Elastic Cloud Serverless Security project** (not Hosted: custom panels exist only on Serverless, Preview):

| Needed | Why |
|---|---|
| Elasticsearch URL, Kibana URL and an API key with full privileges | everything is created through the APIs |
| Fleet (managed by Serverless) | the collector enrols there |
| ML, detection rules, Agent Builder, Workflows and an LLM connector | the POS jobs, rules, the agent and the hunt |

AlertZero is not used: the hunt is built from Workflows and Agent Builder and labelled "AlertZero pattern, preview".

## 2. Install and configure

```bash
make install
make test                       # offline, about 40 seconds
cp .env.example .env
cp infra/terraform.tfvars.example infra/terraform.tfvars
```

In `.env` set `AWS_PROFILE` and the three Serverless values:

```
ELASTIC_CLOUD_SERVERLESS_ELASTICSEARCH=https://....es.<region>.<cloud>.elastic.cloud
ELASTIC_CLOUD_SERVERLESS_KIBANA=https://....kb.<region>.<cloud>.elastic.cloud
ELASTIC_CLOUD_SERVERLESS_API_KEY=...
```

The code copies them over `ELASTICSEARCH_URL`, `KIBANA_URL` and `ELASTIC_API_KEY` (`coldchain/envfile.py`); set
`COLDCHAIN_TARGET=hosted` to use the old values instead. Set your tags in `infra/terraform.tfvars`. Sign in to AWS first
(`aws sso login --profile <p>` or `aws login`).

## 3. Set up, once

```bash
make setup                  # AWS (Terraform), the Elastic side on Serverless, the collector
make backfill               # a year of audit and a week of telemetry: about 30 minutes, about 15,000 objects
make backfill-pos           # the POS scenario (hypothetical)
make baselines epilogue     # what is normal for the tiles; the POS ML jobs and the new-terms rule (disabled)
make sources content        # the Act 0 catalog; dashboards, rules (disabled), the agent, the hunt
make verify
```

Check: `docker ps` shows `coldchain-collector`; `python -m coldchain.fleet status` says the agent is online.

`make hunt` also **starts a schedule**: the workflow runs the agent every 30 minutes and uses the project's LLM each time. Stop it
with `python -m coldchain.hunt delete`.

## 4. Run the demo

Start it **about 4 minutes before you present**, so that the attack lands at minute 2:

```bash
make demo        # live on the real clock: a 6 hour pre-roll (about 3 minutes), then T0 about 3 minutes later
make restore     # a second terminal: the "go" for containment (otherwise it restores after 30 minutes)
```

`make demo` prints `T0=...` (UTC) and the cleanup command. Open Acts 1, 2 and 4 on "Last 24 hours" with auto-refresh. The replay also writes the
truck telemetry and loads the ERP delivery plan (relative to T0), and answers a simulated Osquery live query at T0 + 3 minutes (`make osquery` repeats it). After T0:
the 46 setpoint changes after 5 s, rule 1 alerts after about 1.5 minutes, rule 2 and the warm tile after about 10 minutes.
`make rehearse` is the hands-off variant (it restores by itself after about 9 minutes).

## 5. Between runs

```bash
make reset-demo SINCE=<replay start, printed by the run>
```

Removes the indexed run, the alerts, the hunt findings, the truck telemetry, the ERP plan and the Osquery answers, and reloads the Act 0 catalog (the sizes on the dashboard are counted live). `SINCE` is the replay's start
(T0 minus 3 minutes), after the pre-roll, so the context stays and the next run starts quickly.

## 6. Tear down

`make teardown` removes the hunt, the collector and the AWS stack. The Serverless project is yours to delete in the Elastic Cloud
console, or empty it with `python -m coldchain.wipe --yes` (dry run without `--yes`).

## 7. Things that will bite you

- **AWS session expired** (`LoginRefreshRequired`): `aws login` or `aws sso login`.
- **Collector not running:** `make demo` writes to S3 but nothing is indexed. `make collector-up`, `make collector-logs`.
- **Custom panels are a Preview:** their rendering is not visible through the API; look at each dashboard once after a push.
- **`make dashboards` overwrites edits** made in the Kibana UI. Ask for an edit to be mirrored into `coldchain/dashboards.py`.
- **A second collector on the same queue** (for example the old Hosted one) takes messages and indexes them elsewhere.
- **The POS scenario is dated** 2026-10-22 to 2026-11-11: its dashboard sets its own range.
- **Time zones:** files and logs are UTC; the stage clock is Colmar (UTC+1 in winter).
- **A dashboard looks old:** the browser keeps a copy (and Kibana keeps unsaved edits). Leave edit mode, discard, hard reload (Cmd+Shift+R).
- **`make dashboards` pushes about 57 pages** (Act 0 has nine switch states, Act 1 one page per S07 cabinet, Act 2 one per store).
- **Panel time ranges:** Act 3 defaults to 12 months, Act 5 has a fixed three-week window; ES|QL panels without `?_tstart` ignore the picker.
- **The `blake2` hashlib errors** in the Python output are harmless noise of this Python install.
- **The agent and hunt prompts name no vulnerability.** Add an advisory in `config/advisories.yaml` and run `make lookups`; a test enforces it.

## 8. Repository map

| Path | What |
|---|---|
| `coldchain/` | the generator (`chain`, `telemetry`, `audit`, `network`, `scenario_b` = the POS scenario, `trucks`, `osquery`), `backfill`, `replay`, `prep`, the Elastic side (`elastic`, `fleet`, `rules`, `epilogue` = POS ML, `agent`, `hunt`, `sources`, `baselines`), the dashboards (`dashboards`, `panels`, `geo`, `mapdata`), `wipe`, `infra`, `envfile` |
| `config/` | the chain (4 POS lanes and a back-office POS per store), the attack, the POS scenario, the defrost schedule, `advisories.yaml` |
| `elastic/lookup/` | the knowledge-base seed files (generated by `make lookups`; the ERP plan is loaded by the replay) |
| `tools/` | `build_map.py`: how the base map paths in `coldchain/mapdata.py` were made from Natural Earth data |
| `tests/` | offline tests (`make test`, about 90, 40 seconds) |
| `infra/` | Terraform for the AWS side |
| `compose/collector/` | the central collector (Elastic Agent in Docker) |
| `docs/` | the plan, decisions and measurements, the story flow, the original storyboard and data model (06b) |

Not in this repo: a store-in-a-box. Every store, S07 included, is simulated by the generator writing to S3 with its own write-only
credentials.
