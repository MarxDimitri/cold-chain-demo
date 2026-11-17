# Decisions

## Platform
- **Elastic Cloud Hosted on AWS, not Serverless.** ES|QL Data Federation is listed as unavailable on Serverless, and Serverless has no `_snapshot/*` APIs for the fallback. Stack version: newest 9.x, pinned (record the exact version here once deployed).
- **Object store: Amazon S3** (EU region, default `eu-central-1`), same region as the deployment.

## AWS infrastructure (`infra/`, Terraform)
- **Terraform**, not CloudFormation. `make plan-aws` previews, `make setup-aws` applies and writes `.env` and `.secrets/`, `make verify-infra` runs the acceptance checks, `make teardown-aws` empties the bucket (governance bypass) and destroys the stack.
- **State is local** and holds the IAM access keys in plain text (git-ignored). Acceptable for a demo; use a remote encrypted backend if the stack is shared.
- **Store identities:** one IAM user per store with `s3:PutObject` on its own `detect/` and `raw/` prefixes only. Keys are written to `store-keys.json` for the generator.
- **Collector:** IAM user reading `detect/*` plus the SQS queue (`ReceiveMessage`, `DeleteMessage`, ...). Notifications: `ObjectCreated` on `detect/` to one queue with a dead-letter queue (5 receives).
- **Mandatory SA sandbox tags** (hive-mind skill `hive-sa-cloud-tagging`). The AWS account's org SCP denied `sqs:CreateQueue` until the resource carried `project`, `team`, `org`, `division` and `keep-until`. Terraform sets them as provider default tags: `project=dimitri-coldchain`, `team=emea_dach_area`, `org=sa`, `division=field`, `keep-until=2027-02-07` (90 days). **Custodian deletes expired resources**, so extend `keep-until` (variable `keep_until`) before it passes, or the stack and its bucket disappear. Sandbox cost guidance: stay under about $300/month; this stack costs a few dollars.
- **AWS provider ~> 6.0**, because 5.x cannot read `aws login` credentials; boto3 needs `botocore[crt]` for the same reason.
- **Federation:** an IAM user with read access to `raw/*` for now. Federated identity (an IAM role) replaces it once Elastic's trust details for the deployment are confirmed.
- **Bucket:** versioning, Object Lock (governance, 7 days), Block Public Access, SSE-S3, TLS-only policy, lifecycle for noncurrent versions and multipart uploads.
- **Applied** to account 461485115270, `eu-central-1`, bucket `coldchain-41ac8e`. `make verify-infra` passes 16/16 (store write-only isolation, collector and federation scopes, lock, versioning, BPA). The checks write `dataset=infra.check` objects, which stay for the lock period.

## Data generator
- **Backfill file rotation.** Backfill writes `detect/` files hourly (`--detect-rotation 60`) instead of every minute, to keep 35 days of history to about 50k objects. Live replay uses 1-minute files.
- **Exposure lives on the system manager.** Only `Sxx-SM800` rows in `kb-assets` have `coldchain.exposure.internet = true` (16 of them). Cabinets are `false`, so the act 6 query in 06b section 4 counts controllers per store and returns the 7 untouched stores.
- **Login events carry `device.id = Sxx-SM800`**, so act 6's "touched" check and the act 3 join to `kb-assets` work.
- **Contractors log in as `admin`** from `198.51.100.0/24` (the vendor default account), which is why the act 5 query excludes that range.
- **A13 (chilled) and A03 (chilled) limit rows are seed assumptions**, not manual facts. Only the setpoint row is page-referenced (p.3) in our brief. `kb-manuals` rows other than the setpoint fact are marked `kb.verified = false` until checked against RI8KL45J.
- **Attack set:** 46 cabinets = S07 C01-C16, S11 C01-C16, S19 C01-C14. Touched stores (logins): S01, S02, S04, S06, S07, S08, S10, S11, S19. Patched: S13, S15, S16, S18.
## Replay
- **T0 includes a 3-minute pre-roll.** The replay starts at T0−3 min so the logins at T0−2m20s happen after the start. `--t0 now` rebases onto the wall clock; `--t0 config` replays 2026-11-12 03:52 and continues the default backfill with no jump (telemetry is a pure function of absolute minute).
- **All 9 touched stores show up in raw flows through their inbound login session** (attacker → system manager, tcp/443). 06b's act 6 query matches the attacker range as source or destination, so this is what makes the federated hunt return 9 stores. S07 additionally has the outbound flow at T0+11s. Destination is the manager's LAN address (NAT ignored).
- **Warming is overlaid on the cabinets' own series.** While the setpoint is +50, air = setpoint + exponential excess (about +3 K at T0+10 min, calibrated assumption) and the cabinet reports `setpoint: 50`. After the restore it decays over the 25-minute pull-down.
- **Restore** is automatic at T0+10 min (`--restore auto`) or on `python -m coldchain.replay trigger` (`--restore trigger`, with a timeout), which the mock response service will call. Restore events come from user `workflow-restore`, source `10.99.0.5`.
- **File rotation in replay:** `detect/` is 1-minute files; `raw/` is hourly, so raw files are written when the run ends.
- **`make reset` clears local state only.** Removing attack data from the cluster and bucket needs delete-by-query plus a governance-bypass delete; not built.
- **S07 files mode** (`--s07-mode files`, optional `--netflow host:port`) writes S07's records to `replay/s07/*.ndjson` and sends NetFlow v5 over UDP. It is untested against a real Elastic Agent.

## Elastic Cloud (indexed side)
- **Deployment:** ECH 9.5.6 on AWS `eu-central-1`, Enterprise licence (active to 2028-02-29). Federation enabled by setting `esql.federation.enabled: true` in the deployment's user settings (off by default on 9.5).
- **ECS first.** Streams inherit the built-in `logs@*` / `metrics@*` / `ecs@mappings` components. Custom fields live only under `coldchain.*`, `retail.*`, `kb.*`; the single extra mapping component is `coldchain-mappings`. `ecs.version` is set to 9.4.0 (assumption: sources disagree on the latest ECS; confirm).
- **Generator gaps fixed in the ingest pipeline, not by regenerating:** `event.type` for telemetry and flows, `ecs.version`, `event.ingested` (mapped as `date`; scenario B compares it with `@timestamp`), and `network.flows` (not ECS) moved to `coldchain.netflow.flows`.
- **Routing:** the collector's integration sends everything to `logs-coldchain.ingest-default` with pipeline `coldchain-route`, which sets the data stream type and reroutes by `event.dataset` to `logs-coldchain.audit-default`, `logs-coldchain.case-default` (aliased as `metrics-coldchain.case-default`), `logs-netflow.summary-default`. Unknown datasets (for example `infra.check`) land in `logs-<dataset>-default`.
- **Telemetry is a `logs`-type stream with a `metrics-` alias.** The collector's Fleet-generated API key can write only `logs-*-*` (Custom AWS Logs is a logs-type input package), and Fleet refuses `output_permissions` overrides; an output-level role-descriptor override was accepted but not applied. No general metrics-type S3 reader exists in the Fleet catalog (the only metrics-type S3 input is `aws_billing`, for Cost and Usage Reports). So telemetry goes to `logs-coldchain.case-default`, and `metrics-coldchain.case-default` is a data stream alias created by `coldchain.elastic setup`, so 06b's queries and the ML datafeeds keep the documented name. Say "logs-type stream, metrics alias" if asked; ES|QL `FROM` and datafeeds work through the alias (ES|QL verified).
- **Telemetry lost before the fix.** While the stream was routed to `metrics-`, the collector got 403s and dropped those records; SQS messages were already deleted. After the backfill drains, reconcile per store-hour (documents vs. objects) and re-trigger the missing `detect/dataset=coldchain.case/` objects.
- **Retention:** data stream lifecycle 40 days; the long history stays in the bucket.
- **Collector:** Fleet policy `cold-chain-collector`, Custom AWS Logs (`aws_logs` 1.8.3) in SQS mode, NDJSON parser, run as an Elastic Agent container (`compose/collector`). gzip handling by the S3 input is unverified until the first real file is read.
- **Not yet done:** `kb-manuals` (needs a `semantic_text` inference endpoint), ML nodes (the deployment showed 0 ML memory; check autoscaling before the ML milestone).

