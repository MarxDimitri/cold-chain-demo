> **BRANCH NOTE (updated 2026-11-20): this branch (`simplified-serverless`) is the simplified demo.** Where the brief below disagrees,
> this block, `docs/plan-simplified.md` and `README.md` win. The long brief that follows describes the **full version** (Elastic Cloud Hosted,
> data federation, TV-box epilogue), preserved as the git tag `v1-ech-federation-tv`: sections 3.2, 4.4, 6.6, 8.3 to 8.6 and 12 do not apply here.

## Current state of the simplified demo (read this first)

**What it is:** Elastic Cloud **Serverless** (Security project), no federation and no frozen tier (a year of audit is indexed), **POS systems**
instead of TV boxes, a 15-minute story of six acts (`docs/story-flow.md`, one-page runbook `docs/cheatsheet.md`). Everything is synthetic.
Stores only write to S3 (per-store write-only keys); one collector container reads the SQS queue and indexes into the project.

**The six dashboards** (built by `coldchain/dashboards.py` from `coldchain/panels.py` templates; `make dashboards` pushes about 57 pages and
overwrites UI edits):
| Act | Headline | Pages |
|---|---|---|
| 0 | The streetlight effect - we search where the light is | nine pages: four link-switches (Security, Observability, Knowledge base, the light); sizes counted live from the indices (`sources.live_query`) |
| 1 | The blip in the Colmar store | the store layout (SVG) with state tiles; one page per S07 cabinet (click a cabinet) |
| 2 | Same blip across the entire estate | a map of the 20 stores (Natural Earth base map as SVG), tiles, a native zoomable chart, delivery trucks; one page per store (click a dot) |
| 3 | The history nobody looked at | map: stores an unknown address logged in to as admin (red hit, amber might be next) |
| 4 | Let the agent hunt | map by worst finding, tiles, findings grouped by kind |
| 5 | The POS is now having a PhD and nobody watched it | map of back-office POS PCs, cards, charts, evidence (fixed three-week window) |

**Stories on top of the attack:** delivery **trucks** and an ERP plan (`coldchain/trucks.py`, `docs/logistics-story.md`); the **advisory lens**: simulated
Osquery live-query answers checked against security advisories (`coldchain/osquery.py`, `config/advisories.yaml`, `docs/advisory-lens.md`).
The agent (`coldchain/agent.py`, 13 ES|QL tools) and the scheduled hunt (`coldchain/hunt.py`) are Agent Builder and Workflows, both preview.

**Rules for changes**
- **Prompts name no vulnerability, product or version.** Advisories are data (`config/advisories.yaml` -> `kb-advisories`); a test enforces it. The agent
  proposes, never runs containment; an advisory is an exposure, never the cause.
- Fictional only, documentation IP ranges, `example` domains, never the real incident (section 2 below still holds). Label hypothetical scenarios.
- Custom panels (Serverless Preview): HTML, CSS, Liquid, inline SVG only; no JavaScript, no external resources, links only to dashboards. State changes
  are links between dashboards. Rendering cannot be seen through the API: ask for a screenshot. Native `vis` panels give zoom and tooltips; the
  dashboards API accepts no annotation events and no categorical colour mapping (tried).
- ES|QL: subqueries are not nested; `first`, `last` are reserved; a lookup index needs its fields mapped even when empty (`LOOKUP_PROPERTIES`);
  dashboard time params are `?_tstart`, `?_tend`; panels without them ignore the picker.
- Dashboard ids are lowercase; a push replaces the page (and any unsaved edit in the browser: leave edit mode and discard first).

**Run, reset, test:** `make demo` (4 minutes before presenting), `make restore`, `make reset-demo SINCE=<printed time> DELETE=1`; `make test` (about 90 tests, offline, 40 s).
AWS sessions expire (`aws login`); the `blake2` hashlib errors in the Python output are harmless. Browser caches old dashboards: hard reload.

**Open items:** Terraform removal of the federation IAM user was written but never applied; old objects in the bucket are not emptied; rendering of newer
panels is verified only from the user's screenshots; a full timed 15-minute run has not been done; the GitHub repository is not created yet.

# Cold-chain demo: implementation brief (edge + data federation on AWS S3)

> **How to use this file:** put it in the root of a new repository as `CLAUDE.md`, or reference it from there. Copy the companion files into `docs/`:
> - `06 · Cold-Chain Demo — Storyboard.pptx`: the source of truth for story, screens and timing. Slide 33 shows the target architecture.
> - `06b · Cold-Chain Demo — Data Model and ES|QL.md`: the source of truth for fields and queries. Section 9 adds the federation queries.
>
> Where this brief and 06b disagree, 06b wins on field names and queries. The storyboard wins on story and timing. **This brief wins on architecture.**
>
> **Storage note:** 06b and the storyboard may still say "MinIO" or "S3-compatible". This brief replaces that with **Amazon S3**. Treat every MinIO reference there as S3.

---

## 1. Goal

Build a reproducible Elastic demo that tells the storyboard's cold-chain story with **synthetic data**, on an **edge architecture**:

- **Stores only write to object storage:** every store writes into a central-IT bucket on **Amazon S3**. No store talks to a cluster, and no cluster runs in a store.
- **The central SOC detects on indexed data:** it ingests the small detection stream from the bucket, and rules, ML and AlertZero run on it.
- **The central SOC hunts with federation:** ES|QL data federation queries the bulky raw data in place, in the bucket, without ingesting it.

The demo covers acts 1–7, the reported +50 °C attack (scenario A), and the epilogue: a hypothetical payload on an in-store TV box (scenario B).

