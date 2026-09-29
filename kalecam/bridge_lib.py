"""Device bridge support for kalecam (stdlib only).

A home bridge service dials OUT to this server over HTTPS and long-polls
for switch commands. This module holds everything both the server and the CLI need:

  secrets/bridge.json            {"key", "bridge_id", ...}  mode 600 (separate from the phone secret)
  secrets/bridge-pairing.txt     base64(JSON {url, key, bridge_id})  mode 600
  config.json -> "bridge"        overrides of DEFAULT_BRIDGE_CONFIG (fallback schedule + limits)
  state/bridge/commands/{pending,delivered,done}/<id>.json   file queue (same pattern as the phone)
  state/bridge/heartbeats/<bridge>.json (+ .lastpoll)
  state/bridge/bridge-log.jsonl  append-only log of queued/delivered/result/heartbeat events

Never log or print the bridge key.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

import kalecam_lib as K

BRIDGE_DIR = K.STATE / "bridge"
BCMD_DIR = BRIDGE_DIR / "commands"
BHB_DIR = BRIDGE_DIR / "heartbeats"
BLOG = BRIDGE_DIR / "bridge-log.jsonl"
KEY_PATH = K.SECRETS / "bridge.json"
PAIRING_TXT = K.SECRETS / "bridge-pairing.txt"

ALIASES = ("light", "fan", "pump")
ACTIONS = ("on", "off", "state")
RESULT_STATUSES = ("done", "failed", "expired", "held")
BRIDGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")
CMD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
HHMM_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
MAX_BATCH = 20
LOG_ROTATE_BYTES = 20 * 1024 * 1024

DEFAULT_BRIDGE_CONFIG = {
    # Stable public base URL (e.g. a named Cloudflare tunnel hostname). null = use the current quick
    # tunnel URL from state/url.txt, which changes whenever cloudflared restarts.
    "public_base_url": None,
    "timezone": None,  # null = the bot machine's timezone (auto-detected)
    "poll_hold_s": 25,
    "heartbeat_s": 60,
    "offline_threshold_s": 600,
    "redeliver_after_s": 120,
    "max_attempts": 5,
    "default_expires_s": 300,
    "max_expires_s": 3600,
    "pump_enabled": False,
    "max_duration_s": {"light": 64800, "fan": 3600, "pump": 0},
    "fallback": {
        # light: null = no photoperiod chosen, the bridge leaves the switch alone.
        #        {"on": "HH:MM", "off": "HH:MM"} in `timezone` (wraps midnight if off < on).
        "light": None,
        # fan: {"on_min": 15, "off_min": 15} cycle, or null = leave alone.
        "fan": {"on_min": 15, "off_min": 15},
        # pump: always "off" in fallback (not configurable).
        "pump": "off",
    },
}

# keys sent to the bridge in GET /bridge/config
PUBLIC_KEYS = ("timezone", "poll_hold_s", "heartbeat_s", "offline_threshold_s", "pump_enabled",
               "max_duration_s", "fallback")

_lock = threading.Lock()
_log_lock = threading.Lock()


# ------------------------------------------------------------------ config
def bridge_config(cfg: dict | None = None) -> dict:
    cfg = cfg if cfg is not None else K.load_config()
    return K.deep_merge(DEFAULT_BRIDGE_CONFIG, cfg.get("bridge") or {})


def tzinfo(bc: dict):
    try:
        from zoneinfo import ZoneInfo
        # bridge "timezone", else the bot's config "timezone", else this computer's zone
        name = (bc.get("timezone") or (K.read_json(K.CONFIG_PATH, {}) or {}).get("timezone")
                or K.detect_timezone())
        return ZoneInfo(name) if name else K.local_tz()
    except Exception:  # noqa: BLE001
        return None


def now_b(bc: dict) -> dt.datetime:
    tz = tzinfo(bc)
    return dt.datetime.now(tz) if tz else K.now_local()


def parse_light_schedule(v):
    """Accept null, {"on":"HH:MM","off":"HH:MM"} or the shorthand "HH:MM-HH:MM"."""
    if v is None or v in ("null", "none", "off-schedule"):
        return None
    if isinstance(v, str) and "-" in v:
        a, b = v.split("-", 1)
        v = {"on": a.strip(), "off": b.strip()}
    if not isinstance(v, dict) or set(v) != {"on", "off"}:
        raise ValueError('fallback.light must be null, "HH:MM-HH:MM" or {"on":"HH:MM","off":"HH:MM"}')
    for k in ("on", "off"):
        if not isinstance(v[k], str) or not HHMM_RE.match(v[k]):
            raise ValueError(f"fallback.light.{k} must be HH:MM (24 h)")
    if v["on"] == v["off"]:
        raise ValueError("fallback.light on and off must differ")
    return {"on": v["on"], "off": v["off"]}


def _int_in(bc, key, lo, hi):
    v = bc.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ValueError(f"{key} must be an integer between {lo} and {hi}")


def validate_bridge_config(bc: dict) -> dict:
    """Raise ValueError if the merged bridge config is unusable. Returns bc (normalized)."""
    unknown = set(bc) - set(DEFAULT_BRIDGE_CONFIG)
    if unknown:
        raise ValueError(f"unknown bridge config key(s): {sorted(unknown)}")
    u = bc.get("public_base_url")
    if u is not None:
        if not isinstance(u, str) or not (u.startswith("https://") or u.startswith("http://127.0.0.1")
                                          or u.startswith("http://localhost")):
            raise ValueError("public_base_url must be null or an https:// URL")
        bc["public_base_url"] = u.rstrip("/")
    if tzinfo(bc) is None:
        raise ValueError(f"unknown timezone {bc.get('timezone')!r}")
    _int_in(bc, "poll_hold_s", 1, 25)
    _int_in(bc, "heartbeat_s", 10, 3600)
    _int_in(bc, "offline_threshold_s", 60, 86400)
    _int_in(bc, "redeliver_after_s", 1, 3600)
    _int_in(bc, "max_attempts", 1, 20)
    _int_in(bc, "max_expires_s", 10, 86400)
    _int_in(bc, "default_expires_s", 1, bc["max_expires_s"])
    if not isinstance(bc.get("pump_enabled"), bool):
        raise ValueError("pump_enabled must be true or false")
    md = bc.get("max_duration_s")
    if not isinstance(md, dict) or set(md) - set(ALIASES):
        raise ValueError(f"max_duration_s must be an object with keys from {list(ALIASES)}")
    for k, v in md.items():
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 86400:
            raise ValueError(f"max_duration_s.{k} must be an integer 0..86400")
    fb = bc.get("fallback")
    if not isinstance(fb, dict) or set(fb) != {"light", "fan", "pump"}:
        raise ValueError("fallback must have exactly the keys light, fan, pump")
    fb["light"] = parse_light_schedule(fb["light"])
    fan = fb["fan"]
    if fan is not None:
        if not isinstance(fan, dict) or set(fan) != {"on_min", "off_min"}:
            raise ValueError('fallback.fan must be null or {"on_min": N, "off_min": N}')
        for k, lo in (("on_min", 1), ("off_min", 0)):
            if isinstance(fan[k], bool) or not isinstance(fan[k], int) or not lo <= fan[k] <= 1440:
                raise ValueError(f"fallback.fan.{k} must be an integer {lo}..1440")
    if fb["pump"] != "off":
        raise ValueError('fallback.pump is always "off"')
    return bc


def public_config(bc: dict) -> dict:
    pc = {k: bc[k] for k in PUBLIC_KEYS}
    if not pc.get("timezone"):
        tz = tzinfo(bc)
        pc["timezone"] = getattr(tz, "key", None) or K.detect_timezone()
    pc["aliases"] = list(ALIASES)
    pc["version"] = hashlib.sha256(json.dumps(pc, sort_keys=True).encode()).hexdigest()[:12]
    return pc


# ------------------------------------------------------------------ key + pairing
def load_key() -> dict | None:
    return K.read_json(KEY_PATH, None)


def ensure_key(bridge_id: str | None = None, rotate: bool = False) -> tuple[dict, bool]:
    K.ensure_dirs()
    d = None if rotate else load_key()
    created = False
    if not d or not d.get("key"):
        d = {"v": 1, "key": K.b64u(secrets.token_bytes(32)), "bridge_id": bridge_id or "bridge-1",
             "created_at": K.iso(K.now_local())}
        created = True
    elif bridge_id and d.get("bridge_id") != bridge_id:
        d["bridge_id"] = bridge_id
    else:
        os.chmod(KEY_PATH, 0o600)
        return d, False
    K.write_json_atomic(KEY_PATH, d, mode=0o600)
    return d, created


def fingerprint(key: str) -> str:
    return "sha256:" + hashlib.sha256(b"kalecam-bridge-fp:" + key.encode()).hexdigest()[:16]


def key_matches(got: str | None, expected: str) -> bool:
    return hmac.compare_digest((got or "").encode("utf-8", "replace"), expected.encode())


def pairing_blob(url: str, key: str, bridge_id: str, rv: list | None = None) -> str:
    """base64(JSON {url, key, bridge_id[, rv]}). `rv` = relay list for the bridge rendezvous
    ([["n","https://ntfy.sh"], ...]; see bridge_rendezvous.py). Older readers ignore it."""
    d = {"url": url.rstrip("/"), "key": key, "bridge_id": bridge_id}
    if rv:
        d["rv"] = rv
    return base64.b64encode(json.dumps(d, separators=(",", ":")).encode()).decode()


def write_pairing_file(url: str, key: str, bridge_id: str, rv: list | None = None) -> Path:
    old = os.umask(0o077)
    try:
        tmp = PAIRING_TXT.with_suffix(".tmp")
        tmp.write_text(pairing_blob(url, key, bridge_id, rv) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, PAIRING_TXT)
    finally:
        os.umask(old)
    return PAIRING_TXT


# ------------------------------------------------------------------ log
def ensure_dirs() -> None:
    for d in (BCMD_DIR / "pending", BCMD_DIR / "delivered", BCMD_DIR / "done", BHB_DIR):
        d.mkdir(parents=True, exist_ok=True)


def log_event(event: str, **fields) -> None:
    """Append one JSON line. Callers must never pass the key."""
    ensure_dirs()
    rec = {"ts": K.iso(K.now_local()), "event": event, **fields}
    line = json.dumps(rec, separators=(",", ":"), ensure_ascii=False) + "\n"
    with _log_lock:
        try:
            if BLOG.exists() and BLOG.stat().st_size > LOG_ROTATE_BYTES:
                os.replace(BLOG, BLOG.with_name(f"bridge-log-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"))
        except OSError:
            pass
        with BLOG.open("a", encoding="utf-8") as f:
            f.write(line)


# ------------------------------------------------------------------ commands
def new_id() -> str:
    return "b" + time.strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)


def wire(c: dict) -> dict:
    """The command as the bridge sees it (protocol fields only)."""
    w = {"id": c["id"], "device": c["device"], "action": c["action"]}
    if c.get("duration_s") is not None:
        w["duration_s"] = c["duration_s"]
    w["expires_at"] = c["expires_at"]
    return w


def _summary(c: dict) -> dict:
    keys = ("id", "bridge", "device", "action", "duration_s", "duration_capped_from", "expires_at",
            "status", "attempts", "source", "error", "closed_by", "result")
    return {k: c[k] for k in keys if c.get(k) is not None}


def validate_command(device, action, duration_s, bc: dict) -> tuple[str, str, int | None, int | None]:
    """Server-side rules. Returns (device, action, duration_s, capped_from); raises ValueError."""
    device = str(device or "").strip().lower()
    action = str(action or "").strip().lower()
    if device not in ALIASES:
        raise ValueError(f"unknown device alias {device!r} (allowed: {', '.join(ALIASES)})")
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r} (allowed: {', '.join(ACTIONS)})")
    if device == "pump" and not bc.get("pump_enabled"):
        raise ValueError("pump commands are rejected while pump_enabled is false")
    capped_from = None
    if duration_s is not None:
        if action != "on":
            raise ValueError("duration_s only applies to action 'on'")
        if isinstance(duration_s, bool):
            raise ValueError("duration_s must be a positive integer (seconds)")
        duration_s = int(duration_s)
        if duration_s <= 0:
            raise ValueError("duration_s must be a positive integer (seconds)")
        cap = int((bc.get("max_duration_s") or {}).get(device, 0))
        if cap <= 0:
            raise ValueError(f"timed runs are disabled for {device} (max_duration_s.{device} = {cap})")
        if duration_s > cap:
            capped_from, duration_s = duration_s, cap
    return device, action, duration_s, capped_from


def queue(device, action, duration_s=None, expires_s=None, bridge: str | None = None,
          source: str = "cli", cfg: dict | None = None) -> dict:
    bc = bridge_config(cfg)
    device, action, duration_s, capped_from = validate_command(device, action, duration_s, bc)
    bridge = bridge or "*"
    if bridge != "*" and not BRIDGE_RE.match(bridge):
        raise ValueError("bad bridge id")
    exp = int(bc["default_expires_s"] if expires_s is None else expires_s)
    if exp <= 0:
        raise ValueError("expires must be > 0 seconds")
    exp = min(exp, int(bc["max_expires_s"]))
    now = now_b(bc)
    expires = now + dt.timedelta(seconds=exp)
    c = {"id": new_id(), "bridge": bridge, "device": device, "action": action}
    if duration_s is not None:
        c["duration_s"] = duration_s
    if capped_from is not None:
        c["duration_capped_from"] = capped_from
    c.update({"expires_at": K.iso(expires), "expires_ts": expires.timestamp(),
              "created_at": K.iso(now), "created_ts": time.time(), "source": source,
              "attempts": 0, "status": "pending"})
    ensure_dirs()
    K.write_json_atomic(BCMD_DIR / "pending" / f"{c['id']}.json", c)
    log_event("queued", **_summary(c))
    return c


def command_status(cid: str) -> tuple[str, dict | None]:
    if not CMD_ID_RE.match(cid or ""):
        return "unknown", None
    for st in ("done", "delivered", "pending"):
        p = BCMD_DIR / st / f"{cid}.json"
        if p.exists():
            return st, K.read_json(p, {})
    return "unknown", None


def _finish(src: Path, c: dict, status: str, error: str | None, by: str) -> None:
    c.update({"status": status, "error": error, "closed_by": by, "finished_at": K.iso(K.now_local())})
    dest = BCMD_DIR / "done" / src.name
    K.write_json_atomic(dest, c)
    if src.resolve() != dest.resolve():
        src.unlink(missing_ok=True)
    log_event(status if by == "server" else "result", **_summary(c))


def maintain(bc: dict) -> None:
    """Expire overdue commands and re-queue delivered ones that never got a result. Call under _lock."""
    now = time.time()
    for p in sorted((BCMD_DIR / "pending").glob("*.json")):
        c = K.read_json(p, None)
        if c and c.get("expires_ts", now + 1) <= now:
            _finish(p, c, "expired", "expired before delivery", "server")
    for p in sorted((BCMD_DIR / "delivered").glob("*.json")):
        c = K.read_json(p, None)
        if not c:
            continue
        if c.get("expires_ts", now + 1) <= now:
            _finish(p, c, "expired", "no result before expires_at", "server")
        elif now - c.get("delivered_ts", now) > int(bc["redeliver_after_s"]):
            if c.get("attempts", 0) >= int(bc["max_attempts"]):
                _finish(p, c, "failed", f"no result after {c.get('attempts')} deliveries", "server")
            else:
                c["status"] = "pending"
                K.write_json_atomic(BCMD_DIR / "pending" / p.name, c)
                p.unlink(missing_ok=True)
                log_event("requeued", id=c["id"], attempts=c.get("attempts"))


def take(bridge_id: str, bc: dict) -> list[dict]:
    """Hand every deliverable pending command for this bridge to the poller (marks them delivered)."""
    out = []
    with _lock:
        maintain(bc)
        for p in sorted((BCMD_DIR / "pending").glob("*.json")):
            if len(out) >= MAX_BATCH:
                break
            c = K.read_json(p, None)
            if not c or c.get("bridge", "*") not in (bridge_id, "*"):
                continue
            try:  # the rules may have changed since the command was queued
                _, _, dur, capped = validate_command(c.get("device"), c.get("action"), c.get("duration_s"), bc)
            except ValueError as e:
                _finish(p, c, "rejected", f"rejected at delivery: {e}", "server")
                continue
            if capped is not None:
                c["duration_s"], c["duration_capped_from"] = dur, capped
            c["attempts"] = c.get("attempts", 0) + 1
            c.update({"delivered_ts": time.time(), "delivered_at": K.iso(K.now_local()),
                      "delivered_to": bridge_id, "status": "delivered"})
            K.write_json_atomic(BCMD_DIR / "delivered" / p.name, c)
            p.unlink(missing_ok=True)
            log_event("delivered" if c["attempts"] == 1 else "redelivered", id=c["id"], bridge=bridge_id,
                      attempts=c["attempts"])
            out.append(wire(c))
    return out


def record_result(body: dict) -> tuple[int, dict]:
    if not isinstance(body, dict):
        return 400, {"error": "result must be a JSON object"}
    cid = body.get("id")
    status = body.get("status")
    if not isinstance(cid, str) or not CMD_ID_RE.match(cid):
        return 400, {"error": "missing or bad id"}
    if status not in RESULT_STATUSES:
        return 400, {"error": f"status must be one of {list(RESULT_STATUSES)}"}
    state = body.get("state")
    if state is not None and (not isinstance(state, str) or len(state) > 16):
        return 400, {"error": "state must be a short string or null"}
    err = body.get("error")
    res = {"status": status, "state": state,
           "error": None if err is None else str(err)[:500],
           "at": None if body.get("at") is None else str(body.get("at"))[:40],
           "received_at": K.iso(K.now_local())}
    with _lock:
        where, src, c = None, None, None
        for st in ("delivered", "pending", "done"):
            p = BCMD_DIR / st / f"{cid}.json"
            if p.exists():
                where, src, c = st, p, K.read_json(p, {}) or {}
                break
        if c is None:
            log_event("result_unknown_id", id=cid, status=status)
            return 404, {"error": "unknown command id"}
        if where == "done" and c.get("closed_by") == "bridge":
            log_event("result_duplicate", id=cid, status=status, state=state)
            return 200, {"ok": True, "id": cid, "duplicate": True, "status": c.get("status")}
        if where == "done":  # server had expired/failed it; the bridge's word wins
            c["server_status"] = c.get("status")
        c["result"] = res
        _finish(src, c, status, res["error"], "bridge")
    return 200, {"ok": True, "id": cid, "status": status}


def cancel(cid: str | None = None, all_: bool = False) -> int:
    n = 0
    with _lock:
        for p in sorted((BCMD_DIR / "pending").glob("*.json")):
            if all_ or p.stem == cid:
                c = K.read_json(p, None) or {"id": p.stem}
                _finish(p, c, "cancelled", "cancelled before delivery", "server")
                n += 1
    return n


# ------------------------------------------------------------------ heartbeats
def store_heartbeat(body: dict, bc: dict) -> tuple[int, dict]:
    if not isinstance(body, dict):
        return 400, {"error": "heartbeat must be a JSON object"}
    bridge = body.get("bridge")
    if not isinstance(bridge, str) or not BRIDGE_RE.match(bridge):
        return 400, {"error": "missing or bad bridge id"}

    def small_map(v, conv):
        if not isinstance(v, dict):
            return None
        return {str(k)[:16]: conv(x) for k, x in list(v.items())[:16]}

    hb = {"bridge": bridge,
          "version": None if body.get("version") is None else str(body.get("version"))[:32],
          "devices": small_map(body.get("devices"), lambda x: None if x is None else str(x)[:16]),
          "holds": small_map(body.get("holds"), bool),
          "fallback_active": bool(body.get("fallback_active")),
          "uptime_s": body.get("uptime_s") if isinstance(body.get("uptime_s"), (int, float)) else None,
          "received_at": K.iso(K.now_local()), "received_ts": time.time()}
    ensure_dirs()
    K.write_json_atomic(BHB_DIR / f"{bridge}.json", hb)
    log_event("heartbeat", **{k: v for k, v in hb.items() if k != "received_ts"})
    return 200, {"ok": True, "config_version": public_config(bc)["version"], "server_time": hb["received_at"]}


def mark_poll(bridge: str) -> None:
    ensure_dirs()
    (BHB_DIR / f"{bridge}.lastpoll").write_text(K.iso(K.now_local()))


# ------------------------------------------------------------------ status (CLI)
def status(bc: dict | None = None, recent: int = 8) -> dict:
    bc = bc or bridge_config()
    ensure_dirs()
    now = time.time()
    kd = load_key() or {}
    out = {"paired": bool(kd.get("key")), "bridge_id": kd.get("bridge_id"),
           "key_fingerprint": fingerprint(kd["key"]) if kd.get("key") else None,
           "pairing_file": str(PAIRING_TXT) if PAIRING_TXT.exists() else None,
           "public_base_url": bc.get("public_base_url"), "config_version": public_config(bc)["version"],
           "bridges": {}}
    names = {p.stem for p in BHB_DIR.glob("*.json")} | {p.name[:-9] for p in BHB_DIR.glob("*.lastpoll")}
    for b in sorted(names):
        hb = K.read_json(BHB_DIR / f"{b}.json", None)
        lp = BHB_DIR / f"{b}.lastpoll"
        info = {"last_poll_age_s": int(now - lp.stat().st_mtime) if lp.exists() else None}
        if hb:
            age = int(now - hb.get("received_ts", 0))
            info.update({"heartbeat_at": hb.get("received_at"), "heartbeat_age_s": age,
                         "online": age <= int(bc["offline_threshold_s"]), "version": hb.get("version"),
                         "devices": hb.get("devices"), "holds": hb.get("holds"),
                         "fallback_active": hb.get("fallback_active"), "uptime_s": hb.get("uptime_s")})
        out["bridges"][b] = info
    out["pending"] = [_summary(K.read_json(p, {}) or {}) for p in sorted((BCMD_DIR / "pending").glob("*.json"))]
    out["delivered"] = [_summary(K.read_json(p, {}) or {}) for p in sorted((BCMD_DIR / "delivered").glob("*.json"))]
    done = sorted((BCMD_DIR / "done").glob("*.json"), key=lambda p: p.stat().st_mtime)[-recent:]
    out["recent"] = [_summary(K.read_json(p, {}) or {}) for p in reversed(done)]
    return out