## Data federation (go/no-go: GO)
- **Works on ECH 9.5.6 with the bucket in `eu-central-1`:** data source `cold-chain-s3` (type `s3`, static read-only credentials for the `raw/*` identity, `region` must be set or it defaults to `us-east-1`), datasets over `s3://<bucket>/raw/dataset=<d>/**/*.ndjson.gz`. gzip NDJSON is read (the codec comes from the final extension), Hive-style `store=`, `dt=`, `hh=` folders become columns. Setup: `python -m coldchain.federation setup`.
- **Hard limit: 10,000 files per dataset listing.** The cluster setting `esql.external.max_discovered_files` is accepted but had no effect on this build. The original raw audit history was ~24,000 hourly files (one event each), so a 12-month query failed. **Raw audit is now written as one file per store per day** (`--raw-audit-rotation 1440`, at most ~7,300 files). The 15,948 hourly raw audit versions were deleted (governance bypass) and regenerated. Flows stay hourly (7 days, ~3,400 files). The same limit applies to the optional 12-month raw telemetry: write it daily too.
- **Documented limitation (decision: no compaction in the demo).** The 10,000-file limit caps federated datasets: about 7,300 daily files for 20 stores x 12 months leaves ~27% headroom; hourly raw data over about 14 days x 20 stores would fail (flows: 7 days hourly = ~3,400 files; 30 days would be ~14,400). Real fleets hit it within weeks. Not built, but this is what a production design needs:
  - a central compaction job (daily/weekly Parquet) writing to a separate prefix, because Object Lock prevents deleting the locked hourly originals (they expire through lifecycle);
  - tiered datasets (recent hourly + compacted history) queried with `FROM a, b`;
  - daily rotation of the raw pipeline on a real store box, which holds a day of data locally before upload.
  Unverified: whether filters on the `store`/`dt`/`hh` partition columns narrow the listing. Open question for Elastic: why `esql.external.max_discovered_files` had no effect on 9.5.6. Say on stage: "experimental, 10,000 files per dataset, so production compacts."
- **Dataset names:** `raw_store_audit`, `raw_store_flows` exist; `raw_store_tls` and `raw_edge_metrics` come with scenario B.
- **Timing:** first query over two stores took 9.8 s; the 20-store timing is measured after the backfill completes.

## Independent probes and attack variants (added after the market review, see market-and-story-review.md)
- **`coldchain.probe` dataset:** one independent logger per cabinet (`Sxx-LOGGER`, role `temperature-logger`, own cellular uplink,
  no store-LAN address), 5-minute readings = true air temperature + per-cabinet bias (sd 0.2 K) + noise (sd 0.15 K), so it agrees
  with the controller within about 1 K in normal operation (tested). Indexed from `detect/` only (35 days, ~4.8M documents).
  Stream `logs-coldchain.probe-default` with alias `metrics-coldchain.probe-default` (same collector-permission reason as telemetry).
  `kb-assets` has a `Sxx-LOGGER` row with `coldchain.independent = true`.
- **Forced-defrost variant (A2):** `replay --scenario defrost`. No setpoint change; repeated `defrost-start` from the attacker address.
  Audit action names: `defrost-start` / `defrost-stop`; normal defrosts are `user.name = system` from the store LAN on a schedule, and are logged
  against the system manager device, not per cabinet.
- **Telemetry spoof option:** `replay --spoof` (or `telemetry_spoof.enabled` in attack.yaml). Hypothetical: nothing in the public reports
  confirms spoofing; CSA and Brit say it is possible.
- **Still to build:** the divergence rule (controller vs probe, join on `device.id` and 5-minute bucket), a forced-defrost rule
  (non-`system` defrost command from outside the store LAN, out of schedule, many cabinets), and the session/change-log split suggested by Forescout.
- **T0 confound: resolved (see "T0 moved" below).**
  elevated there. Check before relying on ML scores at that time; shifting T0 away from the defrost slots is the fix.

## ML check, first results (training still running)
- **Defrost false positives are learnable.** Frozen-cabinet defrosts raise `rise_5m` to about 4-5.6 K, more than the attack's ~1.5 K per 5 minutes, so early scores
  were high. Population job: records scoring >= 75 per day fell 96, 18, 7, 6, 1, 1, then 0 from 14 Oct (max score <= 22 since). Per-cabinet job (1-minute buckets,
  480 models): 222, 297, 33, then 0 on day 4. The models learn the 03:00/11:00/19:00 UTC schedule in about 4 to 6 days. Training the 1-minute job over 35 days takes
  about 1.5 to 2 hours.
- **Generator flaw found and fixed: the attack was replayed on top of a defrost recovery.** T0 was 03:52 UTC, inside the pull-down of the 03:00 defrost: at 03:45 a frozen
  cabinet (S07-C14) was still at -18 C with `rise_5m` of -5, and the replay replaced the baseline with `setpoint + excess`, so the air jumped from about -19 to -24 C
  before warming. Fixed by moving T0 (next item).
- **T0 moved to 2026-11-12 07:52 UTC** (config/attack.yaml), a quiet window: defrost slots are 03:00, 11:00, 19:00 UTC and each cycle plus pull-down lasts 70-85 minutes.
  The history now ends at 07:47. Procedure used (no full regeneration, data is a pure function of the absolute minute): stop writers, drain the queue, delete from
  Elasticsearch every document with `@timestamp >= 2026-11-12T03:00Z` in the four detect streams (26,712 docs), delete from S3 (all versions, governance bypass) the
  `dt=2026-11-12` objects with `hh >= 03` plus the raw audit file of that day (110 versions), then `backfill --resume`. For a live `--t0 now` demo the history must be regenerated to
  end at the demo time, and a guard should refuse a start inside a defrost window (not built).
  cabinet (S07-C14) is still at -18 C with `rise_5m` of -5. The replay replaces the baseline with `setpoint + excess` at T0, so the air jumps from about -19 to -24 C
  before warming. That artefact would feed ML. Fix: move T0 into a quiet window (between about 04:30 and 10:30 UTC) or move the defrost slots.
- **Blind spot to state honestly:** an attack timed inside a defrost window hides in `rise_5m` noise; command source, schedule and cross-store simultaneity still catch it.

