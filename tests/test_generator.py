import gzip
import json
import re
from pathlib import Path

import pytest

from coldchain import backfill, lookup
from coldchain.chain import cabinets, load_attack, load_chain

KEY = re.compile(r"^detect/dataset=[\w.]+/store=S\d\d/dt=\d{4}-\d\d-\d\d/hh=\d\d/S\d\d-\d+(-\d+)?\.ndjson\.gz$")


@pytest.fixture(scope="module")
def chain():
    return load_chain()


@pytest.fixture(scope="module")
def attack():
    return load_attack()


def read(root: Path, pattern: str):
    for f in sorted(root.glob(pattern)):
        for line in gzip.open(f, "rt"):
            yield json.loads(line)


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    root = tmp_path_factory.mktemp("bucket")
    backfill.main(["--target", "local", "--out", str(root), "--stores", "S07,S03", "--detect-days", "2"])
    return root


def test_chain_shape(chain, attack):
    assert len(chain.stores) == 20
    assert len({s.owner for s in chain.stores}) == 12
    exposed = {s.id for s in chain.stores if s.internet_facing}
    assert len(exposed) == 16
    touched = set(attack["touched_stores"])
    assert len(touched) == 9 and touched <= exposed
    assert sorted(exposed - touched) == ["S03", "S05", "S09", "S12", "S14", "S17", "S20"]
    assert all(len(cabinets(chain, s)) == 24 for s in chain.stores)


def test_attack_hits_46_cabinets_in_3_stores(attack):
    n = 0
    for rng in attack["setpoint_change"]["cabinets"].values():
        n += int(rng["to"][1:]) - int(rng["from"][1:]) + 1
    assert n == 46 and len(attack["setpoint_change"]["cabinets"]) == 3


def test_bucket_layout(out):
    keys = [str(p.relative_to(out)) for p in out.rglob("*.ndjson.gz")]
    assert keys and all(KEY.match(k) for k in keys)


def test_first_visit_is_in_the_year_of_indexed_history(out, attack):
    ip = attack["attacker_ip"]
    visits = [r for r in read(out, "detect/dataset=coldchain.audit/**/*.ndjson.gz") if r.get("source", {}).get("ip") == ip]
    assert len(visits) == 1 and visits[0]["retail"]["store"]["id"] == "S07"
    assert visits[0]["@timestamp"].startswith("2026-07-09T02:17")  # T0 - 126 days, the first of three visits (S07, S11, S19)


def test_no_attack_traffic_in_history(out, attack):
    for r in read(out, "detect/**/*.ndjson.gz"):
        if attack["attacker_ip"] in json.dumps(r):  # only the first visit of the audit history
            assert r["event"]["dataset"] == "coldchain.audit" and r["event"]["action"] == "logged-in"


def test_telemetry_in_band(out, chain):
    frozen_max, chilled = [], []
    for r in read(out, "detect/dataset=coldchain.case/store=S07/**/*.ndjson.gz"):
        air = r["coldchain"]["case"]["temperature"]["air"]
        (frozen_max if r["coldchain"]["application"] == "frozen" else chilled).append(air)
    assert max(frozen_max) < 6.0 and min(frozen_max) > -30
    assert all(-2 < a < 5 for a in chilled)
    assert len(frozen_max) + len(chilled) > 24 * 2 * 1400


def test_flow_summaries_cover_the_pos_and_the_manager(out):
    summ = list(read(out, "detect/dataset=netflow.summary/store=S07/**/*.ndjson.gz"))
    assert summ and all(not s["source"]["ip"].startswith("203.0.113.") for s in summ)
    roles = {s["retail"]["device"]["role"] for s in summ}
    assert {"pos-lane", "pos-backoffice", "system-manager", "store-server"} <= roles


def test_lookup_assets_support_act6(chain):
    assets, _ = lookup.asset_rows(chain)
    internet = [a for a in assets if a.get("coldchain", {}).get("exposure", {}).get("internet") is True]
    assert len(internet) == 16
    assert all(a["device"]["id"].endswith("-SM800") for a in internet)
    shared = {a["retail"]["store"]["id"] for a in assets
              if a["contractor"]["account"]["id"] == "C-114"}
    assert shared == {"S03", "S05", "S07", "S09", "S11", "S12", "S14"}


def test_limits_keys_unique():
    keys = [r["kb"]["key"] for r in lookup.limits_rows()]
    assert len(keys) == len(set(keys))
