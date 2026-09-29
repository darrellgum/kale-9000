"""Fake LAN devices for tests: Shelly Gen1/Gen2, Tasmota, Kasa (TCP), Home Assistant, a JSON
sensor, and a fake ntfy + textdb relay. Each runs in a background thread on 127.0.0.1."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import socketserver
import struct
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kalebridge.httputil import parse_challenge  # noqa: E402
from kalebridge.drivers import kasa as KASA  # noqa: E402


class _Srv(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class FakeHTTP:
    """Base: subclasses implement route(method, path, query, headers, body) -> (code, obj, headers)."""

    def __init__(self):
        outer = self
        self.lock = threading.Lock()
        self.requests = []

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _go(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                u = urllib.parse.urlsplit(self.path)
                q = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
                with outer.lock:
                    outer.requests.append((method, self.path))
                    code, obj, hdrs = outer.route(method, u.path, q, self.headers, body, self.path)
                raw = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
                self.send_response(code)
                for k, v in (hdrs or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self._go("GET")

            def do_POST(self):
                self._go("POST")

            def log_message(self, *a):
                pass

        self.srv = _Srv(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        self.host = f"127.0.0.1:{self.port}"
        self.url = f"http://{self.host}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class FakeShellyGen1(FakeHTTP):
    def __init__(self, relays=1, user=None, password=None):
        self.on = [False] * relays
        self.user, self.password = user, password
        self.set_calls = 0
        super().__init__()

    def route(self, method, path, q, h, body, raw):
        if self.password:
            want = "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
            if h.get("Authorization") != want:
                return 401, {"error": "unauthorized"}, {"WWW-Authenticate": 'Basic realm="shelly"'}
        if path == "/status":
            return 200, {"relays": [{"ison": v, "has_timer": False} for v in self.on]}, None
        if path.startswith("/relay/"):
            i = int(path.split("/")[2])
            if i >= len(self.on):
                return 404, {"error": "no relay"}, None
            if "turn" in q:
                self.set_calls += 1
                self.on[i] = q["turn"] == "on"
            return 200, {"ison": self.on[i], "has_timer": False}, None
        return 404, {}, None


class FakeShellyGen2(FakeHTTP):
    REALM = "shellyplus1pm-a8032ab12345"

    def __init__(self, switches=1, password=None):
        self.on = [False] * switches
        self.password = password
        self.set_calls = 0
        self.nonce = os.urandom(8).hex()
        super().__init__()

    def _auth_ok(self, h, method, raw):
        a = h.get("Authorization") or ""
        if not a.startswith("Digest "):
            return False
        c = parse_challenge(a)
        H = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731
        ha1 = H(f"admin:{self.REALM}:{self.password}")
        ha2 = H(f"{method}:{c.get('uri')}")
        want = H(f"{ha1}:{self.nonce}:{c.get('nc')}:{c.get('cnonce')}:auth:{ha2}")
        return c.get("username") == "admin" and c.get("response") == want and c.get("uri") == raw

    def route(self, method, path, q, h, body, raw):
        if self.password and not self._auth_ok(h, method, raw):
            return 401, {"code": 401}, {"WWW-Authenticate": f'Digest qop="auth", realm="{self.REALM}", '
                                                             f'nonce="{self.nonce}", algorithm=SHA-256'}
        i = int(q.get("id", 0))
        if i >= len(self.on):
            return 500, {"code": -105, "message": "Argument 'id', value 9 not found!"}, None
        if path == "/rpc/Switch.GetStatus":
            return 200, {"id": i, "source": "http", "output": self.on[i], "apower": 0.0}, None
        if path == "/rpc/Switch.Set":
            self.set_calls += 1
            was = self.on[i]
            self.on[i] = q.get("on") == "true"
            return 200, {"was_on": was}, None
        return 404, {"code": 404}, None


class FakeTasmota(FakeHTTP):
    def __init__(self, relays=1, user=None, password=None):
        self.on = [False] * relays
        self.user, self.password = user, password
        self.set_calls = 0
        super().__init__()

    def route(self, method, path, q, h, body, raw):
        if path != "/cm":
            return 404, {}, None
        if self.password and (q.get("user") != self.user or q.get("password") != self.password):
            return 401, {"WARNING": "Need user=<username>&password=<password>"}, None
        parts = q.get("cmnd", "").split(" ", 1)
        cmd = parts[0].lower()
        if not cmd.startswith("power"):
            return 200, {"Command": "Unknown"}, None
        n = cmd[5:] or ""
        idx = int(n) - 1 if n else 0
        if idx >= len(self.on):
            return 200, {"Command": "Unknown"}, None
        if len(parts) > 1:
            self.set_calls += 1
            self.on[idx] = parts[1].lower() in ("on", "1")
        key = "POWER" if len(self.on) == 1 and not n else f"POWER{n or 1}"
        return 200, {key: "ON" if self.on[idx] else "OFF"}, None


class FakeHA(FakeHTTP):
    def __init__(self, token="tok-123", entities=("switch.tent_fan",)):
        self.token = token
        self.states = {e: "off" for e in entities}
        self.set_calls = 0
        super().__init__()

    def route(self, method, path, q, h, body, raw):
        if h.get("Authorization") != f"Bearer {self.token}":
            return 401, {"message": "unauthorized"}, None
        if method == "GET" and path.startswith("/api/states/"):
            e = path[len("/api/states/"):]
            if e not in self.states:
                return 404, {"message": "Entity not found."}, None
            return 200, {"entity_id": e, "state": self.states[e]}, None
        if method == "POST" and path in ("/api/services/homeassistant/turn_on", "/api/services/homeassistant/turn_off"):
            e = json.loads(body)["entity_id"]
            self.set_calls += 1
            self.states[e] = "on" if path.endswith("turn_on") else "off"
            return 200, [], None
        return 404, {}, None


class FakeSensor(FakeHTTP):
    def __init__(self, value):
        self.value = value
        super().__init__()

    def route(self, method, path, q, h, body, raw):
        return 200, {"reading": {"value": self.value}}, None


class FakeRelay(FakeHTTP):
    """ntfy (POST /<topic>, GET /<topic>/json?poll=1&since=all) and textdb (POST /update, GET /<key>)."""

    def __init__(self, kind="ntfy"):
        self.kind = kind
        self.msgs = {}
        super().__init__()

    def route(self, method, path, q, h, body, raw):
        if self.kind == "ntfy":
            if method == "POST":
                t = path.strip("/")
                self.msgs.setdefault(t, []).append(body.decode())
                return 200, {"id": os.urandom(4).hex(), "event": "message", "topic": t, "expires": 0}, None
            if path.endswith("/json"):
                t = path.strip("/")[:-len("/json")]
                lines = [json.dumps({"event": "open"})] + [json.dumps({"event": "message", "message": m})
                                                           for m in self.msgs.get(t, [])]
                return 200, ("\n".join(lines) + "\n").encode(), None
            return 404, {}, None
        if method == "POST" and path == "/update":
            f = dict(urllib.parse.parse_qsl(body.decode()))
            self.msgs[f["key"]] = [f["value"]]
            return 200, {"status": 1, "data": {"key": f["key"]}}, None
        t = path.strip("/")
        return 200, (self.msgs.get(t, [""])[-1]).encode(), None


class FakeKasa:
    """Legacy Kasa TCP protocol on 127.0.0.1 (plug, or a strip with `children` outlets)."""

    def __init__(self, children=0):
        self.children = [{"id": f"{i:02d}", "state": 0, "alias": f"Plug {i}"} for i in range(children)]
        self.relay = 0
        self.set_calls = 0
        outer = self

        class H(socketserver.BaseRequestHandler):
            def handle(self):
                hdr = self.request.recv(4)
                n = struct.unpack(">I", hdr)[0]
                buf = b""
                while len(buf) < n:
                    buf += self.request.recv(n - len(buf))
                req = json.loads(KASA.decrypt(buf))
                resp = outer.answer(req)
                self.request.sendall(KASA.encrypt(json.dumps(resp).encode()))

        class S(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.srv = S(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        self.host = f"127.0.0.1:{self.port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def answer(self, req):
        sysm = req.get("system", {})
        if "get_sysinfo" in sysm:
            si = {"err_code": 0, "deviceId": "8006ABCDEF", "alias": "fake"}
            if self.children:
                si["children"] = self.children
            else:
                si["relay_state"] = self.relay
            return {"system": {"get_sysinfo": si}}
        if "set_relay_state" in sysm:
            self.set_calls += 1
            st = sysm["set_relay_state"]["state"]
            ids = (req.get("context") or {}).get("child_ids")
            if ids:
                for c in self.children:
                    if "8006ABCDEF" + c["id"] in ids:
                        c["state"] = st
            else:
                self.relay = st
            return {"system": {"set_relay_state": {"err_code": 0}}}
        return {"system": {"err_code": -1}}

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p
