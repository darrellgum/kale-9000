"""Read side of the encrypted rendezvous (stdlib only; `cryptography` used if installed).

The bot publishes its current URL to no-account relays whenever its quick-tunnel URL changes.
This mirrors kalecam/bridge_rendezvous.py on the bot:
  ikm   = base64url-decode(bridge key)
  key   = HKDF-SHA256(ikm, salt="kalecam-bridge-v1", info="bridge-rendezvous", 32 bytes)
  topic = HKDF-SHA256(ikm, salt, info="bridge-topic:<ntfy|textdb>:<host>", 26 bytes) -> [A-Za-z0-9]
  msg   = "kc1." + base64url(iv[12] || AES-256-GCM ciphertext+tag), AAD "kalecam-bridge-rendezvous-v1"
  payload {"v":1, "url":"https://...", "issued_at":"...", "seq":N}
The bridge accepts only seq > last accepted seq (replay protection), only an https origin, and
only after the new URL answers an authenticated GET /bridge/config.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

from . import aesgcm

SALT = b"kalecam-bridge-v1"
AAD = b"kalecam-bridge-rendezvous-v1"
PREFIX = "kc1."
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
TYPES = {"n": "ntfy", "t": "textdb"}


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def hkdf(ikm: bytes, info: bytes, length: int = 32, salt: bytes = SALT) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm, t, i = b"", b"", 1
    while len(okm) < length:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
        i += 1
    return okm[:length]


def rv_key(key: str) -> bytes:
    return hkdf(b64u_dec(key), b"bridge-rendezvous", 32)


def topic_for(key: str, ctype: str, base: str) -> str:
    netloc = urllib.parse.urlparse(base).netloc.lower()
    raw = hkdf(b64u_dec(key), f"bridge-topic:{ctype}:{netloc}".encode(), 26)
    return "".join(ALPHABET[b % len(ALPHABET)] for b in raw)


def channels(key: str, rv: list) -> list:
    out = []
    for r in rv or []:
        t = TYPES.get(r[0])
        if t:
            out.append({"type": t, "base": r[1].rstrip("/"), "topic": topic_for(key, t, r[1])})
    return out


def encrypt(key: str, payload: dict, iv: bytes | None = None) -> str:
    """Used by tests / simulated relays; the bot has its own publisher."""
    import os
    iv = iv or os.urandom(12)
    ct = aesgcm.encrypt(rv_key(key), iv, json.dumps(payload, separators=(",", ":")).encode(), AAD)
    return PREFIX + b64u(iv + ct)


def decrypt(key: str, text: str):
    text = (text or "").strip()
    if not text.startswith(PREFIX):
        return None
    try:
        raw = b64u_dec(text[len(PREFIX):])
        obj = json.loads(aesgcm.decrypt(rv_key(key), raw[:12], raw[12:], AAD))
    except Exception:  # noqa: BLE001  wrong key, tampered, garbage
        return None
    if isinstance(obj, dict) and isinstance(obj.get("url"), str) and isinstance(obj.get("seq"), int) \
            and not isinstance(obj.get("seq"), bool):
        return obj
    return None


def _get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "kalebridge-rv"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(256 * 1024)


def _get_with_http_fallback(url: str, timeout: float):
    """HTTPS first; if TLS itself fails (some networks block TLS to a relay host), retry over
    plain HTTP. Safe: messages are authenticated-encrypted and the URL is verified afterwards."""
    try:
        return _get(url, timeout), "https"
    except (urllib.error.URLError, ssl.SSLError, ConnectionError, TimeoutError, OSError) as e:
        if isinstance(e, urllib.error.HTTPError) or not url.startswith("https://"):
            raise
        return _get("http://" + url[len("https://"):], timeout), "http-fallback"


def read_channel(c: dict, key: str, timeout: float = 12.0) -> dict:
    label = f"{c['type']}:{urllib.parse.urlparse(c['base']).netloc}"
    try:
        if c["type"] == "ntfy":
            body, via = _get_with_http_fallback(f"{c['base']}/{c['topic']}/json?poll=1&since=all", timeout)
            texts = []
            for line in body.decode(errors="replace").splitlines():
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if isinstance(m, dict) and m.get("event") == "message":
                    texts.append(str(m.get("message", "")))
        else:
            body, via = _get_with_http_fallback(f"{c['base']}/{c['topic']}", timeout)
            texts = [body.decode(errors="replace")]
        valid = [p for p in (decrypt(key, t) for t in texts) if p]
        best = max(valid, key=lambda p: p["seq"]) if valid else None
        return {"label": label, "ok": best is not None, "via": via, "messages": len(texts),
                "valid": len(valid), "best": best}
    except Exception as e:  # noqa: BLE001
        return {"label": label, "ok": False, "error": f"{type(e).__name__}"[:80]}


def discover(key: str, rv: list, timeout: float = 12.0) -> dict:
    """Read every channel; return {"best": payload-or-None, "channels": [...]}."""
    import concurrent.futures as cf
    chans = channels(key, rv)
    if not chans:
        return {"best": None, "channels": []}
    with cf.ThreadPoolExecutor(max_workers=len(chans)) as ex:
        res = list(ex.map(lambda c: read_channel(c, key, timeout), chans))
    bests = [r["best"] for r in res if r.get("best")]
    best = max(bests, key=lambda p: p["seq"]) if bests else None
    summary = [{k: r.get(k) for k in ("label", "ok", "via", "messages", "valid", "error")} for r in res]
    for s, r in zip(summary, res):
        s["seq"] = r["best"]["seq"] if r.get("best") else None
    return {"best": best, "channels": summary}
