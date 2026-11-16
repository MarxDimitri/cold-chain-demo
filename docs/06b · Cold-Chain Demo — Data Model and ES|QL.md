# Cold-chain demo: data model and ES|QL queries

How the act 3 correlation (and the knowledge-base check) would look in Elastic. It uses ECS field names wherever ECS has them. It puts non-ECS fields under one custom namespace (`coldchain.*`, `retail.*`), as ECS recommends for custom fields.

**Status:** draft for the synthetic-data build. Field names are our proposal, not a shipped integration. Validate against the Elastic version of the demo tenant (see "Version notes" at the end).

---

## 1. Data sets

| Family | Data stream / index | Source in reality | Key fields |
|---|---|---|---|
| Security | `logs-coldchain.audit-default` | System manager event log or vendor-cloud API (partner integration, PS4) | `@timestamp`, `event.category`, `event.action`, `event.outcome`, `user.name`, `source.ip`, `device.id`, `coldchain.parameter.*`, `retail.store.id` |
| Security | `logs-netflow.log-default` | Elastic NetFlow integration (store router or switch) | `source.ip`, `destination.ip`, `destination.port`, `network.bytes`, `retail.store.id` (added by an enrich processor at ingest) |
| Security | `.alerts-security.alerts-default` | Elastic Security alerts (ML and ES\|QL rules) | `kibana.alert.rule.name`, `kibana.alert.severity`, `device.id`, `retail.store.id` |
| Operational | `metrics-coldchain.case-default` | Cabinet telemetry, 1 reading per minute | `device.id`, `coldchain.case.temperature.air`, `coldchain.case.setpoint`, `coldchain.case.temperature.rise_5m` |
| Knowledge | `kb-assets` (lookup index) | CMDB + contractor records (PS1) | `device.id`, `device.manufacturer`, `device.model.identifier`, `coldchain.application`, `coldchain.controller.firmware`, `coldchain.exposure.internet`, `retail.store.id` |
| Knowledge | `kb-controller-limits` (lookup index) | Vendor manual, curated by the partner (PS6) | `device.model.identifier`, `coldchain.parameter.code`, `coldchain.application`, `kb.doc.min`, `kb.doc.max`, `kb.expected.min`, `kb.expected.max`, `kb.doc.ref`, `kb.rule.ref` |
| Knowledge | `kb-manuals` | Vendor manuals, chunked, `semantic_text` | `doc.title`, `doc.page`, `device.model.identifier`, `content` |

### Sample documents

The audit event for the attack, as the system manager would report it:

```json
{
  "@timestamp": "2026-11-12T03:52:05Z",
  "event": { "kind": "event", "category": ["configuration"], "type": ["change"],
             "action": "parameter-change", "outcome": "success", "dataset": "coldchain.audit" },
  "user":   { "name": "admin" },
  "source": { "ip": "203.0.113.47" },
  "host":   { "name": "S07-SM800" },
  "device": { "id": "S07-C14" },
  "retail": { "store": { "id": "S07" } },
  "coldchain": { "parameter": { "code": "setpoint", "name": "Temperature set point",
                                "value": { "old": -24.0, "new": 50.0 }, "unit": "°C" } }
}
```

One row in the controller-limits lookup index. The `kb.doc.*` values come from the Danfoss EKC 202 instructions (RI8KL45J). The `kb.expected.*` values are the partner's curated "normal for this application":

```json
{
  "device":    { "model": { "identifier": "EKC 202C" } },
  "coldchain": { "parameter": { "code": "setpoint" }, "application": "frozen" },
  "kb": {
    "doc":      { "min": -50, "max": 50, "ref": "Danfoss EKC 202 instructions RI8KL45J, p.3" },
    "expected": { "min": -28, "max": -18 },
    "rule":     { "ref": "EU quick-frozen food rules: -18 °C or colder" }
  }
}
```

Other curated rows for the same model:

| Parameter | `kb.doc` range | `kb.expected` range |
|---|---|---|
| `A13` high-alarm limit | −50 … +50 °C | −20 … −10 °C |
| `A03` alarm delay | 0 … 240 min | 0 … 60 min |

Lookup indices are created with `"index.mode": "lookup"` and always have a single shard.

---

## 2. Act 3: the correlation on screen

This is the timeline for store 07 over the last hour: login, parameter change, flow and alert. Each parameter change is checked against the manual and the curated normal range.