## Rule design: assume any single log source can be forged
- **Allow-lists, not "outside the network".** A scheduled defrost comes from the system manager itself (`user.name = system`, `source.ip` = the manager's own address). Any defrost
  command from another user or source address is a violation, including store-LAN addresses, because a compromised camera or TV box (scenario B) is inside the network.
- **Trust boundary per source.** Controller audit and telemetry are controlled by the controller; independent probes (own uplink) and router flows by other devices; objects in the
  bucket are write-only and locked. A rule that needs one source can be defeated by owning it.
- **Prefer contradictions between sources:** (1) effect without cause: probe warming with no logged command or setpoint change; (2) cause without session: a logged command with no router
  flow to the manager; (3) silence: an expected heartbeat or telemetry stream stops; (4) a third physical signal (smart plug or current on the defrost heater) would be independent of the controller.
- **Out of reach:** an attacker who owns the controller, the store network path and the probe uplink. The aim is to raise the cost, not to claim immunity.
- **Variants to add to prove it (not built):** forced defrost issued from an internal camera address (pivot); log tampering (audit events removed, probe still shows the warming).

## Risk to check before the ML milestone
- **Defrost vs attack signal.** A frozen cabinet's defrost raises the air from −24 to about 0..+5 °C, a `rise_5m` of several K, larger than the attack's roughly +1.5 K per 5 min. The `cc-temp-rise` job may score defrosts at least as high as the attack, unless the model learns their fixed schedule. Check this in milestone 6; the fix may be shortening or damping the generator's defrost peaks.

- **Not yet generated:** attack replay events, scenario B data (TLS records, signage metrics, smart plug, offline window), local-time and °F quirks for the context engine.

## Story framing: the realms customers are not watching (2026-11-09)

Federation and cheap object storage are not unique, so the demo does not sell the mechanism. It sells coverage of
data customers skip today for cost or ownership reasons:
- **Endpoint tax:** per-endpoint licensing makes a controller, camera or TV box too expensive to cover. Here stores
  run no agent and no cluster; they write to a bucket.
- **GB tax and retention tax:** ingest-priced storage makes a year of raw flows and audit unaffordable, so it is dropped.
  Here only the small detect stream is indexed (35 days); the year stays in the bucket and is queried in place.
- **Ownership gap:** refrigeration telemetry is observability data, outside the security team's view. Here the same
  telemetry feeds the ML and the detection rules, and an independent probe feed checks the controller.
- Pricing slide (partner deck): one subscription, metered on consumption, start small. Use it for the commercial
  line only; do not state prices or federation pricing (experimental, not priced).

Measured on 2026-11-09 (history to 2026-11-12 07:47): indexed 2.25 GB primary store (40 d); `detect/` 362 MB in
39,418 objects; `raw/` 22 MB in 10,783 objects. **Gap:** raw is only 6% of detect because raw holds audit and flows
only. The "bulky data stays in the bucket" claim needs realistic raw volume (full flows, TLS records, edge metrics,
5-minute raw telemetry). Scenario B and the optional raw telemetry history close it; until then do not quote ratios.
ML history: both jobs trained on 35 days plus the extension to 07:47 (24,307,200 records).
Minor: probe history is missing for about 7 stores in the first hours of 2026-10-08 (cosmetic, outside the demo window).

## Defrost model follows the manual (2026-11-09)

Reason: the ML scoring showed the +50 attack warms the air slower than a normal defrost, so rise rate alone cannot
tell them apart; the controller's own state (is a defrost running, was it scheduled) can. Details and sources:
`docs/defrost-research.md`.
- `config/defrost.yaml` is the single source: manual facts (factory settings, ranges, p.3) and this chain's
  configuration (three clock starts = factory d03 8 h, 35 to 45 min = inside d04 45 min). `coldchain/defrost.py` is
  read by telemetry, audit and the knowledge base.
- Telemetry carries `coldchain.case.defrost.active` (the defrost relay, readout u60). A +50 setpoint keeps it off; a
  forced defrost (A2) switches it on; a spoofed controller reports the normal state.
- Scheduled `defrost-start` and `defrost-stop` audit events are now per cabinet, from the same windows as the
  telemetry (before: three per manager a day, up to 18 min off the curve). Raw audit grows; this helps the "raw is
  bigger than detect" claim only a little.
- Knowledge base: `kb-controller-limits` gains kb.factory and the defrost rows (d02, d03, d04, d06, A12) with
  kb.expected.basis; `kb-manuals` holds 12 page-referenced, verified paraphrases; new `kb-regulations` holds 9
  sourced facts with `kb.verified` (primary text read or not).
- **Not yet applied to the data in the cluster and bucket.** The generated history (35 days telemetry, audit) still has
  the old shape (no relay field, 2 or 3 defrosts a day). Applying it means deleting and regenerating telemetry and
  audit in S3 and Elasticsearch, retraining the ML jobs, and re-running the scoring. Awaiting go-ahead.
- Assumption flagged: air peak 0 to +5 °C during defrost (see defrost-research.md, last bullet).

## ML scoring results (2026-11-09, models trained on 35 days to 2026-11-12 07:47)

Method: `coldchain/mlscore.py` freezes the trained snapshot, replays each scenario into a throw-away index, and
reverts afterwards. The replay generator matches production data exactly (816 documents compared, 0 differences).
- **Control, 4.2 h, no attack:** nothing at score 75 or above, but normal defrosts reach 69.7 and 73.0.
- **+50 setpoint (A) and forced defrost (A2):** the per-cabinet job flags none of the 46 cabinets at 50 or above
  (best 43.4). The population job produces no records. The attack's peak rise_5m is 1.67 K; normal frozen history
  has p99 4.79 K (defrost).
- **Spoof:** only the restore step (a +3 K jump when real values return) scores about 50.
- **Trained-model defect:** since 7 Nov, S17-C17, S17-C24, S18-C24 and S18-C19 (chilled) have run-away models
  (expected value drifts to -35 K on flat data, scores 80 to 93 every minute, about 9,500 records).
- **Experiment, 72 cabinets, retrained on the same history:** `high_mean(air)` at 1 m and 5 m buckets also detects
  0 of 16 attacked cabinets; the rise job did not reproduce the run-away (max 22), so that defect is
  training-run dependent. Raw temperature, with or without rate, cannot see a +3 K/10 min drift on a cabinet that
  swings 24 K in a normal defrost.
- **Consequence:** acts 2 and 3 cannot assert "ML score >= 75" on temperature alone. Needs the defrost relay and
  schedule as context (see the defrost section above), and the setpoint rule stays the primary detector.

## Defrost groups instead of one estate-wide defrost (2026-11-10)

**Decision:** frozen cabinets defrost in 4 groups per store, 45 min apart, with a per-store shift of 0 to 39 min
and a +-2 min start spread inside a group (`config/defrost.yaml`). Telemetry and audit were regenerated once.

**Why:** the first model started every frozen cabinet of every store within 10 min of the same clock slot. That is
not how a real estate is run, and it made a population ML job look better than it should: when all 320 cabinets
warm together, a peer baseline cancels the schedule perfectly. With groups about 20 to 25% of the cabinets are in
defrost at any time, a harder and more believable baseline. The manual gives the tools (`d05`, coordinated defrost
with `S1` and `o16`) but no store layout, so the group layout is an assumption to validate with a contractor.

**How to apply:** score the population job on this data. Anything that separates the attack here is believable.

## ML scoring on the defrost-group data (2026-11-10)

Same harness as before (frozen baseline snapshots, real replay generator, 46 attacked cabinets, 4 scenarios). Jobs
retrained on 35 days with defrost groups: `cc-temp-rise` per cabinet with relay-on records excluded,
`cc-temp-rise-population` over all records (defrost stays in). Feature for both: `rise_5m`.

| Run | cc-temp-rise, targets at score >=50 / >=75 | population, targets at >=50 |
|---|---|---|
| setpoint +50 | 16/46 (all 3 stores, first +175 s) / 4/46 (S07 only, first +355 s) | 0/46 |
| forced defrost | 4/46 / 2/46 (relay-on records are excluded by design) | 0/46 |
| spoof | 25/46 / 18/46, but first at +595 s = the restore, when the real temperature reappears (artifact) | 0/46 |
| control (no attack) | 1/46 / 0/46; 75 records >=75, almost all on chilled cabinet S15-C20 | 5/46 at +3.8 h, unrelated |

- S07-C14 peaks at 68, below the 75 the acceptance test asks for. Per-cabinet ML on `rise_5m` is a weak, partial
  detector of the +50 attack, not the headline.
- Population on `rise_5m` fails (0/46): the rise of 1.7 K in 5 min is lost against the spread of the peers.
- A persistent false positive on one chilled cabinet (S15-C20) breaks "0 alerts before T0" at 75. It did not come
  from the data (its rise statistics are normal) and has now appeared in three trainings; not yet understood.
- Spoof detections are an artifact of how the spoof ends. Do not quote them.
- Next: population job on a duration-style feature (time above the band) against a threshold rule baseline.

## S15-C20 false positive: cause and fix (2026-11-10)

**Cause:** not the data (its `rise_5m` statistics match its peers) but the 1-minute bucket of `cc-temp-rise`. About 8%
of the 480 cabinets ran away, deterministically: the same cabinets on a three-store re-train (S09-C01, S15-C20,
S15-C02), with a "typical" value far outside anything the cabinet does and sustained scores of 90+. I did not find why
those cabinets; the compressor period explains little. 5-minute buckets removed the run-away (top cabinet 75 records
at >=75 over 28 days of training instead of over 1,000); 15-minute buckets lost the attack and gave 18 false-positive
cabinets, so `cc-temp-rise` now uses `bucket_span: 5m`.

**Result on all 480 cabinets, four scenarios:**

| Run | cc-temp-rise targets at >=50 / >=75 | false positives at >=75 | population targets |
|---|---|---|---|
| setpoint +50 | 3/46 (S11, S19; first +175 s) / 1/46 | 2 records, one cabinet | 0 |
| forced defrost | 1/46 / 0/46 | 2 records, one cabinet | 0 |
| spoof | 6/46 / 1/46 (artifact at the restore) | 2 records, one cabinet | 0 |
| control | 1/46 / 0/46 | 9 records on 7 cabinets, max 86, nothing sustained | 5/46 at >=50 at +3.8 h, 1 record at 75 |

**Consequence:** the false-positive problem is solved; the sensitivity problem is not. Per-cabinet ML on `rise_5m`
sees 1 of 46 attacked cabinets at 75 and cannot be the headline detector. An ML rule on it would need a threshold
above 86 to stay silent before T0. Next: a population job on a duration-style feature (time above the band), against a
threshold-rule baseline.

## Threshold rule versus ML on cabinet temperature (2026-11-10)

All numbers on the synthetic data with defrost groups (so the zero false alarms below are a property of clean
synthetic history, not a promise for a real estate). Probe script: `coldchain/ruleprobe.py`.

**Rule:** a cabinet is in excursion when its air is more than T K above its nominal temperature (frozen -24, chilled
+2) with the defrost relay off and more than X minutes after the last relay-off (the controller's own A12 idea,
which defrost recovery needs). Alert when 3 of the last 5 minutes are in excursion.

| T | hold X | setpoint +50 detected | first alert | false alarms in 35 days x 480 cabinets |
|---|---|---|---|---|
| 1.5 K | 30-90 min | 46/46 | 475 s | 0 |
| 2.0 K | 30-90 min | 46/46 | 535 s | 0 |
| 2.5 K | 30-90 min | 43/46 | 655 s | 0 |
| 2.0 K | none | 46/46 | 535 s | about 34,000 (one per defrost) |

Forced defrost is not seen (relay on): it needs its own rule (relay on outside the schedule, command source not
`system`, probe divergence).

**ML on the same feature:** population job on a scripted "unexplained warm" indicator (5- and 15-minute buckets),
subset S15, S09, S19: 0/14 attacked cabinets at 50 or above, max score 24, silent on control. The per-cabinet job
(`rise_5m`, 5-minute buckets) flags 1/46 at 75. No ML variant on cabinet temperature beats the rule.

**Consequence:** for known attack mechanisms on cabinet temperature the deterministic rules lead and ML adds
nothing measurable. "Three stores at once" is a plain ES|QL aggregation (distinct stores with 3+ cabinets in
excursion). ML earns its place where no rule exists: scenario B (`edge-inbound-population`, new peers, bytes), and
as an unknown-cause hint only if a variant proves itself. Act 2 of the brief and the storyboard need rewording;
that is the presenter's decision.

## Duration rules and slow warming (2026-11-10)

**Scenario (hypothetical, scoring harness only, `slow_warming` in config/attack.yaml):** an unknown cause such as a
failed evaporator fan or a door left open. Twelve frozen cabinets (S05 C01-C06, S14 C01-C06) warm gradually to
+1.5 K above nominal over about 16 minutes, stay there for 120 minutes, defrost relay off, no audit event, no flow.
The 10-minute attack cannot test duration; this can. Probe: `coldchain/ruleprobe_duration.py`.

| Detector | Detected | First alert after start | False alarms (35 days x 480 cabinets) |
|---|---|---|---|
| Rolling 30 min mean of (air - nominal) above 0.5 K, relay off, 30 min after a relay-off | 12/12 | about 21 min | 0 |
| Same with 0.4 to 0.8 K, 20 or 30 min windows | 12/12 | 13 to 27 min | 0 (0.3 K gives thousands) |
| At least 24 of the last 30 min above 0.8 K | 12/12 | 52 min | 0 |
| The 2 K 3-of-5 rule | 0/12 | never | 0 |
| cc-dev-30m, per-cabinet ML on the 30-minute mean deviation | 7/12 at >=50, 6/12 at >=75 | 38 to 68 min | one record at 74; also fires after the 11:00 defrost recovery in the control run |
| Population ML, same feature | 3/12 at >=50, all after the 11:00 defrost (same as control) | not a detection | 3/12 cabinets flagged in control |

**Why the mean:** the compressor cycle swings the air by about +-1 K and averages out over 30 minutes: the normal
30-minute mean never exceeds 0.39 K in 35 days, the slow warming sits at 1.3 K. Counting minutes above a threshold
works worse because the swing keeps dipping a warm cabinet below it.

**Expected duration, in numbers:** relay on 41 min typical, 46 maximum (manual d04 = 45); recovery 19 to 24 min above
+2 K after relay-off; longest relay-off excursion 26 min in 35 days; controller alarm delays A12 = 90 min (after
defrost) and A03 = 30 min (manual p.3).

**Result:** a deterministic duration rule catches the slow warming completely and earlier than ML, and needs no
training. ML (per cabinet) catches about half, later, and alarms on the post-defrost recovery because it has no
notion of the hold-off. The remaining use for ML on temperature is learning per-cabinet thresholds at scale, which
this data does not require. Same conclusion as for the fast attack: rules lead.

## Storyboard v2 (2026-11-10)

`docs/06 · Cold-Chain Demo — Storyboard v2.pptx` and `docs/storyboard-review.md`: Act 2 reframed from ML to knowledge-base rules,
a new optional Act 2+ (onboard new equipment), an "Elastic tech" strip on every act, MinIO references changed to Amazon S3.
Open decision: the on-screen clock (03:52 narrative vs 07:52 data); recommended night T0 with shifted defrost slots.

## Response to the storyboard review (2026-11-10)

- **Accepted:** Act 2 is rules from the KB; ML moves to the epilogue; Agent Builder carries Act 6, AlertZero is the alternative; Amazon S3 with SQS; no cost ratio in Act 5; the independent probe is the fourth source in Act 4. Brief sections 8.2, 8.3 and the Act 2 and epilogue acceptance rows rewritten.
- **Sensor check (challenge 1, upheld):** the generator wrote a 24-29 K defrost swing into the air channel, which is evaporator scale. The air now rises 8-14 K (`air_rise_k`, assumption) and a separate evaporator channel `coldchain.case.temperature.evaporator` (S5, about -30 to the d02 stop temperature, 6-8 C) carries the large swing. Telemetry regenerated once more together with the night T0 (defrost slots 05:00/13:00/21:00 UTC, T0 02:52 UTC = 03:52 CET). Offline rule probes unchanged: rule 1 46/46, rule 2 46/46 at 535 s, 0 false alarms; slow-warming rule 12/12. The three ML jobs are re-run after the backfill and the result kept either way.
- **File limit (challenge 2):** Elastic's docs describe `esql.external.max_discovered_files` as a dynamic setting (default 25,000). On 9.5.6 Cloud Hosted it was accepted but a dataset still matched 10,000 files. Wording: "default cap". Re-test with the 12-month federated query.
- **Clock:** 02:52 UTC is clear of the last defrost (about 00:40 UTC) and its 90-minute alarm delay (A12) ends about 02:10, before T0.
- **Still to verify on the tenant:** rule type behind rules 1-2 (does `LOOKUP JOIN` carry `retail.store.id` into the alert), dashboard controls over ES|QL panels, `waitForApproval` label (approve inside Kibana, never an emailed link, in Act 7), LLM connector token cost per act, 9.6 on Cloud Hosted.

### ML re-run after the sensor fix (2026-11-10, synthetic data, night T0 history)

Models retrained on 35 days with the air rise at 8-14 K (evaporator separate). Scored with `coldchain.mlscore` against 46 attacked cabinets:
- `cc-temp-rise` (per cabinet, 5 min): **9 of 46 at score >= 75, 19 of 46 at >= 50**, first record at T0+175 s (was 1 of 46 before the fix). Control run (no attack): 5 records on 3 cabinets at >= 50; attack run: 10 false-positive records on 8 cabinets.
- `cc-temp-rise-population`: 0 of 46 at 50 and at 75 (max score 16.4).
- Reading: the smaller defrost swing helps the per-cabinet model, but 9 of 46 is not a detector; the population job still cannot see 3 stores warming together. Act 2 stays rules (46/46). Not quoted: the harness `bucket@` first-bucket times (they show 07:45, outside the replay window, so the label is suspect; unverified).

## Scenario B built: TV box, edge metrics, ML and rule (2026-11-10, synthetic, hypothetical)

- **Data** (`config/scenario_b.yaml`, `coldchain/scenario_b.py`): 21 days from 2026-11-19 in the `epilogue` namespace, routed by `labels.namespace` (the pipeline `reroute` takes `["{{labels.namespace}}", "default"]`). The main streams and live replay are untouched. 123 chunks of 20-60 MB over 9 nights from `models.example-hub.net` = 4.6 GiB (the 06b query divides by 2^30). Internal flows escalate: TVBOX to signage tcp/8080 (12-02), signage to camera tcp/554 (12-05), TVBOX to the system manager tcp/80 (12-07). `S07-SIG-02` CPU about 97% for 4 days with storage 62% to 8%; plug 3 W to 6.5 W from the first night. Offline window 12-03 02:10-02:58: those S07 files are uploaded at 02:59 and carry `event.ingested` = upload time (the pipeline keeps an existing value).
- **Peer baseline lowered:** peer TV boxes received 67 MB a week, against the brief's "under 50 MB". The TV box update-server baseline is now 15 KB per flow (about 35 MB a week); the main flow history was regenerated.
- **ML (population jobs, 1 h buckets, whole window):** `edge-inbound-population` flags only `S07-TVBOX-01` (score 98, first record 12-01 01:00, the bucket of the first chunk); `edge-signage-cpu` and `edge-signage-storage` flag only `S07-SIG-02` (first 12-06); `edge-plug-power` flags only `S07-PLUG-01` (first 12-01 02:00). No peer flagged at 75 or 50, nothing flagged before the story starts. Synthetic peers are very uniform, so this is easier than a real estate; say so.
- **Rule:** "First-seen internal peer" (new terms on `source.ip` + `destination.ip`, 14-day history, index `logs-netflow.summary-*`, created disabled). Preview over 12-01..12-08: 5 alerts, all S07: TVBOX to 192.0.2.77, TVBOX to both signage players (8080), SIG-02 to camera 10.7.0.51 (554), TVBOX to 10.7.0.21 tcp/80 (the system manager, alert on 12-08 for 12-07). No alert on any other store. The data is dated after the main history, so the rule is verified by preview, not live.
- **Federated hunt:** `raw_store_tls` (new dataset, S07 only) with the 06b query returns `S07-TVBOX-01`, `models.example-hub.net`, 4,939,212,390 bytes (4.6), 123 chunks, 9 nights, the unusual JA3, in 5.1 s. Multi-field `LOOKUP JOIN` (`retail.device.role`, `tls.client.server_name`) works. Two findings: a federated dataset reads strings as `text`, so the query casts with `TO_STRING(...)` on the left, and the lookup indices now map strings as keyword (join keys must be keyword). The query uses an explicit time range because the data is dated after "now". `raw_edge_metrics` is two datasets (`raw_edge_signage`, `raw_edge_plug`).
- **Not built:** the S07 store-in-a-box live path for scenario B, the epilogue dashboard, a replay that rebases the epilogue onto "now" (so rules and ML fire live), and `raw_store_telemetry`.

## Dashboards and rules 1 and 2 (2026-11-10)

- **Dashboards API on the tenant:** 9.5.6 serves `/api/dashboards` (GA since 9.5, header `elastic-api-version: 2023-10-31`); `PUT /api/dashboards/{id}` creates or replaces by a stable id. ES|QL charts (metric, data_table, xy) and ES|QL controls are accepted; Kibana does not publish its OpenAPI on Cloud, so panel schemas were learned from validation errors. `coldchain/dashboards.py`, `make dashboards`, `make dashboards-check`.
- **Three dashboards:** `coldchain-act1b-estate`, `coldchain-act4-evidence`, `coldchain-epilogue-edge` (fixed range 2026-11-19..12-10, labelled hypothetical; the last panel reads `raw_store_tls` in place).
- **Controls over ES|QL panels:** an options-list control does not apply to ES|QL panels without a data view, so Act 4 uses an ES|QL control (`?feeds`, multi-select) and the panels test `MV_CONTAINS(?feeds, event.dataset)` (`IN (?feeds)` with several values returned null). Verified through the query API; how Kibana passes a multi-select to the panel is still to be seen in the browser.
- **Act 4 verdict measured (local attack replay loaded into temporary `zzcheck` data streams, since deleted):** all feeds "Remote attack"; without flows "A contractor change?"; without audit "Odd traffic, no idea why"; temperature only "A faulty cabinet"; without temperature "Nothing happened". Verdict counts mean something (warm cabinets with the relay off, setpoint above 5 C, flows to 203.0.113.0/24), not just that a feed has rows: telemetry and audit exist all the time, so 06b's presence-only `CASE` would say "Remote attack" at baseline. The indexed flow dataset is `netflow.summary`, not `netflow.log`.
- **Warm cabinets, no defrost (panel and rule 2):** at least 3 of the last 10 minutes more than 2 K above nominal, relay off, no relay in the range. A plain "above nominal with the relay off" fires on 14-24k baseline rows because the air stays high for a while after a defrost. Measured: 0 cabinets in 34 days of baseline hour windows, 46 cabinets from T0+10 min to the restore.
- **Rules 1 and 2 (`coldchain/rules.py`, `make rules`, created disabled):** ES|QL rules grouped by store, so each alert carries `retail.store.id` (3 alerts: S07 16, S11 16, S19 14 = 46 cabinets). Rule 1 on 35 days of baseline: 0 rows. Preview at 02:56: 3 alerts "at documented maximum". Rule 2 preview at 03:06: 3 alerts, warmest +3.1..3.2 K. Preview uses the preview time for `NOW()`; rules do not get `?_tstart`/`?_tend`. Rule 2's nominal (-24, +2 C) is still a constant, not a `kb-thresholds` row. Rules 3 to 5 not built.
- **Not verified:** how Kibana renders any panel (the API cannot show it), federated panels in a dashboard, and the Act 1 "Open alerts" and "Alerts by rule" panels with real alerts (nothing fires until a rule is enabled and a replay runs). Open the three dashboards once before a show.

## Live rehearsal of the dashboards and rules (2026-11-11)

`make rules ENABLE=1` plus `make replay-fast TARGET=s3` (T0 09:04 UTC, 10x, auto restore). Needs `.env` sourced (`COLDCHAIN_BUCKET`).

- **Worked:** rule 1 fired about 25 s after T0 on S07, S11 and S19 (`setpoint 50`, "at documented maximum"). Act 1 panels (changes 92, cabinets 480, alerts, restore events) and the Act 4 timeline filled.
- **Rule 2 and the warm panels stayed empty:** with the automatic restore the air peaks about 2.8 K above nominal, so "3 of 10 minutes above 2 K" is never met before the restore. Consistent with 8.2 (rule 2 fires close to containment). The Act 4 verdicts "A faulty cabinet" and "Remote attack" need `--restore trigger` or a lower threshold to show live. Open design choice.
- **Duplicate alerts:** rule 1 re-alerts every minute while the 6-minute lookback sees the same changes (27 alert documents for 3 stores). Needs suppression or a shorter lookback.
- **`--t0 now` collides with the backfilled baseline** (it runs to 2026-11-12 02:46): replayed and baseline documents share cabinet and minute, and at 10x the replay is dated ahead of the wall clock. Use `--t0 config` for the real run.
- **Cleanup done:** replayed documents deleted from the four detect streams (`event.ingested` >= 09:00 today), alerts deleted, rules disabled. The replay's S3 objects stay (object lock, 7 days).
- **Dashboards:** the epilogue data is dated after today, so its panels need the picker on 2026-11-19 to 2026-12-10; neither the saved range nor `ignore_global_filters` overrides the picker. A federated dataset renders in a dashboard panel (closes that item in section 12). The 43 managed Kibana dashboards were deleted; reinstalling an integration may restore them.

## Story flow v3 (2026-11-11): blip, history, TV box, agentic SOC

Requested focus: Act 1 (the blip), Act 5 (the history), the epilogue (outside and inside the store), ending with an agent that hunts
and ties it into one narrative. See `docs/story-flow.md`.

- **Act 5 is a campaign, not one login:** `config/attack.yaml` `probes` lists three first visits from `203.0.113.47`: S07 at T-126 d,
  S11 at T-84 d, S19 at T-49 d. All are older than the 35 indexed days, so they exist only in `raw/`. They are the three stores hit
  at T0. `backfill --only audit-raw` rewrites the raw audit files of those stores without touching the indexed copy.
- **The blip comes from outside and inside:** `setpoint_change.from_inside: {S07: tv-box}`. S07's 16 setpoint changes carry the TV
  box address (`10.7.0.41`); S11 and S19 carry the internet address. The replay adds a TV box to system manager flow on tcp/80 three
  seconds before. The logins on the 9 stores at T0-2m20s are unchanged. Consequence: the limits rule now reports two source
  addresses, and the acceptance row "one source" becomes "two sources, one outside, one inside".
- **The epilogue moves before the blip:** 2026-10-22 to 2026-11-12 (was 2026-11-19 to 12-10), first download night 2026-11-03, the
  first tcp/80 call to the system manager 2026-11-09. Cause precedes effect. The old epilogue S3 objects (dt >= 2026-11-19) and
  indexed documents were replaced. Normal flows of S07 now overlap the main history's last 7 flow days (same hourly keys, so the
  epilogue's files replace the backfill's for S07; accepted).
