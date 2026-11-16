# Cold-chain demo: edge, data federation and an agent that keeps hunting

A reproducible Elastic demo with **synthetic data**: a fictional retail chain (20 stores on the Upper Rhine, 480 refrigeration
cabinets) is attacked, and a security team finds out how, how long ago, and who is next. Everything is invented. Nothing
here is a real retailer, store, person or customer.

- Stores only **write to an S3 bucket**. Nothing runs in a store.
- The central SOC **detects** on a small indexed stream (rules, ML) and **hunts** with ES|QL data federation over the bulky
  raw files, read in place (experimental).
- An **agent** (Agent Builder plus an Elastic Workflow) keeps looking without being asked.

The story is in [docs/story-flow.md](docs/story-flow.md), the design in [CLAUDE.md](CLAUDE.md), the decisions and
measurements in [docs/decisions.md](docs/decisions.md).

| Dashboard (Kibana) | Shows | Picker |
|---|---|---|
| CC Act 1: One cabinet, the contractor's view | one attacked cabinet | Last 24 hours |
| CC Act 2: The same blip across the whole estate, not on SOC's radar | all 480 cabinets, alerts, inventory | Last 24 hours |
| CC Act 3a: The history nobody ingested | a year of raw audit read in place (federation) | own one-year range |
| CC Act 3b: The history ingested at a predictable price | the same year on the frozen tier | own one-year range |
| CC Act 4: Edge devices on no one's radar | the TV box, hypothetical (scenario B) | 2026-10-22 to 2026-11-11 |
| CC Act 5: Hunting agent - the agent that keeps looking | findings of the scheduled hunt | Last 24 hours |

> **Status of this runbook.** The commands below are the ones the author ran, collected in order. A run from an empty AWS
> account and a new Elastic deployment, following only this file, has **not** been done yet. Expect to fix a step or two,
> and please note them in `docs/decisions.md`.

## 1. What you need

**On your machine:** Python 3.11+, Docker (for the collector), Terraform 1.5+, AWS CLI v2, `make`. macOS or Linux
(federation is not supported on Windows).

**AWS:** an account and a CLI profile that can create an S3 bucket (versioning and Object Lock), an SQS queue with a
dead-letter queue, and about 22 IAM users (20 stores, the collector, federation) with policies. The bucket and the Elastic deployment should be in the same region
(default `eu-central-1`). If your organisation requires resource tags, set them in step 3.

**Elastic Cloud Hosted** (not Serverless: federation is unavailable there), on AWS, same region as the bucket:

| Needed | Why |
|---|---|
| Stack **9.5.x**, pinned (the author used 9.5.6) | Dashboards API, Workflows and Agent Builder (the last two are preview) |
| **Enterprise** subscription (a trial is fine; mind the expiry) | ES\|QL data federation, frozen tier |
| Elasticsearch, Kibana, **ML node**, **Integrations Server** (Fleet), Elastic Security | collector, ML, rules |
| A **frozen node** | Act 3b only (searchable snapshot, `make history-frozen`) |
| User setting `esql.federation.enabled: true` (restarts nodes) and, for the UI, `xpack.dataFederation.enabled: true` | federation is off by default on 9.5 |
| An LLM connector (Elastic-managed ones are preconfigured), Agent Builder and Workflows on | the agent and the hunt |
| An API key with full privileges | the demo creates Fleet policies, ML jobs, rules, dashboards, agents and snapshots; a narrower role has not been worked out |

