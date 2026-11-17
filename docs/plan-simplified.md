# Plan: the simplified demo (branch `simplified-serverless`)

The full version is preserved as the tag `v1-ech-federation-tv` (Elastic Cloud Hosted, federation, TV-box epilogue) and on `main`.

## Decisions (from the user, 2026-11-17)

1. **Elastic Cloud Serverless**, a Security project, to use custom panels (HTML, CSS and Liquid over one ES|QL query each; Preview; no JavaScript).
2. **No data federation.** The raw `raw/` files are no longer queried. The history is indexed.
3. **Frozen tier was meant, not gold.** Serverless has no tier to choose (object storage with a cache layer, search capacity sized automatically), so the "frozen" story becomes: a year of history indexed once, on storage that behaves like a frozen tier by default. Act 3b as built (searchable snapshot on a frozen node) goes away.
4. **No ES|QL explanations on the dashboards:** the query listings, the correlation query, the "one question, three places" text and the tools table. The visuals stay. ES|QL stays the engine.
5. **15 minutes** for the whole demo.
6. **POS (point of sale) systems replace the TV boxes.** The TV box did not resonate in a dry run.

Assumed unless changed: keep the S3 bucket, queue and collector as the ingestion path (reuse the bucket, re-trigger its objects); POS terminals in a store are compromised and talk to the refrigeration system manager, then change setpoints from inside.

## Run of show (15 minutes)

| Time | Act | What the audience sees |
|---|---|---|
| 0:00 | **Act 0** The realms you usually do not watch (1.5 min) | Every source, one platform, one language. The streetlight (inline SVG in a custom panel): what the live index lights, what stays in the dark. |
| 1:30 | **Act 1 and 2** The blip (4 min) | One cabinet (the contractor's view), then the whole estate. The live attack lands during this segment: 46 setpoint changes, rule 1 alerts after about 1.5 minutes. |
| 5:30 | **Act 3** The history nobody ingested (2.5 min) | A year of store audit, indexed: the same address visited S07, S11 and S19 months ago. No tier decisions. |
| 8:00 | **Act 4** The hunting agent (3.5 min) | "Something is going on and nobody asked": findings with evidence, including a POS terminal talking to the system manager. |
| 11:30 | **Act 5** The POS lead (3 min) | The evidence: what the POS terminal downloaded, when it first called the controller, how it differs from its peers. |
| 14:30 | Close (0.5 min) | Rules detect, the agent hunts, the same language everywhere. |

The live replay must be started before the presentation so that T0 lands at about minute 2; the 15 minutes do not include the pre-roll. Rule 2 (about 10 minutes after T0) falls at the end of Act 4, a bonus rather than a dependency.

## What changes

| Area | Remove | Keep | Replace or add |
|---|---|---|---|
| Platform | Hosted deployment, snapshot repository, frozen node | Terraform and S3 side | Serverless Security project |
| Federation | `federation.py`, the five datasets, `raw_*` queries, "three places" and correlation panels, federation checks | the bucket | history indexed through the collector |
| Frozen tier | `frozen.py`, Act 3b | | one history index |
| TV box | TV-box devices, flows, TLS, signage and plug metrics, `tv-box` role, the epilogue ML jobs as named | the epilogue idea | POS terminals: devices, flows, update downloads, odd traffic to the controller, peers for comparison |
| Dashboards | ES|QL text blocks, tools table | tiles, charts, tables, navigation strip | custom panels (streetlight SVG, scorecards), fewer acts (0 to 5 become 0, 1+2, 3, 4, 5) |
| Agent | `cc_history_of_address`, `cc_estate_footprint`, `cc_device_evidence` as written (they read raw files) | the other tools | the same questions over indexed data, with POS evidence |
| Docs | | README structure | architecture, runbook, story flow, brief |

## Phases and gates

1. **Spike on the Serverless project.** Gate: (a) the Dashboards API accepts a custom panel, or the panel can be authored another way and saved; (b) the collector enrols in Fleet and reads the queue; (c) a data stream, a lookup index, an ES|QL rule, an ML job and the Agent Builder agent can be created; (d) the workflow runs. Any failure is reported before building on it.
2. **Data model: POS scenario** (config, generator, knowledge base, lookups). Gate: tests pass, local generation looks right.
3. **Ingest and history on Serverless:** setup, backfill or re-trigger, indexing the year of audit. Gate: counts match expectations.
4. **Detection and agent:** rules, ML, the agent tools, the hunt. Gate: a rehearsal gives the expected alerts and findings.
5. **Dashboards:** rebuilt for six short acts with custom panels. Gate: queries return rows; the user checks the rendering.
6. **15-minute rehearsal** and documentation. Gate: a timed run.

## Risks

- **Custom panels may not be creatable through the Dashboards API** (the page mentions only the UI and the Agent Builder chat). If not, panels are authored once in the UI and exported, or the dashboards are no longer pure code.
- **Serverless limits** (settings on data streams, no snapshot APIs, feature differences) may force changes to templates, pipelines and ML.
- **The frozen-tier message** changes; the speed-versus-spend knob (Search Power) exists only on Elasticsearch projects, not Security ones.
- **The 15 minutes** are tight with a live attack; the replay has to start early.

## Needed from the user

A Serverless **Security** project: its Elasticsearch URL, Kibana URL and an API key with full privileges (kept in `.env`, never in the repository).