```esql
FROM logs-coldchain.audit-*, logs-netflow.log-*, .alerts-security.alerts-default
| WHERE retail.store.id == "S07" AND @timestamp > NOW() - 1 hour
| LOOKUP JOIN kb-assets ON device.id
| LOOKUP JOIN kb-controller-limits
    ON device.model.identifier, coldchain.parameter.code, coldchain.application
| EVAL kb.verdict = CASE(
      coldchain.parameter.value.new IS NULL, NULL,
      coldchain.parameter.value.new >= kb.doc.max, "at documented maximum",
      coldchain.parameter.value.new > kb.expected.max, "outside normal for frozen",
      "within normal")
| EVAL what = COALESCE(kibana.alert.rule.name,
                       CONCAT(event.action, " ", COALESCE(coldchain.parameter.code, "")))
| KEEP @timestamp, what, user.name, source.ip, destination.ip,
       coldchain.controller.firmware, coldchain.parameter.value.new,
       kb.doc.max, kb.verdict, kb.doc.ref
| SORT @timestamp
```

Expected result (synthetic data):

| @timestamp | what | user.name | source.ip | destination.ip | firmware | value.new | kb.doc.max | kb.verdict |
|---|---|---|---|---|---|---|---|---|
| 03:51:40 | logged-in | admin | 203.0.113.47 | | 4.2 | | | |
| 03:52:05 | parameter-change setpoint | admin | 203.0.113.47 | | 4.2 | 50.0 | 50 | at documented maximum |
| 03:52:11 | netflow_flow | | 10.7.0.21 | 203.0.113.47 | | | | |
| 03:54:00 | Cold chain – abnormal temperature rise | | | | | | | |

**Notes**
- Rows without `device.id` (flows) or without a parameter (logins, alerts) simply get `null` from the joins.
- On ES|QL versions without multi-field join keys, build one key instead:

  ```esql
  | EVAL kb.key = CONCAT(device.model.identifier, ":", coldchain.parameter.code, ":", coldchain.application)
  | LOOKUP JOIN kb-controller-limits ON kb.key
  ```

  Store the same `kb.key` in the lookup index.
- After a join, fields from the lookup index overwrite same-named fields on the left. That's why the knowledge fields live under `kb.*`.
- `retail.store.id` on flows comes from an enrich processor at ingest that maps the router (`observer.ip`) to the store.
- On alerts, `retail.store.id` assumes the rule copies it from the source data. Confirm this for the ML rule type.

---

## 3. Detection rule: settings outside the documented normal

This is an ES|QL rule in Elastic Security, run every 1 minute over the last 5 minutes. It's deterministic: the knowledge base defines "normal", and no per-parameter rule is needed.

```esql
FROM logs-coldchain.audit-*
| WHERE event.action == "parameter-change"
| LOOKUP JOIN kb-assets ON device.id
| LOOKUP JOIN kb-controller-limits
    ON device.model.identifier, coldchain.parameter.code, coldchain.application
| WHERE coldchain.parameter.value.new > kb.expected.max
     OR coldchain.parameter.value.new < kb.expected.min
| STATS cabinets = COUNT_DISTINCT(device.id),
        stores   = COUNT_DISTINCT(retail.store.id),
        first    = MIN(@timestamp),
        sources  = VALUES(source.ip),
        users    = VALUES(user.name),
        refs     = VALUES(kb.doc.ref)
    BY coldchain.parameter.code, coldchain.parameter.value.new
| WHERE cabinets >= 1
| SORT stores DESC
```

With the attack data, this returns one row: `setpoint = 50.0` on 46 cabinets in 3 stores, from one source address, with the manual reference attached. The same rule catches an attacker who raises `A13` (alarm limit) or `A03` (alarm delay) to silence the alarm.

---

## 4. Act 6: who is next?

These are controllers with the same exposure that haven't been touched yet. ES|QL has no anti-join, so the query reads both indices and counts per device.

