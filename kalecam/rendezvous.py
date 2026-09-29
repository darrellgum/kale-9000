"""Publish / read the encrypted tunnel address on no-account rendezvous channels.

Channel types:
  ntfy   - any ntfy server (ntfy.sh, ntfy.envs.net, ...): POST <base>/<topic>,
           read GET <base>/<topic>/json?poll=1&since=all (messages cached ~12 h).
  textdb - textdb.online: POST <base>/update key=<topic>&value=<msg>, read GET <base>/<topic>
           (single value, kept 30 days after last access/update).
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import kalecam_lib as K

UA = "kalecam/" + K.APP_VERSION


def _req(url: str, data: bytes | None = None, headers: dict | None = None, timeout: float = 15.0):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})},
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def _with_http_fallback(url: str, **kw):
    """Try HTTPS; if the TLS connection itself fails (some networks block TLS to a host),
    retry over plain HTTP. Safe because payloads are AES-GCM encrypted + authenticated;
    only the topic name is exposed on the wire in that case."""
    try:
        return _req(url, **kw) + ("https",)
    except (urllib.error.URLError, ssl.SSLError, ConnectionError, TimeoutError, OSError) as e:
        if isinstance(e, urllib.error.HTTPError) or not url.startswith("https://"):
            raise
        s, b = _req("http://" + url[len("https://"):], **kw)
        return s, b, "http-fallback"


def channel_label(c: dict) -> str:
    return f"{c['type']}:{urllib.parse.urlparse(c['base']).netloc}"


def publish_one(c: dict, message: str) -> dict:
    t0 = time.time()
    try:
        if c["type"] == "ntfy":
            s, b, via = _with_http_fallback(
                f"{c['base']}/{c['topic']}", data=message.encode(),
                headers={"Cache": "yes", "Firebase": "no", "Priority": "min", "Content-Type": "text/plain"})
            j = json.loads(b)
            ok = s == 200 and j.get("event") == "message"
            detail = {"id": j.get("id"), "expires": j.get("expires")}
        elif c["type"] == "textdb":
            body = urllib.parse.urlencode({"key": c["topic"], "value": message}).encode()
            s, b, via = _with_http_fallback(f"{c['base']}/update", data=body,
                                            headers={"Content-Type": "application/x-www-form-urlencoded"})
            j = json.loads(b)
            ok = s == 200 and j.get("status") == 1
            detail = {}
        else:
            return {"ok": False, "error": f"unknown channel type {c['type']}"}
        return {"ok": ok, "via": via, "ms": int((time.time() - t0) * 1000), **detail}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300], "ms": int((time.time() - t0) * 1000)}


def read_one(c: dict, pairing: dict) -> dict:
    """Return the newest valid payload on a channel (and how many messages were seen)."""
    try:
        if c["type"] == "ntfy":
            s, b, via = _with_http_fallback(f"{c['base']}/{c['topic']}/json?poll=1&since=all")
            texts = []
            for line in b.decode().splitlines():
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if m.get("event") == "message":
                    texts.append(m.get("message", ""))
        else:
            s, b, via = _with_http_fallback(f"{c['base']}/{c['topic']}")
            texts = [b.decode(errors="replace")]
        valid = [p for p in (K.rv_decrypt(pairing, t) for t in texts) if p]
        best = max(valid, key=lambda p: p["seq"]) if valid else None
        return {"ok": best is not None, "via": via, "messages": len(texts), "valid": len(valid),
                "invalid": len(texts) - len(valid), "latest": best}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}


def next_seq(prev: int | None) -> int:
    return max((prev or 0) + 1, int(time.time() * 1000))


def note_failure(ch: dict, error: str | None) -> None:
    ch["error"] = error
    ch["error_ts"] = time.time()
    ch["fail_streak"] = int(ch.get("fail_streak") or 0) + 1


def retry_due(ch: dict, now: float | None = None) -> bool:
    """A failed channel is retried with backoff (1, 2, 4 ... 15 min; 15 min straight away after a
    429 rate limit), so a relay that is down or rate limiting us isn't hammered every pass."""
    if not ch.get("error"):
        return True
    now = time.time() if now is None else now
    streak = max(1, int(ch.get("fail_streak") or 1))
    wait = 900 if "429" in str(ch.get("error")) else min(60 * 2 ** (streak - 1), 900)
    return now - float(ch.get("error_ts") or 0) >= wait


def publish(url: str, pairing: dict, state: dict, only: list[str] | None = None) -> dict:
    """Publish {url, issued_at, seq} to every channel (or just `only`). Updates `state` in place."""
    seq = next_seq(state.get("seq"))
    payload = {"v": 1, "url": url, "issued_at": K.iso(K.now_local()), "seq": seq}
    results = {}
    for c in pairing["channels"]:
        lab = channel_label(c)
        if only is not None and lab not in only:
            continue
        r = publish_one(c, K.rv_encrypt(pairing, payload))  # fresh IV per channel
        results[lab] = r
        ch = state.setdefault("channels", {}).setdefault(lab, {})
        ch["last_attempt_at"] = payload["issued_at"]
        if r["ok"]:
            ch.update({"last_ok_at": payload["issued_at"], "last_ok_ts": time.time(), "url": url,
                       "seq": seq, "via": r.get("via"), "error": None, "fail_streak": 0})
        else:
            note_failure(ch, r.get("error"))
    state["seq"] = seq
    return {"seq": seq, "payload": payload, "results": results}
