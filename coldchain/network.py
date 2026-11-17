"""Normal store traffic: raw flows (netflow.log) and 5-minute summaries (netflow.summary).

Documentation ranges only: 192.0.2.0/24 stands in for external services.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

from .chain import Chain, Store, devices

# (source role, destination, port, transport, mean bytes sent, mean bytes received, diurnal)
# destination is a device role (resolved to the first device of that role) or an external IP.
PAIRS = [
    ("system-manager", "store-server", 8443, "tcp", 4_000, 1_500, False),
    ("store-server", "192.0.2.10", 443, "tcp", 60_000, 20_000, False),   # vendor cloud
    ("pos-lane", "store-server", 8443, "tcp", 6_000, 3_000, True),       # transactions to the store server
    ("pos-lane", "192.0.2.40", 443, "tcp", 4_000, 6_000, True),          # payment gateway
    ("pos-lane", "192.0.2.31", 123, "udp", 90, 90, False),               # NTP
    ("pos-backoffice", "store-server", 8443, "tcp", 10_000, 5_000, True),  # prices, reports
    ("pos-backoffice", "192.0.2.30", 443, "tcp", 3_000, 15_000, True),   # POS vendor update server (about 35 MB a week)
    ("pos-backoffice", "192.0.2.31", 123, "udp", 90, 90, False),         # NTP
    ("store-server", "camera", 554, "tcp", 2_000, 900_000, False),       # recording
]
WINDOW = 300


def _flow(ts: int, store: Store, src, dst_ip: str, port: int, proto: str, sent: int, recv: int,
          router_ip: str, dataset: str = "netflow.log") -> dict:
    return {"@timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event": {"kind": "event", "category": ["network"], "dataset": dataset},
            "source": {"ip": src.ip, "bytes": sent}, "destination": {"ip": dst_ip, "port": port, "bytes": recv},
            "network": {"transport": proto, "bytes": sent + recv, "packets": max(1, (sent + recv) // 900)},
            "observer": {"ip": router_ip}, "host": {"name": src.name},
            "retail": {"store": {"id": store.id}, "device": {"role": src.role}}}


def flows(chain: Chain, store: Store, start_epoch: int, days: float, seed: int,
          windows: int | None = None) -> tuple[list[tuple[int, dict]], list[tuple[int, dict]]]:
    """Return (raw flows, 5-minute summaries) as (epoch, record) lists.

    `windows` limits the run to that many 5-minute windows (replay generates one at a time).
    """
    rng = np.random.default_rng([seed, store.number, 11, start_epoch if windows else 0])
    devs = devices(chain, store)
    by_role = {d.role: [x for x in devs if x.role == d.role] for d in devs}
    router_ip = by_role["router"][0].ip
    raw, summary = [], []
    n_windows = windows if windows is not None else int(days * 86400 // WINDOW)
    for src_role, dst, port, proto, sent_mean, recv_mean, diurnal in PAIRS:
        for src in by_role[src_role]:
            dst_ip = by_role[dst][0].ip if dst in by_role else dst
            for w in range(n_windows):
                wstart = start_epoch + w * WINDOW
                factor = 1.0
                if diurnal:
                    hour = (wstart % 86400) / 3600
                    factor = 0.15 + 0.85 * max(0.0, np.sin(np.pi * (hour - 6) / 16)) if 6 <= hour <= 22 else 0.15
                k = int(rng.integers(1, 4))
                sent_t = recv_t = pk = 0
                for _ in range(k):
                    sent = max(40, int(rng.lognormal(np.log(sent_mean * factor + 40), 0.4)))
                    recv = max(40, int(rng.lognormal(np.log(recv_mean * factor + 40), 0.4)))
                    ts = wstart + int(rng.integers(0, WINDOW))
                    rec = _flow(ts, store, src, dst_ip, port, proto, sent, recv, router_ip)
                    raw.append((ts, rec))
                    sent_t, recv_t, pk = sent_t + sent, recv_t + recv, pk + rec["network"]["packets"]
                s = _flow(wstart, store, src, dst_ip, port, proto, sent_t, recv_t, router_ip,
                          dataset="netflow.summary")
                s["network"]["packets"], s["network"]["flows"] = pk, k
                summary.append((wstart, s))
    raw.sort(key=lambda x: x[0])
    summary.sort(key=lambda x: x[0])
    return raw, summary
