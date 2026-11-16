# Defrost and food-temperature rules: what the demo takes from them (2026-11-09)

Short paraphrased facts from public sources, for the knowledge base (`kb-manuals`, `kb-regulations`,
`kb-controller-limits`). Not legal advice. Never store manual text beyond a short paraphrase.

## 1. The controller manual (verified against the text)

Source: Danfoss EKC 202A/B/C instructions RI8KL45J (08/2010, document 084R9976, SW 1.3x), parameter survey p.3,
readouts and status codes p.4. Downloaded from Danfoss; other editions and firmware can differ.
[PDF](https://assets.danfoss.com/documents/latest/28550/AN00008642932201-000401.pdf)

| Parameter | Meaning | Documented range | Factory |
|---|---|---|---|
| d01 | defrost method | none / EL / gas | EL |
| d02 | defrost stop temperature | 0 to 25 °C | 6 °C |
| d03 | interval between starts | 0 to 48 h | 8 h |
| d04 | maximum defrost duration | 0 to 180 min | 45 min |
| d06, d07 | drip-off, fan start delay | 0 to 60 min | 0 |
| d10 | what ends a defrost (time, S5, air) | 0 to 2 | 0 (time) |
| d18 | max refrigeration time between defrosts | 0 to 48 h | 0 (off) |
| A03 | temperature alarm delay | 0 to 240 min | 30 min |
| A12 | temperature alarm delay after defrost | 0 to 240 min | **90 min** |
| A13, A14 | high, low alarm limit | -50 to 50 °C | 8 °C, -30 °C |
| t01 to t06 | up to six clock start times | hours 0 to 23 | off |
| u60 | readout of the defrost relay state | | |

What follows for the data:
- **Schedule:** the factory interval of 8 h means three defrosts a day. The generator now always runs three
  (now 05:00, 13:00, 21:00 UTC, in staggered groups), not "2 or 3".
- **Duration:** 35 to 45 min, inside the factory d04 of 45 min.
- **A defrost does not alarm by itself:** A12 holds back the temperature alarm after a defrost (90 min). The
  controller's own alarm is therefore blind to a forced defrost, which is what makes variant A2 hard to see.
- **The defrost relay is visible to the network (u60):** telemetry now carries `coldchain.case.defrost.active`.
  A +50 setpoint heats the cabinet with the relay off; a forced defrost switches it on out of schedule.
- **Sequence (what the manual says and does not say):** it gives the tools, not a store layout. `d05` displaces the
  first defrost after start-up by 0 to 240 min (factory 0). A coordinated defrost over the network is supported:
  status `S1` is "waiting for the end of the coordinated defrost" and `o16` is the maximum hold time after one
  (0 to 60 min, factory 20), p.3 and p.4. How a store splits its cabinets into groups is a system-manager choice.
- **Assumption, not a manual fact:** the demo staggers the 16 frozen cabinets of a store into 4 groups of 4 that
  start 45 min apart (0, 45, 90, 135), with a 0 to 39 min shift per store and +-2 min inside a group. At any time
  about 20 to 25% of the estate's frozen cabinets are in defrost, never the whole estate. Staggering to avoid
  unloading the rack at once is common refrigeration practice; validate with a refrigeration contractor.
- **Assumption, not a manual fact:** how far the air sensor rises during a defrost (0 to +5 °C here). The manual
  gives the stop temperature for the defrost sensor, not for the air. Validate with a refrigeration contractor.

## 2. Rules on food temperature

| Rule | Paraphrase | Checked |
|---|---|---|
| [Directive 89/108/EEC](https://eur-lex.europa.eu/eli/dir/1989/108/oj/eng) Art. 1, 5 | Quick-frozen food at -18 °C or colder throughout; brief rises up to 3 K tolerated in transport; good practice tolerates up to 3 K in local distribution and retail display cabinets; Member States may allow up to 6 K in retail display cabinets | EUR-Lex text read |
| [Regulation (EC) 37/2005](https://eur-lex.europa.eu/eli/reg/2005/37/oj/eng) Art. 2, 3 | Record the **air** temperature of transport, warehousing and storage at regular intervals; instruments to EN 12830, 13485, 13486; keep records at least one year. Retail display cabinets may use one visible thermometer instead | EUR-Lex text read |
| [Regulation (EC) 852/2004](https://eur-lex.europa.eu/eli/reg/2004/852/oj) Annex II ch. IX | Do not interrupt the cold chain; limited periods outside temperature control are allowed when handling needs it and health is not at risk; thaw so pathogens do not grow | UK copy read, confirm on EUR-Lex |
| [NIS2](https://eur-lex.europa.eu/eli/dir/2022/2555/oj) Annex II | Food businesses in wholesale distribution and industrial production or processing are in scope (important entities, medium or larger). Retail is not listed per [Finnish authority guidance](https://www.ruokavirasto.fi/en/foodstuffs/food-sector/setting-up-a-food-business/kyberturvallisuusdirektiivi-nis2-elintarviketoimialalla/): the DCs of the chain may be in scope, the stores are not | Secondary, check national law |
| France, arrêté du 21 décembre 2009 | -18 °C ceiling for frozen food in retail. The "+3 °C" in the arrêté is for pre-prepared dishes, **not** frozen food | Secondary, check Légifrance |
| EN ISO 23953-2 | Display cabinets are classified by test-package temperature during a test that includes defrost; class limits not verified | Not verified |
| US (informational) | State guidance applying the FDA Food Code: cold food above 41 °F (5 °C) for more than 4 h is discarded unless a written plan applies | Secondary |

Not found: the German frozen-food ordinance text. Nothing about it is in the knowledge base.

What follows for the story:
- The rules are about **product** temperature and **air** monitoring for a year. The independent probe feed is the
  evidence an insurer or inspector asks for, and Object Lock keeps it.
- A normal defrost is allowed to warm the air; the tolerance (3 K, up to 6 K by national choice) is why a +3 K
  attack in 10 minutes is hard to tell from normal by temperature alone. Context (relay, schedule, source) decides.
- NIS2 reaches the distribution centres, probably not the stores: say so before using NIS2 in the case template.
- Open question for the data: the generator's air peak of 0 to +5 °C in every normal defrost sits above the -15 °C
  (-18 °C plus 3 K) tolerance if read as product temperature. It is air temperature, but a refrigeration contractor
  should say what a realistic return-air peak is.
