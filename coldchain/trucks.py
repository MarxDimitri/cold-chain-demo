"""Trucks delivering to the stores: telemetry (GPS and reefer temperature) and the delivery plan an ERP would hold.

    python -m coldchain.trucks plan        # print the schedule relative to T0

The fleet is fictional. Six trucks leave the two distribution centres and visit one to three stores each. The truck unit sends its
position, speed and cargo temperature every minute (dataset `logistics.truck`, no idea where it is going); the destination lives in
the ERP (`kb-erp-deliveries`: stop, planned arrival, cargo, value). Three frozen trucks are timed to reach the stores that the attack
hits (S07, S11, S19) while their cabinets are still warm: the demo's logistics story. All times are minutes relative to T0.
Hypothetical, synthetic data.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .geo import DEPOTS, STORE_GEO

SPEED_KMH = 68.0       # average road speed
ROAD_FACTOR = 1.25     # road distance over straight line
DWELL_MIN = 20         # unloading time at a store
HISTORY_MIN = 90       # minutes of telemetry before the replay starts, so the trucks are already on the road

# cargo type -> (reefer setpoint, normal reading), pallets and value of a full load
CARGO = {"frozen": (-22.0, -20.8, 12, 38400), "chilled": (2.0, 3.1, 10, 19800), "ambient": (None, 17.5, 14, 9600)}

# id, cargo, depot, minutes after T0 at which it leaves the depot (negative: before T0), stops in order
FLEET = [
    ("TRK-FZ-01", "frozen", "DCS", -19, ["S07", "S05"]),          # reaches Colmar (S07) about T0+20
    ("TRK-FZ-02", "frozen", "DCN", -4, ["S01", "S11"]),           # Strasbourg first, then Kehl (S11) about T0+25
    ("TRK-FZ-03", "frozen", "DCN", -37, ["S19", "S16"]),          # reaches Karlsruhe (S19) about T0+35
    ("TRK-FZ-04", "frozen", "DCS", -18, ["S03", "S18"]),          # frozen as well, but the stores it serves are fine
    ("TRK-CH-05", "chilled", "DCN", -25, ["S02", "S10"]),
    ("TRK-AM-06", "ambient", "DCS", -15, ["S09", "S13"]),
]


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Road distance in km between two (lon, lat) points: great circle times a road factor."""
    (lo1, la1), (lo2, la2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h)) * ROAD_FACTOR


@dataclass
class Leg:
    start: float  # minutes relative to T0
    end: float
    a: tuple[float, float]
    b: tuple[float, float]
    store: str | None  # destination store of this leg
    dwell: bool = False  # standing at the store (unloading)


@dataclass
class Truck:
    id: str
    cargo: str
    depot: str
    legs: list[Leg] = field(default_factory=list)
    stops: list[tuple[str, float]] = field(default_factory=list)  # (store, arrival minute)


def build() -> list[Truck]:
    trucks = []
    for tid, cargo, depot, leave, stops in FLEET:
        tr = Truck(tid, cargo, depot)
        pos, t = DEPOTS[depot][:2], float(leave)
        for store in stops:
            dest = STORE_GEO[store][:2]
            travel = km(pos, dest) / SPEED_KMH * 60
            tr.legs.append(Leg(t, t + travel, pos, dest, store))
            t += travel
            tr.stops.append((store, t))
            tr.legs.append(Leg(t, t + DWELL_MIN, dest, dest, store, dwell=True))
            t += DWELL_MIN
            pos = dest
        # back to the depot
        back = km(pos, DEPOTS[depot][:2]) / SPEED_KMH * 60
        tr.legs.append(Leg(t, t + back, pos, DEPOTS[depot][:2], None))
        trucks.append(tr)
    return trucks


def state(tr: Truck, m: float) -> dict | None:
    """Position of a truck at minute m (relative to T0), or None while it is parked at the depot."""
    for leg in tr.legs:
        if leg.start <= m < leg.end:
            f = (m - leg.start) / (leg.end - leg.start) if leg.end > leg.start else 0.0
            lon = leg.a[0] + (leg.b[0] - leg.a[0]) * f
            lat = leg.a[1] + (leg.b[1] - leg.a[1]) * f
            speed = 0.0 if leg.dwell else SPEED_KMH
            heading = (math.degrees(math.atan2(leg.b[0] - leg.a[0], leg.b[1] - leg.a[1])) + 360) % 360 if not leg.dwell else 0
            return {"lon": lon, "lat": lat, "speed": speed, "heading": heading,
                    "status": "unloading" if leg.dwell else "moving", "store": leg.store}
    return None


