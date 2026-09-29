"""Home Assistant REST API on your LAN (optional). Needs a long-lived access token from your HA
profile page; no cloud account. Works with any entity HA can turn on/off (switch., light., fan.,
input_boolean.).

    set:  POST /api/services/homeassistant/turn_on|turn_off  {"entity_id": "..."}
    get:  GET  /api/states/<entity_id>                         -> {"state": "on"|"off"|...}
"""
from __future__ import annotations

import time

from .. import httputil as H
from .base import Driver, DriverError, base_url


class HomeAssistant(Driver):
    name = "homeassistant"

    def __init__(self, spec: dict):
        super().__init__(spec)
        self.base = base_url(spec.get("url") or spec.get("host"))
        self.entity = str(spec.get("entity_id") or "")
        if "." not in self.entity:
            raise DriverError("homeassistant: 'entity_id' like switch.tent_fan is required")
        if not spec.get("token"):
            raise DriverError("homeassistant: 'token' (long-lived access token) is required")
        self.h = {"Authorization": "Bearer " + spec["token"]}

    def get(self) -> bool:
        def f():
            j = H.get_json(f"{self.base}/api/states/{self.entity}", timeout=self.timeout, headers=self.h)
            st = str((j or {}).get("state", "")).lower()
            if st not in ("on", "off"):
                raise DriverError(f"homeassistant: {self.entity} state is {st!r}")
            return st == "on"
        return self._wrap(f, "get")

    def set(self, on: bool) -> bool:
        self._wrap(lambda: H.request("POST", f"{self.base}/api/services/homeassistant/turn_{'on' if on else 'off'}",
                                     {"entity_id": self.entity}, headers=self.h, timeout=self.timeout), "set")
        st = self.get()
        for _ in range(10):  # HA state can lag the service call slightly
            if st == on:
                break
            time.sleep(0.3)
            st = self.get()
        return st
