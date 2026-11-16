"""Scenario B (epilogue): the TV box story is in the data, the peers are quiet, the offline window is late."""
import gzip
import json
from collections import defaultdict

import pytest

from coldchain import scenario_b as sb
from coldchain.chain import load_chain
from coldchain.sink import LocalSink

GIB = 2 ** 30


@pytest.fixture(scope="module")
def chain():
    return load_chain()


@pytest.fixture(scope="module")
def s07(chain):
    return sb.store_flows(chain, chain.store("S07"), 42)


def test_download_is_4_6_gib_in_123_chunks_over_9_nights(s07):
    raw, _, tls = s07
    d = sb.config()["download"]
    dl = [(t, r) for t, r in raw if r["destination"]["ip"] == d["server_ip"]]
    sizes = [r["destination"]["bytes"] for _, r in dl]
    assert len(dl) == 123
    assert abs(sum(sizes) - 4.6 * GIB) < 1e6
    assert all(20e6 <= s <= 60e6 for s in sizes)
    assert len({r["@timestamp"][:10] for _, r in dl}) == 9
    # TLS evidence: the server name and an unusual client fingerprint, read in place in S3
    ev = [r for _, r in tls if r["tls"]["client"]["server_name"] == d["server_name"]]
    assert len(ev) == 123 and {r["tls"]["client"]["ja3"] for r in ev} == {d["ja3"]}
    normal = {r["tls"]["client"]["ja3"] for _, r in tls if r["host"]["name"] == "S07-TVBOX-01"
              and r["tls"]["client"]["server_name"] != d["server_name"]}
    assert d["ja3"] not in normal


def test_peer_tv_boxes_stay_under_50_mb_a_week(chain):
    for sid in ("S03", "S12"):
        _, summary, _ = sb.store_flows(chain, chain.store(sid), 42)
        got = sum(r["destination"]["bytes"] for _, r in summary if r["host"]["name"].endswith("TVBOX-01"))
        assert got / 3 < 50e6, (sid, got / 3)  # the window is 3 weeks


def test_internal_flows_escalate_and_are_new(s07):
    _, summary, _ = s07
    first = {}
    for t, r in summary:
        key = (r["host"]["name"].split("-", 1)[1].rsplit("-", 1)[0], r["destination"]["port"])
        first.setdefault(key, r["@timestamp"][:10])
    assert first[("TVBOX", 8080)] == "2026-11-04"
    assert first[("SIG", 554)] == "2026-11-07"
    assert first[("TVBOX", 80)] == "2026-11-09"
    ips = {r["destination"]["ip"] for _, r in summary if r["destination"]["port"] == 80}
    assert "10.7.0.21" in ips  # the system manager


def test_edge_metrics_tell_the_story(chain):
    s = chain.store("S07")
    sig, plug = sb.edge_series(s, chain, 42, 3600)
    busy = sb.epoch(sb.config()["edge"]["signage_busy_from"])

    def mean(rows, host, sel, lo, hi):
        v = [sel(r) for t, r in rows if r["host"]["name"] == host and lo <= t < hi]
        return sum(v) / len(v)
    start, end = sb.window()
    cpu = lambda r: r["host"]["cpu"]["usage"]
    assert mean(sig, "S07-SIG-02", cpu, busy, end) > 0.95
    assert mean(sig, "S07-SIG-02", cpu, start, busy) < 0.5
    assert mean(sig, "S07-SIG-01", cpu, busy, end) < 0.5
    free = lambda r: r["coldchain"]["edge"]["storage"]["free_pct"]
    assert mean(sig, "S07-SIG-02", free, end - 3600 * 6, end) < 15
    w = lambda r: r["coldchain"]["edge"]["power"]["watts"]
    first = sb.epoch(sb.config()["download"]["first_night"])
    assert mean(plug, "S07-PLUG-01", w, start, first) < 3.6
    assert 6 < mean(plug, "S07-PLUG-01", w, first + 86400, end) < 7.2


def test_offline_window_files_arrive_late(tmp_path, chain):
    sink = LocalSink(tmp_path)
    raw, summary, _ = sb.store_flows(chain, chain.store("S07"), 42)
    sb.write_late(sink, chain.store("S07"), "detect", "netflow.summary", summary, 60)
    a, b, up = sb.offline_span()
    files = list(tmp_path.rglob("*.ndjson.gz"))
    late, normal_in_window = [], 0
    for f in files:
        for line in gzip.open(f, "rt"):
            r = json.loads(line)
            t = sb.epoch(r["@timestamp"][:10], r["@timestamp"][11:16]) + int(r["@timestamp"][17:19])
            if a <= t <= b:
                if "ingested" in r["event"]:
                    late.append(r)
                else:
                    normal_in_window += 1
    assert late and normal_in_window == 0
    assert all(r["event"]["ingested"] > r["@timestamp"] and r["event"]["ingested"] >= sb.iso(up) for r in late)
