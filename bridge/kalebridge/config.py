"""Paths, pairing blob, settings and alias file (stdlib only).

Everything lives in one directory (mode 700), by default ~/.config/kalebridge, or $KALEBRIDGE_HOME:
  config.json        pairing {url, key, bridge_id, rv} + settings            mode 600 (SECRET)
  aliases.json       light/fan/pump -> driver + host (+ device passwords)     mode 600 (SECRET)
  state.json         timers, holds, executed ids, current URL, last seq ...   mode 600
  config-cache.json  last GET /bridge/config from the bot                      mode 600
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

ALIASES = ("light", "fan", "pump")
ACTIONS = ("on", "off", "state")
BRIDGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
CMD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Hard ceilings enforced by the bridge no matter what the bot or the config says.
HARD_MAX_DURATION_S = {"light": 86400, "fan": 4 * 3600, "pump": 600}
HARD_MAX_PUMP_DAILY_S = 1800

DEFAULT_SETTINGS = {
    "dry_run": False,              # log commands, switch nothing (simulated states)
    "poll_hold_s": 25,             # long-poll hold asked of the bot (max 25)
    "heartbeat_s": None,           # null = use the bot's /bridge/config value (60)
    "offline_threshold_s": None,   # null = use the bot's value (600 = 10 min)
    "state_poll_s": 30,            # how often plugs are read (manual-change detection)
    "backoff_max_s": 60,           # retry backoff cap
    "rendezvous_after_failures": 3,
    "rendezvous_min_interval_s": 60,
    "hold_max_s": 4 * 3600,        # hold length when no fallback boundary can be computed
    "allow_http_urls": False,      # testing only: accept http://127.0.0.1 / localhost bot URLs
    "request_timeout_s": 15,
}

DEFAULT_ALIASES = {
    "_comment": "Bind each alias to a local plug, or leave it null. See README.md. This file may "
                "hold device passwords: keep it mode 600.",
    "light": None,
    "fan": None,
    "pump": None,
    "pump_policy": {
        "enabled": False,
        "max_run_s": 60,
        "max_daily_s": 300,
        "min_interval_s": 3600,
        "sensors": {"float": None, "leak": None, "soil": None},
    },
}


def home() -> Path:
    return Path(os.environ.get("KALEBRIDGE_HOME") or Path.home() / ".config" / "kalebridge").expanduser()


def paths(h: Path | None = None) -> dict:
    h = h or home()
    return {"home": h, "config": h / "config.json", "aliases": h / "aliases.json",
            "state": h / "state.json", "cache": h / "config-cache.json"}


def ensure_home(h: Path | None = None) -> Path:
    h = h or home()
    h.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(h, 0o700)
    except OSError:
        pass
    return h


def write_json_atomic(path: Path, obj, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def fingerprint(key: str) -> str:
    """Same fingerprint `kalecam bridge pair` prints, so the owner can compare without seeing the key."""
    return "sha256:" + hashlib.sha256(b"kalecam-bridge-fp:" + key.encode()).hexdigest()[:16]


def valid_bot_url(url: str, allow_http: bool = False) -> bool:
    if not isinstance(url, str):
        return False
    u = url.rstrip("/")
    if re.match(r"^https://[A-Za-z0-9.-]+(:\d{1,5})?$", u):
        return True
    return bool(allow_http and re.match(r"^http://(127\.0\.0\.1|localhost)(:\d{1,5})?$", u))


def parse_blob(blob: str, allow_http: bool = False) -> dict:
    """Decode the base64 JSON blob from `kalecam bridge pair`. Raises ValueError with a safe message."""
    s = re.sub(r"\s+", "", blob or "")
    if not s:
        raise ValueError("empty pairing blob")
    raw = None
    for dec in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            raw = dec(s + "=" * (-len(s) % 4))
            break
        except (binascii.Error, ValueError):
            continue
    try:
        d = json.loads(raw) if raw is not None else None
    except ValueError:
        d = None
    if not isinstance(d, dict):
        raise ValueError("not a pairing blob (expected base64 of a JSON object)")
    url, key, bid = d.get("url"), d.get("key"), d.get("bridge_id")
    if not valid_bot_url(url, allow_http):
        raise ValueError("pairing blob: 'url' must be an https:// origin")
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise ValueError("pairing blob: 'key' is missing or malformed")
    if not isinstance(bid, str) or not BRIDGE_RE.match(bid):
        raise ValueError("pairing blob: 'bridge_id' is missing or malformed")
    rv = []
    for r in d.get("rv") or []:
        if (isinstance(r, list) and len(r) >= 2 and r[0] in ("n", "t") and isinstance(r[1], str)
                and re.match(r"^https?://[A-Za-z0-9.:-]+$", r[1].rstrip("/"))):
            rv.append([r[0], r[1].rstrip("/")])
    return {"url": url.rstrip("/"), "key": key, "bridge_id": bid, "rv": rv}


def load_config(p: dict | None = None) -> dict:
    p = p or paths()
    c = read_json(p["config"], None) or {}
    c["settings"] = {**DEFAULT_SETTINGS, **(c.get("settings") or {})}
    return c


def save_config(c: dict, p: dict | None = None) -> None:
    p = p or paths()
    ensure_home(p["home"])
    out = dict(c)
    out["settings"] = {k: v for k, v in (c.get("settings") or {}).items()
                       if k not in DEFAULT_SETTINGS or DEFAULT_SETTINGS[k] != v}
    write_json_atomic(p["config"], out, 0o600)


def ensure_aliases(p: dict | None = None) -> bool:
    p = p or paths()
    if p["aliases"].exists():
        return False
    write_json_atomic(p["aliases"], DEFAULT_ALIASES, 0o600)
    return True


def validate_aliases(a) -> dict:
    """Return a normalized alias map; raise ValueError on anything unusable."""
    from .drivers import REGISTRY
    if not isinstance(a, dict):
        raise ValueError("aliases.json must be a JSON object")
    out = {"pump_policy": dict(DEFAULT_ALIASES["pump_policy"])}
    for k, v in a.items():
        if k.startswith("_"):
            continue
        if k == "pump_policy":
            if not isinstance(v, dict):
                raise ValueError("pump_policy must be an object")
            pp = {**DEFAULT_ALIASES["pump_policy"], **v}
            pp["sensors"] = {**DEFAULT_ALIASES["pump_policy"]["sensors"], **(v.get("sensors") or {})}
            for n in ("max_run_s", "max_daily_s", "min_interval_s"):
                if isinstance(pp[n], bool) or not isinstance(pp[n], int) or pp[n] < 0:
                    raise ValueError(f"pump_policy.{n} must be a non-negative integer")
            if not isinstance(pp["enabled"], bool):
                raise ValueError("pump_policy.enabled must be true or false")
            out["pump_policy"] = pp
            continue
        if k not in ALIASES:
            raise ValueError(f"unknown alias {k!r} (allowed: light, fan, pump, pump_policy)")
        if v is None:
            out[k] = None
            continue
        if not isinstance(v, dict) or str(v.get("driver", "")).lower() not in REGISTRY:
            raise ValueError(f"{k}: must be null or an object with driver one of {sorted(REGISTRY)}")
        out[k] = v
    for k in ALIASES:
        out.setdefault(k, None)
    return out


def load_aliases(p: dict | None = None) -> dict:
    p = p or paths()
    raw = read_json(p["aliases"], None)
    if raw is None:
        if p["aliases"].exists():
            raise ValueError("aliases.json is not valid JSON")
        raw = DEFAULT_ALIASES
    return validate_aliases(raw)
