"""In-memory (or file-backed) fake plug for dry runs and tests. Switches nothing."""
from __future__ import annotations

import json
from pathlib import Path

from .base import Driver, DriverError


class DummyDriver(Driver):
    name = "dummy"

    def __init__(self, spec: dict):
        super().__init__(spec)
        self.path = Path(spec["state_file"]).expanduser() if spec.get("state_file") else None
        self._state = bool(spec.get("initial", False))
        if spec.get("fail"):
            self._fail = str(spec["fail"])
        else:
            self._fail = None

    def _load(self) -> bool:
        if self.path and self.path.exists():
            try:
                return bool(json.loads(self.path.read_text()).get("on"))
            except (ValueError, OSError):
                pass
        return self._state

    def get(self) -> bool:
        if self._fail:
            raise DriverError(f"dummy: simulated failure ({self._fail})")
        return self._load()

    def set(self, on: bool) -> bool:
        if self._fail:
            raise DriverError(f"dummy: simulated failure ({self._fail})")
        self._state = bool(on)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"on": self._state}))
        return self._load()
