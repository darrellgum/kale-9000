"""Pluggable plug drivers. Each module defines one Driver subclass; the registry maps the
`driver` name used in aliases.json to the class.

    {"driver": "shelly_gen2", "host": "device-50.lan", "channel": 0, "password": "..."}

Every driver implements:
    get() -> bool            current relay state (True = on); raises DriverError
    set(on: bool) -> bool    switch, then read back; returns the read-back state
"""
from __future__ import annotations

from .base import Driver, DriverError  # noqa: F401
from . import dummy, homeassistant, kasa, shelly_gen1, shelly_gen2, tasmota

REGISTRY = {
    "dummy": dummy.DummyDriver,
    "shelly_gen1": shelly_gen1.ShellyGen1,
    "shelly1": shelly_gen1.ShellyGen1,
    "shelly_gen2": shelly_gen2.ShellyGen2,
    "shelly2": shelly_gen2.ShellyGen2,
    "shelly_plus": shelly_gen2.ShellyGen2,
    "tasmota": tasmota.Tasmota,
    "kasa": kasa.Kasa,
    "homeassistant": homeassistant.HomeAssistant,
}
EXPERIMENTAL = {"kasa"}


def make(spec: dict) -> Driver:
    if not isinstance(spec, dict):
        raise DriverError("alias binding must be null or an object with a 'driver' field")
    name = str(spec.get("driver", "")).lower()
    cls = REGISTRY.get(name)
    if cls is None:
        raise DriverError(f"unknown driver {name!r} (known: {', '.join(sorted(REGISTRY))})")
    return cls(spec)