AlertZero (Elastic Security's agentic layer) is **not offered** on 9.5.6 Cloud Hosted. The hunt is built from Workflows and
Agent Builder instead and is labelled "AlertZero pattern, preview". See `docs/decisions.md`.

## 2. Install

```bash
make install        # creates .venv and installs requirements.txt
make test           # 50+ tests, offline, about 30 seconds
```

Every command on this machine prints a few `hashlib ... blake2b` lines on some pyenv builds. They are harmless noise.

## 3. Configure

```bash
cp .env.example .env
cp infra/terraform.tfvars.example infra/terraform.tfvars
```

Fill in `.env`: `AWS_PROFILE`, `ELASTICSEARCH_URL`, `KIBANA_URL`, `ELASTIC_API_KEY`, `ELASTIC_STACK_VERSION`. Everything else
(`COLDCHAIN_BUCKET`, the queue URLs) is written by `make setup-aws`. `ELASTIC_CLOUD_ID`, `FLEET_ENROLLMENT_TOKEN` and
`FEDERATION_ROLE_ARN` are not read by the code today (the enrollment token and the federation identity are created by the
setup steps and kept in `.secrets/`).

In `infra/terraform.tfvars` set your profile, region and tags. The defaults in `variables.tf` are the author's
(`project_tag`, `team`, `keep_until`: an Elastic SA sandbox policy that denies creates without tags). Use a lease of 30 to 90
days. Sign in first (`aws sso login --profile <p>`, or `aws login`).

## 4. Set up, once

```bash
make setup
```

This runs, in order: `setup-aws` (Terraform: bucket with Object Lock and versioning, SQS and DLQ, per-store write-only IAM,
collector and federation read identities; it writes `.env`, `store-keys.json` and `.secrets/`), `verify-infra` (store
isolation, Object Lock, queue events), `setup-elastic` (templates, pipelines, knowledge-base lookup indices, Fleet policy and
the AWS S3 integration), `collector-up` (an Elastic Agent container enrolled in Fleet, reading the queue) and `federation`
(the data source and datasets over `raw/`; there are no files yet, so `make federation-check` comes after the backfill).

Check: `docker ps` shows `coldchain-collector`; `make verify-infra` ends with all checks passing.

Then the history. This is the long step (tens of thousands of S3 PUTs; restartable, it skips what exists):

```bash
make backfill            # raw/ 12 months of audit, 7 days of flows; detect/ 35 days indexed
make backfill-epilogue   # scenario B: the TV box (hypothetical)
```

Wait until the collector has drained the queue (Kibana > Discover on `metrics-coldchain.case-default`, about 24 million
documents; `python -m coldchain.reingest telemetry --dry-run` lists hours that did not arrive), then:

```bash
make federation-check    # one query per dataset, with timings
make baselines           # what is normal for the Act 2 tiles, measured from the cluster
make epilogue            # ML jobs and datafeeds over the epilogue window, the new-terms rule (disabled)
make content             # dashboards, detection rules (disabled), the agent, the scheduled hunt
make history-frozen      # Act 3b: needs the frozen node; reads raw/ with your AWS profile, about 2 minutes
make verify
```

`make hunt` also **starts a schedule**: the workflow runs the agent every 30 minutes and uses the deployment's LLM each time.
Stop it with `python -m coldchain.hunt delete` (or set `enabled: false` in the workflow).

## 5. Run a demo

Make sure the collector is up (`docker ps`) and your AWS session is valid.

```bash
make demo        # live on the real clock, waits for `make restore`
make rehearse    # the same, hands-off: setpoints are restored by themselves after about 9 minutes
make restore     # second terminal: the "go" for containment (otherwise it restores after 30 minutes)
```

Before T0, `make demo` writes and indexes a day of normal data (about a minute) so the dashboards start with context, then
prints `T0=...` (UTC; Kibana shows your browser's time zone). Open Acts 1 and 2 on "Last 24 hours" with auto-refresh.

| After T0 | You should see |
|---|---|
| about 5 s | 46 setpoint changes to +50 in S07, S11 and S19 (S07's from an address inside the store) |
| about 1 min | rule 1 alerts, one per store |
| about 10 min | rule 2 ("warm, no defrost") and the warm tile (`make demo` only) |
| 40 to 60 min | the run ends and its raw files are written to S3 (Act 3 shows them until cleaned) |

The scripted agent question: `make agent-ask`, or paste it from `docs/story-flow.md` into Agent Builder.

## 6. Between runs

A run leaves indexed documents, alerts, hunt findings and (when it ends) raw files in the bucket. Use the time you
**started** the demo, in UTC, not T0:

```bash
make reset-demo SINCE=2026-11-16T08:50:00Z                 # dry run for the raw files
make reset-demo SINCE=2026-11-16T08:50:00Z DELETE=1        # also deletes them and rebuilds Act 3b
```

`clean-raw` (called by the above) lists or deletes the `raw/` object versions written since that time, with governance
bypass. It refuses a time older than a week without `--force`, because that would reach the backfilled history. Deleting is
permanent.

## 7. Tear down

```bash
make teardown
```

Removes the hunt, the frozen copy, the collector and the AWS stack (all object versions first). The Elastic Cloud deployment
is yours to delete in the console, and the frozen node costs money while it exists.

## 8. Things that will bite you

- **AWS session expired** (`LoginRefreshRequired`): run `aws login` or `aws sso login`.
- **Collector not running:** `make demo` writes to S3 but nothing is indexed. `make collector-up`, `make collector-logs`.
- **Act 3a empty or slow:** federation reads a year of files, about 40 seconds a query, one federated panel per dashboard.
  The dashboard sets its own one-year range because Kibana applies the picker to `@timestamp`.
- **File limit:** a federated dataset lists at most 10,000 files on 9.5.6, so raw audit is one file per store per day. Say
  "default cap" on stage.
- **Rules:** `make demo` and `make rehearse` enable them; `clean-run` switches them off again.
- **Two runs on top of each other:** clean first, or Acts 2 and 3 show both.
- **Federation is experimental,** Workflows and Agent Builder are preview. Say so on stage.
- **Time zones:** everything is UTC in the files and logs; the stage clock is Colmar (UTC+1 in winter).

## 9. Repository map

| Path | What |
|---|---|
| `coldchain/` | the generator (`chain`, `telemetry`, `audit`, `network`, `scenario_b`), `backfill`, `replay`, the Elastic side (`elastic`, `fleet`, `federation`, `rules`, `ml`, `epilogue`, `dashboards`, `agent`, `hunt`, `frozen`), and `infra` |
| `config/` | the chain, the attack, the defrost schedule, scenario B |
| `elastic/lookup/` | the knowledge-base seed files (generated by `make lookups`) |
| `infra/` | Terraform for the AWS side |
| `compose/collector/` | the central collector (Elastic Agent in Docker) |
| `tests/` | offline tests |
| `docs/` | storyboard, data model (06b), story flow, decisions and measurements |

Not in this repo: a store-in-a-box (Elastic Agent, Logstash, S3 output on a store). Every store, S07 included, is simulated
by the generator writing to S3 with its own write-only credentials.
