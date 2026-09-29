"""Shared helpers for the kalecam capture system (stdlib only, except the
rendezvous crypto, which imports `cryptography` lazily).

Everything is relative to this file's directory, so the template can live anywhere.
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
import tempfile
import time
from pathlib import Path

BASE = Path(os.environ.get("KALECAM_HOME", Path(__file__).resolve().parent))
APP_DIR = BASE / "app"
STATE = BASE / "state"
LOGS = BASE / "logs"
SECRETS = BASE / "secrets"
BIN = BASE / "bin"
CONFIG_PATH = BASE / "config.json"
CONFIG_EXAMPLE = BASE / "config.example.json"
PAIRING_PATH = SECRETS / "pairing.json"
PAIRING_URL_PATH = SECRETS / "pairing-url.txt"
QR_PATH = BASE / "pairing-qr.png"
URL_PATH = STATE / "url.txt"
CMD_DIR = STATE / "commands"
HB_DIR = STATE / "heartbeats"
PUBLISH_STATE = STATE / "publish-state.json"
WATCHDOG_STATE = STATE / "watchdog-state.json"
INSTANCE_PATH = STATE / "server-instance.json"

APP_VERSION = "1.0.1"
PLANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CAMERA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")
TOPIC_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
HKDF_SALT = b"kalecam-v1"
RV_AAD = b"kalecam-rendezvous-v1"
RV_PREFIX = "kc1."

DEFAULT_CONFIG = {
    "port": 8765,
    "photo_root": "/workspace/grow-photos",
    "default_plant": "plant-01",
    "default_camera": "phone-1",
    "camera_plants": {},  # e.g. {"phone-1": "basil-01"}: server-side override of the phone's plant id
    "camera_suffix": True,
    "strip_exif": True,
    "timezone": None,  # null = auto-detect from this machine
    "schedule": {"enabled": True, "interval_min": 30, "start": "06:00", "end": "22:00"},
    "capture": {
        "facing": "environment",
        "ideal_width": 4096,
        "ideal_height": 3072,
        "use_image_capture": True,
        "jpeg_max_bytes": 3500000,
        "jpeg_quality": 0.92,
        "keep_camera_open": True,
        "warmup_ms": 1500,
    },
    "heartbeat_s": 60,
    "poll_hold_s": 25,
    "migrate": "sticky",  # sticky = stay on the first origin, follow API via CORS; navigate = move page to new origin
    "dim_preview": False,
    "orientation": "any",
    "republish_s": 3600,
    "rendezvous": [
        {"type": "ntfy", "base": "https://ntfy.sh"},
        {"type": "ntfy", "base": "https://ntfy.envs.net"},
        {"type": "textdb", "base": "https://textdb.online"},
    ],
}

# Keys of the config that the phone is allowed to see via GET /config
PHONE_CONFIG_KEYS = ["schedule", "capture", "heartbeat_s", "poll_hold_s", "migrate",
                     "dim_preview", "orientation"]


# ------------------------------------------------------------------ basics
_TZ_CACHE: dict = {}


def local_tz():
    """The bot's timezone as a tzinfo: config "timezone", else TZ / /etc/timezone / /etc/localtime.
    Resolved explicitly (not via the process's C-library zone), so a server started before the
    machine's zone was set, or with a different TZ, still names folders in bot-local time."""
    now = time.time()
    if _TZ_CACHE and now - _TZ_CACHE["at"] < 60:
        return _TZ_CACHE["tz"]
    tz = None
    try:
        name = (read_json(CONFIG_PATH, {}) or {}).get("timezone") or detect_timezone()
        if name:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(name)
    except Exception:  # noqa: BLE001
        tz = None
    _TZ_CACHE.update(at=now, tz=tz)
    return tz


def now_local() -> dt.datetime:
    tz = local_tz()
    return dt.datetime.now(tz) if tz else dt.datetime.now().astimezone()


def to_local(t: dt.datetime) -> dt.datetime:
    tz = local_tz()
    return t.astimezone(tz) if tz else t.astimezone()


def iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def ensure_dirs() -> None:
    for d in (STATE, LOGS, BIN, CMD_DIR / "pending", CMD_DIR / "delivered", CMD_DIR / "done", HB_DIR):
        d.mkdir(parents=True, exist_ok=True)
    SECRETS.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS, 0o700)


