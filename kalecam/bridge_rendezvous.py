"""Encrypted rendezvous for the home device bridge (publish side).

The phone rendezvous (rendezvous.py) is keyed from the PHONE secret. The device bridge must never
hold that secret, so the bridge gets its own channels, keyed from the BRIDGE key it already has
(secrets/bridge.json). Nothing new has to be pasted on the bridge side: the relay list travels in
the pairing blob ("rv"), and the topics and the AES key are derived from the bridge key.

Spec (the reference bridge implements the read side in bridge/reference/kalebridge/rendezvous.py):
  ikm      = base64url-decode(bridge_key)                       (32 bytes)
  aes key  = HKDF-SHA256(ikm, salt=b"kalecam-bridge-v1", info=b"bridge-rendezvous", 32)
  topic    = HKDF-SHA256(ikm, salt=b"kalecam-bridge-v1", info=b"bridge-topic:<type>:<netloc>", 26)
             each byte mapped to TOPIC_ALPHABET[byte % 62]  (type is "ntfy" or "textdb")
  message  = "kc1." + base64url(iv[12] || AES-256-GCM(key, iv, json(payload), aad))   (same envelope
             as the phone), aad = b"kalecam-bridge-rendezvous-v1"
  payload  = {"v":1, "url":"https://...", "issued_at":"ISO8601", "seq":<int, strictly increasing>}
  blob.rv  = [["n","https://ntfy.sh"],["n","https://ntfy.envs.net"],["t","https://textdb.online"]]

Rotating the bridge key (`kalecam bridge pair --rotate-key`) rotates the topics and the AES key too.
Never log the key or the derived key.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
import urllib.parse

import bridge_lib as B
import kalecam_lib as K
import rendezvous as RV

BRV_SALT = b"kalecam-bridge-v1"
BRV_AAD = b"kalecam-bridge-rendezvous-v1"
PUBLISH_STATE = B.BRIDGE_DIR / "publish-state.json"
TYPE_CODE = {"ntfy": "n", "textdb": "t"}


def _ikm(key: str) -> bytes:
    return K.b64u_dec(key)


def rv_key(key: str) -> bytes:
    return K.hkdf(_ikm(key), b"bridge-rendezvous", 32, salt=BRV_SALT)


def topic_for(key: str, ctype: str, base: str) -> str:
    netloc = urllib.parse.urlparse(base).netloc.lower()
    raw = K.hkdf(_ikm(key), f"bridge-topic:{ctype}:{netloc}".encode(), 26, salt=BRV_SALT)
    return "".join(K.TOPIC_ALPHABET[b % len(K.TOPIC_ALPHABET)] for b in raw)


def relays(cfg: dict) -> list[dict]:
    out = []
    for c in cfg.get("rendezvous") or []:
        if c.get("type") in TYPE_CODE and str(c.get("base", "")).startswith(("https://", "http://")):
            out.append({"type": c["type"], "base": c["base"].rstrip("/")})
    return out


def channels(key: str, cfg: dict) -> list[dict]:
    return [dict(c, topic=topic_for(key, c["type"], c["base"])) for c in relays(cfg)]


def blob_rv(cfg: dict) -> list[list[str]]:
    """The relay list for the pairing blob (no topics: the bridge derives them from the key)."""
    return [[TYPE_CODE[c["type"]], c["base"]] for c in relays(cfg)]


def encrypt(key: str, payload: dict) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    iv = secrets.token_bytes(12)
    ct = AESGCM(rv_key(key)).encrypt(iv, json.dumps(payload, separators=(",", ":")).encode(), BRV_AAD)
    return K.RV_PREFIX + K.b64u(iv + ct)


def decrypt(key: str, text: str) -> dict | None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    text = (text or "").strip()
    if not text.startswith(K.RV_PREFIX):
        return None
    try:
        raw = K.b64u_dec(text[len(K.RV_PREFIX):])
        obj = json.loads(AESGCM(rv_key(key)).decrypt(raw[:12], raw[12:], BRV_AAD))
        return obj if isinstance(obj, dict) and "url" in obj and "seq" in obj else None
    except Exception:  # noqa: BLE001
        return None


def _fp(key: str) -> str:
    return hashlib.sha256(b"kalecam-bridge-rv-state:" + key.encode()).hexdigest()[:16]


def publish(url: str, key: str, cfg: dict, st: dict, only: list[str] | None = None) -> dict:
    seq = RV.next_seq(st.get("seq"))
    payload = {"v": 1, "url": url.rstrip("/"), "issued_at": K.iso(K.now_local()), "seq": seq}
    results = {}
    for c in channels(key, cfg):
        lab = RV.channel_label(c)
        if only is not None and lab not in only:
            continue
        r = RV.publish_one(c, encrypt(key, payload))  # fresh IV per channel
        results[lab] = r
        ch = st.setdefault("channels", {}).setdefault(lab, {})
        ch["last_attempt_at"] = payload["issued_at"]
        if r["ok"]:
            ch.update({"last_ok_at": payload["issued_at"], "url": payload["url"], "seq": seq,
                       "via": r.get("via"), "error": None, "fail_streak": 0})
        else:
            RV.note_failure(ch, r.get("error"))
    st["seq"] = seq
    return {"seq": seq, "results": results}


def maybe_publish(cfg: dict, tunnel_url: str | None, force: bool = False, log=print) -> dict | None:
    """Called by the watchdog after the phone publish. Publishes the bridge URL (public_base_url
    if set, else the tunnel URL) when it changed, when the key changed, when a channel failed last
    time, or every `republish_s`. Returns the publish result or None if nothing was done."""
    kd = B.load_key() or {}
    key = kd.get("key")
    bc = B.bridge_config(cfg)
    url = (bc.get("public_base_url") or tunnel_url or "").rstrip("/")
    if not key or not url or not relays(cfg):
        return None
    st = K.read_json(PUBLISH_STATE, {}) or {}
    labels = [RV.channel_label(c) for c in relays(cfg)]
    chans = st.get("channels", {})
    stale = time.time() - st.get("last_full_ts", 0) >= float(cfg.get("republish_s", 3600))
    first = not st.get("key_state")
    keychg = not first and st.get("key_state") != _fp(key)
    if keychg or first:
        st["channels"] = {}
        chans = {}
    if force or first or keychg or url != st.get("url") or stale:
        todo = None
        why = ("forced" if force else "first publish" if first else "key changed" if keychg
               else "url changed" if url != st.get("url") else "periodic refresh")
    else:
        todo = [lab for lab in labels
                if (chans.get(lab, {}).get("url") != url or chans.get(lab, {}).get("error"))
                and RV.retry_due(chans.get(lab, {}))]
        why = "retry failed channels"
        if not todo:
            return None
    res = publish(url, key, cfg, st, only=todo)
    if todo is None:
        st["last_full_ts"] = time.time()
    st["url"] = url
    st["key_state"] = _fp(key)
    K.write_json_atomic(PUBLISH_STATE, st)
    ok = [k for k, v in res["results"].items() if v["ok"]]
    bad = {k: v.get("error") for k, v in res["results"].items() if not v["ok"]}
    log(f"bridge rendezvous published seq={res['seq']} ({why}) ok={ok}" + (f" failed={bad}" if bad else ""))
    B.log_event("rendezvous_published", seq=res["seq"], reason=why, ok=ok, failed=list(bad))
    return res


def status() -> dict:
    return K.read_json(PUBLISH_STATE, {}) or {}
