import gzip
import json
import struct
from collections import defaultdict
from pathlib import Path

import pytest

from coldchain import netflow, replay
from coldchain.chain import load_attack, load_chain, cabinets


def read(root: Path, pattern: str):
    for f in sorted(root.glob(pattern)):
        for line in gzip.open(f, "rt"):
            yield json.loads(line)


@pytest.fixture(scope="module")
def attack():
    return load_attack()


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    root = tmp_path_factory.mktemp("replay")
    replay.main(["run", "--t0", "config", "--speed", "0", "--restore", "auto", "--out", str(root)])
    return root


def test_logins_precede_t0_on_nine_stores(out, attack):
    logins = [r for r in read(out, "detect/dataset=coldchain.audit/**/*.ndjson.gz")
              if r["event"]["action"] == "logged-in" and r["source"]["ip"] == attack["attacker_ip"]]
    assert {r["retail"]["store"]["id"] for r in logins} == set(attack["touched_stores"])
    assert all(r["@timestamp"] < "2026-11-12T02:52:00Z" for r in logins)
    assert min(r["@timestamp"] for r in logins) == "2026-11-12T02:49:40Z"  # T0 - 2m20s


def test_setpoint_changed_on_46_cabinets_in_3_stores(out, attack):
    ch = [r for r in read(out, "detect/dataset=coldchain.audit/**/*.ndjson.gz")
          if r["event"]["action"] == "parameter-change" and r["user"]["name"] == "admin"]
    assert len(ch) == 46 and len({r["device"]["id"] for r in ch}) == 46
    assert {r["retail"]["store"]["id"] for r in ch} == {"S07", "S11", "S19"}
    assert all(r["coldchain"]["parameter"]["value"] == {"old": -24.0, "new": 50.0} for r in ch)
    assert all("2026-11-12T02:52:05Z" <= r["@timestamp"] <= "2026-11-12T02:52:07Z" for r in ch)


def test_restore_events_follow(out):
    rs = [r for r in read(out, "detect/dataset=coldchain.audit/**/*.ndjson.gz")
          if r["user"]["name"] == "workflow-restore"]
    assert len(rs) == 46
    assert all(r["coldchain"]["parameter"]["value"]["new"] == -24.0 for r in rs)
    assert min(r["@timestamp"] for r in rs) >= "2026-11-12T03:02:00Z"  # T0 + 10 min


def test_audit_also_lands_in_raw(out):
    n_raw = sum(1 for r in read(out, "raw/dataset=coldchain.audit/**/*.ndjson.gz")
                if r["event"]["action"] == "parameter-change")
    assert n_raw == 92  # 46 attack changes + 46 restores


def test_warming_stays_within_3_5_k_and_recovers(out):
    chain = load_chain()
    sp = {c.id: c.setpoint for s in chain.stores for c in cabinets(chain, s)}
    by_cab = defaultdict(list)
    for r in read(out, "detect/dataset=coldchain.case/store=S07/**/*.ndjson.gz"):
        by_cab[r["device"]["id"]].append((r["@timestamp"], r["coldchain"]["case"]))
    series = sorted(by_cab["S07-C14"])
    excess = [(t, c["temperature"]["air"] - sp["S07-C14"]) for t, c in series if t >= "2026-11-12T02:52:00Z"]
    peak = max(e for _, e in excess)
    assert 2.5 <= peak <= 3.5
    at = dict(excess)
    assert at["2026-11-12T03:02:00Z"] > 2.5
    assert at["2026-11-12T03:30:00Z"] < 1.5
    during = {c["setpoint"] for t, c in series if "02:53:00" <= t[11:] <= "03:01:00" and t[:10] == "2026-11-12"}
    assert during == {50.0}
    rise = max(c["temperature"]["rise_5m"] for t, c in series if "02:57:00" <= t[11:] <= "03:02:00")
    assert rise > 0.5
    # an unattacked cabinet keeps its setpoint
    assert {c["setpoint"] for _, c in by_cab["S07-C20"]} == {2.0}


def test_hunt_finds_nine_stores_in_raw_flows(out, attack):
    stores = {r["retail"]["store"]["id"] for r in read(out, "raw/dataset=netflow.log/**/*.ndjson.gz")
              if r["source"]["ip"].startswith("203.0.113.") or r["destination"]["ip"].startswith("203.0.113.")}
    assert stores == set(attack["touched_stores"])
    out_flow = [r for r in read(out, "raw/dataset=netflow.log/store=S07/**/*.ndjson.gz")
                if r["destination"]["ip"] == attack["attacker_ip"]]
    assert len(out_flow) == 1 and out_flow[0]["source"]["ip"] == "10.7.0.21"
    assert out_flow[0]["@timestamp"] == "2026-11-12T02:52:11Z"


def test_attack_summary_reaches_detect(out, attack):
    summ = [r for r in read(out, "detect/dataset=netflow.summary/**/*.ndjson.gz")
            if attack["attacker_ip"] in (r["source"]["ip"], r["destination"]["ip"])]
    assert {r["retail"]["store"]["id"] for r in summ} == set(attack["touched_stores"])


def test_netflow_v5_packet_shape():
    rec = {"@timestamp": "2026-11-12T02:52:11Z", "source": {"ip": "10.7.0.21"},
           "destination": {"ip": "203.0.113.47", "port": 443},
           "network": {"transport": "tcp", "bytes": 20500, "packets": 23}}
    pkt = netflow.encode([rec], 0)
    assert len(pkt) == 24 + 48
    version, count = struct.unpack("!HH", pkt[:4])
    assert (version, count) == (5, 1)


def test_s07_setpoints_come_from_the_tv_box_the_rest_from_outside(tmp_path_factory):
    """The blip is changed from outside (S11, S19) and from inside the store (S07: the compromised TV box)."""
    import gzip, json
    from coldchain import replay
    root = tmp_path_factory.mktemp("inside")
    replay.main(["run", "--t0", "config", "--speed", "0", "--restore", "auto", "--out", str(root)])
    src = {}
    for f in root.glob("detect/dataset=coldchain.audit/**/*.ndjson.gz"):
        for line in gzip.open(f, "rt"):
            r = json.loads(line)
            if r["event"]["action"] == "parameter-change" and r["user"]["name"] == "admin":
                src.setdefault(r["retail"]["store"]["id"], set()).add(r["source"]["ip"])
    assert src == {"S07": {"10.7.0.41"}, "S11": {"203.0.113.47"}, "S19": {"203.0.113.47"}}
