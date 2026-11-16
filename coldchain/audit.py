"""Audit history (logs-coldchain.audit): contractor logins, in-range changes, defrost commands, the probe."""
from __future__ import annotations

import zlib
from datetime import datetime, timedelta, timezone

import numpy as np

from .chain import Chain, Store, cabinets
from .defrost import cabinet_offset, windows

PARAM_NAMES = {"setpoint": ("Temperature set point", "°C"),
               "A13": ("High alarm limit", "°C"),
               "A03": ("Alarm delay", "min")}


def _base(store: Store, ts: datetime, action: str, outcome: str = "success") -> dict:
    return {"@timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event": {"kind": "event", "dataset": "coldchain.audit", "action": action, "outcome": outcome},
            "host": {"name": store.manager}, "device": {"id": store.manager},
            "retail": {"store": {"id": store.id}}}


def login(store: Store, ts: datetime, user: str, ip: str) -> dict:
    r = _base(store, ts, "logged-in")
    r["event"] |= {"category": ["authentication"], "type": ["start"]}
    r["user"], r["source"] = {"name": user}, {"ip": ip}
    return r


def parameter_change(store: Store, ts: datetime, user: str, ip: str, cabinet: str,
                     code: str, old: float, new: float) -> dict:
    name, unit = PARAM_NAMES[code]
    r = _base(store, ts, "parameter-change")
    r["event"] |= {"category": ["configuration"], "type": ["change"]}
    r["user"], r["source"], r["device"] = {"name": user}, {"ip": ip}, {"id": cabinet}
    r["coldchain"] = {"parameter": {"code": code, "name": name, "unit": unit,
                                    "value": {"old": float(old), "new": float(new)}}}
    return r


def defrost_command(store: Store, ts: datetime, user: str, ip: str, cabinet: str, action: str) -> dict:
    """A defrost command on one cabinet (action: defrost-start or defrost-stop). The system schedule issues
    these from the store LAN as user `system`; a forced defrost comes from an outside address."""
    r = _base(store, ts, action)
    r["event"] |= {"category": ["configuration"], "type": ["info"]}
    r["user"], r["source"], r["device"] = {"name": user}, {"ip": ip}, {"id": cabinet}
    r["coldchain"] = {"parameter": {"code": "defrost", "name": "Defrost start" if action == "defrost-start"
                                    else "Defrost stop"}}
    return r


def _normal_change(rng, cab) -> tuple[str, float, float]:
    code = str(rng.choice(["setpoint", "A13", "A03"], p=[0.5, 0.25, 0.25]))
    frozen = cab.application == "frozen"
    if code == "setpoint":
        old = cab.setpoint
        new = old + float(rng.choice([-1, 1, 2]))
    elif code == "A13":
        old = -15.0 if frozen else 10.0
        new = old + float(rng.choice([-1, 1]))
    else:
        old = 45.0
        new = float(rng.choice([30, 45, 60]))
    return code, old, new


def audit_history(chain: Chain, store: Store, start: datetime, end: datetime, seed: int,
                  probes: list[dict] | None, t0: datetime) -> list[tuple[int, dict]]:
    """12 months of normal activity for one store, plus the attacker's first visit if one of `probes` targets it."""
    rng = np.random.default_rng([seed, store.number, 7])
    cabs = cabinets(chain, store)
    contractor_ip = f"198.51.100.{10 + zlib.crc32(store.contractor_account.encode()) % 40}"
    lan_ip = f"10.{store.number}.0.21"
    out: list[dict] = []
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end:
        # scheduled defrosts: the same windows as the telemetry (config/defrost.yaml), one start and one stop per cabinet
        day_index = int(day.timestamp() // 86400)
        for idx, cab in enumerate(cabs):
            if cab.application != "frozen":
                continue
            for start_abs, dur, _ in windows(seed, store, idx, day_index, cabinet_offset(seed, store, idx)):
                for action, minute in (("defrost-start", start_abs), ("defrost-stop", start_abs + dur)):
                    out.append(defrost_command(store, datetime.fromtimestamp(minute * 60, tz=timezone.utc),
                                               "system", lan_ip, cab.id, action))
        # contractor session on a weekday daytime
        if day.weekday() < 5 and rng.random() < 0.18:
            ts = day + timedelta(hours=int(rng.integers(8, 17)), minutes=int(rng.integers(0, 60)))
            out.append(login(store, ts, "admin", contractor_ip))
            for _ in range(int(rng.integers(0, 4))):
                ts += timedelta(minutes=int(rng.integers(1, 4)))
                cab = cabs[int(rng.integers(0, len(cabs)))]
                code, old, new = _normal_change(rng, cab)
                out.append(parameter_change(store, ts, "admin", contractor_ip, cab.id, code, old, new))
        day += timedelta(days=1)

    for probe in probes or []:
        if probe["store"] != store.id:
            continue
        d = (t0 - timedelta(days=probe["days_before_t0"])).date()
        hh, mm, ss = map(int, probe["time_utc"].split(":"))
        ts = datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=timezone.utc)
        out.append(login(store, ts, probe["user"], probe["attacker_ip"]))

    return sorted(((int(datetime.fromisoformat(r["@timestamp"].replace("Z", "+00:00")).timestamp()), r)
                   for r in out if start <= datetime.fromisoformat(r["@timestamp"].replace("Z", "+00:00")) < end),
                  key=lambda x: x[0])