def telemetry_line(tr: Truck, m: float, ts_iso: str, rng) -> str | None:
    """One NDJSON record of the truck unit: position, speed, cargo temperature. No destination: that is in the ERP."""
    s = state(tr, m)
    if s is None:
        return None
    setpoint, normal, _, _ = CARGO[tr.cargo]
    temp = normal + float(rng.normal(0, 0.25))
    cp = {"id": tr.id, "cargo": tr.cargo, "speed_kmh": round(s["speed"] + (float(rng.normal(0, 2.0)) if s["speed"] else 0), 1),
          "heading": round(s["heading"]), "status": s["status"], "cargo_temp": round(temp, 1)}
    if setpoint is not None:
        cp["reefer_setpoint"] = setpoint
    rec = {"@timestamp": ts_iso,
           "event": {"kind": "metric", "dataset": "logistics.truck", "category": ["host"]},
           "device": {"id": tr.id},
           "host": {"geo": {"location": {"lat": round(s["lat"] + float(rng.normal(0, 0.0002)), 5), "lon": round(s["lon"] + float(rng.normal(0, 0.0002)), 5)}}},
           "coldchain": {"truck": cp}}
    return json.dumps(rec, separators=(",", ":"))


def erp_rows(t0: int) -> list[dict]:
    """The delivery plan as an ERP holds it: one row per stop, with the planned arrival, the cargo and its value."""
    rows = []
    n = 48200
    for tr in build():
        _, _, pallets, value = CARGO[tr.cargo]
        for k, (store, arrive) in enumerate(tr.stops, start=1):
            n += 1
            share = 1.0 if k == 1 else 0.55  # the first stop gets the larger drop
            lon, lat, town = STORE_GEO[store]
            planned = datetime.fromtimestamp(t0 + arrive * 60, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            rows.append({"erp": {"system": "ERP (fictional)", "delivery": {"id": f"DL-{n}", "stop": k, "planned_arrival": planned,
                                                                          "town": town, "lon": lon, "lat": lat},
                                 "cargo": {"type": tr.cargo, "pallets": round(pallets * share), "value_eur": round(value * share)}},
                         "coldchain": {"truck": {"id": tr.id}}, "retail": {"store": {"id": store}},
                         "kb": {"key": f"DL-{n}"}})
    return rows


# --- ES|QL over the truck stream, the ERP plan and the cabinets ---------------------------------------------------------------

BAD_CABINETS = 8  # frozen cabinets of a store that are too warm (setpoint raised, or air above -18 with no defrost) before the store counts as in trouble

# frozen cabinets that are not safe to load right now: setpoint raised, or above the -18 C food rule with no defrost running
BAD_CABINET = "(coldchain.case.setpoint > 5 OR (coldchain.case.temperature.air > -18 AND coldchain.case.defrost.active == false))"


def store_trouble() -> str:
    """Per store: how many frozen cabinets are not safe to load in the last 15 minutes (column bad_cabinets)."""
    return ('FROM metrics-coldchain.case-default | WHERE @timestamp >= NOW() - 15 minutes AND @timestamp <= NOW() AND coldchain.application == "frozen" '
            f"| STATS bad_cabinets = COUNT_DISTINCT(device.id) WHERE {BAD_CABINET} BY store = retail.store.id")


def upcoming_stops() -> str:
    """The latest position of every truck joined to its ERP stops that are not finished yet (one row per truck and stop)."""
    return ("FROM logs-logistics.truck-default | WHERE @timestamp >= NOW() - 10 minutes AND @timestamp <= NOW() "
            "| INLINE STATS newest = MAX(@timestamp) BY device.id | WHERE @timestamp == newest "
            "| LOOKUP JOIN kb-erp-deliveries ON coldchain.truck.id "
            "| WHERE erp.delivery.planned_arrival + 25 minutes > NOW()")


def at_risk_query(keep: str = "") -> str:
    """Frozen deliveries on their way to a store whose frozen cabinets are not safe to load: the logistics story in one ES|QL query.

    Three sources in one query: the cabinet telemetry (is the store in trouble), the truck telemetry (where is the truck, how warm is
    the cargo) and the ERP plan (which store, when, what is on board). INLINE STATS over the union joins them on the store.
    """
    return (f'FROM ({store_trouble()} | EVAL kind = "store"), ({upcoming_stops()} | EVAL store = retail.store.id, kind = "delivery") '
            f'| INLINE STATS bad = MAX(bad_cabinets) BY store | WHERE kind == "delivery" AND erp.cargo.type == "frozen" AND bad >= {BAD_CABINETS} '
            '| EVAL km_to_go = ROUND(ST_DISTANCE(host.geo.location, TO_GEOPOINT(CONCAT("POINT(", TO_STRING(erp.delivery.lon), " ", '
            'TO_STRING(erp.delivery.lat), ")"))) / 1000.0, 1), minutes_to_planned_arrival = DATE_DIFF("minutes", NOW(), erp.delivery.planned_arrival), '
            'truck_status = coldchain.truck.status, at_destination = km_to_go < 0.5 '
            + (keep or "| SORT erp.delivery.planned_arrival | KEEP coldchain.truck.id, store, bad, km_to_go, minutes_to_planned_arrival, "
                       "erp.delivery.id, erp.cargo.pallets, erp.cargo.value_eur, coldchain.truck.cargo_temp, truck_status, at_destination"))


def main() -> None:
    for tr in build():
        stops = ", ".join(f"{s} at T{a:+.0f}m" for s, a in tr.stops)
        print(f"{tr.id} ({tr.cargo}) from {tr.depot} at T{tr.legs[0].start:+.0f}m: {stops}")


if __name__ == "__main__":
    main()