- **The agent:** `coldchain/agent.py`, Agent Builder (preview, available on 9.5.6 with an LLM connector). Eight ES|QL tools
  (recent changes with the knowledge-base verdict, warm cabinets, history of an address, estate footprint, exposed controllers,
  device evidence, internal movement, what is normal) and one agent that follows the four-step story and never acts.
  `make agent`, `make agent-check`, `make agent-ask`. Federation tools are labelled experimental in their descriptions.
- **Live runs:** `make demo` is on the real clock (see earlier section); Act 1 and the agent read "now", Act 5 and the epilogue are
  fixed windows.
- **Lessons:** replay uploads overwrite the backfill's hourly raw flow files for the same hours (same S3 keys; versions keep the
  originals), and leave locked `raw/` objects that federation reads. After a rehearsal, delete the object versions written by the
  replay (operator credentials, governance bypass), and the indexed documents.
- **Verified on the new data (2026-11-11):** Act 5 federated query returns the three first visits (S07 2026-07-09, S11 2026-08-20,
  S19 2026-09-24), 46 s for about 700k events over 12 months (slow: expect to wait on stage, or run it first). The TV box evidence
  returns 4.6 GB, 123 chunks, 9 nights (2026-11-03 to 11-11), JA3 included, in 3 s. The four epilogue ML jobs flag S07-TVBOX-01,
  S07-SIG-02 (CPU and storage) and S07-PLUG-01 at score 96 to 99, no peer at 75, nothing before the story. The new-terms rule
  preview alerts on 11-05, 11-08 and 11-10, one day after each first-seen internal flow (fields not read individually). The agent
  answered the history, TV box and exposure questions with the right tools and the 7 stores at risk (S03, S05, S09, S12, S14,
  S17, S20) and the shared contractor account. 45 tests pass.
