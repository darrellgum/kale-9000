"""TP-Link Kasa, legacy local protocol (EXPERIMENTAL). No account needed.

TCP port 9999, 4-byte big-endian length + "autokey XOR" (initial key 171) JSON.
    set:  {"system": {"set_relay_state": {"state": 1}}}
    get:  {"system": {"get_sysinfo": {}}}  -> relay_state (or children[i].state for strips)
Works on older Kasa plugs/strips (HS100/HS103/HS105/HS110/KP115/HS300/KP303/KP400...) whose
firmware still answers on port 9999. Newer firmware that switched to the "KLAP" protocol needs
TP-Link cloud credentials and is NOT supported here (out of scope: it would need an account).
`channel` selects an outlet on a strip (0-based index into sysinfo.children).
"""
from __future__ import annotations

import json
import socket
import struct

from .base import Driver, DriverError


def encrypt(data: bytes) -> bytes:
    key, out = 171, bytearray()
    for b in data:
        key ^= b
        out.append(key)
    return struct.pack(">I", len(data)) + bytes(out)


def decrypt(data: bytes) -> bytes:
    key, out = 171, bytearray()
    for b in data:
        out.append(key ^ b)
        key = b
    return bytes(out)


class Kasa(Driver):
    name = "kasa"

    def __init__(self, spec: dict):
        super().__init__(spec)
        host = str(spec.get("host") or "").strip()
        if not host:
            raise DriverError("missing 'host'")
        if ":" in host:
            host, port = host.rsplit(":", 1)
            self.port = int(port)
        else:
            self.port = int(spec.get("port") or 9999)
        self.host = host
        self.ch = spec.get("channel")
        self._child_id = None

    def _send(self, obj: dict) -> dict:
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
            s.sendall(encrypt(json.dumps(obj).encode()))
            hdr = self._recv(s, 4)
            n = struct.unpack(">I", hdr)[0]
            if n > 1 << 20:
                raise DriverError("kasa: reply too large")
            return json.loads(decrypt(self._recv(s, n)))

    @staticmethod
    def _recv(s, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = s.recv(n - len(buf))
            if not chunk:
                raise DriverError("kasa: connection closed early")
            buf += chunk
        return buf

    def _sysinfo(self) -> dict:
        j = self._send({"system": {"get_sysinfo": {}}})
        si = (j.get("system") or {}).get("get_sysinfo") or {}
        if si.get("err_code", 0) != 0:
            raise DriverError(f"kasa: get_sysinfo err_code {si.get('err_code')}")
        return si

    def _child(self, si: dict) -> dict:
        kids = si.get("children") or []
        i = int(self.ch)
        if i >= len(kids):
            raise DriverError(f"kasa: no outlet {i} (device has {len(kids)})")
        return kids[i]

    def get(self) -> bool:
        def f():
            si = self._sysinfo()
            if self.ch is None:
                if "relay_state" not in si:
                    raise DriverError("kasa: no relay_state (strip? set 'channel')")
                return bool(si["relay_state"])
            return bool(self._child(si).get("state"))
        return self._wrap(f, "get")

    def set(self, on: bool) -> bool:
        def f():
            cmd = {"system": {"set_relay_state": {"state": 1 if on else 0}}}
            if self.ch is not None:
                si = self._sysinfo()
                cid = str(self._child(si).get("id", ""))
                if len(cid) <= 2:  # some firmware lists only the suffix
                    cid = str(si.get("deviceId", "")) + cid.zfill(2)
                cmd["context"] = {"child_ids": [cid]}
            j = self._send(cmd)
            r = (j.get("system") or {}).get("set_relay_state") or {}
            if r.get("err_code", 0) != 0:
                raise DriverError(f"kasa: set_relay_state err_code {r.get('err_code')}")
        self._wrap(f, "set")
        return self.get()
