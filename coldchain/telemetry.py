"""Cabinet telemetry: 1 reading per minute per cabinet (metrics-coldchain.case).

Series are a pure function of (seed, store, cabinet, absolute minute), so a replay that starts
later continues the backfill history without a jump.
"""
from __future__ import annotations

import numpy as np

from .chain import Chain, Store, cabinets
from .defrost import cabinet_offset, config, windows


def air_rise_k() -> tuple[float, float]:
    lo, hi = config()["chain"]["air_rise_k"]
    return float(lo), float(hi)
from .sink import write_chunk


def _noise(seed: int, store: Store, idx: int, abs_m: np.ndarray, key: int = 1, sd: float = 0.12) -> np.ndarray:
    days = np.arange(abs_m[0] // 1440, abs_m[-1] // 1440 + 1)
    arr = np.concatenate([np.random.default_rng([seed, store.number, idx, key, int(d)]).normal(0, sd, 1440)
                          for d in days])
    off = int(abs_m[0] - days[0] * 1440)
    return arr[off: off + len(abs_m)]


def _defrost(air: np.ndarray, abs_m: np.ndarray, sp: float, seed: int, store: Store, idx: int,
             cab_offset: int) -> np.ndarray:
    """Add the scheduled electric defrosts (config/defrost.yaml), then a short pull-down.

    Returns a boolean mask: the defrost relay (`u60`) is on from the start to the end of the heating phase.
    """
    mask = np.zeros(len(air), dtype=bool)
    for day in range(int(abs_m[0] // 1440), int(abs_m[-1] // 1440) + 1):
        for start_abs, dur, peak_c in windows(seed, store, idx, day, cab_offset):
            start = start_abs - int(abs_m[0])
            lo_k, hi_k = air_rise_k()
            peak = lo_k + (hi_k - lo_k) * peak_c / 5.0  # peak_c is a draw in 0..5: it only scales the air rise
            x = np.arange(0, dur + 25)
            prof = np.where(x <= dur, peak * np.clip(x / dur, 0, 1) ** 1.5,
                            peak * np.exp(-(x - dur) / 8.0))
            lo, hi = max(start, 0), min(start + len(x), len(air))
            if lo < hi:
                air[lo:hi] += prof[lo - start: hi - start]
            lo, hi = max(start, 0), min(start + dur + 1, len(air))
            if lo < hi:
                mask[lo:hi] = True
    return mask


def store_series(chain: Chain, store: Store, start_epoch: int, minutes: int, seed: int):
    """Return ({cabinet id: (air, rise_5m, defrost_active)}, cabinets), arrays of length `minutes`."""
    abs_m = start_epoch // 60 + np.arange(minutes)
    minute_of_day = abs_m % 1440
    day_of_year = (abs_m // 1440) % 365
    out = {}
    cabs = cabinets(chain, store)
    for idx, cab in enumerate(cabs):
        rng = np.random.default_rng([seed, store.number, idx, 0])
        amp = 0.8 if cab.application == "frozen" else 0.5
        period, phase = rng.uniform(16, 24), rng.uniform(0, 2 * np.pi)
        cab_offset = cabinet_offset(seed, store, idx)
        air = (cab.setpoint
               + amp * np.sin(2 * np.pi * abs_m / period + phase)
               + 0.25 * np.sin(2 * np.pi * (minute_of_day - 600) / 1440)
               + 0.15 * np.sin(2 * np.pi * day_of_year / 365)
               + _noise(seed, store, idx, abs_m))
        defrosting = np.zeros(minutes, dtype=bool)
        if cab.application == "frozen":
            defrosting = _defrost(air, abs_m, cab.setpoint, seed, store, idx, cab_offset)
        rise = np.zeros(minutes)
        rise[5:] = air[5:] - air[:-5]
        out[cab.id] = (air, rise, defrosting)
    return out, cabs


def evaporator_series(chain: Chain, store: Store, start_epoch: int, minutes: int, seed: int) -> dict[str, np.ndarray]:
    """Per cabinet: the evaporator (defrost sensor S5) temperature. Same windows as the relay and the air."""
    abs_m = start_epoch // 60 + np.arange(minutes)
    ev = config()["chain"]["evaporator"]
    out = {}
    for idx, cab in enumerate(cabinets(chain, store)):
        base = (cab.setpoint + ev["offset_k"]
                + 1.5 * np.sin(2 * np.pi * abs_m / (14 + idx % 7))
                + _noise(seed, store, idx, abs_m, key=7, sd=0.3))
        if cab.application == "frozen":
            off = cabinet_offset(seed, store, idx)
            lo_c, hi_c = ev["stop_c"]
            for day in range(int(abs_m[0] // 1440), int(abs_m[-1] // 1440) + 1):
                for start_abs, dur, u in windows(seed, store, idx, day, off):
                    stop = lo_c + (hi_c - lo_c) * u / 5.0
                    heat = max(int(dur * 0.6), 1)  # S5 reaches d02 first, the heating then holds until dur
                    x = np.arange(0, dur + 30)
                    top = stop - (cab.setpoint + ev["offset_k"])
                    prof = np.where(x <= heat, top * x / heat,
                                    np.where(x <= dur, top, top * np.exp(-(x - dur) / ev["tau_min"])))
                    s = start_abs - int(abs_m[0])
                    lo, hi = max(s, 0), min(s + len(x), minutes)
                    if lo < hi:
                        base[lo:hi] += prof[lo - s: hi - s]
        out[cab.id] = base
    return out


PROBE_KEY = 9  # rng stream of the independent probes (separate from the controller's own noise)


def probe_offsets(chain: Chain, store: Store, start_epoch: int, minutes: int, seed: int) -> dict[str, np.ndarray]:
    """Per cabinet: probe reading minus true air temperature (sensor bias plus noise), by absolute minute.

    The probes are independent loggers (own battery and cellular uplink, outside the controller's trust
    boundary), so they see the true temperature even if the controller's reports are altered.
    """
    abs_m = start_epoch // 60 + np.arange(minutes)
    out = {}
    for idx, cab in enumerate(cabinets(chain, store)):
        bias = float(np.random.default_rng([seed, store.number, idx, PROBE_KEY]).normal(0, 0.2))
        out[cab.id] = bias + _noise(seed, store, idx, abs_m, key=PROBE_KEY, sd=0.15)
    return out


def probe_line(stamp: str, store: Store, cab, temp: float) -> str:
    return (f'{{"@timestamp":"{stamp}","event":{{"kind":"metric","category":["host"],"dataset":"coldchain.probe"}},'
            f'"host":{{"name":"{store.id}-LOGGER"}},"device":{{"id":"{cab.id}"}},'
            f'"retail":{{"store":{{"id":"{store.id}"}},"device":{{"role":"temperature-logger"}}}},'
            f'"coldchain":{{"application":"{cab.application}","probe":{{"temperature":{temp:.2f}}}}}}}')


def telemetry_line(stamp: str, store: Store, cab, setpoint: float, air: float, rise: float,
                   defrost: bool = False, evap: float | None = None) -> str:
    """`defrost` is the controller's defrost relay (`u60`): true while a defrost is running.
    `evap` is the evaporator (defrost sensor S5) temperature."""
    ev = f',"evaporator":{evap:.2f}' if evap is not None else ""
    return (f'{{"@timestamp":"{stamp}","event":{{"kind":"metric","category":["host"],"dataset":"coldchain.case"}},'
            f'"host":{{"name":"{store.manager}"}},"device":{{"id":"{cab.id}"}},'
            f'"retail":{{"store":{{"id":"{store.id}"}}}},'
            f'"coldchain":{{"application":"{cab.application}","case":{{"setpoint":{setpoint},'
            f'"temperature":{{"air":{air:.2f},"rise_5m":{rise:.2f}{ev}}},'
            f'"defrost":{{"active":{"true" if defrost else "false"}}}}}}}}}')


def write_telemetry(sink, chain: Chain, store: Store, layer: str, start_epoch: int, minutes: int,
                    step_minutes: int, rotation_minutes: int, seed: int) -> int:
    """Write telemetry for one store. `step_minutes` thins the 1-minute series (5 for raw history)."""
    series, cabs = store_series(chain, store, start_epoch, minutes, seed)
    evap = evaporator_series(chain, store, start_epoch, minutes, seed)
    ts = (start_epoch // 60 + np.arange(minutes)) * 60
    stamps = np.datetime_as_string(ts.astype("datetime64[s]"), unit="s", timezone="UTC")
    span = rotation_minutes * 60
    chunk = ts - ts % span
    bounds = np.flatnonzero(np.diff(chunk)) + 1
    starts = np.concatenate(([0], bounds))
    ends = np.concatenate((bounds, [minutes]))
    n = 0
    for a, b in zip(starts, ends):
        lines = []
        for cab in cabs:
            air, rise, dfr = series[cab.id]
            ev = evap[cab.id]
            for i in range(a, b):
                if (ts[i] // 60) % step_minutes:
                    continue
                lines.append(telemetry_line(stamps[i], store, cab, cab.setpoint, air[i], rise[i], bool(dfr[i]), ev[i]))
        write_chunk(sink, layer, "coldchain.case", store.id, int(chunk[a]), lines)
        n += len(lines)
    return n


PROBE_STEP = 5  # minutes between independent probe readings


def write_probe(sink, chain: Chain, store: Store, layer: str, start_epoch: int, minutes: int,
                rotation_minutes: int, seed: int) -> int:
    """Write the independent probe readings (every 5 minutes) for one store."""
    series, cabs = store_series(chain, store, start_epoch, minutes, seed)
    offs = probe_offsets(chain, store, start_epoch, minutes, seed)
    ts = (start_epoch // 60 + np.arange(minutes)) * 60
    stamps = np.datetime_as_string(ts.astype("datetime64[s]"), unit="s", timezone="UTC")
    span = rotation_minutes * 60
    chunk = ts - ts % span
    bounds = np.flatnonzero(np.diff(chunk)) + 1
    starts = np.concatenate(([0], bounds))
    ends = np.concatenate((bounds, [minutes]))
    n = 0
    for a, b in zip(starts, ends):
        lines = []
        for cab in cabs:
            air = series[cab.id][0]
            for i in range(a, b):
                if (ts[i] // 60) % PROBE_STEP:
                    continue
                lines.append(probe_line(stamps[i], store, cab, air[i] + offs[cab.id][i]))
        write_chunk(sink, layer, "coldchain.probe", store.id, int(chunk[a]), lines)
        n += len(lines)
    return n