- **Not yet done:** the full scripted question against a live attack (needs `make demo` first, then `make agent-ask`); the live demo's raw files were deleted from S3 (Act 5 now returns exactly the three first visits), but the same delete also removed 24 regenerated S07 epilogue raw flow files dated 2026-11-11, so S07's raw flows lack that night's tcp/80 calls (the TLS evidence is unaffected); re-running `scenario_b --stores S07` would restore them but re-ingests the S07 detect files; a baseline gap in the indexed default streams on 2026-11-11 from about 09:38 to
  10:43 UTC (the `prep` step deleted it for the live run; `make backfill` would refill it, with duplicates elsewhere); rules 3 to 5, the
  mock response service and the storyboard deck v3.

### Live run with the full scripted question (2026-11-11, T0 12:23 UTC)

`make demo`, then `make agent-ask` about 12 minutes after T0. The audit showed S07's 16 changes from the TV box `10.7.0.41`, S11 (16) and
S19 (14) from `203.0.113.47`. The agent called all tools in order and told the four-step story. Two defects found and fixed: (1) the
raw logins of the 9 touched stores are written to S3 only when the run ends, so federation alone said "3 stores touched, 13 at risk";
new tool `cc_recent_outside_logins` reads the live logins from the indexed audit, and the agent now names 9 touched and the 7 at risk
(S03, S05, S09, S12, S14, S17, S20) plus the shared account C-114; (2) it speculated about how the credentials were obtained and swapped
two cabinet counts (the store column came last); the instructions now forbid guessing causes and the tool puts the store first.
Cabinets were not yet warm in the metrics at that point (the replay's warming needs about 10 minutes and the trigger timeout restored at
T+15). `make clean-run SINCE=<ISO>` deletes the indexed replay documents afterwards; the S3 objects need the operator.

