"""Wake-on-LAN (Phase 4): PC1 wakes a sleeping PC2 with a magic packet on the LAN."""
from __future__ import annotations

import re
import socket

_MAC = re.compile(r"^([0-9a-fA-F]{2})([:-]?)([0-9a-fA-F]{2})(\2[0-9a-fA-F]{2}){4}$")


def magic_packet(mac: str) -> bytes:
    if not _MAC.match(mac.strip()):
        raise ValueError("MAC address must look like 00-11-22-33-44-55")
    raw = bytes.fromhex(re.sub(r"[^0-9a-fA-F]", "", mac))
    return b"\xff" * 6 + raw * 16


def send_magic_packet(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    pkt = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(3):  # UDP: send a few times
            s.sendto(pkt, (broadcast, port))
