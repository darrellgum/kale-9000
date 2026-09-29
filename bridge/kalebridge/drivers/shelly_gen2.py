"""Shelly Gen2 / Plus / Pro / Gen3 (RPC API), optional digest auth (user "admin", SHA-256).

    set:  GET /rpc/Switch.Set?id=<ch>&on=true|false   -> {"was_on": false}
    get:  GET /rpc/Switch.GetStatus?id=<ch>          -> {"id": 0, "output": true, ...}
"""
from __future__ import annotations

from .. import httputil as H
from .base import Driver, DriverError, base_url


class ShellyGen2(Driver):
    name = "shelly_gen2"

    def __init__(self, spec: dict):
        super().__init__(spec)
        self.base = base_url(spec.get("host"))
        self.ch = int(spec.get("channel") or 0)
        self.auth = (spec.get("user") or "admin", spec["password"]) if spec.get("password") else None

    def get(self) -> bool:
        def f():
            j = H.get_json(f"{self.base}/rpc/Switch.GetStatus?id={self.ch}", timeout=self.timeout, digest=self.auth)
            if not isinstance(j, dict) or "output" not in j:
                raise DriverError("shelly_gen2: unexpected reply to Switch.GetStatus")
            return bool(j["output"])
        return self._wrap(f, "get")

    def set(self, on: bool) -> bool:
        def f():
            j = H.get_json(f"{self.base}/rpc/Switch.Set?id={self.ch}&on={'true' if on else 'false'}",
                           timeout=self.timeout, digest=self.auth)
            if not isinstance(j, dict) or "was_on" not in j:
                raise DriverError("shelly_gen2: unexpected reply to Switch.Set")
        self._wrap(f, "set")
        return self.get()
