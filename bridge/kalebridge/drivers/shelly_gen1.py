"""Shelly Gen1 (Shelly 1, 1PM, Plug S, 2.5, ...). Local HTTP API, optional Basic auth.

    set:  GET /relay/<ch>?turn=on|off   -> {"ison": true, ...}
    get:  GET /status                    -> {"relays": [{"ison": true, ...}, ...], ...}
"""
from __future__ import annotations

from .. import httputil as H
from .base import Driver, DriverError, base_url


class ShellyGen1(Driver):
    name = "shelly_gen1"

    def __init__(self, spec: dict):
        super().__init__(spec)
        self.base = base_url(spec.get("host"))
        self.ch = int(spec.get("channel") or 0)
        self.auth = (spec.get("user") or "admin", spec["password"]) if spec.get("password") else None

    def get(self) -> bool:
        def f():
            j = H.get_json(f"{self.base}/status", timeout=self.timeout, basic=self.auth)
            relays = j.get("relays") if isinstance(j, dict) else None
            if not isinstance(relays, list) or len(relays) <= self.ch:
                raise DriverError(f"shelly_gen1: /status has no relay {self.ch}")
            return bool(relays[self.ch].get("ison"))
        return self._wrap(f, "get")

    def set(self, on: bool) -> bool:
        def f():
            j = H.get_json(f"{self.base}/relay/{self.ch}?turn={'on' if on else 'off'}", timeout=self.timeout,
                           basic=self.auth)
            if not isinstance(j, dict) or "ison" not in j:
                raise DriverError("shelly_gen1: unexpected reply to /relay")
            return bool(j["ison"])
        self._wrap(f, "set")
        return self.get()
