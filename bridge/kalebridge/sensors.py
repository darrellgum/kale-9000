"""Local sensor reads for the pump interlock (stdlib only).

A sensor source is one of:
  {"type": "http_json", "url": "http://device-60.lan/rpc/Input.GetStatus?id=0", "path": "state",
   "ok_when": true}                                    # value must equal ok_when
  {"type": "http_json", "url": "...", "path": "moisture", "ok_below": 35}   # numeric threshold
  {"type": "file", "path": "/run/sensors/float", "ok_when": "ok"}          # file contents (stripped)
Optional: "user"/"password" (HTTP Basic), "timeout_s".
`ok` means "safe to pump" for that sensor: float = water in the reservoir, leak = dry,
soil = dry enough to water. Any read error counts as NOT ok.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import httputil as H

REQUIRED = ("float", "leak", "soil")


def _dig(obj, path: str):
    if not path:
        return obj
    for part in str(path).split("."):
        if isinstance(obj, list):
            obj = obj[int(part)]
        elif isinstance(obj, dict):
            obj = obj[part]
        else:
            raise KeyError(part)
    return obj


def read(spec: dict):
    t = spec.get("type")
    if t == "http_json":
        auth = (spec.get("user") or "admin", spec["password"]) if spec.get("password") else None
        j = H.get_json(spec["url"], timeout=float(spec.get("timeout_s", 4)), basic=auth)
        return _dig(j, spec.get("path", ""))
    if t == "file":
        txt = Path(spec["path"]).read_text().strip()
        try:
            return json.loads(txt)
        except ValueError:
            return txt
    raise ValueError(f"unknown sensor type {t!r}")


def check(name: str, spec) -> tuple:
    """Return (ok, detail). Never raises."""
    if not isinstance(spec, dict):
        return False, f"{name}: no sensor configured"
    try:
        v = read(spec)
    except Exception as e:  # noqa: BLE001
        return False, f"{name}: read failed ({type(e).__name__})"
    try:
        if "ok_when" in spec:
            ok = v == spec["ok_when"]
        elif "ok_below" in spec:
            ok = float(v) < float(spec["ok_below"])
        elif "ok_above" in spec:
            ok = float(v) > float(spec["ok_above"])
        else:
            return False, f"{name}: sensor has no ok_when/ok_below/ok_above rule"
    except (TypeError, ValueError):
        return False, f"{name}: unexpected value {str(v)[:20]!r}"
    return bool(ok), f"{name}={str(v)[:20]}{'' if ok else ' (not safe)'}"


def configured(policy: dict) -> list:
    s = policy.get("sensors") or {}
    return [n for n in REQUIRED if isinstance(s.get(n), dict) and s[n].get("type")]