**Main story (v3, `docs/story-flow.md`):** the blip (Act 1) → the history nobody ingested (Act 5: the same address visited S07, S11 and S19 months ago) → outside and inside the store (epilogue: the TV box that changes S07's setpoints from within) → the agentic SOC ties it into one narrative while hunting. Acts 2, 3, 4, 6 and 7 are an optional appendix.

**What "done" means:** on a fresh **Elastic Cloud Hosted** deployment and an AWS account, someone runs `make setup && make backfill`. During a presentation they run `make replay`. Every act's screen then shows the expected result within the measured timings (section 10).

**Why federation is not the detection path:** detection rules and ML jobs need indexed data. ES|QL data federation is documented as **experimental** (not for production) and Enterprise-only. So the demo uses it where it shines, for hunting history and raw data in place. It never sits on the critical path from attack to alert. Say "experimental" on stage.

---

## 2. Ground rules (non-negotiable)

- **Fictional only:**
  - The chain is invented. It has 20 stores on the Upper Rhine: HQ and DC Nord in Strasbourg, DC Sud in Mulhouse, store S07 in Colmar.
  - No real retailer, store, person or customer data.
  - Never name the Estonian store from the real incident.
- **IP addresses:**
  - Attacker: `203.0.113.0/24`.
  - Contractors: `198.51.100.0/24`.
  - Store LANs: `10.<store>.0.0/16`.
  - These are documentation and private ranges only.
- **Domains:** use `example` domains for external services, for example `models.example-hub.net` and `cdn.signage-vendor.example`.
- **Labelling:** label scenario B, the optional "quiet toggling" variant and data federation as hypothetical or experimental, in dashboards, case notes and the script.
- **Vendor facts:** short paraphrased facts from the public Danfoss EKC 202 manual only, with a page reference. Never store full manual text.
- **Secrets:**
  - No credentials in the repo. Use `.env` (git-ignored) and `.env.example`.
  - Prefer an AWS profile or short-lived credentials (SSO, STS) for the operator. Static access keys exist only where a component can't assume a role (the simulated stores, S07's Logstash, the federation data source if it needs keys). Keep them in `.env` or a secrets store, never in code.
  - Least-privilege IAM: each simulated store can write only to its own prefix.
- **Idempotency:** every step can be re-run safely. `make teardown` removes everything the repo created, including the bucket objects, versions and delete markers (subject to object lock; see 4.2).
- **Cost hygiene:** tag every AWS resource per the SA sandbox policy (hive-mind skill `hive-sa-cloud-tagging`): `project=dimitri-coldchain`, `team=emea_dach_area`, `org=sa`, `division=field`, `keep-until=<date, ≤ 90 days>`. The org SCP denies creates without them (SQS creation failed until they were set). Terraform sets them as provider default tags. `make teardown` must leave no billable resource behind. Report the S3 request counts and the cost of a rehearsal in `make verify`.

---

## 3. Target environment

### 3.1 Object storage: Amazon S3
- **One S3 bucket owned by "central IT":** one bucket `coldchain-<suffix>` (bucket names are global, so `make setup` appends a short unique suffix and records it in `.env`) in one **EU region** (default `eu-central-1`, Frankfurt, matching the Upper Rhine story). Settings:
  - **versioning** on and **Object Lock** on (Object Lock can only be enabled when the bucket is created, or later through a support-free API call on a versioned bucket; create it with locking enabled);
  - **Block Public Access** all four settings on;
  - default encryption SSE-S3 (or SSE-KMS if the demo wants to show key control);
  - bucket policy denying non-TLS requests (`aws:SecureTransport`);
  - a lifecycle rule that expires noncurrent versions and incomplete multipart uploads after a few days, so the demo doesn't accumulate cost.
- **Identities and policies (IAM):**
  - one write-only identity per store (`s3:PutObject` on `arn:aws:s3:::<bucket>/*/dataset=*/store=Sxx/*` only; no `GetObject`, `DeleteObject` or `ListBucket`);
  - one read identity for the central collector (`s3:GetObject` on `detect/*`, `s3:ListBucket` with a `detect/` prefix condition, plus SQS receive and delete on the notification queue, see 4.3);
  - one read identity for the federation data source (`s3:GetObject` on `raw/*`, `s3:ListBucket` with a `raw/` prefix condition).
- **How stores authenticate:**
  - S07's Logstash and the generator use per-store IAM users with access keys, as the simplest thing that works offline from AWS identity providers. Real stores would use IAM Roles Anywhere or a similar short-lived credential.
  - The collector can use an IAM role if the Agent runs on EC2, otherwise a read-only key.
- **Why S3:** it is the object store federation officially supports, it has native event notifications (SQS), and Elastic Cloud on AWS reaches it without firewall work.

### 3.2 Elastic: Elastic Cloud Hosted (ECH) on AWS

**Decision:** the demo runs on **Elastic Cloud Hosted**, not Serverless and not self-managed. Record the reasoning in `docs/decisions.md`.
- **Why not Serverless:** the ES|QL Data Federation docs list Elastic Cloud Serverless as **unavailable**. Federation carries acts 3, 5, 6 and the epilogue. Serverless also has no `_snapshot/*` APIs, so the snapshot fallback in 4.4 would not work either, and it upgrades automatically, which is unwelcome with experimental features.
- **Why ECH:** federation is available (Enterprise subscription), you choose and pin the version, ILM and snapshot repositories are available, and the platform is the managed one customers usually see.
- **Revisit Serverless** only if the docs show federation available there; the rest of the demo (rules, ML, Agent Builder) would likely work.

Deployment settings:
- **Cloud provider and region:** AWS, the **same region as the bucket** (default `eu-central-1`), which keeps S3 traffic local and avoids cross-region transfer cost.
- **Subscription:** Enterprise (trial is fine, mind the expiry date).
- **Stack version:** the **most recent 9.x available** on Elastic Cloud, pinned (no automatic upgrade before the demo). Minimum 9.1 for GA `LOOKUP JOIN`. Record the exact version.
- **Components:** Elasticsearch, Kibana, ML nodes, Integrations Server (Fleet Server), Elastic Security.
- **Data federation enablement:**
  - 9.5: experimental and off by default. Add `esql.federation.enabled: true` to the deployment's Elasticsearch user settings (static, restarts nodes), and `xpack.dataFederation.enabled: true` for the Kibana UI.
  - 9.6 and later: the docs say it becomes a preview and is on by default (`esql.federation.enabled: false` turns it off; the Kibana toggle is `dataFederation:enabled`). That is marked as planned, so confirm on the deployed version.
  - Not supported on Windows. The Kibana UI needs the cluster `manage` privilege.
