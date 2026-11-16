"""The defrost model follows the manual (config/defrost.yaml) and the audit trail matches the temperature curve."""
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from coldchain import backfill, lookup, replay
from coldchain.chain import load_chain
from coldchain.defrost import config, slots
from coldchain.telemetry import store_series


def read(root: Path, pattern: str):
    for f in sorted(root.glob(pattern)):
        for line in gzip.open(f, "rt"):
            yield json.loads(line)


def minute(ts: str) -> int:
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() // 60)


@pytest.fixture(scope="module")
def chain():
    return load_chain()


@pytest.fixture(scope="module")
def two_days(tmp_path_factory, chain):
    root = tmp_path_factory.mktemp("defrost")
    backfill.main(["--target", "local", "--out", str(root), "--stores", "S07", "--detect-days", "2",
                   "--flow-days", "1", "--raw-days", "3", "--only", "telemetry,audit"])
    return root


def test_chain_settings_stay_inside_the_manual():
    c, m = config()["chain"], config()["manual"]
    assert c["duration_minutes"][1] <= m["d04"]["factory"] <= m["d04"]["max"]  # never longer than d04
    assert len(c["slots_utc"]) * m["d03"]["factory"] == 24                       # three starts = the factory 8 h interval
    for code, (lo, hi) in c["expected"].items():
        assert m[code]["min"] <= lo <= hi <= m[code]["max"], code
    assert slots() == (300, 780, 1260)


def test_defrost_relay_matches_the_schedule(chain):
    store = chain.store("S07")
    start = int(datetime(2026, 11, 10, tzinfo=timezone.utc).timestamp())
    series, cabs = store_series(chain, store, start, 3 * 1440, 42)
    for cab in cabs:
        air, rise, relay = series[cab.id]
        if cab.application == "chilled":
            assert not relay.any()
            continue
        runs = np.flatnonzero(np.diff(np.concatenate(([0], relay.astype(int), [0]))))
        starts, ends = runs[::2], runs[1::2]
        assert len(starts) == 9                                   # three a day for three days
        assert (ends - starts).max() <= config()["manual"]["d04"]["factory"] + 1
        gaps = np.diff(starts)
        assert gaps.min() >= 480 - 12 and gaps.max() <= 480 + 12  # the d03 interval, plus the start jitter
        assert air[relay].mean() > air[~relay].mean() + 3          # the air does warm while the relay is on


def test_audit_defrosts_align_with_telemetry(two_days):
    tel = {}
    for r in read(two_days, "detect/dataset=coldchain.case/store=S07/**/*.ndjson.gz"):
        if r["device"]["id"] == "S07-C03":
            tel[minute(r["@timestamp"])] = r["coldchain"]["case"]["defrost"]["active"]
    audit = [r for r in read(two_days, "detect/dataset=coldchain.audit/store=S07/**/*.ndjson.gz")
             if r["device"]["id"] == "S07-C03" and r["event"]["action"].startswith("defrost")]
    starts = sorted(minute(r["@timestamp"]) for r in audit if r["event"]["action"] == "defrost-start")
    assert starts and all(r["user"]["name"] == "system" and r["source"]["ip"] == "10.7.0.21" for r in audit)
    inside = [m for m in starts if m - 1 in tel and m in tel]
    assert inside
    for m in inside:
        assert tel[m] and not tel[m - 1]  # the relay switches on in the minute of the audit event


def test_kb_rows_are_consistent():
    rows = lookup.limits_rows()
    keys = [r["kb"]["key"] for r in rows]
    assert len(keys) == len(set(keys))
    for r in rows:
        k = r["kb"]
        if "factory" in k and isinstance(k["factory"], (int, float)):
            assert k["doc"]["min"] <= k["factory"] <= k["doc"]["max"], k["key"]
        assert k["doc"]["min"] <= k["expected"]["min"] <= k["expected"]["max"] <= k["doc"]["max"], k["key"]
    codes = {r["coldchain"]["parameter"]["code"] for r in rows}
    assert {"d02", "d03", "d04", "d06", "A12"} <= codes
    assert all(m["doc"]["page"] in (3, 4) and m["kb"]["verified"] for m in lookup.manual_rows())
    reg = lookup.regulation_rows()
    assert {r["kb"]["jurisdiction"] for r in reg} >= {"EU", "FR", "US"}
    assert all(r["kb"]["source"]["url"].startswith("https://") for r in reg)


def run(tmp_path_factory, *extra):
    root = tmp_path_factory.mktemp("rep")
    replay.main(["run", "--t0", "config", "--speed", "0", "--restore", "auto", "--out", str(root), *extra])
    return {(r["device"]["id"], r["@timestamp"]): r["coldchain"]["case"]["defrost"]["active"]
            for r in read(root, "detect/dataset=coldchain.case/store=S07/**/*.ndjson.gz")}


def test_defrost_relay_in_the_attacks(tmp_path_factory):
    setpoint = run(tmp_path_factory)
    forced = run(tmp_path_factory, "--scenario", "defrost")
    spoof = run(tmp_path_factory, "--scenario", "defrost", "--spoof")
    t = ("S07-C14", "2026-11-12T02:58:00Z")
    assert setpoint[t] is False  # the +50 setpoint heats the cabinet without a defrost: the relay stays off
    assert forced[t] is True     # a forced defrost switches the relay on, outside any scheduled slot
    assert spoof[t] is False     # a spoofed controller reports the normal state


def test_defrost_groups_are_staggered_and_clear_of_t0():
    from coldchain import defrost
    day = 20800
    chain = load_chain()
    spans = []
    for s in chain.stores:
        for idx in range(16):
            off = defrost.cabinet_offset(42, s, idx)
            spans += [((st - day * 1440), d) for st, d, _ in defrost.windows(42, s, idx, day, off)]
    for t in range(0, 1440, 5):
        assert sum(1 for m, d in spans if m <= t < m + d) / 320 < 0.35  # never a whole-estate defrost
    assert not [1 for m, d in spans if m < 2 * 60 + 53 < m + d]  # the attack start (02:52 UTC) is outside
    assert len({m % 480 // 30 for m, _ in spans}) >= 4  # several groups, not one slot


def test_air_and_evaporator_swing_differently(chain):
    """The air (Sair) rises about 8-14 K in a defrost; the evaporator (S5) swings about 40 K. Never the same channel."""
    from coldchain.telemetry import evaporator_series
    store = chain.store("S07")
    start = int(datetime(2026, 11, 10, tzinfo=timezone.utc).timestamp())
    series, cabs = store_series(chain, store, start, 2 * 1440, 42)
    evap = evaporator_series(chain, store, start, 2 * 1440, 42)
    cab = next(c for c in cabs if c.application == "frozen")
    air = series[cab.id][0]
    assert 7 <= air.max() - cab.setpoint <= 16
    assert 30 <= evap[cab.id].max() - evap[cab.id].min() <= 45
    assert evap[cab.id].max() > 5  # S5 reaches the stop temperature d02
