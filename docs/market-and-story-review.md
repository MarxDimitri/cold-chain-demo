# Market response and story review (2026-11-09)

Public research on the autumn 2026 refrigeration attacks, what vendors said, and what it means for the demo and a
partner blog post. **Everything here is from public sources, summarised, with links. It is not Elastic-internal.**
The storyboard footer says "TLP:AMBER+STRICT, not for partners as is": nothing from it may go into partner material
without approval. Per CLAUDE.md, never name the Estonian store.

## 1. What happened (public facts, figures disagree by source)

- **France, night of 11-12 Oct 2026:** controllers at supermarkets compromised; CERT-FR's alert (12 Oct) named Danfoss
  AK-SM and AK-SC, Copeland XWEB and Dixell XWEB. Reported scale: roughly 250 to 700 stores depending on source.
- **Second wave, 1-3 Nov:** Belgium, Luxembourg, Netherlands, Sweden, Ireland, Estonia and others, 100+ locations.
  The Estonian chain reported a freezer *setting* of +50 C but only about +2-3 C actual rise within roughly 10 minutes,
  no products damaged (Reuters via [ERR](https://news.err.ee/1610183296/hackers-raised-freezer-temperature-at-selver-supermarket-to-50-c) -
  do not reuse the store name). An Irish retailer's own monitoring alerted it and 13 stores were back to trading by 3 Nov.
- **Mechanism is reported two ways:** setpoint raised to +50 C (Estonia) and controllers forced into **defrost mode**
  (France, [Unit 42](https://unit42.paloaltonetworks.com/europes-refrigeration-systems-attacks/),
  [SentinelLABS](https://www.sentinelone.com/labs/defrost-and-disrupt-an-assessment-of-europe-s-refrigeration-attacks/)).
- **Initial access is unconfirmed.** Pointers: internet-exposed web interfaces, default or weak credentials, end-of-life
  AK-SM 800 / AK-SC 355 units, and the three AK-SM 8xxA flaws Claroty Team82 published (one is an authentication bypass
  from a date-derived value; fixed in R4.3.1; CISA ICSA-25-140-03).
- **Attribution:** none confirmed. Pro-Russian groups claimed it on Telegram on 3 Nov; Unit 42 and SentinelLABS treat the claims as unverified.
- **Government:** CERT-FR alert 12 Oct; CISA, FBI and three other US agencies joint advisory 5 Nov.

## 2. Who responded, and with what

| Who | What they said | Gap for a defender |
|---|---|---|
| **Claroty Team82** | Aug research, 2,765 exposed AK-SM 800A, 3 CVEs | Vulnerability research, not detection |
| **Forescout** ([blog](https://www.forescout.com/blog/cold-chain-open-control-exposed-refrigeration-systems-reveal-global-risk/)) | 12,976 services, 6,017 IPs, 99 countries; "correlate remote sessions with configuration, alarm and network changes"; a gateway may log a session without the setpoint change, a supervisor may log temperature without the account | Says *what* to correlate, shows no worked example |
| **Armis** | "Frostbyte10": ten Copeland E3 flaws | Vulnerability research |
| **Palo Alto Networks** ([blog](https://www.paloaltonetworks.com/blog/?p=370967), [Unit 42](https://unit42.paloaltonetworks.com/europes-refrigeration-systems-attacks/)) | Asset discovery, segmentation, virtual patching on the firewall, "alert on out-of-window setpoint changes"; says detection-only tools leave a bottleneck of writing firewall rules | Network-centric; no hunting queries or IOCs; the pitch needs their firewall at every site |
| **SentinelOne** (SentinelLABS) | Assessment, attribution open, exposed interfaces and default passwords | Analysis, no store-level detection content found |
| **Barracuda** ([blog](https://blog.barracuda.com/2026/10/30/what-managed-service-providers-can-learn-from-the-2026-french-su)) | Written for MSPs: inventory, map third-party access, out-of-band monitoring, preserve logs | Advice for partners, no product content |
| **Orange Cyberdefense** | CERT blog: legacy cold-monitoring devices without updates | Advisory |
| **Cloud Security Alliance** ([note](https://labs.cloudsecurityalliance.org/research/csa-research-note-refrigeration-ot-correlated-risk-20261103/)) | **Correlated risk**: shared controllers, shared contractors, overnight staffing gaps; monitor *outside* the control system's trust boundary; model it "like a shared cloud dependency" | Framing only |
| **Brit (insurer)** ([article](https://www.britinsurance.com/news/spoilage)) | Aggregation risk; "independent environmental verification"; inability to prove tolerance can mean destroying safe goods | Wants evidence, names no tooling |
| **CrowdStrike, Splunk, Datadog, Microsoft, Fortinet, Cisco Talos, Rapid7, Tenable** | **Nothing found** in several searches | Absence is not proven: check their blogs and social directly, or ask CI |
| **Elastic** | Nothing found | Open ground |

**Pattern:** the market converged on exposure, end-of-life, third-party access and segmentation. Almost nobody shows
detection and hunting on the data. Unit 42 states it gives no hunting queries. Forescout and the CSA note describe the
right correlation without demonstrating it. Nobody shows an estate-wide, per-owner hunt or a year of history.

## 3. Challenges to the demo, data and story

1. **We only model the +50 setpoint, but France was reported as forced defrost.** The ES|QL limits rule fires on
   `setpoint = 50`; a forced-defrost attack changes no setpoint. Add a **forced-defrost variant** (many cabinets, out of schedule,
   from an unusual source) ahead of the "quiet toggling" variant.
2. **Defrost vs attack in the ML.** A forced defrost looks like a normal defrost in `rise_5m` (already flagged in decisions.md).
   The signal is context: who issued it, schedule, simultaneity across stores. The population job and a defrost-command-rate
   rule carry that; check them before claiming "ML sees it".
3. **The telemetry comes from the controller the attacker controls.** CSA and Brit both say alarms and readings can be
   suppressed or spoofed. The demo has no independent signal for acts 1 to 7 (the smart plug appears only in the epilogue).
   Add an **independent probe feed** and a divergence rule: this is the "outside the trust boundary" point.
4. **Our audit event is too clean.** One record holds user, source IP, setpoint and cabinet. Forescout says real gateways
   log sessions without the setpoint, and supervisors log changes without the account. Split the data into a **session log**
   and a **controller change log** and make the join (time, device, ECS `host`/`device`) the work. It is harder and more credible to OT partners.
5. **Who writes to the bucket?** "Stores write to S3" hides the hard part. End-of-life controllers run nothing. Name the
   writer: store gateway or router export, the contractor's monitoring platform, vendor cloud API. Without it, OT-literate
   partners will ask on slide one.
6. **Scale and exposure numbers.** 16 of 20 managers internet-facing is high but plausible; label it illustrative. Do not
   claim the demo replays the Estonian event: the public account (+2-3 C in 10 min, no loss) matches our warming
   calibration, but the 46-cabinet, 9-store scenario is fiction.
7. **Too many ideas for one story.** ML, federation, context engine, AlertZero, Workflows, scenario B. For partners, lead
   with three: detect the cause and effect together, hunt a year in place, shared-contractor risk across owners. Keep scenario B as a labelled epilogue.
8. **Preview and experimental features.** Federation (experimental, 10,000-file limit), AlertZero, context engine and
   Workflows may not be GA or available to partners. A public blog must stand on generally available parts and call the rest "preview".
9. **Do not claim uniqueness for cheap storage or search over object storage.** Other vendors have comparable features;
   this research did not verify them. Differentiate on the combined workflow, not the mechanism.
10. **Real data availability.** The brief assumes a system manager event log or vendor-cloud API with source IP and parameter
    changes. Validate against a real AK-SM audit export before saying it on stage.

## 4. Differentiators that hold up

1. **Cause and effect in one query:** control-plane change + network session + physical effect (+ alert), which Forescout and CSA call for and nobody demonstrates.
2. **A year of raw OT history hunted in place, never ingested** (experimental): answers "was this exposure used before?" with the T-42-day probe.
3. **Estate-wide, per-owner correlation:** one contractor account across seven stores is the CSA "correlated risk" made visible; per-owner access control makes it a **partner service** (a contractor or MSP runs it for many cooperative owners).
4. **No LLM, no GPU on the detection path:** rules and ML detect; the LLM comes last. Contrast with "detect, then someone writes a firewall rule".
5. **Evidence that survives:** Object Lock bucket plus a timeline answers insurers (prove conditions stayed within tolerance) and NIS2 early warning.
6. **Vendor-neutral:** the schema covers Danfoss, Copeland, Dixell, CAREL; no sensor at every site.

## 5. Blog post for the partner ecosystem (outline, not yet drafted)

- **Audience:** refrigeration contractors, MSP/MSSPs, integrators, OT vendors. Not end customers.
- **Angle:** "Your contractors are the shared risk. Here is how to turn that into a service." Anchor on the CSA correlated-risk idea and Barracuda's MSP lesson; show the Elastic answer.
- **Structure (about 1,000 words):** 1) what public reports say, with sources and the caveat that access is unconfirmed; 2) why per-store thinking fails (shared platforms, shared contractors, unattended nights); 3) three things a partner can offer: cause-and-effect detection, estate-wide hunting, independent evidence; 4) architecture picture (stores write only to a bucket; detect indexed; hunt in place); 5) what is GA and what is preview; 6) call to action: partner enablement session, the open repo.
- **Rules:** public facts only; fictional chain; no vendor blame (say "legacy controllers"); do not name the Estonian store; label federation experimental; no attribution claims.
- **Approvals needed:** PMM, legal and comms, and a check that nothing came from the TLP:AMBER+STRICT storyboard. Time-sensitive: the news cycle is about a week old.
- **Assets:** the architecture diagram, one ES|QL screenshot of the probe-login hunt, a short recorded replay.
