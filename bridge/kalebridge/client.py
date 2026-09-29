"""HTTPS client for the bot's /bridge/* API (stdlib only). Never logs the key."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

from . import VERSION


class AuthError(Exception):
    """401: the key is wrong or was rotated. Re-pair needed."""


class NetError(Exception):
    """Anything else: DNS, TLS, timeouts, 5xx, tunnel down, bad JSON."""


class BotClient:
    def __init__(self, url: str, key: str, bridge_id: str, timeout: float = 15.0):
        self.url, self.key, self.bridge_id, self.timeout = url.rstrip("/"), key, bridge_id, timeout

    def _call(self, method: str, path: str, body=None, timeout: float | None = None):
        data = None if body is None else json.dumps(body).encode()
        h = {"X-Bridge-Key": self.key, "User-Agent": f"kalebridge/{VERSION}", "Accept": "application/json"}
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                raw = r.read(1024 * 1024)
                hdrs = {k.lower(): v for k, v in r.headers.items()}
                code = r.status
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise AuthError("bot rejected the bridge key (401): re-pair with a new blob") from None
            try:
                raw = e.read(4096)
            except Exception:  # noqa: BLE001
                raw = b""
            err = NetError(f"HTTP {e.code}")
            err.code = e.code
            err.body = raw
            raise err from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
            reason = getattr(e, "reason", e)
            raise NetError(f"{type(e).__name__}: {str(reason)[:120]}") from None
        try:
            obj = json.loads(raw or b"null")
        except ValueError:
            raise NetError(f"non-JSON reply (HTTP {code}); wrong URL or tunnel page?") from None
        return obj, hdrs

    def poll(self, hold: int = 25):
        obj, hdrs = self._call("GET", f"/bridge/poll?bridge={self.bridge_id}&hold={int(hold)}",
                               timeout=max(hold + 15, self.timeout))
        if not isinstance(obj, list):
            raise NetError("poll reply is not a list")
        return obj, hdrs

    def config(self):
        obj, _ = self._call("GET", "/bridge/config")
        if not isinstance(obj, dict) or "fallback" not in obj:
            raise NetError("config reply has no 'fallback'")
        return obj

    def result(self, res: dict):
        return self._call("POST", "/bridge/result", res)[0]

    def heartbeat(self, hb: dict):
        return self._call("POST", "/bridge/heartbeat", hb)[0]
