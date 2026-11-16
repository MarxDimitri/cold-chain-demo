"""Independent probes, the forced-defrost variant (A2) and the telemetry spoof option."""
import gzip
import json
from collections import defaultdict
from pathlib import Path

import pytest

from coldchain import backfill, replay
from coldchain.chain import cabinets, load_attack, load_chain

T0 = "2026-11-12T02:52:00Z"


def read(root: Path, pattern: str):
    for f in sorted(root.glob(pattern)):
        for line in gzip.open(f, "rt"):
            yield json.loads(line)


def run(tmp_path_factory, *extra):
    root = tmp_path_factory.mktemp("variant")
    replay.main(["run", "--t0", "config", "--speed", "0", "--restore", "auto", "--out", str(root), *extra])
    return root


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return run(tmp_path_factory)


@pytest.fixture(scope="module")
def defrost(tmp_path_factory):
    return run(tmp_path_factory, "--scenario", "defrost")


@pytest.fixture(scope="module")
def spoof(tmp_path_factory):
    return run(tmp_path_factory, "--spoof")


def series(root, store, cab, dataset, field):
    out = {}
    for r in read(root, f"detect/dataset={dataset}/store={store}/**/*.ndjson.gz"):
        if r["device"]["id"] == cab:
            out[r["@timestamp"]] = field(r["coldchain"])
    return out


def sp_of(cab_id):
    chain = load_chain()
    return next(c.setpoint for s in chain.stores for c in cabinets(chain, s) if c.id == cab_id)


def test_probe_records_are_ecs_shaped_and_every_five_minutes(base):
    recs = [r for r in read(base, "detect/dataset=coldchain.probe/store=S07/**/*.ndjson.gz")
            if r["device"]["id"] == "S07-C01"]
    assert recs
    r = recs[0]
    assert r["event"]["dataset"] == "coldchain.probe" and r["host"]["name"] == "S07-LOGGER"
    assert r["retail"]["device"]["role"] == "temperature-logger"
    assert isinstance(r["coldchain"]["probe"]["temperature"], float)
    assert all(int(x["@timestamp"][14:16]) % 5 == 0 for x in recs)


def test_probe_and_controller_agree_in_normal_operation(tmp_path):
    backfill.main(["--target", "local", "--out", str(tmp_path), "--stores", "S07", "--detect-days", "1",
                   "--only", "telemetry,probe"])
    for cab in ("S07-C03", "S07-C20"):  # one frozen (with defrosts), one chilled
        air = series(tmp_path, "S07", cab, "coldchain.case", lambda c: c["case"]["temperature"]["air"])
        probe = series(tmp_path, "S07", cab, "coldchain.probe", lambda c: c["probe"]["temperature"])
        common = [t for t in probe if t in air]
        assert len(common) > 250  # one day at 5-minute resolution
        assert max(abs(probe[t] - air[t]) for t in common) < 1.0


def test_probe_sees_the_warming_in_scenario_a(base):
    probe = series(base, "S07", "S07-C14", "coldchain.probe", lambda c: c["probe"]["temperature"])
    assert probe["2026-11-12T03:00:00Z"] - sp_of("S07-C14") > 1.5  # T0+8 min; probes read every 5 minutes


def test_forced_defrost_changes_no_setpoint(defrost):
    audit = list(read(defrost, "detect/dataset=coldchain.audit/**/*.ndjson.gz"))
    assert not [r for r in audit if r["event"]["action"] == "parameter-change"]
    sp = series(defrost, "S07", "S07-C14", "coldchain.case", lambda c: c["case"]["setpoint"])
    assert set(sp.values()) == {-24.0}


def test_forced_defrost_commands_come_from_the_attacker_and_repeat(defrost):
    attack = load_attack()
    cmds = [r for r in read(defrost, "detect/dataset=coldchain.audit/**/*.ndjson.gz")
            if r["event"]["action"] == "defrost-start" and r["user"]["name"] == "admin"]
    assert {r["source"]["ip"] for r in cmds} == {attack["attacker_ip"]}
    assert {r["retail"]["store"]["id"] for r in cmds} == {"S07", "S11", "S19"}
    per_cab = defaultdict(int)
    for r in cmds:
        per_cab[r["device"]["id"]] += 1
    assert len(per_cab) == 46
    assert min(per_cab.values()) >= 2  # the first command plus repeats until the restore
    assert min(r["@timestamp"] for r in cmds) == "2026-11-12T02:52:05Z" or \
        min(r["@timestamp"] for r in cmds) <= "2026-11-12T02:52:07Z"
    assert all(r["@timestamp"] < "2026-11-12T03:02:00Z" for r in cmds)  # none after the restore at T0+10 min


def test_forced_defrost_is_stopped_by_the_workflow(defrost):
    stops = [r for r in read(defrost, "detect/dataset=coldchain.audit/**/*.ndjson.gz")
             if r["event"]["action"] == "defrost-stop"]
    assert len(stops) == 46 and {r["user"]["name"] for r in stops} == {"workflow-restore"}


def test_forced_defrost_warms_like_scenario_a_and_the_probe_sees_it(defrost):
    air = series(defrost, "S07", "S07-C14", "coldchain.case", lambda c: c["case"]["temperature"]["air"])
    probe = series(defrost, "S07", "S07-C14", "coldchain.probe", lambda c: c["probe"]["temperature"])
    sp = sp_of("S07-C14")
    assert air["2026-11-12T03:00:00Z"] - sp > 1.5
    assert probe["2026-11-12T03:00:00Z"] - sp > 1.5


def test_spoof_hides_the_warming_from_the_controller_only(spoof):
    air = series(spoof, "S07", "S07-C14", "coldchain.case", lambda c: c["case"]["temperature"]["air"])
    sp = series(spoof, "S07", "S07-C14", "coldchain.case", lambda c: c["case"]["setpoint"])
    probe = series(spoof, "S07", "S07-C14", "coldchain.probe", lambda c: c["probe"]["temperature"])
    base_sp = sp_of("S07-C14")
    t = "2026-11-12T03:00:00Z"
    assert abs(air[t] - base_sp) < 1.5            # the controller reports normal
    assert sp[t] == base_sp                        # and a normal setpoint
    assert probe[t] - air[t] > 1.0                 # the independent probe diverges (about 1.5 K at T0+8 min)
    # an unattacked cabinet does not diverge
    air20 = series(spoof, "S07", "S07-C20", "coldchain.case", lambda c: c["case"]["temperature"]["air"])
    probe20 = series(spoof, "S07", "S07-C20", "coldchain.probe", lambda c: c["probe"]["temperature"])
    assert abs(probe20[t] - air20[t]) < 1.0


def test_spoof_still_leaves_the_audit_trail(spoof):
    ch = [r for r in read(spoof, "detect/dataset=coldchain.audit/**/*.ndjson.gz")
          if r["event"]["action"] == "parameter-change" and r["user"]["name"] == "admin"]
    assert len(ch) == 46
