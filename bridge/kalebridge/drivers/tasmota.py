"""Tasmota (flashed Sonoff, Athom, Gosund, ... plugs). Local HTTP, optional web user/password.

    set:  GET /cm?cmnd=Power<N>%20On|Off   -> {"POWER": "ON"}  (or "POWER<N>")
    get:  GET /cm?cmnd=Power<N>            -> {"POWER": "OFF"}
`channel` is Tasmota's relay number (1-based); leave it out for single-relay plugs.
"""
from __future__ import annotations

import urllib.parse

from .. import httputil as H
from .base import Driver, DriverError, base_url


class Tasmota(Driver):
    name = "tasmota"

    def __init__(self, spec: dict):
        super().__init__(spec)
        self.base = base_url(spec.get("host"))
        ch = spec.get("channel")
        self.n = "" if ch in (None, "", 0) else str(int(ch))
        self.user = spec.get("user") or "admin"
        self.password = spec.get("password")

    def _cmd(self, cmnd: str) -> bool:
        q = {"cmnd": cmnd}
        if self.password:
            q.update({"user": self.user, "password": self.password})
        j = H.get_json(f"{self.base}/cm?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote),
                       timeout=self.timeout)
        if not isinstance(j, dict):
            raise DriverError("tasmota: unexpected reply")
        if "WARNING" in j or "Command" in j and j.get("Command") == "Unknown":
            raise DriverError(f"tasmota: {str(j.get('WARNING') or j)[:120]}")
        for k in (f"POWER{self.n}", "POWER", "POWER1" if not self.n else None):
            if k and k in j:
                v = str(j[k]).upper()
                if v in ("ON", "OFF"):
                    return v == "ON"
        raise DriverError("tasmota: reply has no POWER field (wrong channel?)")

    def get(self) -> bool:
        return self._wrap(lambda: self._cmd(f"Power{self.n}"), "get")

    def set(self, on: bool) -> bool:
        self._wrap(lambda: self._cmd(f"Power{self.n} {'On' if on else 'Off'}"), "set")
        return self.get()