```esql
FROM kb-assets, logs-coldchain.audit-* METADATA _index
| WHERE _index LIKE "kb-assets*"
     OR (@timestamp > NOW() - 24 hours AND source.ip == "203.0.113.47")
| EVAL in_inventory = CASE(_index LIKE "kb-assets*", 1, 0),
       touched      = CASE(_index LIKE "*coldchain.audit*", 1, 0)
| STATS in_inventory = MAX(in_inventory), touched = MAX(touched),
        store = VALUES(retail.store.id), fw = VALUES(coldchain.controller.firmware),
        internet = VALUES(coldchain.exposure.internet)
    BY device.id
| WHERE in_inventory == 1 AND touched == 0 AND internet == true
| WHERE TO_VERSION(fw) < TO_VERSION("4.3.1")
| STATS controllers = COUNT(*) BY store
| SORT controllers DESC
```

This feeds the AlertZero "at risk" list: 7 stores in the storyboard. `4.3.1` is the Danfoss firmware reported to fix the 2025 vulnerabilities. Keep it generic if in doubt.

---

## 5. Knowledge retrieval: what the agent cites

The agent retrieves the manual passage it quotes. This is semantic search over a `semantic_text` field.

```esql
FROM kb-manuals METADATA _score
| WHERE device.model.identifier == "EKC 202C"
  AND MATCH(content, "temperature set point range maximum")
| SORT _score DESC
| LIMIT 3
| KEEP doc.title, doc.page, content
```

Expected top hit: "Temperature (set point) −50 °C … 50 °C, factory setting 2 °C" (Danfoss RI8KL45J, p.3). The agent explains with this passage; the detection itself came from section 3.

---

## 6. Machine learning jobs (operational data)

Abbreviated anomaly-detection job for the warming in act 2:

```json
{
  "analysis_config": {
    "bucket_span": "5m",
    "detectors": [
      { "function": "high_mean", "field_name": "coldchain.case.temperature.rise_5m",
        "partition_field_name": "device.id" }
    ],
    "influencers": ["device.id", "retail.store.id"]
  },
  "data_description": { "time_field": "@timestamp" },
  "datafeed_config": { "indices": ["metrics-coldchain.case-*"] }
}
```

- `rise_5m` is computed by the generator, or by an ingest pipeline from consecutive readings.
- The model learns the nightly defrost, so only warming outside that pattern scores.
- A second job, a population job with `over_field_name: device.id` grouped by `coldchain.application`, separates "3 stores at once" from one faulty cabinet.

---

## 7. Epilogue (scenario B): chunked download and expected-behaviour profile

The bytes received per TV box over 7 days are checked against the device type's expected destinations. The URL path is not visible over TLS; the server name, IP and client fingerprint are.

```esql
FROM logs-network_traffic.tls-*
| WHERE @timestamp > NOW() - 7 days AND retail.store.id == "S07"
| EVAL host.ip = source.ip
| LOOKUP JOIN kb-assets-by-ip ON host.ip
| LOOKUP JOIN kb-device-profiles ON retail.device.role, tls.client.server_name
| WHERE profile.allowed IS NULL
| STATS received = SUM(destination.bytes),
        sessions = COUNT(*),
        nights   = COUNT_DISTINCT(DATE_TRUNC(1 day, @timestamp)),
        ja3      = VALUES(tls.client.ja3)
    BY host.name, retail.device.role, tls.client.server_name
| EVAL received_gb = ROUND(received / 1073741824.0, 2)
| SORT received DESC
```

How to read it:
- `destination.bytes` is what the server sent to the client, so for a download it's the volume received by the TV box.
- `kb-device-profiles` holds the allowed destinations per device role (`retail.device.role`, a custom field because ECS has no device-type field), in the spirit of MUD (RFC 8520). "No match" means "not expected".
- The comparison with the 19 peer boxes is the job of an ML population job (`high_sum` of `destination.bytes` over `host.name`, by `retail.device.role`). It isn't done in this query.

---

## 8. Act 4: remove one feed (verdict panel)

This is a dashboard called "Case S07 — evidence" with three parts:

- **Control:** an options-list control on `event.dataset`, offering `coldchain.case`, `coldchain.audit` and `netflow.log`.
- **Verdict panel:** an ES|QL panel (below).
- **Event list:** an ES|QL event list (the section 2 query).

Dashboard controls filter ES|QL panels, so unticking a dataset changes both panels live.

