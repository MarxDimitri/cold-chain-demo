"""Minimal NetFlow v5 exporter, so S07's Elastic Agent (UDP NetFlow input) sees real packets."""
from __future__ import annotations

import socket
import struct
import time
import zlib
from datetime import datetime

HEADER = struct.Struct("!HHIIIIBBH")
RECORD = struct.Struct("!4s4s4sHHIIIIHHBBBBHHBBH")
PROTO = {"tcp": 6, "udp": 17}
MAX_PER_PACKET = 30


def _ip(value: str) -> bytes:
    return socket.inet_aton(value)


def encode(flows: list[dict], sequence: int, now: float | None = None) -> bytes:
    """Encode up to 30 raw flow records (netflow.log) as one NetFlow v5 packet."""
    now = now if now is not None else time.time()
    uptime = int((now % 86_400_000) * 1000) & 0xFFFFFFFF
    body = b""
    for f in flows:
        ts = datetime.fromisoformat(f["@timestamp"].replace("Z", "+00:00")).timestamp()
        first = int((ts % 86_400_000) * 1000) & 0xFFFFFFFF
        port = 49152 + zlib.crc32((f["source"]["ip"] + f["@timestamp"]).encode()) % 16000
        body += RECORD.pack(_ip(f["source"]["ip"]), _ip(f["destination"]["ip"]), b"\0\0\0\0", 1, 2,
                            f["network"]["packets"], f["network"]["bytes"], first, first,
                            port, f["destination"]["port"], 0, 0x1B, PROTO.get(f["network"]["transport"], 6), 0,
                            0, 0, 24, 24, 0)
    return HEADER.pack(5, len(flows), uptime, int(now), int((now % 1) * 1e9), sequence, 0, 0, 0) + body


class Exporter:
    def __init__(self, host: str, port: int):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sequence = 0

    def send(self, flows: list[dict]) -> None:
        for i in range(0, len(flows), MAX_PER_PACKET):
            batch = flows[i:i + MAX_PER_PACKET]
            self.sock.sendto(encode(batch, self.sequence), self.addr)
            self.sequence += len(batch)