### Federation memory limit (2026-11-11)

The Act 5 dashboard first had four federated panels (three counters and the table). Opened together, they hit the Elasticsearch
parent circuit breaker (`streaming-parse-chunk-buffer`, 3.7 GB heap): every panel scans the whole year of raw audit
(about 7,300 files, 700k events), about 41 to 46 s alone. Now it has one federated panel. Rule: at most one federated scan of the
12-month audit at a time; do not auto-refresh the Act 5 dashboard; run the agent's history tool and the dashboard apart. A bigger
node (more heap) or compaction into fewer, larger files would lift this; neither is done.

### Act 5 chart and the time picker (2026-11-11)

Kibana applies the picker to every ES|QL panel on `@timestamp`, federated datasets included, so a chart over history needs a picker that
covers the whole history (Last 6 months or longer, link with `_g=(time:(from:now-6M,to:now))`); with a shorter range the "first
login per store" is computed over the remaining rows only and is wrong. The chart has two layers: the federated history alone (one scan)
and the indexed blip (empty until a live run). The dashboard's saved range is not applied on open; use the link.

### Baselines on the Act 1 tiles (2026-11-11)

Each Act 1 tile shows its value and how far it is from normal, with an arrow in text (up, down or equal) and the baseline in
brackets, for example "up 41 above normal (5)". Normal is a row of `kb-baselines` (`python -m coldchain.baselines`; also loaded by
`make lookups`'s reload path): parameter changes 5.4 per day (mean of 24 days of indexed contractor changes, range 1 to 13, scaled to the
picker window), cabinets reporting 480, cabinets warm 0, open alerts 0, each with its basis. The baseline must come from a row, not
from the panel's own history: Kibana's picker filter removes everything before the window. Kibana's own "compare to primary" badge
(arrow plus difference) was rejected: its only documented palette colours an increase green, which would show the attack green; the
reversed palette is not documented. Rendering of the text secondary line was checked by query only, not in the browser.

### ML count job on parameter changes: experiment (2026-11-11)

`coldchain/mlcount.py`: a `count` job on `parameter-change` over `logs-coldchain.audit-default` (24 days of history, then the live burst
of 46 setpoint changes at 14:11 UTC), 5-minute and 15-minute buckets, model plot on, influencers store, source address and user.
- **Detection: works.** Burst bucket scored 95 in both jobs; the bucket closes 3.9 minutes after the attack, so a real-time alert would
  come about 5 to 6 minutes after the attack (query delay on top), against 25 seconds for rule 1. History: 0 anomalies at score 25 or more.
- **Baseline number: no better than the constant.** Mean absolute error per day against the real daily count: model 4.05 (5 m) and 5.63
  (15 m), constant 5.4 per day 3.29. The model's expected value is a median, and the median of a sparse count is 0, so summing it
  gives about 0.5 a day; day-to-day counts range 0 to 13 with no pattern to learn from 127 events in 24 days. A band would not help.
- **Decision:** the tile's baseline stays a `kb-baselines` row. ML is a possible extra detector ("volume of changes is unusual"),
  not the baseline. Rebuild with `python -m coldchain.mlcount run` and `score`. Jobs removed after the run.

### `make demo` shows alerts and warm cabinets (2026-11-11)

`make demo` now enables both rules before the replay starts and waits 30 minutes (was 15) for `make restore`, so rule 1's alerts
and rule 2 with the "Cabinets warm, no defrost" tile (about 10 minutes after the attack) are visible for about 20 minutes. Both rules
have alert suppression by store for 15 minutes: rule 1 over the live run gave 3 alerts (one per store) in a preview, not one per
minute. `make clean-run SINCE=<ISO>` now also deletes the run's alerts and switches the rules off. Rule 2 cannot be previewed (NOW()
resolves to the preview time); it has fired only in a real-time test, not yet with this setup. ML count job: left out.

### Warm tile fixed for wide pickers (2026-11-11)