```esql
FROM logs-coldchain.audit-*, logs-netflow.log-*, metrics-coldchain.case-*
| WHERE retail.store.id == "S07" AND @timestamp > NOW() - 1 hour
| EVAL t = CASE(event.dataset == "coldchain.case", 1, 0),
       a = CASE(event.dataset == "coldchain.audit", 1, 0),
       f = CASE(event.dataset == "netflow.log", 1, 0)
| STATS temp = SUM(t), audit = SUM(a), flows = SUM(f)
| EVAL verdict = CASE(
    temp == 0,                "Nothing happened",
    audit == 0 AND flows == 0, "A faulty cabinet",
    audit == 0,               "Odd traffic, no idea why",
    flows == 0,               "A contractor change?",
    "Remote attack: login from the internet, +50 °C setpoint, warming")
| KEEP verdict
```

**Notes**
- **The verdict is our wording.** It comes from a `CASE` expression we wrote, not from Elastic AI reasoning. Present it as a teaching panel.
- **The inventory isn't in this query.** It has no `event.dataset` and no timestamps, so its effect ("no idea who is next") is shown in act 6.
- **The control field:** if the integrations don't set `event.dataset` on every document, put the control on `data_stream.dataset` instead. Data streams always carry that field.
- **A product-native close:** open a detection rule and show its required integrations. Without the integration installed, the rule has no data. The MITRE ATT&CK coverage page makes the same point.

---

## 9. Edge architecture: queries over data federation (experimental)

In the edge setup, stores write only to a central-IT bucket on MinIO (S3-compatible):

- **`detect/`:** 1-minute files, ingested into the data streams above, for rules and ML.
- **`raw/`:** hourly files, never ingested, queried in place as ES|QL data-federation datasets.

| Dataset | Contents |
|---|---|
| `raw_store_audit` | 12 months of audit events |
| `raw_store_flows` | full NetFlow records |
| `raw_store_tls` | TLS sessions |
| `raw_store_telemetry` | long telemetry history |
| `raw_edge_metrics` | signage and plug metrics |

The schema is the same as the indexed data streams, so the field names in this file apply unchanged. Data federation is documented as experimental, Enterprise-only and Amazon-S3-only; whether a MinIO endpoint works must be tested first (fallback in the implementation brief, section 4.4). `LOOKUP JOIN` *into* a dataset isn't supported; a dataset as the source of a join against lookup indices is.

**Act 3, timeline with raw flows read in place**

```esql
FROM logs-coldchain.audit-*, raw_store_flows, .alerts-security.alerts-default
| WHERE retail.store.id == "S07" AND @timestamp > NOW() - 1 hour
| LOOKUP JOIN kb-assets ON device.id
| LOOKUP JOIN kb-controller-limits
    ON device.model.identifier, coldchain.parameter.code, coldchain.application
| EVAL kb.verdict = CASE(coldchain.parameter.value.new >= kb.doc.max, "at documented maximum", NULL)
| KEEP @timestamp, event.dataset, event.action, user.name, source.ip, destination.ip,
       coldchain.parameter.value.new, kb.doc.max, kb.verdict
| SORT @timestamp
```

**Act 5, twelve months of history that was never ingested**

```esql
FROM raw_store_audit
| WHERE @timestamp > NOW() - 365 days
  AND user.name == "admin" AND event.action == "logged-in"
  AND NOT CIDR_MATCH(source.ip, "198.51.100.0/24")      // known contractor range
| STATS logins = COUNT(*), first = MIN(@timestamp), last = MAX(@timestamp)
    BY retail.store.id, source.ip
| SORT first ASC
```

The expected result has two rows for 203.0.113.47:

- S07 with first seen T−42 days. This is the probe: one login, no changes.
- Today's 9 stores.

The probe row exists only in the bucket.

**Act 6, which stores did the attacker touch (all stores, raw flows)**

```esql
FROM raw_store_flows
| WHERE @timestamp > NOW() - 24 hours
  AND (CIDR_MATCH(destination.ip, "203.0.113.0/24") OR CIDR_MATCH(source.ip, "203.0.113.0/24"))
| STATS flows = COUNT(*), bytes = SUM(network.bytes), first = MIN(@timestamp) BY retail.store.id
| SORT first ASC
```

**Epilogue, chunked download, evidence read in place**

```esql
FROM raw_store_tls
| WHERE @timestamp > NOW() - 10 days AND retail.store.id == "S07"
| EVAL host.ip = source.ip
| LOOKUP JOIN kb-assets-by-ip ON host.ip
| LOOKUP JOIN kb-device-profiles ON retail.device.role, tls.client.server_name
| WHERE profile.allowed IS NULL
| STATS received = SUM(destination.bytes),
        chunks   = COUNT(*),
        nights   = COUNT_DISTINCT(DATE_TRUNC(1 day, @timestamp)),
        ja3      = VALUES(tls.client.ja3)
    BY host.name, tls.client.server_name
| EVAL received_gb = ROUND(received / 1073741824.0, 2)
```

