"""Scenario A: the +50 C setpoint attack (config/attack.yaml). All times are epoch seconds.

Everything here is synthetic and uses documentation address ranges only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from .audit import defrost_command, login, parameter_change
from .chain import Cabinet, Chain, Device, Store, cabinets, devices
from .network import WINDOW, _flow

MOCK_SERVICE_IP = "10.99.0.5"  # central IT mock response service (private range)
PULLDOWN_K = 3.5               # excess decays to ~3% over the pull-down time


def iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class AttackPlan:
    chain: Chain
    cfg: dict
    t0: int
    scenario: str = "setpoint"  # "setpoint" (A) or "defrost" (A2, forced defrost, no setpoint change)

    @property
    def attacker(self) -> str:
        return self.cfg["attacker_ip"]

    @property
    def start(self) -> int:
        """When the +50 setpoint takes effect."""
        return self.t0 + self.cfg["setpoint_change"]["offset_seconds"]

    def targets(self) -> list[tuple[Store, Cabinet]]:
        out = []
        for sid, rng in self.cfg["setpoint_change"]["cabinets"].items():
            store = self.chain.store(sid)
            lo, hi = int(rng["from"][1:]), int(rng["to"][1:])
            out += [(store, c) for c in cabinets(self.chain, store) if lo <= int(c.id[-2:]) <= hi]
        return out

    # --- physical model -------------------------------------------------------------------

    def tau(self, sp: float) -> float:
        """Time constant (min) so the air rises `rise_c` in `rise_minutes` toward ambient."""
        w = self.cfg["warming"]
        return -w["rise_minutes"] / math.log(1 - w["rise_c"] / (w["ambient_c"] - sp))

    def excess(self, sp: float, t: int, restore_t: int | None) -> float:
        """Degrees above setpoint at time t (0 before the attack and after the pull-down)."""
        if t < self.start:
            return 0.0
        amb = self.cfg["warming"]["ambient_c"]
        warm = lambda dt: (amb - sp) * (1 - math.exp(-dt / 60 / self.tau(sp)))
        if restore_t is None or t < restore_t:
            return warm(t - self.start)
        pull = self.cfg["restore"]["pulldown_minutes"] * 60
        return warm(restore_t - self.start) * math.exp(-PULLDOWN_K * (t - restore_t) / pull)

    def in_recovery(self, t: int, restore_t: int | None) -> bool:
        if t < self.start:
            return False
        if restore_t is None or t < restore_t:
            return True
        return t < restore_t + self.cfg["restore"]["pulldown_minutes"] * 60

    # --- events ---------------------------------------------------------------------------

    def __post_init__(self) -> None:
        rng = np.random.default_rng(1)
        flow_store = self.cfg["flow"]["store"]
        self.login_t = {sid: self.t0 + self.cfg["login_offset_seconds"]
                        + (0 if sid == flow_store else int(rng.integers(0, 21)))
                        for sid in self.cfg["touched_stores"]}

    def login_events(self) -> list[tuple[int, str, dict]]:
        """(epoch, store id, record): admin logins on the touched stores' system managers."""
        return [(t, sid, login(self.chain.store(sid), datetime.fromtimestamp(t, tz=timezone.utc),
                               "admin", self.attacker))
                for sid, t in self.login_t.items()]

    def setpoint_events(self, rng: np.random.Generator) -> list[tuple[int, str, dict]]:
        new = self.cfg["setpoint_change"]["new_value"]
        out = []
        for store, cab in self.targets():
            t = self.start + int(rng.integers(0, 3))
            out.append((t, store.id, parameter_change(
                store, datetime.fromtimestamp(t, tz=timezone.utc), "admin", self.source_ip(store),
                cab.id, "setpoint", cab.setpoint, new)))
        return out

    def inside_devices(self) -> dict[str, Device]:
        """Stores whose setpoints are changed from a device inside the store (config setpoint_change.from_inside)."""
        out = {}
        for sid, role in self.cfg["setpoint_change"].get("from_inside", {}).items():
            out[sid] = next(d for d in devices(self.chain, self.chain.store(sid)) if d.role == role)
        return out

    def source_ip(self, store: Store) -> str:
        """Where the change comes from: the compromised in-store device, else the internet address."""
        dev = self.inside_devices().get(store.id)
        return dev.ip if dev else self.attacker

    def defrost_events(self, t: int, rng: np.random.Generator) -> list[tuple[int, str, dict]]:
        """Scenario A2: one forced `defrost-start` per targeted cabinet at about time t."""
        out = []
        for store, cab in self.targets():
            ts = t + int(rng.integers(0, 3))
            out.append((ts, store.id, defrost_command(
                store, datetime.fromtimestamp(ts, tz=timezone.utc), "admin", self.attacker, cab.id,
                "defrost-start")))
        return out

    def defrost_times(self, lo: int, hi: int) -> list[int]:
        """Repeat times of the forced defrost command that fall in [lo, hi), after the first one."""
        step = self.cfg["forced_defrost"]["repeat_minutes"] * 60
        k = max(1, -(-(lo - self.start) // step))
        out = []
        while self.start + k * step < hi:
            out.append(self.start + k * step)
            k += 1
        return out

    def restore_events(self, restore_t: int, rng: np.random.Generator) -> list[tuple[int, str, dict]]:
        """Contractor-approved restore, issued by the response workflow through the mock service."""
        new = self.cfg["setpoint_change"]["new_value"]
        out = []
        for store, cab in self.targets():
            t = restore_t + int(rng.integers(0, 3))
            if self.scenario == "defrost":
                r = defrost_command(store, datetime.fromtimestamp(t, tz=timezone.utc), "workflow-restore",
                                    MOCK_SERVICE_IP, cab.id, "defrost-stop")
                r["coldchain"]["change"] = {"approved_by": "contractor", "reason": "stop forced defrost"}
                out.append((t, store.id, r))
                continue
            r = parameter_change(store, datetime.fromtimestamp(t, tz=timezone.utc), "workflow-restore",
                                 MOCK_SERVICE_IP, cab.id, "setpoint", new, cab.setpoint)
            r["coldchain"]["change"] = {"approved_by": "contractor", "reason": "restore after unauthorised change"}
            out.append((t, store.id, r))
        return out

    def attack_flows(self) -> list[tuple[int, str, dict]]:
        """Raw flows: inbound login sessions on the 9 touched stores, plus S07's outbound flow.

        The act 6 hunt matches the attacker range as source or destination, so each touched
        store shows up through its inbound login session.
        """
        out = []
        for sid, t in self.login_t.items():
            store = self.chain.store(sid)
            devs = devices(self.chain, store)
            sm = next(d for d in devs if d.role == "system-manager")
            router = next(d for d in devs if d.role == "router")
            ext = Device(sm.name, sid, "system-manager", self.attacker)
            out.append((t, sid, _flow(t, store, ext, sm.ip, 443, "tcp", 3_200, 41_000, router.ip)))
        for sid, dev in self.inside_devices().items():  # the pivot: the in-store device calls the system manager on tcp/80
            store = self.chain.store(sid)
            devs = devices(self.chain, store)
            sm = next(d for d in devs if d.role == "system-manager")
            router = next(d for d in devs if d.role == "router")
            t = self.t0 + 3
            out.append((t, sid, _flow(t, store, dev, sm.ip, 80, "tcp", 6_000, 14_000, router.ip)))
        f = self.cfg["flow"]
        store = self.chain.store(f["store"])
        devs = devices(self.chain, store)
        sm = next(d for d in devs if d.role == "system-manager")
        router = next(d for d in devs if d.role == "router")
        t = self.t0 + f["offset_seconds"]
        out.append((t, store.id, _flow(t, store, sm, self.attacker, 443, "tcp", 18_000, 2_500, router.ip)))
        return out

    @staticmethod
    def summarize(flows: list[tuple[int, str, dict]]) -> list[tuple[int, str, dict]]:
        """Derive 5-minute summaries (netflow.summary) from raw attack flows."""
        groups: dict[tuple, dict] = {}
        for t, sid, rec in flows:
            w = t - t % WINDOW
            key = (w, sid, rec["source"]["ip"], rec["destination"]["ip"], rec["destination"]["port"])
            if key not in groups:
                s = {**rec, "event": {**rec["event"], "dataset": "netflow.summary"},
                     "@timestamp": iso(w), "source": {**rec["source"], "bytes": 0},
                     "destination": {**rec["destination"], "bytes": 0},
                     "network": {**rec["network"], "bytes": 0, "packets": 0, "flows": 0}}
                groups[key] = s
            g = groups[key]
            g["source"]["bytes"] += rec["source"]["bytes"]
            g["destination"]["bytes"] += rec["destination"]["bytes"]
            g["network"]["bytes"] += rec["network"]["bytes"]
            g["network"]["packets"] += rec["network"]["packets"]
            g["network"]["flows"] += 1
        return [(k[0], k[1], g) for k, g in groups.items()]