The "Cabinets warm, no defrost" tile (and the Act 4 verdict, and the agent's `cc_warm_cabinets`) read 0 during a live attack on "Today" and
"Last 24 hours": (1) the newest-data anchor included the backfilled baseline, which runs into the future, so the last 10 minutes were
calm; now rows are limited to `@timestamp <= NOW()`; (2) cabinets with any defrost relay in the whole picker range were excluded, and every
frozen cabinet has one per day; now the relay is checked over the last 60 minutes only, like the rule. The agent's "no cabinets warm yet"
at 12:35 UTC was most likely the same bug. The Act 1 header is now the dashboard title only; the panel under it was removed.

## Act 1 split into 1a and 1b (2026-11-12)

- **1a** (`coldchain-act1a-cabinet`) shows one attacked cabinet (S07-C05): the contractor's visibility. **1b** (`coldchain-act1b-estate`, replaces `coldchain-act1-estate`) shows all 480 cabinets: central IT's visibility. The point is the scope, not the data: 1a is the same indexed streams filtered to one `device.id`.
- 1b gets an inventory table from `kb-assets` (cabinets, signage, TV boxes, cameras, routers, loggers) with a "live feed" column; only cabinets, loggers and managers report live.
- Signage and cameras are not added to the live Act 1 view: no camera telemetry exists, and signage/TV-box evidence stays the epilogue's reveal.

## Act 5b: the history on the frozen tier (2026-11-12)

- **Why:** to show the customer's choice: Act 5a reads the year in place (nothing ingested, about 44 s a question, S3 requests per query), Act 5b ingests it once and serves it from the frozen tier (about 1.1 s cold, 0.1 s cached on the measured run), with a spend fixed by the frozen node and the object storage.
- **How (`coldchain/frozen.py`, `make history-frozen`):** read `raw/dataset=coldchain.audit/` from S3 with operator credentials, index 703,517 events into `cc-history-audit-src` (135 s), snapshot into the deployment's `found-snapshots` repository, delete the source and mount the snapshot as `cc-history-audit` with `storage=shared_cache` (partially mounted, `_tier_preference: data_frozen`). The deployment got a frozen node (2 GB heap, 296 GB disk) for this; before that it had none. The snapshot lives in Elastic's repository, not in the central-IT bucket.
- **Caveat:** the index is a copy of `raw/` at load time. After a replay or cleanup of the raw files, run `make history-frozen` again. `python -m coldchain.frozen delete` removes the index and the snapshot.
- **Act 5a fix:** the history chart now has its own one-year panel range, so the time picker kept from another dashboard no longer empties it. The panel `time_range` is accepted by the Dashboards API; its effect in the browser was not checked.

## Pre-roll before a live demo (2026-11-13)

- **Problem found in a live run:** the backfilled baseline ends at the configured T0 (2026-11-12 02:46 UTC) and `make demo` only wrote normal data from T0-3m. On a later day the Act 1 chart was blank until the attack, and rule 2 raised false alerts on 11 untouched stores at T0+2m: the relay-on readings that explain a cabinet's post-defrost warmth were not in its one-hour lookback.
- **Fix (`coldchain/prep.py`, part of `make demo`):** after deleting overlapping baseline, write 24 hours (`--preroll-hours`, 0 = off) of normal telemetry, probes, audit and flow summaries, or just the gap since the newest indexed telemetry, to `detect/` in S3 (10-minute files, same writers as the backfill) and wait until the collector has indexed them (about 10 s after the 40 s upload on the one-hour test). The replay then starts its loop at the end of the pre-roll and catches up on the minutes before T0-3m without waiting (marker `.replay/preroll.json`, ignored if older than 30 minutes). Raw files are not written for the pre-roll.
- **Cost of the fix (measured 2026-11-16, not "about a minute"):** a full 24-hour pre-roll wrote 9,303 files (16.9 MB) in 648 s and the collector indexed them: 15 minutes from `make rehearse` to `T0=`. A one-hour pre-roll takes under a minute. A run right after a reset only fills the gap; one PUT per store, dataset and 10 minutes. A day of pre-roll is 8,000 files; the one-hour test wrote 400.
- **Cleanup:** `make clean-run SINCE=<time you started make demo>` removes the indexed pre-roll with the run (it filters on `event.ingested`). Use the replay's start (T0 minus 3 minutes, printed by the run), which is after the pre-roll: the day of context stays and the next demo only fills the gap. The S3 pre-roll files stay, they are not read again. (Corrected 2026-11-16: an earlier version of this note said to use the time `make demo` was started, which also deleted the pre-roll.)

## AlertZero is not available here; the scheduled hunt (AlertZero pattern) (2026-11-16)

- **Research:** AlertZero (Technical Preview since October 2026) has four Watches (Triage, Hunt, Detection, Forensics), each a Workflow calling Agent Builder agents and skills, and is switched on by the Advanced Setting `securitySolution:enableAlertZero` per space. Its docs list Serverless Security as Preview and self-managed as Planned; Cloud Hosted appears only in the billing section. The Hunt Watch's one Worker, Continuous Threat Hunt, hunts for activity in public threat reports (needs outbound access to threat feeds); custom Workers are not documented.
- **Tenant:** Kibana 9.5.6 Cloud Hosted. The setting is not in Advanced Settings (checked by the user in the UI), so AlertZero is not available. Workflows (API responds), Agent Builder with the built-in skills `threat-hunting`, `alert-triage` and `attack-discovery-generator`, and Elastic-managed LLM connectors are.
- **What was built (`coldchain/hunt.py`, `make hunt`, `make hunt-run`):** Elastic Workflow "Cold-chain hunt (AlertZero pattern, preview)", triggers manual and scheduled every 30 minutes. One `ai.agent` step runs `cc-soc-hunter` with a hunting prompt and a JSON schema (stable key `<type>:<store>`, severity, stores, evidence, why abnormal, proposed action); a `foreach` writes each finding to `cc-hunt-findings` with the key as document id, so a finding keeps one row across runs. An ingest pipeline stamps `@timestamp` and turns the JSON arrays back into arrays. Dashboard `coldchain-hunt-findings`. The agent proposes and runs nothing.
- **Measured:** a run takes about 2 minutes (4 on the first); with the live rehearsal attack and the history in place it returned 9 findings (3 critical, 5 high, 1 medium, 16 stores): first visits S07, S11, S19 from the raw history, first contact on S01, S02, S04, S06, S08, S10 (live), setpoint changes, the TV box download and pivot, 5 exposed controllers on one contractor account, 2 on separate accounts.
- **Caveats:** the schedule runs unattended every 30 minutes and uses the deployment's LLM each time (`python -m coldchain.hunt delete` removes it, or set `enabled: false` in the workflow). The update route is `PUT /api/workflows/workflow/{id}`, and a run is started through Agent Builder's `platform.core.execute_workflow` tool, because `/api/workflows/{id}/run` does not exist on 9.5.6. It is not AlertZero and is labelled "AlertZero pattern, preview". Finding keys are asked of the model, not enforced; a prompt change can duplicate findings once (clear the index).
- **Dashboard readability (2026-11-16):** the 9.5.6 Dashboards API has no row-height or text-wrap option for `data_table` (checked: `density`, `row_height`, `wrap` are rejected), so long text was cut. The hunt now asks for short text (title at most 70 characters, action 120, why 200, evidence 250), the table has fixed column widths, and the long fields sit in a second table. Colour: an ingest pipeline adds `risk` (critical 95, high 75, medium 50, low 25); the risk cell is red from 85, amber from 60, blue below, and the three severity tiles turn red, amber or blue when they are not zero. Kibana's data grid shows a full cell value on click (expand). The model sometimes groups stores in a key (`setpoint-change:S11+S19`) where an earlier run used one key per store, so a changed grouping leaves an old row: delete it by id.

## Dashboards renamed to CC Act 1 to 5; evidence dashboard removed (2026-11-16)

- Titles: "CC Act 1: One cabinet, the contractor's view" (`coldchain-act1a-cabinet`), "CC Act 2: The same blip across the whole estate, not on SOC's radar" (`coldchain-act1b-estate`), "CC Act 3a: The history nobody ingested" (`coldchain-act5a-history`), "CC Act 3b: The history ingested at a predictable price" (`coldchain-act5b-history-frozen`), "CC Act 4: Edge devices on no one\u2019s radar" (`coldchain-epilogue-edge`), "CC Act 5: Hunting agent - the agent that keeps looking" (`coldchain-hunt-findings`). The ids did not change, so links and scripts keep working.
- "Case S07: evidence (Act 4)" (`coldchain-act4-evidence`) is removed: deleted from Kibana, and its code (`act4`, `VERDICT`, `TIMELINE`, the `?feeds` control) and test removed. The verdict idea (what each feed adds) is no longer in the story. Older entries in this file that mention it describe what was measured at the time.

## One platform, one language: Act 0 and the ES|QL moment (2026-11-16)

- **Assessment:** ES|QL did almost all the work (every panel, both rules, the 9 agent tools, the knowledge-base joins) but was never shown, and "one platform, one language for all data" was implicit. Added: **CC Act 0: Every source of truth, one language** (`coldchain-act0-sources`), a catalog `kb-sources` (22 sources in five tiers: Indexed, Frozen tier, Raw in S3, Knowledge base, Produced; rows, first and last time, how to ask it) measured by `make sources`; **"one question, three places"** on Act 3b (`cc-esql-moment`: the same ES|QL, only the `FROM` changed, against the live index, the frozen tier and the raw files, with seconds and answer); the query text on Act 3a; and, on the hunt dashboard, a `tools` column and the nine tool queries, so the audience sees what the agent asks.
- **Measured (2026-11-16):** the live index answers in 0.2 s and finds nothing (it holds 35 days); the frozen tier in under a second (0.0 s warm, the cache) and the raw files in about 79 s, both finding S07, S11 and S19. Federated counts: audit 703,214, flows 621,698, TLS 48,375, signage 12,096, plug 6,048.
- **Limit found:** one `FROM` over an index and a federated dataset fails: `Column [source.ip] has conflicting data types in subqueries: [keyword, ip]`. Federated datasets infer IPs as text, so the same text needs `TO_IP(source.ip)`, and a single statement across tiers is not possible today. Say "same language, same query, different `FROM`", not "one statement". Federated plus knowledge-base joins work (about 76 s); frozen plus knowledge base 0.1 s. ES|QL reserves `first` and `last`: the catalog uses `first_seen` and `last_seen`.
- **Catalog caveat:** raw-file counts are measured once, not live (a federated count takes 5 to 75 s and Kibana limits memory to about one federated panel per dashboard). Re-run `make sources` after changing the data.

- **Hunt tool corrected (2026-11-16):** `cc_warm_cabinets` listed cabinets recovering from a defrost on 11 to 14 stores (the hunt reported them as medium findings). It now uses rule 2's logic: more than 2 K warm in 3 of the last 10 minutes, relay off, and no relay reading in the last hour. On the live attack it lists S07, S11 and S19 only.
- **Rehearsal measured (2026-11-16, T0 16:05):** 9 logins at T0-2m20s, 46 setpoint changes at T0+5s (S07's 16 from 10.7.0.41, S11's 16 and S19's 14 from 203.0.113.47); rule 1 alerts for the three stores at T0+99 s; with `make rehearse` (restore at T0+10 min) rule 2 still fired for exactly S07, S11 and S19 at T0+10 min 57 s, no false alerts; the hunt ran in 261 s. `make reset-demo` then removed the run and kept the pre-roll (691,200 telemetry documents = 480 cabinets x 1,440 minutes).
- **`make verify` fix:** the queue-event check could not peek at the SQS message once the collector ran (it deletes it first); it now accepts the configured `detect/` notification as proof when the message is gone.

## Act 0 renamed (2026-11-17)

- `coldchain-act0-sources` is now titled "CC Act: The realms you usually do not watch" (no number, as asked), and its first heading reads "Every source of truth, one language" because the old "Act 0:" prefix repeated the title. The id did not change. Earlier entries in this file call it "Act 0".
- Renamed again the same day to "CC Act 0: The realms you usually do not watch" (number restored at the user's request).

## Navigation between the acts (2026-11-17)

- Every dashboard starts with a three-row strip (a markdown panel built by `nav_panel` in `coldchain/dashboards.py`): a link to the previous act, links to all acts with the current one in bold, and a link to the next act. The order is the `ACTS` list (0, 1, 2, 3a, 3b, 4, 5); Act 0 has no previous link and Act 5 no next link. The links are relative (`/app/dashboards#/view/<id>`), so they work on any Kibana host. Every other panel moves down by the strip's height when the dashboard is pushed. Not verified in a browser: how Kibana opens a markdown link (same tab or new tab) and whether the time picker carries over.

## Streetlight visual on Act 0 (2026-11-17)

- A row on "CC Act 0" illustrates the streetlight effect (we search where the light is): an ASCII streetlight (markdown) next to a weekly bar chart of the store audit from the frozen index, in two layers: events older than 35 days, dark grey, "in the dark: only in raw files and on the frozen tier", and the last 35 days, amber, "under the streetlight: the live index". The 35 days are the indexed retention; the boundary slides with `NOW()`. Not verified in a browser: how Kibana renders the code block art and whether the per-layer static colours are honoured (the API accepts them). A real illustration would need an image panel with a hosted image: not done.
- **Superseded the same day:** the user removed the ASCII lamp and moved the chart to the top, full width, under the navigation strip, and wanted that as the dashboard. The code now builds exactly that layout (nav, chart, intro, tiles, two charts, table), the chart's own range is one year, the heading reads "Every source of truth, one platform, one language", the dashboard's default range is a year (an absolute range had been saved in Kibana and would go stale), and the navigation strip opens links in a new tab as Kibana saved it.
- **Dashboards are code:** `make dashboards` overwrites what was changed in Kibana. When a dashboard is edited in the Kibana UI and the edit should stay, it has to be mirrored into `coldchain/dashboards.py`. Compare the saved dashboard with what the code builds (panel positions, titles, config) before pushing; on 2026-11-17 only Act 0 had been edited.

## A correlation across sources on Act 0 (2026-11-17)

- **Added:** "One statement, three sources" on Act 0: the live index and the raw files in S3, as two subqueries of one `FROM`, joined to the knowledge base with `LOOKUP JOIN`, in one ES|QL statement (`CORRELATION` in `coldchain/sources.py`). It answers: which stores did the attacker's address visit, when first, where is that on record (live index, raw files, or both), and whose contractor account runs each store. On the live demo it showed S07, S11 and S19 in both (first seen 2026-07-09, 2026-08-20, 2026-09-24, visits 2 each) and six stores first visited today, with contractor accounts (C-114 for S07 and S11).
- **How it works around the type conflict:** a plain `FROM index, dataset` fails because the dataset types `source.ip` as text. Subqueries (`FROM (FROM a | ...), (FROM b | ...)`) each turn the IP into text with `EVAL ip = TO_STRING(source.ip)` and `DROP source.ip`, then the statement works: 73 to 80 s, dominated by the raw files. Two variants failed on this build (experimental): `KEEP` in the federated subquery, and aggregating inside it, both with "output schema size [4] does not match mapping width [17]". So the earlier note "a single statement across tiers is not possible" is wrong: it is possible with subqueries, `EVAL ... DROP` and no `KEEP`.
- **Measured, not live:** the table reads `cc-esql-correlation`, filled by `make correlation` (also part of `make sources`, and run at the end of `make reset-demo DELETE=1` so it does not show a finished demo). A federated panel would add about 75 s to opening Act 0 and use the one federated panel Kibana can hold.

## Acts 4 and 5 swapped: the agent raises the lead, the epilogue investigates it (2026-11-17)

- **Order now:** CC Act 4 is the hunting agent ("something is going on, and nobody asked": among its findings a TV box talks to a store's system manager, a path no rule watches), CC Act 5 is the epilogue ("let's see what the TV boxes are doing": the raw TLS evidence, the 4.6 GB over nine nights, the signage and plug metrics). Titles, the navigation strip (ACTS order), the dashboards' intro texts, README, story flow and the stage script follow. Dashboard ids did not change.
- **Why it works:** breadth first, depth second. The agent is the detective that surfaces an unknown unknown; the epilogue is the proof behind one lead, with the evidence read in place from S3. The epilogue's time-travel (the data is dated three weeks before the blip) is introduced as "what happened before", not as a flashback in the middle of a hunt.
- **Caveat:** the agent already tells most of the story (TV box downloads, pivot), so Act 5 must show what the agent cannot: the per-night bytes against 19 peers, the JA3 fingerprint, the signage and plug evidence. The agent's finding must stay short and point at the lead.

## Simplified version on Serverless (2026-11-17, branch `simplified-serverless`)

- **Decisions:** Serverless Security project (custom panels, Preview, Serverless only); no federation; no frozen tier ("frozen"
  was the user's word for the storage idea: Serverless stores data in object storage with a cache layer and sizes search
  capacity itself, so a year of audit is simply indexed); no ES|QL explanations on dashboards; 15 minutes; POS instead of TV boxes.
  The full version is the tag `v1-ech-federation-tv`.
- **Spike (Serverless 9.7.0, europe-west3):** custom panels are a Dashboards API panel type, `custom_content`, with `title`,
  `template` and `esql_query` (an array of one ES|QL string); templates see `rows` and `row["column"].value`. Fleet, data streams
  with `data_retention`, reroute pipelines, lookup indices with `LOOKUP JOIN`, ML jobs, ES|QL rules, Agent Builder tools and
  workflows all work. `aws_logs` integration 2.1.1 replaces the pinned 1.8.3 (the policy was created without error).
- **POS scenario:** per store 4 lanes (`pos-lane`, 10.n.0.31-34) and one back-office PC (`pos-backoffice`, 10.n.0.41); no signage
  players, no TV box, no smart plug. S07's back-office PC downloads 4.0 GiB in 96 chunks of 20 to 60 MB over 7 nights from
  `sync.example-cdn.net` (not in `kb-device-profiles`, an unusual JA3), runs at 88% CPU on those nights while the store is closed, fills
  its disk (64% to 22% free), calls the cameras from 2026-11-07 and the system manager (tcp/80) from 2026-11-09, and at T0 changes S07's
  setpoints from inside. The store network is flat: an assumption of the fictional chain, to be said as such. The offline-window
  story and the smart plug are dropped.
- **Data model:** everything goes through `detect/` and the collector; there is no `raw/` side. Backfill: a year of audit (one file per
  store and day), 7 days of telemetry, probes and flow summaries; the audit stream keeps 400 days, the others 90. The pre-roll
  default is 6 hours (a 24 hour pre-roll took 15 minutes). The agent's history, footprint and device-evidence tools query the
  indexed streams. The cabinet ML jobs and the experiment modules (`ml`, `mlexp`, `mlscore`, `mlcount`, `ruleprobe*`) are removed;
  the three POS ML jobs remain (`edge-inbound-population`, `edge-pos-cpu`, `edge-pos-disk`).
- **Not run in AWS (blocked, needs the operator):** `terraform apply` of the federation IAM user removal and emptying the old bucket
  objects. The new backfill overwrites the keys it needs; old objects without events are never indexed.
