"""Tiny HTTP helpers on top of urllib (stdlib only): JSON GET/POST, Basic and Digest auth.

Digest auth is implemented here because urllib's handler does not support SHA-256, which is what
Shelly Gen2+ devices use (RFC 7616, qop=auth).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

UA = "kalebridge"
# LAN devices are always reached directly: an http(s)_proxy variable meant for the internet must not
# route plug traffic through a proxy.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class HTTPStatusError(Exception):
    def __init__(self, code: int, body: bytes = b"", headers=None):
        super().__init__(f"HTTP {code}")
        self.code, self.body, self.headers = code, body, headers or {}


def request(method: str, url: str, body=None, headers: dict | None = None, timeout: float = 10.0,
            basic: tuple | None = None, digest: tuple | None = None):
    """Return (status, headers, bytes). Raises HTTPStatusError for >= 400, OSError/URLError on network
    errors. `basic`/`digest` = (user, password)."""
    data = None
    h = {"User-Agent": UA}
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    if basic:
        h["Authorization"] = "Basic " + base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode()
    try:
        return _do(method, url, data, h, timeout)
    except HTTPStatusError as e:
        if e.code == 401 and digest:
            chal = e.headers.get("WWW-Authenticate") or e.headers.get("www-authenticate") or ""
            if chal.lower().startswith("digest"):
                h["Authorization"] = digest_header(chal, method, url, digest[0], digest[1])
                return _do(method, url, data, h, timeout)
        raise


def _do(method, url, data, h, timeout):
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read(1024 * 1024)
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:  # noqa: BLE001
            body = b""
        raise HTTPStatusError(e.code, body, dict(e.headers or {})) from None


def get_json(url: str, **kw):
    _, _, b = request("GET", url, **kw)
    return json.loads(b or b"null")


def parse_challenge(chal: str) -> dict:
    chal = re.sub(r"^\s*digest\s+", "", chal, flags=re.I)
    return {k.lower(): (v1 if v1 else v2) for k, v1, v2 in
            re.findall(r'([A-Za-z0-9_-]+)\s*=\s*(?:"([^"]*)"|([^,\s]*))', chal)}


def digest_header(chal: str, method: str, url: str, user: str, password: str,
                  cnonce: str | None = None, nc: int = 1) -> str:
    c = parse_challenge(chal)
    alg = (c.get("algorithm") or "MD5").upper()
    hfun = {"MD5": hashlib.md5, "MD5-SESS": hashlib.md5, "SHA-256": hashlib.sha256,
            "SHA-256-SESS": hashlib.sha256}.get(alg)
    if hfun is None:
        raise ValueError(f"unsupported digest algorithm {alg}")

    def H(s: str) -> str:
        return hfun(s.encode()).hexdigest()

    p = urllib.parse.urlsplit(url)
    uri = p.path + ("?" + p.query if p.query else "")
    cnonce = cnonce or os.urandom(8).hex()
    ncs = f"{nc:08x}"
    ha1 = H(f"{user}:{c.get('realm', '')}:{password}")
    if alg.endswith("-SESS"):
        ha1 = H(f"{ha1}:{c.get('nonce', '')}:{cnonce}")
    ha2 = H(f"{method}:{uri}")
    qop = c.get("qop")
    if qop:
        qop = "auth" if "auth" in [q.strip() for q in qop.split(",")] else qop.split(",")[0].strip()
        resp = H(f"{ha1}:{c.get('nonce', '')}:{ncs}:{cnonce}:{qop}:{ha2}")
    else:
        resp = H(f"{ha1}:{c.get('nonce', '')}:{ha2}")
    parts = [f'username="{user}"', f'realm="{c.get("realm", "")}"', f'nonce="{c.get("nonce", "")}"',
             f'uri="{uri}"', f'algorithm={alg}', f'response="{resp}"']
    if qop:
        parts += [f"qop={qop}", f"nc={ncs}", f'cnonce="{cnonce}"']
    if c.get("opaque"):
        parts.append(f'opaque="{c["opaque"]}"')
    return "Digest " + ", ".join(parts)
