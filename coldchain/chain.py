"""Chain model: stores, cabinets and devices, loaded from config/chain.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
LOOKUP_DIR = ROOT / "elastic" / "lookup"


class Store(BaseModel):
    id: str
    town: str
    region: str
    owner: str
    internet_facing: bool
    contractor_account: str

    @property
    def number(self) -> int:
        return int(self.id[1:])

    @property
    def manager(self) -> str:
        return f"{self.id}-SM800"


class PerStore(BaseModel):
    frozen_cabinets: int
    chilled_cabinets: int
    frozen_setpoint: float
    chilled_setpoint: float
    cabinet_model: str
    manager_model: str
    patched_firmware: str
    vulnerable_firmware: str
    signage_players: int
    tv_boxes: int
    cameras: int


class Chain(BaseModel):
    name: str
    per_store: PerStore
    stores: list[Store]

    def store(self, store_id: str) -> Store:
        return next(s for s in self.stores if s.id == store_id)

    def firmware(self, store: Store) -> str:
        p = self.per_store
        return p.vulnerable_firmware if store.internet_facing else p.patched_firmware


@dataclass(frozen=True)
class Cabinet:
    id: str
    store_id: str
    application: str  # "frozen" | "chilled"
    setpoint: float


@dataclass(frozen=True)
class Device:
    name: str
    store_id: str
    role: str
    ip: str
    model: str | None = None


def load_chain(path: Path | None = None) -> Chain:
    raw = yaml.safe_load((path or CONFIG_DIR / "chain.yaml").read_text())
    return Chain(name=raw["chain"]["name"], per_store=raw["per_store"], stores=raw["stores"])


def load_attack(path: Path | None = None) -> dict:
    return yaml.safe_load((path or CONFIG_DIR / "attack.yaml").read_text())


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def cabinets(chain: Chain, store: Store) -> list[Cabinet]:
    p = chain.per_store
    out = []
    for i in range(1, p.frozen_cabinets + p.chilled_cabinets + 1):
        frozen = i <= p.frozen_cabinets
        out.append(Cabinet(f"{store.id}-C{i:02d}", store.id,
                           "frozen" if frozen else "chilled",
                           p.frozen_setpoint if frozen else p.chilled_setpoint))
    return out


def devices(chain: Chain, store: Store) -> list[Device]:
    """Non-cabinet devices. Store LAN is 10.<store number>.0.0/16."""
    n, sid, p = store.number, store.id, chain.per_store
    out = [
        Device(f"{sid}-RTR", sid, "router", f"10.{n}.0.1"),
        Device(f"{sid}-SRV", sid, "store-server", f"10.{n}.0.10"),
        Device(store.manager, sid, "system-manager", f"10.{n}.0.21", p.manager_model),
    ]
    out += [Device(f"{sid}-SIG-{i:02d}", sid, "signage-player", f"10.{n}.0.{30 + i}")
            for i in range(1, p.signage_players + 1)]
    out += [Device(f"{sid}-TVBOX-{i:02d}", sid, "tv-box", f"10.{n}.0.{40 + i}")
            for i in range(1, p.tv_boxes + 1)]
    out += [Device(f"{sid}-CAM-{i:02d}", sid, "camera", f"10.{n}.0.{50 + i}")
            for i in range(1, p.cameras + 1)]
    return out