The expected result is `S07-TVBOX-01`, `models.example-hub.net`, about 4.6 GB, 9 nights and about 100–200 chunks. Built and measured: 4,939,212,390 bytes (4.6), 123 chunks, 9 nights, 5.1 s. On a federated dataset, cast the join keys: `EVAL host.ip = TO_STRING(source.ip), tls.client.server_name = TO_STRING(tls.client.server_name)` before the `LOOKUP JOIN`s (strings are `text` there), and use an explicit time range for the epilogue dates. Detection itself came from the indexed flow summaries (new terms rule, ML population job). This query supplies the evidence.

**Notes**
- **Same names on both paths:** keep the field names identical on `detect/` and `raw/`, so queries move between indexed and federated data without changes.
- **Time filters:** filter on time and store early. Whether the engine prunes `dt=`/`store=` folders depends on the dataset's resource pattern and file filtering, so verify it on the tenant.
- **Cost:** every federated query costs S3 requests. Keep hourly files and consider a daily compaction.

---

## 10. Context engine: Knowledge Indicators for the cold chain (act 6+, early access)

A context engine precomputes knowledge into an AI index, so agents retrieve small structured units instead of rediscovering schemas and relationships. Elastic calls these units Knowledge Indicators (KIs). Field names below are our proposal; the product's own KI schema may differ. In the fallback, they live in a `kb-context` index with a `semantic_text` field.

```json
{ "ki": { "type": "relationship", "text": "Stores S03, S05, S07, S09, S11, S12 and S14 are serviced through one vendor-cloud account (contractor C-114). One credential reaches all of them.",
          "entities": ["S03","S05","S07","S09","S11","S12","S14","C-114"],
          "provenance": "kb-assets, contractor records", "built_by": "nightly-relationships", "valid_from": "2026-11-12" },
  "retail": { "owner": { "id": "OWN-03" } } }
```

```json
{ "ki": { "type": "quirk", "text": "EKC 202C controllers in stores S01–S10 log local time (Europe/Paris), not UTC. Shift by the offset before correlating with flows.",
          "provenance": "coldchain.audit sample analysis", "built_by": "nightly-profiles" } }
```

```json
{ "ki": { "type": "fact", "text": "203.0.113.47 first seen on S07-SM800 at T-42 days (one login, no changes). Not seen on any other controller before today.",
          "provenance": "raw_store_audit (federated, 12 months)", "built_by": "nightly-first-seen" } }
```

**The nightly first-seen automation.** It summarises the bucket once a night, so daytime hunts read the KI instead of scanning a year of raw files:

```esql
FROM raw_store_audit
| WHERE @timestamp > NOW() - 365 days AND event.action == "logged-in"
| STATS first_seen = MIN(@timestamp), logins = COUNT(*), stores = COUNT_DISTINCT(retail.store.id)
    BY source.ip, host.name
| WHERE first_seen > NOW() - 60 days          // new sources only
```

**Notes**
- **Not detection:** the context engine detects nothing; rules and ML do. KIs make the agent faster and more complete.
- **Access control:** every KI carries `retail.owner.id`. Agents retrieve with the asking user's permissions (document-level security), so cooperative owners stay separated. Verify how the context engine applies this.
- **Measure both runs:** run act 6 with and without KIs and record tool calls, tokens, latency and the finding. Elastic's published numbers are Elastic's test, not ours.

---

## Version notes (check before the build)

- **`LOOKUP JOIN` versions:**
  - Preview in 9.0, generally available since 9.1.
  - Multi-field join keys and join expressions appear as preview in later 9.x releases.
  - Fallback: the composite key in section 2.
  - Lookup indices need `index.mode: lookup`.
- **Search functions:** `MATCH` on `semantic_text` and `METADATA _score` need a recent 9.x release.
- **Alert fields:** which source fields ML rule alerts carry (for example `retail.store.id`) needs confirming per rule type.
- **Custom fields:** all `coldchain.*`, `retail.*` and `kb.*` fields are our proposal. The audit fields depend on what the system manager or vendor cloud actually exports. That is part of the PS4 integration work.
