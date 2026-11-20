# The truck story (Act 2): frozen deliveries heading into trouble

Hypothetical, synthetic. Real towns are used only as locations. Trucks, drivers, loads and the ERP are invented.

## The story in one minute

The attack warms the freezers of S07, S11 and S19. Nobody on the refrigeration side thinks about the trucks on the road. Three frozen trucks
(12, 7 and 12 pallets, about EUR 98,000) are 15 to 40 minutes from those stores. The truck is cold (about -21 C), the ERP knows where it is going,
and the cabinets at the destination are not. Put together in one query, the agent says: hold or reroute these three, unload into the cold room.
The flag clears by itself when the cabinets have pulled down.

On the Act 2 page: trucks move on the map (live, one position a minute), a dashed line joins each truck to its next stop, and a frozen truck
heading into trouble is red and pulses. There is no tile: catching it is the agent's job (Act 4), from the three sources, with ETA, pallets, value and cargo temperature.

## Data (three sources, three systems of record)

| Source | Where | What |
|---|---|---|
| Truck telemetry | `logs-logistics.truck-default` (dataset `logistics.truck`) | position (`host.geo.location`), speed, cargo temperature, reefer setpoint, every minute. No destination: a telematics unit does not know it |
| ERP delivery plan | `kb-erp-deliveries` (lookup index, loaded by the replay) | per stop: truck, store, planned arrival, cargo type, pallets, value in euros. The ERP is fictional and generic |
| Cabinet telemetry | `logs-coldchain.case-default` | which frozen cabinets are not safe to load right now |

`coldchain/trucks.py` holds the fleet (6 trucks, 2 depots: DC Nord and DC Sud) and the query. The query (`at_risk_query`) joins all three:
`INLINE STATS bad = MAX(bad_cabinets) BY store` over a union of the store and the delivery rows, `LOOKUP JOIN` for the ERP and `ST_DISTANCE`
for the distance. A store is "in trouble" when at least 8 of its frozen cabinets have the setpoint raised or the air above -18 C with no defrost
running (the EU quick-frozen rule). Timeline relative to T0: S07 about +20 min, S11 about +25, S19 about +35, one more frozen truck serves
fine stores (S03, S18) so the flag is not on every frozen truck.

## Honest assessment

**Coolness.** High, for three reasons. It takes the incident out of the store: the blip becomes money on a road, with a clock. It uses data the
refrigeration team has never seen (GPS, ERP) and answers a question nobody could answer by looking at one tool. And it is the cleanest
demonstration of "one platform, one language": three systems, one ES|QL query, no integration project. The geo and the movement also make Act 2
the most visual act. The risk is time: it adds about a minute and the story already has six acts, so it replaces the "20 stores" detail, not an act.

**Real business interest.** Real, with a caveat on realism.
- Frozen goods in transit are the largest single loss in a cold-chain incident, and a retailer's distribution and store systems are rarely joined:
  the ERP/WMS knows the load, the telematics knows the truck, the refrigeration SCADA knows the store, and security knows none of it.
  The decision (hold, reroute, unload into the cold room, refuse the delivery) is a logistics decision, worth tens of thousands of euros per truck.
- Real incidents motivate it: ransomware and outages at cold-chain logistics and food distributors have stopped deliveries and spoiled stock.
- It fits Elastic's strengths: geo, joins across indices, time series, and an agent that can reason over several sources.

**Caveats to say out loud.**
- A real store has a cold room and a back room, so a warm cabinet is not automatically a lost load. The agent proposes unloading into the cold room.
- A real ERP does not expose a clean lookup table: in practice this is an integration (SAP, a WMS or a TMS export). The demo's table is the shape of that feed.
- Telematics rarely knows its next stop; the join to the ERP is exactly the value. Reefer trailers do report cargo temperature (this is real).
- The GPS path is a straight line between towns, not a road route. The ETA is the ERP's planned arrival, not a prediction.

**What it does not claim.** It does not say the attacker targeted the trucks, and the agent only reports what the three sources show.

## Run it

`make demo` (or `make rehearse`) loads the ERP plan and writes the truck telemetry together with the attack, relative to T0. `make reset-demo`
removes the truck documents and the ERP plan. The agent tool is `cc_trucks_at_risk`; the hunt reports one `truck-at-risk:<store>` finding per
destination store (`make agent`, `make hunt` after this change).
