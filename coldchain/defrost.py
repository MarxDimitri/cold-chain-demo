"""Defrost schedule: one source of truth for telemetry, audit events and the knowledge base.

Parameters live in config/defrost.yaml (factory settings from the Danfoss EKC 202 manual, plus what this chain
configured). Both the cabinet telemetry and the scheduled `defrost-start` / `defrost-stop` audit events call
`windows()`, so the audit trail and the temperature curve always agree.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import yaml

from .chain import CONFIG_DIR, Store


@lru_cache(maxsize=1)
def config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "defrost.yaml").read_text())


def slots() -> tuple[int, ...]:
    """Defrost start times as minutes of the UTC day."""
    return tuple(int(h) * 60 + int(m) for h, m in (t.split(":") for t in config()["chain"]["slots_utc"]))


def cabinet_offset(seed: int, store: Store, idx: int) -> int:
    """The cabinet's fixed offset against the clock slot (replays the draws of the telemetry generator).

    Group offset (cabinets in blocks of `group_size` defrost one group after the other) plus a store shift
    plus a small jitter inside the group (coordinated start).
    """
    rng = np.random.default_rng([seed, store.number, idx, 0])
    rng.uniform(16, 24)
    rng.uniform(0, 2 * np.pi)
    c = config()["chain"]
    lim = c["cabinet_offset_minutes"]
    jitter = int(rng.integers(-lim, lim + 1))
    groups = c["groups"]
    group = (idx // c["group_size"]) % groups
    store_shift = (store.number * 13) % c["store_stagger_minutes"]
    return group * c["group_offset_minutes"] + store_shift + jitter


def windows(seed: int, store: Store, idx: int, day: int, offset: int) -> list[tuple[int, int, float]]:
    """Defrosts of one frozen cabinet on one UTC day (`day` = days since the epoch).

    Returns (start as absolute minute, heating duration in minutes, peak air temperature in °C).
    """
    c = config()["chain"]
    lo, hi = c["duration_minutes"]
    jit = c["start_jitter_minutes"]
    rng = np.random.default_rng([seed, store.number, idx, 2, day])
    rng.random()  # kept from the earlier generator so the first two slots keep their draws
    out = []
    for base in slots():
        start = day * 1440 + base + offset + int(rng.integers(-jit, jit + 1))
        dur = int(rng.integers(lo, hi + 1))
        out.append((start, dur, float(rng.uniform(0.0, 5.0))))
    return out