def write_json_atomic(path: Path, obj, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.chmod(tmp, mode if mode is not None else 0o644)
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    """config.json merged over the defaults. Creates config.json on first use."""
    if not CONFIG_PATH.exists():
        seed = read_json(CONFIG_EXAMPLE, None) or DEFAULT_CONFIG
        write_json_atomic(CONFIG_PATH, seed)
    return deep_merge(DEFAULT_CONFIG, read_json(CONFIG_PATH, {}) or {})


def save_config_overrides(cfg: dict) -> None:
    write_json_atomic(CONFIG_PATH, cfg)


def detect_timezone() -> str | None:
    tz = os.environ.get("TZ")
    if tz and "/" in tz:
        return tz.lstrip(":")
    try:
        t = Path("/etc/timezone").read_text().strip()
        if t:
            return t
    except OSError:
        pass
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return None


def phone_config(cfg: dict) -> dict:
    pc = {k: cfg[k] for k in PHONE_CONFIG_KEYS if k in cfg}
    pc["timezone"] = cfg.get("timezone") or detect_timezone()
    pc["version"] = hashlib.sha256(json.dumps(pc, sort_keys=True).encode()).hexdigest()[:12]
    return pc


# ------------------------------------------------------------------ keys
def hkdf(ikm: bytes, info: bytes, length: int = 32, salt: bytes = HKDF_SALT) -> bytes:
    """RFC 5869 HKDF-SHA256 (matches WebCrypto deriveBits with HKDF)."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm, t, i = b"", b"", 1
    while len(okm) < length:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
        i += 1
    return okm[:length]


def random_topic(n: int = 26) -> str:
    return "".join(secrets.choice(TOPIC_ALPHABET) for _ in range(n))


def load_pairing() -> dict | None:
    return read_json(PAIRING_PATH, None)


def ensure_pairing(cfg: dict, rotate: bool = False) -> tuple[dict, bool]:
    """Create secrets/pairing.json (secret + one random topic per rendezvous channel)."""
    ensure_dirs()
    p = None if rotate else load_pairing()
    if p and p.get("secret") and p.get("channels"):
        return p, False
    p = {
        "v": 1,
        "secret": b64u(secrets.token_bytes(32)),
        "channels": [{"type": c["type"], "base": c["base"].rstrip("/"), "topic": random_topic()}
                     for c in cfg["rendezvous"]],
        "created_at": iso(now_local()),
    }
    write_json_atomic(PAIRING_PATH, p, mode=0o600)
    return p, True


def auth_token(pairing: dict) -> str:
    return b64u(hkdf(b64u_dec(pairing["secret"]), b"auth"))


def rv_key(pairing: dict) -> bytes:
    return hkdf(b64u_dec(pairing["secret"]), b"rendezvous")


def pairing_blob(pairing: dict, plant: str, camera: str) -> str:
    code = {"ntfy": "n", "textdb": "t"}
    blob = {"v": 1, "k": pairing["secret"],
            "r": [[code[c["type"]], c["base"], c["topic"]] for c in pairing["channels"]],
            "p": plant, "c": camera}
    return b64u(json.dumps(blob, separators=(",", ":")).encode())


# ------------------------------------------------------------------ rendezvous crypto
def rv_encrypt(pairing: dict, payload: dict) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    iv = secrets.token_bytes(12)
    ct = AESGCM(rv_key(pairing)).encrypt(iv, json.dumps(payload, separators=(",", ":")).encode(), RV_AAD)
    return RV_PREFIX + b64u(iv + ct)


def rv_decrypt(pairing: dict, text: str) -> dict | None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    text = (text or "").strip()
    if not text.startswith(RV_PREFIX):
        return None
    try:
        raw = b64u_dec(text[len(RV_PREFIX):])
        pt = AESGCM(rv_key(pairing)).decrypt(raw[:12], raw[12:], RV_AAD)
        obj = json.loads(pt)
        return obj if isinstance(obj, dict) and "url" in obj and "seq" in obj else None
    except Exception:
        return None


# ------------------------------------------------------------------ commands (file queue)
def new_cmd_id() -> str:
    return "c" + time.strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)


def queue_command(camera: str, cmd: str = "capture", settings: dict | None = None,
                  plant: str | None = None) -> dict:
    ensure_dirs()
    c = {"id": new_cmd_id(), "cmd": cmd, "camera": camera, "settings": settings or {},
         "plant": plant, "created_at": iso(now_local()), "attempts": 0}
    write_json_atomic(CMD_DIR / "pending" / f"{c['id']}.json", c)
    return c


def command_status(cid: str) -> tuple[str, dict | None]:
    for st in ("done", "delivered", "pending"):
        p = CMD_DIR / st / f"{cid}.json"
        if p.exists():
            return st, read_json(p, {})
    return "unknown", None


def current_url() -> str | None:
    try:
        u = URL_PATH.read_text().strip()
        return u or None
    except FileNotFoundError:
        return None


def pid_alive(pid: int | None, must_contain: str | None = None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    if must_contain:
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            return False
        if must_contain not in cmd:
            return False
        try:  # zombie?
            if Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0] == "Z":
                return False
        except OSError:
            pass
    return True


# ------------------------------------------------------------------ pairing QR
def write_pairing_qr(pairing: dict, url: str, plant: str, camera: str) -> tuple[str, int]:
    """Write pairing-qr.png + secrets/pairing-url.txt (both 0600) for the given tunnel URL."""
    import qrcode
    link = f"{url}/app#{pairing_blob(pairing, plant, camera)}"
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    qr.add_data(link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    old = os.umask(0o077)
    try:
        tmp = QR_PATH.with_suffix(".tmp.png")
        img.save(tmp)
        os.chmod(tmp, 0o600)
        os.replace(tmp, QR_PATH)
        PAIRING_URL_PATH.write_text(link + "\n")
        os.chmod(PAIRING_URL_PATH, 0o600)
    finally:
        os.umask(old)
    # remember what the QR was made for, so the watchdog can refresh it when the URL changes
    if pairing.get("qr") != {"plant": plant, "camera": camera}:
        pairing["qr"] = {"plant": plant, "camera": camera}
        write_json_atomic(PAIRING_PATH, pairing, mode=0o600)
    return link, qr.version
