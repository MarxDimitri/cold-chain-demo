"""The POS scenario: the back-office POS story is in the data, the peers are quiet."""
import pytest

from coldchain import scenario_b as sb
from coldchain.chain import load_chain

GIB = 2 ** 30


@pytest.fixture(scope="module")
def chain():
    return load_chain()


@pytest.fixture(scope="module")
def s07(chain):
    return sb.store_flows(chain, chain.store("S07"), 42)


def test_download_is_4_gib_in_96_chunks_over_7_nights(s07):
    raw, _, tls = s07
    d = sb.config()["download"]
    dl = [(t, r) for t, r in raw if r["destination"]["ip"] == d["server_ip"]]
    sizes = [r["destination"]["bytes"] for _, r in dl]
    assert len(dl) == d["chunks"] == 96
    assert abs(sum(sizes) - d["total_gib"] * GIB) < 1e6
    assert all(20e6 <= s <= 60e6 for s in sizes)
    assert len({r["@timestamp"][:10] for _, r in dl}) == d["nights"] == 7
    # TLS evidence: the server name and an unusual client fingerprint
    ev = [r for _, r in tls if r["tls"]["client"]["server_name"] == d["server_name"]]
    assert len(ev) == 96 and {r["tls"]["client"]["ja3"] for r in ev} == {d["ja3"]}
    normal = {r["tls"]["client"]["ja3"] for _, r in tls if r["host"]["name"] == "S07-POS-BO-01"
              and r["tls"]["client"]["server_name"] != d["server_name"]}
    assert d["ja3"] not in normal


def test_peer_back_office_pcs_stay_under_50_mb_a_week(chain):
    for sid in ("S03", "S12"):
        _, summary, _ = sb.store_flows(chain, chain.store(sid), 42)
        got = sum(r["destination"]["bytes"] for _, r in summary if r["host"]["name"].endswith("POS-BO-01"))
        assert got / 3 < 50e6, (sid, got / 3)  # the window is 3 weeks


def test_internal_flows_escalate_and_are_new(s07):
    _, summary, _ = s07
    first = {}
    for t, r in summary:
        if r["retail"]["device"]["role"] == "pos-backoffice":
            first.setdefault(r["destination"]["port"], r["@timestamp"][:10])
    assert first[554] == "2026-11-07"
    assert first[80] == "2026-11-09"
    ips = {r["destination"]["ip"] for _, r in summary if r["destination"]["port"] == 80}
    assert "10.7.0.21" in ips  # the system manager


def test_pos_metrics_tell_the_story(chain):
    s = chain.store("S07")
    rows = sb.pos_series(s, chain, 42, 3600)
    start, end = sb.window()
    first = sb.epoch(sb.config()["download"]["first_night"], sb.config()["download"]["night_start_utc"])

    def vals(host, sel, lo, hi, hours=None):
        return [sel(r) for t, r in rows if r["host"]["name"] == host and lo <= t < hi
                and (hours is None or (t % 86400) // 3600 in hours)]
    cpu = lambda r: r["host"]["cpu"]["usage"]
    night = range(2, 5)
    assert min(vals("S07-POS-BO-01", cpu, first, first + 86400, night)) > 0.8   # busy while the store is closed
    assert max(vals("S07-POS-BO-01", cpu, start, first)) < 0.3                 # normal before
    assert max(vals("S07-POS-01", cpu, first, end)) < 0.3                       # a lane stays quiet
    free = lambda r: r["coldchain"]["pos"]["disk_free_pct"]
    assert vals("S07-POS-BO-01", free, end - 3600 * 6, end)[-1] < 25
    tx = lambda r: r["coldchain"]["pos"]["tx_per_min"]
    assert max(vals("S07-POS-01", tx, start, end)) > 3 and max(vals("S07-POS-BO-01", tx, start, end)) == 0
