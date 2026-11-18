"""The truck story: a fleet timed to reach the attacked stores, the ERP plan, the telemetry records and the queries."""
import json

import numpy as np

from coldchain import trucks
from coldchain.geo import DEPOTS, STORE_GEO


def test_every_store_and_depot_has_coordinates():
    assert len(STORE_GEO) == 20 and set(DEPOTS) == {"DCN", "DCS"}
    for lon, lat, _ in STORE_GEO.values():
        assert 6.9 < lon < 8.6 and 47.5 < lat < 49.1


def test_frozen_trucks_reach_the_attacked_stores_after_the_attack_and_while_cabinets_are_warm():
    arrive = {store: t for tr in trucks.build() if tr.cargo == "frozen" for store, t in tr.stops}
    assert 15 <= arrive["S07"] <= 25 and 20 <= arrive["S11"] <= 32 and 30 <= arrive["S19"] <= 45  # minutes after T0
    others = [tr for tr in trucks.build() if tr.cargo == "frozen" and not {"S07", "S11", "S19"} & {s for s, _ in tr.stops}]
    assert others, "one frozen truck serves stores that are fine, so the flag is not on every frozen truck"


def test_trucks_are_already_on_the_road_at_the_start_of_the_replay():
    moving = [tr for tr in trucks.build() if (s := trucks.state(tr, -3)) and s["status"] == "moving"]
    assert len(moving) >= 4


def test_telemetry_has_position_and_cargo_temperature_but_no_destination():
    rec = json.loads(trucks.telemetry_line(trucks.build()[0], 0, "2026-11-18T08:15:00Z", np.random.default_rng(1)))
    assert rec["event"]["dataset"] == "logistics.truck" and rec["device"]["id"] == "TRK-FZ-01"
    assert set(rec["host"]["geo"]["location"]) == {"lat", "lon"}
    assert -25 < rec["coldchain"]["truck"]["cargo_temp"] < -18  # the cargo itself is cold
    assert "destination" not in json.dumps(rec) and "store" not in rec.get("retail", {})


def test_erp_rows_carry_stop_arrival_cargo_and_value():
    rows = trucks.erp_rows(1_800_000_000)
    assert len(rows) == 12 and len({r["kb"]["key"] for r in rows}) == 12
    r = next(r for r in rows if r["retail"]["store"]["id"] == "S07")
    assert r["coldchain"]["truck"]["id"] == "TRK-FZ-01" and r["erp"]["cargo"]["type"] == "frozen"
    assert r["erp"]["cargo"]["value_eur"] > 10_000 and r["erp"]["delivery"]["planned_arrival"].endswith("Z")


def test_at_risk_query_joins_cabinets_trucks_and_the_erp_without_nesting_subqueries():
    q = trucks.at_risk_query()
    assert q.startswith("FROM (") and q.count("FROM (") == 1  # subqueries are not nested
    for part in ("metrics-coldchain.case-default", "logs-logistics.truck-default", "kb-erp-deliveries", "INLINE STATS bad = MAX(bad_cabinets) BY store",
                 'erp.cargo.type == "frozen"'):
        assert part in q


def test_the_query_says_whether_the_truck_is_at_the_destination_or_busy_elsewhere():
    q = trucks.at_risk_query()
    assert "at_destination = km_to_go < 0.5" in q and q.rstrip().endswith("at_destination")
