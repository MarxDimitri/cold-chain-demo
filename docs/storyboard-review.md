# Storyboard review: does the story hold? (2026-11-10)

Reviewed `06 · Cold-Chain Demo — Storyboard.pptx` (34 slides) against what the build measured and what Elastic's public
documentation says about the features. The adjusted deck is `docs/06 · Cold-Chain Demo — Storyboard v2.pptx` (the original is
untouched). It could not be rendered here (no LibreOffice): shapes were checked for bounds and the text for fit by estimate,
so **open it in PowerPoint and look at slides 14, 16, 17 and the footer strip on every act**.

## 1. What no longer holds

| Claim in the storyboard | Finding | Change |
|---|---|---|
| Act 2: "ML knows normal… no defrost in twelve months warmed this fast, never in three stores at once" | False. A normal electric defrost warms a cabinet by about 25 K; the attack warms about +3 K in 10 minutes. Per-cabinet ML on the 5-minute rise flags 1 of 46 attacked cabinets at score 75; a population job 0; a duration-feature population job 0 of 14. | Act 2 is now deterministic rules whose thresholds come from the knowledge base. The signal is the cause (defrost relay off, off schedule), not the speed. |
| Act 2: "No LLM needed" as the headline of ML | Still true for rules, but it is the rules that carry it. | Kept the line, moved to rules. |
| Clock: "ML knows normal" at T+0 | See above. | Relabelled "KB sets normal". |
| Architecture and backlog: "ML baselines per cabinet" | Same. | Slides 6, 7, 25, 34 say "rules from the KB; ML where no rule fits". |
| Act 6+: context engine "early access", needs a tenant with it | Docs: Stack 9.6 with Enterprise, or Serverless (experimental). The demo is 9.5.6 Cloud Hosted; Serverless has no federation. | Labelled "9.6 or pattern"; the act runs as the context-engine pattern (`kb-context`). |
| Act 6: AlertZero as the hunter | AlertZero is a preview. Agent Builder (GA since 9.3) with custom skills (GA since 9.4) can carry the act. | Act 6 is "the agent hunts"; AlertZero stays as the preview option with a recorded fallback. |
| Slides 33/34: MinIO, polled by the collector | The brief replaced MinIO by Amazon S3 with S3 events to SQS. | Updated. |
| Act 5: "12 months raw, index only what you detect on" | One federated dataset may match 10,000 files at most; raw audit is one file per store per day. The raw volume is smaller than the detection stream, so a cost ratio cannot be quoted. | Notes say so. No cost claim. |

## 2. What holds

Acts 1, 3, 4, 5 and 7 keep their story. The epilogue is where ML earns its place: nothing is a rule for "a TV box that never
downloads anything downloads 4.6 GB over nine nights". The principle "any single log source can be forged" strengthens Act 4: add the
independent probe as a fourth source and the forced-defrost and lying-controller variants show it.

## 3. Elastic technology per act (the new footer strip and clock line)

| Act | What carries it | Status per Elastic docs (verify on the tenant) |
|---|---|---|
| 1 Blip | Kibana dashboards (AI-drafted), ES|QL panels, logs and metrics in one store | |
| 2 KB sets normal | ES|QL detection rules, LOOKUP JOIN to `kb-thresholds` / `kb-controller-limits`, lookup indices | rule type status to confirm |
| 2+ Onboarding (new, optional) | Streams (AI pipeline suggestion), Agent Builder skills, Workflows with an approval step, ES|QL rules | Streams AI pipeline: preview since 9.3. `waitForApproval`: preview since 9.5. Workflows: GA 9.4. Skills: GA 9.4 |
| 3 Correlation | ES|QL, LOOKUP JOIN, data federation, detection alerts | federation: experimental, Enterprise |
| 4 Coverage | Dashboard controls, ES|QL panels, independent probe feed | controls filtering ES|QL panels: confirm |
| 5 History | ES|QL data federation over Amazon S3, Object Lock | experimental; 10,000-file limit |
| 6 Hunt | Agent Builder agent, custom skills, ES|QL tools, AlertZero (preview) | Agent Builder GA 9.3; skills GA 9.4 |
| 6+ Context | Workflows automations; AI index (context engine) or the `kb-context` pattern | context engine 9.6 / Serverless only |
| 7 Respond | Workflows (`http`, `waitForApproval`, `cases.*`, connectors), Cases | approval step preview |
| Epilogue | Elastic Agent + Logstash S3 output, ML population jobs, new-terms rule, LOOKUP JOIN to profiles, federation for TLS | federation experimental |

## 4. Added: Act 2+ "Onboard new equipment" (optional, no clock)

The operator says "new equipment onboarded"; a workflow maps the new model's fields with Streams, reads the manual into the KB,
measures normal on the first cabinets, proposes thresholds and rules, back-tests them over 35 days and the replays, waits for approval,
then enables them. Thresholds are rows (`kb-thresholds`) with provenance, so one set of generic rules covers every model. It is a
**proposal**: nothing is built, and short history means manual-only, low-confidence first thresholds in shadow mode.

## 5. Decisions needed

1. **The clock on the screens.** The data replays at 07:52 UTC (away from the defrost slots); the deck says 03:52. With defrosts now in groups
   (03:00-06:40 UTC and the same shifted by 8 and 16 hours), a night attack at 03:52 would land inside a defrost window. Options: (a) keep
   the data and relabel the story as 07:52 (loses the 4 a.m. line); (b) move the defrost slots to 05:00, 13:00 and 21:00 UTC and replay at
   02:52 UTC, which is 03:52 in Colmar in November (needs one more regeneration, about 1.5 hours). Recommended: (b).
2. **Times on the clock are scripted.** Replace them with measured values (ingest latency, rule interval) from `make verify`. The setpoint rule fires
   first; the warm-for-too-long rule needs about 9 minutes, close to containment, so it is the "unknown cause" net, not the lead detector.
3. **Act 2+**: keep as optional, or hold until the preview items are tested.
4. **Brief**: sections 8.2, 8.3 and 12 still describe ML as the Act 2 detector; they need the same reframing.

## 6. To verify before promising anything on stage

Streams classic-stream processing on collector-fed data streams; what a workflow can do with Streams (the `kibana.streams.*` steps are
technical preview and read-only); `waitForApproval` behaviour; Agent Builder tool and skill limits; whether ES|QL rules and dashboard
controls over ES|QL panels behave as the storyboard assumes; the LLM connector and its token cost; whether 9.6 reaches Cloud Hosted before the demo.