- **Access from Elastic Cloud to S3:** prefer federated identity (an IAM role trusted by the deployment), as in Elastic's "Connect to Amazon S3 with federated identity" page. Fall back to a read-only access key limited to `raw/*`.
- **Preview features:** AlertZero, Workflows and the context engine must be enabled on the deployment (see 12).
- **Where the collector runs:** Elastic Cloud doesn't run the central collector. Run one Elastic Agent container on the operator's host (or a small EC2 instance), enrolled in the cloud Fleet Server (3.3).

### 3.3 Containers (Docker Compose)
- **Store side:** the S07 "store-in-a-box" (Elastic Agent + Logstash). Optional: run it on a Raspberry Pi 5 as a stage prop.
- **Central side:** the central collector (Elastic Agent with the AWS S3 input in SQS mode, enrolled in Elastic Cloud's Fleet Server), the mock response service and the generator. Elasticsearch, Kibana and Fleet Server live in Elastic Cloud, not in Compose.
- **AWS side (not a container):** the bucket, the SQS queue, the IAM identities. Provisioned by `make setup` from `infra/` (default: CloudFormation or Terraform, whichever the user prefers; record it in `docs/decisions.md`).
- **Language:** Python 3.11+ (`elasticsearch`, `boto3`, `pydantic`, `numpy`).

Ask the user for: the Elastic Cloud deployment (Cloud ID or Elasticsearch and Kibana URLs, an API key, the Fleet enrollment token) and its exact Stack version; the AWS account, region and CLI profile; the provisioning tool (CloudFormation or Terraform); whether data federation, AlertZero and Workflows are enabled on the deployment.

---

## 4. Architecture

```
 STORES (×20)                         CENTRAL IT (AWS S3, EU region)          CENTRAL SOC (Elastic)
 ┌────────────────────────┐           ┌──────────────────────────┐            ┌────────────────────────────────┐
 │ S07 store-in-a-box     │  upload   │  s3://coldchain-<sfx>/   │  S3 event  │ Ingest → data streams          │
 │  Elastic Agent         │ ────────▶ │   detect/… (1-min files) │ ─▶ SQS ──▶ │  rules · ML · AlertZero · cases│
 │  └▶ Logstash (S3 out)  │           │   raw/…    (hourly files)│  S3 input  │                                │
 ├────────────────────────┤           │  object lock · per-store │            │ ES|QL data federation  ◀ ─ ─ ─ │
 │ S01…S20 simulated      │ ────────▶ │  prefixes · write-only   │ ◀─ ─ ─ ─ ─ │  datasets over raw/… (hunts)   │
 │  (generator → S3)      │           └──────────────────────────┘  read in   │ Lookup indices (knowledge base)│
 └────────────────────────┘                                          place    └────────────────────────────────┘
```

### 4.1 Store side
- **S07 runs the real path:**
  - **Elastic Agent** collects locally. Its inputs are a log file for the system-manager audit, a UDP NetFlow listener, and log files for telemetry and edge metrics, all fed by the generator.
  - Elastic Agent's output is **Logstash**: Agent can't write to S3 directly.
  - Logstash uses the **S3 output** pointed at the bucket (`region => "eu-central-1"`, `bucket => "<bucket>"`, the store's own credentials, no custom endpoint), with a disk-backed persistent queue, so it buffers when "offline".
- **Two Logstash pipelines:**
  - `detect`: audit events, flow summaries (5-minute aggregates per device pair) and telemetry. They're written as gzip NDJSON with **1-minute** rotation to `detect/…`.
  - `raw`: full flows, TLS session records, edge metrics and raw telemetry. They're written as gzip NDJSON with **hourly** rotation to `raw/…`.
- **The other 19 stores are simulated:** the generator writes their files straight to S3 (`boto3`) with the same layout, schema and rotation, using each store's write-only credentials.

### 4.2 Bucket layout (`s3://coldchain-<suffix>/`)
```
detect/dataset=<dataset>/store=<Sxx>/dt=<YYYY-MM-DD>/hh=<HH>/<Sxx>-<epoch>-<seq>.ndjson.gz
raw/dataset=<dataset>/store=<Sxx>/dt=<YYYY-MM-DD>/hh=<HH>/<Sxx>-<epoch>.ndjson.gz
```
- **Datasets:**
  - `coldchain.audit`
  - `coldchain.case` (telemetry)
  - `netflow.summary` (detect only)
  - `netflow.log` (raw)
  - `network_traffic.tls` (raw)
  - `signage.cms`
  - `power.plug`
  - `coldchain.probe` (independent temperature loggers, detect only)
- **Object Lock:** governance mode with a short default retention (for example 7 days) in the demo, so teardown remains possible. `make teardown` needs `s3:BypassGovernanceRetention` and must delete all versions and delete markers, not just current objects. In production it would be compliance mode with the real retention.
- **Event notifications:** an S3 event notification on `s3:ObjectCreated:*` with prefix `detect/` sends to one SQS queue (4.3). The `raw/` prefix has no notification, because nothing ingests it.
- **Request volume:** 20 stores × 1-minute files is about 29,000 `PUT`s a day for `detect/`, plus a few thousand for `raw/`. That is cheap, but the backfill of 12 months of hourly raw files is not trivial; count it.

### 4.3 Central ingest (detection path)
- **Collector:** an Elastic Agent with the **AWS S3 input (Custom AWS Logs integration) in SQS mode.**
  - Settings: `queue_url: <detect queue>`, `region`, the collector's read credentials or role, `file_selectors`/content type for gzip NDJSON.
  - SQS mode is the default here: it picks up a new object within seconds, with no listing cost. The input deletes the message after a successful read, and a dead-letter queue catches poison files.
  - **Alternative:** bucket polling (`bucket_arn`, `bucket_list_prefix: detect/`, `bucket_list_interval: 10s`). Use it only if SQS is a problem.
  - It decodes the NDJSON lines; one ingest pipeline with the `reroute` processor sends each record to its data stream by `event.dataset`: `logs-coldchain.audit-default`, `metrics-coldchain.case-default`, `logs-netflow.summary-default`.
- **Ingest pipelines** enrich `retail.store.id`, if missing, and compute `coldchain.case.temperature.rise_5m`, if not generated.
- **Measure the latency budget:** store rotation (≤ 60 s) + S3 event and SQS delivery + Agent pickup + indexing. Report it; it feeds the stage clock (section 10).

### 4.4 Data federation (hunting path)
- **Data source:** `cold-chain-s3`: type `s3`, the bucket's region, federated identity (an IAM role) or read-only credentials limited to `raw/*`.
- **Go/no-go first:** federation officially supports Amazon S3, so the risk is lower than with a non-AWS store. It is still experimental or preview and version-dependent. **Test it in milestone 1, before building anything on it:** create the data source and one dataset, and query one file.
- **Gzip check:** the docs list Parquet, NDJSON, CSV and TSV, but gzip is not confirmed. Include it in the go/no-go. If gzip NDJSON fails, write `raw/` as uncompressed NDJSON or Parquet (update the Logstash `raw` pipeline and the generator), and keep `detect/` gzipped.
- **Fallback if federation is not available or too unstable on the tenant:**
  - Act 5: register the bucket as an S3 snapshot repository, snapshot the 12-month history and mount it as a historical (frozen) searchable snapshot.
  - Act 3, act 6 and the epilogue: re-ingest the needed raw files on demand into an `investigation-*` index with the same collector.
- **Datasets** (resource patterns on `raw/…`; NDJSON with gzip):

  | Dataset | Resource pattern (indicative) | Used in |
  |---|---|---|
  | `raw_store_audit` | `raw/dataset=coldchain.audit/**` | Act 5 (12 months of history) |
  | `raw_store_flows` | `raw/dataset=netflow.log/**` | Act 3 flow row, act 6 hunt |
  | `raw_store_tls` | `raw/dataset=network_traffic.tls/**` | Epilogue |
  | `raw_store_telemetry` | `raw/dataset=coldchain.case/**` | Act 5 optional, long history |
  | `raw_edge_metrics` | `raw/dataset=signage.cms/**`, `raw/dataset=power.plug/**` | Epilogue |

- **Setup:** create the data source and datasets through the ES|QL data-federation APIs (`put-data-source`, `put-dataset`) or the Kibana UI. Check the exact request bodies, the resource-pattern syntax and the file-filtering options in the tenant's docs.
- **Documented limits:**
  - no `LOOKUP JOIN` *into* a dataset (a dataset as the *source* joining lookup indices is fine);
  - no `TS`;
  - S3 request costs per query (`GET` and `LIST` requests, plus data transfer if Elastic runs in another region);
  - experimental.
- **File-count limit:** a dataset listing matched at most 10,000 files on 9.5.6. Elastic's docs describe `esql.external.max_discovered_files` as a dynamic cluster setting (default 25,000, up to 1,000,000); setting it had no effect here. Say "default cap" on stage. Raw audit is therefore written as one file per store per day; other raw datasets stay hourly as long as they stay under the limit.
- **Known limitation, accepted for the demo:** the file-count limit above caps scale; compaction is not built. See `docs/decisions.md`.
- **Small files:** hourly files keep the object count manageable. Optional: a central compaction job turns a day's files into one file per store and dataset (Parquet is better, if the writer supports it).

---

## 5. Data model (summary; 06b has the details)

| Family | Where it lives | Notes |
|---|---|---|
| Security | `logs-coldchain.audit-default` (indexed from `detect/`) + `raw_store_audit` (federated) | ECS plus `coldchain.parameter.*`, `retail.store.id` |
| Security | `logs-netflow.summary-default` (indexed) + `raw_store_flows` (federated) | Summaries: 5-minute bytes and packets per `source.ip` / `destination.ip` / `destination.port` |
| Security | `raw_store_tls` (federated) | `tls.client.server_name`, `tls.client.ja3`, `destination.bytes`, `source.ip` |
| Security | `.alerts-security.alerts-default` | Produced by rules only |
| Operational | `metrics-coldchain.case-default` (indexed) + `raw_store_telemetry` (federated) | 1-minute cabinet telemetry |
| Operational | `logs-coldchain.probe-default` (alias `metrics-coldchain.probe-default`, indexed) | Independent probes, one per cabinet, every 5 minutes, own uplink: outside the controller's trust boundary |
| Operational | `raw_edge_metrics` (federated); hourly roll-ups indexed for ML (optional) | Signage CPU and storage; smart-plug watts |
| Knowledge | `kb-assets`, `kb-assets-by-ip`, `kb-controller-limits`, `kb-device-profiles` (lookup indices) | `index.mode: lookup` |
| Knowledge | `kb-manuals` | Short paraphrased facts with page references, `semantic_text` |
| Knowledge | `kb-regulations` | Paraphrased food-temperature and NIS2 facts with source and `kb.verified` |

**Conventions**
- **One schema per dataset:** the same ECS-shaped records go to `detect/` and `raw/`, so a query reads the same whether it's indexed or federated.
- **Namespaces:** custom fields only under `coldchain.*`, `retail.*`, `kb.*` and `profile.*`.
- **Store ID:** `retail.store.id` is on every record.
- **Dataset:** `event.dataset` is on every record.

---

## 6. Synthetic data

### 6.1 Chain model (`config/chain.yaml`)
- **Stores:** 20 stores (`S01`–`S20`), 10 in Alsace and 10 in Baden, with about 12 owners (cooperative-style).
- **Per store:**
  - one system manager (`Sxx-SM800`, AK-SM 800A);
  - 24 cabinets (`Sxx-C01`–`C24`, EKC 202C): 16 frozen at −24 °C and 8 chilled at +2 °C;
  - an SD-WAN router;
  - a store server;
  - 2 signage players;
  - 1 TV box (staff room);
  - 3 cameras.
- **Exposure:** 16 system managers are internet-facing with the default account and firmware below 4.3.1. 4 are patched.

### 6.2 Cabinet telemetry
- **Normal operation:**
  - compressor and valve cycles around the setpoint, roughly ±0.8 K frozen and ±0.5 K chilled, plus noise;
  - three electric defrosts a day for frozen cabinets (clock starts 05:00, 13:00, 21:00 UTC, the factory 8 h interval of `d03`; staggered in 4 groups of cabinets 45 min apart plus a per-store shift, so about a quarter of the frozen cabinets defrost at any time and never the whole estate), 35–45 minutes each (inside the factory `d04` of 45 min), with the cabinet air rising 8–14 K above its setpoint (an assumption to validate) and the evaporator (S5) swinging about 40 K; parameters in `config/defrost.yaml`, from the EKC 202 manual p.3;
  - the defrost relay is reported as `coldchain.case.defrost.active` (readout `u60`): off during the +50 attack, on during a forced defrost;
  - seasonality.
- **Attack warming:** the +50 °C setpoint stops refrigeration. The air warms exponentially toward about +18 °C ambient, calibrated to **about +3 °C within about 10 minutes**. This is configurable and an assumption; validate it with a refrigeration contractor.
- **Restore:** pull-down over 20–30 minutes.
- **Volumes:**
  - *Indexed* telemetry: **35 days at 1-minute resolution**, about 24 M documents, enough for ML baselines.
  - *Raw* telemetry in S3: optionally 12 months at 5-minute resolution, so act 5 can query a year in place.

### 6.3 Audit events
- **12 months of history in `raw/`, the federated history:**
  - contractor logins on weekday daytimes from `198.51.100.0/24`;
  - legitimate changes within the normal range;
  - scheduled `defrost-start` and `defrost-stop` per cabinet, user `system`, from the manager's address, matching the telemetry windows.
- **The last 35 days also go to `detect/`,** so they're indexed.
- **First visits (`config/attack.yaml` `probes`):** three night logins from `203.0.113.47` (`admin`, success, no changes): S07 at T−126 days, S11 at T−84 days, S19 at T−49 days. They are the three stores hit at T0, in the order the attacker walked in. All are older than the 35 indexed days, so they exist **only in the raw history**, which is the point of act 5: the federated query finds what nobody ingested.

### 6.4 Network
- **Raw flows:** normal store traffic, plus the attack flow `10.7.0.21 → 203.0.113.47`.
- **Flow summaries:** derived from the raw flows for `detect/`.

### 6.5 Knowledge seed (`elastic/lookup/*.ndjson`)
- **`kb-controller-limits`,** for EKC 202C (values as in 06b):

  | Parameter | Application | Documented range (`kb.doc`) | Curated normal (`kb.expected`) |
  |---|---|---|---|
  | `setpoint` | frozen | −50…+50 °C | −28…−18 °C |
  | `setpoint` | chilled | −50…+50 °C | 0…+5 °C |
  | `A13` | frozen | −50…+50 °C | −20…−10 °C |
  | `A03` | — | 0…240 min | 0…60 min |

  Each row has a reference to "Danfoss EKC 202 instructions RI8KL45J, p.3".
- **`kb-device-profiles`:** allowed server names per `retail.device.role`. The TV box may reach the vendor update server and NTP, **not** the model hub.
- **`kb-manuals`:** 5–10 short paraphrased facts.

### 6.6 Scenario B (epilogue, hypothetical)
- **Where it lives (implemented, `config/scenario_b.yaml`, `coldchain/scenario_b.py`):** 21 days, 2026-10-22 to 2026-11-12 (before the blip, so it is the cause of the S07 change at T0), in its own data-stream namespace `epilogue` (`logs-netflow.summary-epilogue`, `logs-signage.cms-epilogue`, `logs-power.plug-epilogue`; routed by `labels.namespace`), so the main demo's streams and live replay are untouched. Detect: flow summaries for all 20 stores, hourly signage and smart-plug roll-ups. Raw (S07 only): `netflow.log`, `network_traffic.tls`, `signage.cms`, `power.plug`. `raw_edge_metrics` is two federation datasets (`raw_edge_signage`, `raw_edge_plug`) because the schemas differ. The download is 4.6 GiB (the 06b query divides by 2^30), 123 chunks. The data is dated before the blip and is not replayed live: the rule and ML are exercised over the window with a rule preview and bounded datafeeds. From 2026-11-09 the TV box calls the system manager on tcp/80, and at T0 its address (`10.7.0.41`) makes S07's setpoint changes.
- **Offline window:** S07 is offline at 02:10–02:58 on 2026-11-05, two days into the download. Logstash buffers, and the files for that window are uploaded after 02:59, so `event.ingested` is later than `@timestamp`.
- **Chunked download:** `S07-TVBOX-01` receives **4.6 GB over 9 nights** in 20–60 MB chunks from `models.example-hub.net` (TLS, an unusual JA3). The 19 peer TV boxes receive less than 50 MB a week.
- **Signage metrics:** `S07-SIG-02` CPU sits at about 97% for 4 days and free storage drops.
- **Smart plug:** TV box power doubles from about 3 W to 6–7 W.
- **Internal flows:**
  - TVBOX→SIG on tcp/8080
  - SIG→CAM on tcp/554
  - **TVBOX→SM800 on tcp/80**: never seen before.
- **What goes where:**
  - **Indexed:** flow summaries, so the new-terms rule and the ML population job see the new peer and the weekly bytes.
  - **Federated only:** the raw TLS records with server names and JA3, used for the hunt.

---

## 7. Attack timeline (`config/attack.yaml`): scenario A

`T0` is the replay start. The configured `t0` is 2026-11-12 02:52 UTC, which is 03:52 in Colmar (CET) and the storyboard's 4 a.m. line. It sits in a quiet window away from the 05:00/13:00/21:00 UTC defrost slots; a live `--t0 now` replay shows the real clock.

| Time | Event | Path |
|---|---|---|
| T0−2m 20s | Logins on **9 stores'** system managers, `admin`, from `203.0.113.47` | detect + raw |
| T0+5s | **46 cabinets in 3 stores (S07, S11, S19)**: setpoint −24 → **+50**. S11 and S19 from `203.0.113.47`; **S07 from the TV box `10.7.0.41`** (inside the store; a tcp/80 flow to the manager at T0+3s) | detect + raw |
| T0+11s | Flow from S07's system manager (10.7.0.21) to 203.0.113.47 | raw (+ summary in detect) |
| T0 → | Affected cabinets warm | detect + raw |
| ≈T0 + ingest latency + ML latency | ML temperature-rise anomaly; ES\|QL limits rule | alerts |
| ≈T0+9–11 min | Workflow: block IPs, lock out and restore setpoints (contractor-approved), notify, open case | mock calls; restore events via detect |
| → +35 min | Pull-down; warmest cabinet about +3 °C above setpoint | detect + raw |

- **Act 6 numbers:** 16 controllers are exposed, 9 of them touched. The 7 not-yet-touched stores are S03, S05, S09, S12, S14, S17 and S20.
- **Variant A2, forced defrost (hypothetical, `replay --scenario defrost`):** same 46 cabinets and timing, but no setpoint
  change. The attacker issues `defrost-start` from `203.0.113.47` at T0+5s and repeats every 8 minutes until the restore
  (`defrost-stop` by the workflow). Public reports describe both mechanisms (setpoint +50 in Estonia, forced defrost in
  France). The limits rule stays silent; the temperature rise, the command source (not `system`, not the store LAN) and the
  out-of-schedule timing (normal slots 05:00, 13:00, 21:00 UTC) are the signal. Warming uses the same calibrated model.
- **Option, telemetry spoof (hypothetical, `replay --spoof`):** the controller reports normal air temperature and setpoint on the
  targeted cabinets until the restore; the audit trail still shows the change. Only the independent probes see the warming.
  Probes read every 5 minutes (independent loggers are slow but trustworthy), so the controller-versus-probe gap is only about
  1.5 K at T0+8 min under this calibration: a divergence rule needs two readings and has about 10 minutes.
- **Optional quiet variant (hypothetical):** setpoints toggled inside the band; compressor starts up about 4×.
- **`replay.py`** drives the S07 box (local files, UDP NetFlow) and writes the simulated stores' S3 files. It has a speed factor (1× on stage, 10× in rehearsal) and `make reset`.

---

## 8. Elastic configuration

### 8.1 Indexed side
- **Templates and pipelines:** index templates for the detection streams, plus ingest pipelines (store enrich, `rise_5m`).
- **Lifecycle:** ingest, then interactive at 30 days, then delete at 35–40 days. Long history lives in the bucket, not in the cluster.
- **Lookup indices:** with their seed data.

### 8.2 Detection by rules from the knowledge base (Act 2)

Act 2 is deterministic rules, not ML (measured: per-cabinet ML on temperature flags 1 of 46 attacked cabinets at score 75, population jobs 0; see `docs/decisions.md`). Thresholds are **rows, not constants**: `kb-thresholds` (and `kb-controller-limits`) hold each threshold with provenance (manual page, measured history, approver, `draft`/`approved`), so one generic set of rules covers every controller model.

| Rule | Logic (ES\|QL, `LOOKUP JOIN` to the KB) | Measured on synthetic data |
|---|---|---|
| 1 Setpoint outside documented normal | `setpoint` above `kb.expected`; at the documented maximum is its own verdict | 46/46 attacked cabinets within one rule interval |
| 2 Warm for too long | air minus nominal > 2 K, relay off, more than 30 min after the last relay-off, 3 of the last 5 minutes | 46/46 at about 9 min; 0 false alarms in 35 days (synthetic) |
| 3 Forced defrost | relay on outside the schedule, or `defrost-start` from a source not in `kb-command-allowlist` | needs relay-versus-schedule; temperature rules are blind to it |
| 4 Probe divergence | independent probe minus controller air above the sensor bias for two readings | about 10 min after a spoof |
| 5 Many stores at once | count of stores with rule 1 or 2 hits in the window | separates one faulty cabinet from an attack |

Rule 2 is the "unknown cause" net (it fires at about T+9 min, close to containment); rule 1 is the lead detector. Rules 1 and 2 are built (`coldchain/rules.py`, created disabled; `make rules ENABLE=1`); rules 3-5 and `kb-thresholds` are not built yet.

### 8.3 Machine learning (epilogue and where no rule fits)

| Job | Detector | Partition / over | Use |
|---|---|---|---|
| `edge-inbound-population` | `high_sum(destination.bytes)` on flow summaries | over `host.name`, by `retail.device.role` | Epilogue: must flag `S07-TVBOX-01` |
| `cc-rare-source` | `rare(source.ip)` | partition `host.name` | Act 3 context |
| edge CPU / storage | `high_mean` on signage metrics | partition `host.name` | Epilogue |
| `cc-temp-rise`, `cc-temp-rise-population` | `high_mean(rise_5m)`, `bucket_span: 5m` (1m made 8% of the cabinets run away) | per `device.id` / over `device.id` | Kept as the honest comparison, re-run after the sensor change (below); not the Act 2 detector |

- **Sensor check:** the air channel (Sair, what alarms and rules read) rises 8-14 K in a defrost, the evaporator (S5) swings about 40 K (`coldchain.case.temperature.evaporator`). The first generator wrote the evaporator-scale swing into the air channel; fixed 2026-11-10. The air rise is an assumption to validate with a contractor.
- **Rule detections:** `ES|QL` rules, a new terms rule "First-seen internal peer" on flow summaries, and ML rules on the epilogue jobs.

### 8.4 Federated queries (06b section 9)
- **Act 3:** timeline joining the indexed audit with the raw flows from `raw_store_flows`.
- **Act 5:** 12 months of `raw_store_audit` in place. It finds the three first visits (S07, S11, S19 at T−126, −84, −49 days) that were never ingested. Record the query time.
- **Act 6:** hunt across all stores' raw flows for `203.0.113.0/24`.
- **Epilogue:** `raw_store_tls` checked against `kb-device-profiles`, giving 4.6 GB over 9 nights from the model hub.

Test whether dashboard ES|QL panels and Discover can use datasets on the tenant. If not, run the federated queries in Discover or the ES|QL query API and show the results.

### 8.5 Kibana objects
- **Built (`coldchain/dashboards.py`, `make dashboards`):** `coldchain-act0-sources` ("Act 0: The streetlight effect - we search where the light is": every source of truth in five tiers, from the `kb-sources` catalog, `make sources`), `coldchain-act1a-cabinet` ("Act 1": one cabinet, the contractor's view), `coldchain-act1b-estate` ("Act 2": the whole estate, central IT), `coldchain-act5a-history` ("Act 3a", federated), `coldchain-act5b-history-frozen` ("Act 3b", same history on the frozen tier, `make history-frozen`), `coldchain-hunt-findings` ("Act 4", the scheduled hunt, it raises the TV-box lead), `coldchain-epilogue-edge` ("Act 5", the evidence). Not yet: the case template, the Act 5 to 7 screens.
- **Act 1, estate dashboard:** draft it with Kibana's AI dashboard generation if available, then export it as saved objects.
- **Removed:** the "Case S07 — evidence" dashboard (old Act 4, a feed control and verdict panel) was dropped from Kibana and the story on 2026-11-16.
- **Epilogue, "S07 edge devices" dashboard:** indexed summaries plus a federated table, if supported.
- **Case template:** for the NIS2 early warning.

### 8.6 Response and AI
- **Workflows,** if enabled: block IPs, lock out and restore setpoints (mock service), notify, create case. The mock restore triggers `replay.py`'s restore events.
  - Fallback: a webhook connector plus a script, or a recording.
- **Built: the agentic SOC (the ending),** `coldchain/agent.py`: an Agent Builder agent (`make agent`, `make agent-ask`; the simplified branch has thirteen ES|QL tools and six steps, see the block at the top) that tells the story in four steps and proposes containment without running it. Preview; say so.
- **Built: the scheduled hunt, the AlertZero pattern** (`coldchain/hunt.py`, `make hunt`, `make hunt-run`): an Elastic Workflow every 30 minutes calls `cc-soc-hunter` and records findings in `cc-hunt-findings`. AlertZero itself is not offered on 9.5.6 Cloud Hosted (no `securitySolution:enableAlertZero` setting; see `docs/decisions.md`).
- **AlertZero "Cold-chain hunt" Watch,** if enabled, with the knowledge base and federated datasets in its context.
  - Fallback: Agent Builder with ES|QL tools (06b sections 4, 5 and 9) and a recorded video.
  - Mark both as "preview" on stage.

---

### 8.7 Context engine (act 6+, optional, early access)

**Purpose:** show that the assistant gets faster and more correct when it arrives knowing the estate. The context engine does **not** detect; rules, ML and joins detect.

- **Prerequisite:** context engine access on the tenant (it's request-access today). Without it, build the same thing as a fallback:
  - a `kb-context` index with a `semantic_text` field, holding the Knowledge Indicators (KIs) below;
  - an Agent Builder tool that retrieves them.

  Label the fallback "context-engine pattern", not the product.
- **KIs to build** (examples in 06b section 10):

  | KI type | Example |
  |---|---|
  | Relationship | store → owner → contractor → vendor-cloud account → controller model → firmware |
  | Source profile | `coldchain.audit` = parameter changes; `admin` = vendor default account |
  | Data quirk | controllers log local time; S12 reports °F; defrost windows differ by cabinet type |
  | Nightly fact | first-seen source IP per controller over 12 months; normal contractor login hours and IP ranges |
  | Manual fact | A03 = alarm delay, A13 = high alarm limit, setpoint maximum +50 °C |

- **Automations:**
  - Elastic Workflows on a nightly schedule, using ES|QL plus a small model where text extraction is needed.
  - The "nightly fact" automation reads the raw bucket once (data federation, or the re-ingest fallback), so daytime hunts don't need costly federated scans.
- **Data to generate:**
  - add a `contractor.account.id` to `kb-assets`, so that S03, S07, S11 and four more stores share one vendor-cloud account;
  - local-time timestamps on one controller family;
  - °F on store S12.
- **Access control:**
  - Each KI carries `retail.owner.id`.
  - Agents query with the asking user's permissions (document-level security), so one cooperative owner never sees another owner's KIs.
  - Verify how the context engine applies this.
- **Measurement:**
  - Run the act 6 hunt prompt twice with the same model: without KIs, then with KIs.
  - Record tool calls, input tokens, latency, and whether the shared contractor account was found.
  - Quote Elastic's published numbers (33 → 9 calls, −71% tokens) only as Elastic's test.

## 9. Storyboard adjustments implied by this architecture

Record these in `docs/decisions.md` and tell the presenter:

- **Act 3:** the flow row comes from the bucket (federated). Say "read in place".
- **Act 5:** the 12 months come from the bucket via data federation, not from the frozen tier. Line: "a year of raw store data, never ingested, one query".
- **Epilogue:** detection runs on the indexed summaries; the evidence (server name, JA3, chunks) comes from the federated raw TLS records.
- **Stage clock:** add the measured ingest latency.
- **Storage:** the storyboard's object store is Amazon S3, in an EU region. Say "the bucket central IT runs in AWS".
- **Connectivity:** the demo needs internet to reach Elastic Cloud and S3. Record the stage-wifi risk and the recorded fallback.
- **Platform:** Elastic Cloud Hosted on AWS, not Serverless (federation is unavailable there).

---

## 10. Acceptance tests (`make test`)

| Act | Assertion |
|---|---|
| Infra | Each store's credentials can write only to its own prefix and can't read, list or delete. Object Lock and versioning are on, Block Public Access is on. The collector picks up a new `detect/` file through SQS within the latency budget |
| 1 | Before T0: 0 alerts, all cabinets in band. At T0 + ingest latency: "parameter changes in the last hour" ≥ 46 |
| 2 | Rule 1 fires on all 46 attacked cabinets within one rule interval; rule 2 at ≤ 10 min with 0 false alarms over the 35 replay days (synthetic). Report the measured time from T0 |
| 3 | The timeline query (indexed + federated) returns login, setpoint `50.0` with `kb.verdict = "at documented maximum"`, the flow, and the alert |
| 3 rule | The limits rule returns `setpoint = 50.0`, 46 cabinets, 3 stores, one source |
| 4 | Removed (the evidence dashboard with the verdict panel was dropped on 2026-11-16) |
| 5 | The federated 12-month query finds exactly three first visits from the attacker address: S07 at T−126 d, S11 at T−84 d, S19 at T−49 d, none older, none indexed. Report the query time and the number of S3 requests if available |
| 6 | 06b section 4 returns the 7 at-risk stores. The federated hunt returns 9 touched stores |
| 7 | The mock received all four calls; warmest cabinet ≤ setpoint + 3.5 K; a case exists |
| 6+ | The context-engine run makes fewer tool calls and uses fewer input tokens than the baseline, and names the shared contractor account. The baseline does not. Report both runs. A user scoped to one owner retrieves only that owner's KIs |
| Agent | The scripted question makes the agent call the history, footprint, device-evidence and exposed-controller tools, name S07, S11 and S19 as first visited, the TV box and `models.example-hub.net`, the 7 stores at risk and the shared contractor account, and run no containment. Report the tool calls and the time |
| Epilogue | Offline window files arrive late. The new-terms rule fires on TVBOX→SM800; the epilogue ML population job flags `S07-TVBOX-01`. The federated TLS query returns about 4.6 GB, 9 nights, `models.example-hub.net` |

`make verify` prints a readiness report with every measured latency and the S3 request counts.

---

## 11. Milestones

1. **Infra:** S3 bucket (versioning, Object Lock, Block Public Access, lifecycle), IAM identities and policies; the Elastic Cloud Hosted deployment (pinned version, federation enabled); `.env`; setup and teardown. **Go/no-go: data federation against the bucket, including gzip NDJSON.**
2. **Store-in-a-box:** S07 Docker Compose (Agent → Logstash → S3), offline buffering test.
3. **Generator:** chain, telemetry, audit history, network; backfill to `raw/` and `detect/`.
4. **Central ingest:** collector reading the SQS queue, data streams, `reroute` pipeline; latency measured.
5. **Federation:** data source, datasets, the four federated queries; timings measured.
6. **Detection:** ML jobs, rules; time to first alert measured.
7. **Replay and response:** `replay.py`, mock service, Workflows or fallback.
8. **Screens and AI:** dashboards, case template, AlertZero or Agent Builder.
9. **Scenario B:** edge data, epilogue queries and dashboard.
10. **Context engine (optional):** KIs, nightly automations, the two-run measurement, the access-control test.
11. **Hardening:** acceptance tests, readiness report, rehearsals at 10× and 1×, recorded fallbacks for federation, AlertZero, Workflows and the context engine.

---

## 12. Verify on the tenant before building on it

- **Context engine:** access (early access), its configuration API, how it applies document-level security per owner, and whether its automations can read data-federation datasets.

- **Data federation:**
  - availability in the tenant's version;
  - the exact settings to enable it (Elasticsearch and Kibana);
  - API request bodies for data sources and datasets;
  - how the ECH deployment authenticates to S3 (federated identity role, or access keys);
  - the most recent 9.x version's status (experimental or preview) and whether it is on by default;
  - resource-pattern syntax and file filtering;
  - **gzip NDJSON support** (the docs list Parquet, NDJSON, CSV and TSV, not gzip);
  - schema inference across files;
  - whether Discover and dashboard panels can query datasets;
  - performance over 12 months × 20 stores of hourly files;
  - S3 request costs and cross-region transfer.
- **S3 ingest:** the AWS S3 input in SQS mode against the bucket; gzip NDJSON handling; dead-letter queue behaviour; routing by `event.dataset`; end-to-end latency.
- **AWS setup:**
  - Object Lock enablement on the new bucket, and the teardown path (governance bypass, all versions and delete markers);
  - per-store IAM policies actually deny read, list and delete;
  - bucket names are global, so the suffix scheme works;
  - service quotas for 20+ IAM users (default is fine).
- **Logstash S3 output:** rotation by time, `json_lines` codec with gzip, persistent queue behaviour while "offline", credential handling.
- **Connectivity:** whether the stage network can reach Elastic Cloud, S3 and SQS; the recorded fallback if not.
- **Workflows and ES|QL rules:** whether Workflows is GA or technical preview, and whether ES|QL rules are still preview, on the deployed version (sources disagree).
- **ES|QL:**
  - multi-field `LOOKUP JOIN` (otherwise use the composite key from 06b);
  - `MATCH` on `semantic_text`;
  - mixing indices and datasets in one `FROM`.
- **Rules and Kibana:** ES|QL rule and new terms rule types; which fields ML-rule alerts carry; options-list controls filtering ES|QL panels.
- **Previews:** Workflows and AlertZero enablement and configuration APIs.
- **Physical assumptions:** the warming curve (validate with a refrigeration contractor); smart-plug resolution at 3–7 W.

---

## 13. Out of scope

- Real Danfoss or vendor-cloud integration.
- Real store sensors or packet capture.
- Edge clusters, cross-cluster search or replication, regional hubs. These remain options in the storyboard appendix.
- Elastic Cloud Serverless (federation unavailable) and self-managed Elastic.
- Other S3-compatible stores (MinIO and similar). The design is the same, but this demo uses Amazon S3 only. Federation support for non-AWS endpoints is undocumented.
