#!/usr/bin/env python3
"""kalecam server: photo upload + command long-poll + heartbeat + config + PWA,
plus the device-bridge API (/bridge/*, see bridge_lib.py and ../bridge/KALE-SIDE.md).

Binds 127.0.0.1 only; exposed to the phone through a Cloudflare quick tunnel.
Stdlib only (Pillow is used for JPEG verification if importable).
"""
from __future__ import annotations

import datetime as dt
import email.parser
import email.policy
import hashlib
import hmac
import json
import os
import secrets
import shutil
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kalecam_lib as K  # noqa: E402
import bridge_lib as B  # noqa: E402

try:
    from PIL import Image  # type: ignore
    import io
except Exception:  # pragma: no cover
    Image = None

MAX_BYTES = 25 * 1024 * 1024
BRIDGE_MAX_BODY = 64 * 1024
INSTANCE = secrets.token_hex(8)
STARTED = time.time()
REDELIVER_AFTER_S = 120
# A capture command handed to a long-poll that belonged to a page that was reloading/closing is
# lost with that page. If a NEWER poll from the same camera is waiting and the command still has
# no photo after this many seconds, hand it over once more (the phone ignores command ids it has
# already seen, so a live page is never asked twice).
EARLY_REDELIVER_S = 8
MAX_ATTEMPTS = 3
STATIC = {
    "/app": ("index.html", "text/html; charset=utf-8"),
    "/app/": ("index.html", "text/html; charset=utf-8"),
    "/app/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app/db.js": ("db.js", "text/javascript; charset=utf-8"),
    "/app/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/app/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/app/icon-192.png": ("icon-192.png", "image/png"),
    "/app/icon-512.png": ("icon-512.png", "image/png"),
}
CORS_HEADERS = ("Content-Type, X-Upload-Key, X-Plant-Id, X-Camera, X-Captured-At, X-Trigger, "
                "X-Cmd-Id, X-Photo-Id, X-App-Version, X-Queued")
_index_lock = threading.Lock()
_cmd_lock = threading.Lock()
_seen_ids: dict[str, str] = {}
_last_poll: dict[str, float] = {}
_poll_gen: dict[str, int] = {}


# ------------------------------------------------------------------ cached config / pairing
class _Cached:
    def __init__(self, path: Path, loader):
        self.path, self.loader, self.mtime, self.value = path, loader, None, None

    def get(self):
        try:
            m = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            m = None
        if m != self.mtime or self.value is None:
            self.mtime, self.value = m, self.loader()
        return self.value


CFG = _Cached(K.CONFIG_PATH, K.load_config)
PAIR = _Cached(K.PAIRING_PATH, lambda: K.load_pairing() or {})
BKEY = _Cached(B.KEY_PATH, lambda: B.load_key() or {})


def expected_token() -> str | None:
    p = PAIR.get()
    return K.auth_token(p) if p.get("secret") else None


def log(msg: str) -> None:
    sys.stderr.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")
    sys.stderr.flush()


# ------------------------------------------------------------------ JPEG helpers
def jpeg_check(data: bytes) -> tuple[bool, str]:
    if len(data) < 4 or data[:3] != b"\xff\xd8\xff" or b"\xff\xd9" not in data[-1024:]:
        return False, "missing JPEG SOI/EOI markers"
    if Image:
        try:
            im = Image.open(io.BytesIO(data))
            fmt = im.format
            im.verify()
            if fmt != "JPEG":
                return False, f"format={fmt}"
        except Exception as e:
            return False, f"decode failed: {e}"
    return True, "ok"


def jpeg_strip_and_size(data: bytes, strip: bool) -> tuple[bytes, int | None, int | None]:
    """Drop APP1 (EXIF/XMP) + APP13 segments (GPS/device info) and read SOF dimensions."""
    out, i, w, h = bytearray(data[:2]), 2, None, None
    try:
        while i + 4 <= len(data):
            if data[i] != 0xFF:
                return data, w, h  # unexpected layout: store untouched
            marker = data[i + 1]
            if marker == 0xDA:  # start of scan: copy the rest verbatim
                out += data[i:]
                break
            if 0xD0 <= marker <= 0xD7 or marker == 0x01:
                out += data[i:i + 2]
                i += 2
                continue
            seglen = struct.unpack(">H", data[i + 2:i + 4])[0]
            seg = data[i:i + 2 + seglen]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
            if not (strip and marker in (0xE1, 0xED)):
                out += seg
            i += 2 + seglen
        else:
            return data, w, h
        return bytes(out), w, h
    except Exception:
        return data, w, h


# ------------------------------------------------------------------ storage
def parse_captured_at(s: str | None) -> tuple[dt.datetime, str | None]:
    now = K.now_local()
    if not s:
        return now, None
    try:
        t = dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=now.tzinfo)  # naive = bot-local
        t = K.to_local(t)
        if t - now > dt.timedelta(minutes=10) or now - t > dt.timedelta(days=30):
            return now, s  # implausible clock: use receive time, keep the original
        return t, None
    except ValueError:
        return now, s


def rotation_lock_wait(root: Path, max_wait: float = 20.0) -> None:
    lock = root / ".rotate.lock"
    end = time.time() + max_wait
    while lock.exists() and time.time() < end:
        time.sleep(0.5)


def store_photo(data: bytes, meta: dict) -> dict:
    cfg = CFG.get()
    root = Path(cfg["photo_root"])
    camera = meta.get("camera") or cfg["default_camera"]
    # plant precedence: explicit plant on the command > camera_plants mapping > phone's plant > default
    cmd_plant = None
    if meta.get("cmd_id"):
        _, c = K.command_status(meta["cmd_id"])
        cmd_plant = (c or {}).get("plant")
    plant = (cmd_plant or (cfg.get("camera_plants") or {}).get(camera) or meta.get("plant_id")
             or cfg["default_plant"])
    if not K.PLANT_RE.match(plant):
        raise ValueError("plant_id must be lowercase letters, digits, '-' or '_' (max 64)")
    if not K.CAMERA_RE.match(camera):
        raise ValueError("camera must be letters, digits, '.', '_' or '-' (max 32)")
    photo_id = (meta.get("photo_id") or "")[:64]
    if photo_id and photo_id in _seen_ids:
        return {"ok": True, "duplicate": True, "file": _seen_ids[photo_id], "plant": plant}
    taken, bad_ts = parse_captured_at(meta.get("captured_at"))
    data, w, h = jpeg_strip_and_size(data, bool(cfg.get("strip_exif", True)))
    plant_dir = root / plant
    day_dir = plant_dir / taken.strftime("%Y/%m/%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    base = taken.strftime("%H%M%S") + (f"-{camera}" if cfg.get("camera_suffix", True) else "")
    tmp = day_dir / f".upload-{secrets.token_hex(6)}.tmp"
    tmp.write_bytes(data)
    n = 0
    while True:
        dest = day_dir / (f"{base}.jpg" if n == 0 else f"{base}-{n}.jpg")
        try:
            os.link(tmp, dest)  # atomic, fails if dest exists
            break
        except FileExistsError:
            n += 1
    tmp.unlink()
    os.chmod(dest, 0o644)
    rel = dest.relative_to(plant_dir).as_posix()
    entry = {"file": rel, "ts": K.iso(taken), "plant": plant, "source": camera,
             "bytes": len(data), "status": "active", "milestone": None, "keep": False,
             "quality": None, "best": False,
             "trigger": meta.get("trigger") or "unknown", "cmd_id": meta.get("cmd_id") or None,
             "photo_id": photo_id or None, "received_at": K.iso(K.now_local()),
             "queued": str(meta.get("queued", "")).lower() in ("1", "true", "yes"),
             "width": w, "height": h, "sha256": hashlib.sha256(data).hexdigest(),
             "app_version": meta.get("app_version") or None}
    if bad_ts:
        entry["captured_at_client"] = bad_ts
    with _index_lock:
        rotation_lock_wait(root)
        with (plant_dir / "index.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if photo_id:
        _seen_ids[photo_id] = rel
        if len(_seen_ids) > 5000:
            for k in list(_seen_ids)[:1000]:
                _seen_ids.pop(k, None)
    cid = meta.get("cmd_id")
    if cid:
        complete_command(cid, plant, str(dest), entry)
    return {"ok": True, "duplicate": False, "file": rel, "path": str(dest), "plant": plant,
            "bytes": len(data), "sha256": entry["sha256"], "width": w, "height": h, "ts": entry["ts"]}


def seed_seen_ids() -> None:
    """Rebuild the de-duplication set from recent index rows after a restart."""
    root = Path(CFG.get()["photo_root"])
    if not root.exists():
        return
    for idx in root.glob("*/index.jsonl"):
        try:
            lines = idx.read_text(encoding="utf-8").splitlines()[-500:]
        except OSError:
            continue
        for line in lines:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("photo_id"):
                _seen_ids[r["photo_id"]] = r.get("file")


# ------------------------------------------------------------------ commands
def complete_command(cid: str, plant: str, path: str, entry: dict) -> None:
    with _cmd_lock:
        for st in ("delivered", "pending"):
            src = K.CMD_DIR / st / f"{cid}.json"
            if src.exists():
                c = K.read_json(src, {}) or {}
                c.update({"status": "done", "done_at": K.iso(K.now_local()), "file": path,
                          "plant_result": plant, "bytes": entry["bytes"]})
                K.write_json_atomic(K.CMD_DIR / "done" / f"{cid}.json", c)
                src.unlink(missing_ok=True)
                return


def requeue_stale() -> None:
    now = time.time()
    for p in (K.CMD_DIR / "delivered").glob("*.json"):
        c = K.read_json(p, None)
        if not c:
            continue
        if now - c.get("delivered_ts", now) > REDELIVER_AFTER_S:
            if c.get("attempts", 0) >= MAX_ATTEMPTS:
                c["status"] = "failed"
                K.write_json_atomic(K.CMD_DIR / "done" / p.name, c)
            else:
                K.write_json_atomic(K.CMD_DIR / "pending" / p.name, c)
            p.unlink(missing_ok=True)


def take_command(camera: str, gen: int | None = None) -> dict | None:
    with _cmd_lock:
        requeue_stale()
        if gen is not None:
            now = time.time()
            for p in sorted((K.CMD_DIR / "delivered").glob("*.json")):
                c = K.read_json(p, None)
                if (not c or c.get("camera") != camera or c.get("early_redelivered")
                        or c.get("poll_gen") is None or c["poll_gen"] >= gen
                        or now - c.get("delivered_ts", now) < EARLY_REDELIVER_S):
                    continue
                c.update(early_redelivered=True, poll_gen=gen, delivered_ts=now,
                         delivered_at=K.iso(K.now_local()))
                K.write_json_atomic(p, c)
                return c
        for p in sorted((K.CMD_DIR / "pending").glob("*.json")):
            c = K.read_json(p, None)
            if not c or c.get("camera") not in (camera, "*"):
                continue
            c["attempts"] = c.get("attempts", 0) + 1
            c["delivered_ts"] = time.time()
            c["delivered_at"] = K.iso(K.now_local())
            c["status"] = "delivered"
            c["poll_gen"] = gen
            if c.get("cmd") != "capture":  # fire-and-forget commands are done once delivered
                K.write_json_atomic(K.CMD_DIR / "done" / p.name, c)
            else:
                K.write_json_atomic(K.CMD_DIR / "delivered" / p.name, c)
            p.unlink(missing_ok=True)
            return c
    return None


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "kalecam/" + K.APP_VERSION
    protocol_version = "HTTP/1.1"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", CORS_HEADERS)
        self.send_header("Access-Control-Max-Age", "600")

    def _send(self, code: int, obj, ctype="application/json", extra: dict | None = None):
        body = obj if isinstance(obj, bytes) else (
            json.dumps(obj).encode() if ctype == "application/json" else str(obj).encode())
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _auth(self) -> bool:
        exp = expected_token()
        if not exp:
            self._send(503, {"error": "not paired yet: run `kalecam pair`"})
            return False
        got = self.headers.get("X-Upload-Key", "")
        if not hmac.compare_digest(got.encode(), exp.encode()):
            self.close_connection = True
            self._send(401, {"error": "missing or invalid X-Upload-Key"})
            return False
        return True

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        if path in ("/", "/healthz"):
            return self._send(200, {"ok": True, "app": "kalecam", "instance": INSTANCE,
                                    "version": K.APP_VERSION, "uptime_s": int(time.time() - STARTED)})
        if path in STATIC:
            name, ctype = STATIC[path]
            f = K.APP_DIR / name
            if not f.exists():
                return self._send(404, {"error": "not found"})
            extra = {"Cache-Control": "no-cache"}
            if name == "sw.js":
                extra["Service-Worker-Allowed"] = "/app"
            if name == "index.html":
                extra["Referrer-Policy"] = "no-referrer"
                extra["Permissions-Policy"] = "camera=(self), screen-wake-lock=(self), fullscreen=(self)"
            body = f.read_bytes()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        if path.startswith("/bridge/"):
            return self._bridge_get(path, u)
        if path == "/config":
            if not self._auth():
                return
            cfg = K.phone_config(CFG.get())
            cfg["server_time"] = K.iso(K.now_local())
            cfg["instance"] = INSTANCE
            return self._send(200, cfg)
        if path == "/poll":
            if not self._auth():
                return
            q = parse_qs(u.query)
            camera = (q.get("camera") or [CFG.get()["default_camera"]])[0]
            if not K.CAMERA_RE.match(camera):
                return self._send(400, {"error": "bad camera"})
            hold = min(float((q.get("hold") or [CFG.get().get("poll_hold_s", 25)])[0]), 25.0)
            end = time.time() + max(0.0, hold)
            _last_poll[camera] = time.time()
            with _cmd_lock:
                gen = _poll_gen[camera] = _poll_gen.get(camera, 0) + 1
            (K.HB_DIR / f"{camera}.lastpoll").write_text(K.iso(K.now_local()))
            while True:
                c = take_command(camera, gen)
                if c:
                    return self._send(200, {"cmd": c["cmd"], "id": c["id"], "settings": c.get("settings", {}),
                                            "plant": c.get("plant"), "config_version": K.phone_config(CFG.get())["version"],
                                            "instance": INSTANCE})
                if time.time() >= end:
                    return self._send(200, {"cmd": None, "config_version": K.phone_config(CFG.get())["version"],
                                            "instance": INSTANCE})
                time.sleep(0.5)
        return self._send(404, {"error": "not found"})

    # -------------------------------------------------------------- POST
    def _read_body(self) -> bytes:
        te = self.headers.get("Transfer-Encoding", "").lower()
        if "chunked" in te:
            buf = bytearray()
            while True:
                line = self.rfile.readline(1024)
                size = int(line.split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline(1024) not in (b"\r\n", b"\n", b""):
                        pass
                    break
                if len(buf) + size > MAX_BYTES:
                    raise OverflowError
                buf += self.rfile.read(size)
                self.rfile.readline(8)
            return bytes(buf)
        cl = self.headers.get("Content-Length")
        if cl is None:
            raise ValueError("Content-Length required")
        n = int(cl)
        if n > MAX_BYTES:
            raise OverflowError
        return self.rfile.read(n)

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/bridge/"):
            return self._bridge_post(path)
        if path not in ("/upload", "/heartbeat"):
            return self._send(404, {"error": "not found"})
        if not self._auth():
            return
        try:
            body = self._read_body()
        except OverflowError:
            self.close_connection = True
            return self._send(413, {"error": f"payload exceeds {MAX_BYTES} bytes"})
        except ValueError as e:
            return self._send(411, {"error": str(e)})
        if path == "/heartbeat":
            return self._heartbeat(body)
        return self._upload(body)

    def _heartbeat(self, body: bytes):
        try:
            hb = json.loads(body or b"{}")
            assert isinstance(hb, dict)
        except Exception:
            return self._send(400, {"error": "heartbeat must be a JSON object"})
        camera = str(hb.get("camera") or CFG.get()["default_camera"])
        if not K.CAMERA_RE.match(camera):
            return self._send(400, {"error": "bad camera"})
        hb = {k: hb[k] for k in list(hb)[:60]}  # bound size
        hb["received_at"] = K.iso(K.now_local())
        hb["received_ts"] = time.time()
        K.write_json_atomic(K.HB_DIR / f"{camera}.json", hb)
        logp = K.STATE / "heartbeats.jsonl"
        if logp.exists() and logp.stat().st_size > 5 * 1024 * 1024:
            shutil.move(logp, logp.with_suffix(".jsonl.1"))
        with logp.open("a", encoding="utf-8") as f:
            f.write(json.dumps(hb, separators=(",", ":")) + "\n")
        return self._send(200, {"ok": True, "config_version": K.phone_config(CFG.get())["version"],
                                "instance": INSTANCE, "server_time": hb["received_at"]})

    def _upload(self, body: bytes):
        h = self.headers
        meta = {"plant_id": h.get("X-Plant-Id"), "camera": h.get("X-Camera"),
                "captured_at": h.get("X-Captured-At"), "trigger": h.get("X-Trigger"),
                "cmd_id": h.get("X-Cmd-Id"), "photo_id": h.get("X-Photo-Id"),
                "app_version": h.get("X-App-Version"), "queued": h.get("X-Queued")}
        ctype = h.get("Content-Type", "")
        if ctype.lower().startswith("multipart/form-data"):
            msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                b"Content-Type: " + ctype.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
            data = None
            for part in msg.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if name == "photo":
                    data = part.get_payload(decode=True)
                elif name in ("plant_id", "camera", "captured_at", "trigger", "cmd_id", "photo_id",
                              "app_version", "queued"):
                    val = (part.get_payload(decode=True) or b"").decode("utf-8", "replace").strip()
                    if val:
                        meta[name] = val
            if data is None:
                return self._send(400, {"error": "multipart field 'photo' not found"})
        elif ctype.lower().split(";")[0].strip() in ("image/jpeg", "image/jpg"):
            data = body
        else:
            return self._send(415, {"error": "use multipart/form-data (field 'photo') or image/jpeg"})
        ok, why = jpeg_check(data)
        if not ok:
            return self._send(422, {"error": f"not a valid JPEG: {why}"})
        try:
            res = store_photo(data, meta)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        log(f"stored {res.get('plant')}/{res.get('file')} bytes={res.get('bytes')} trigger={meta.get('trigger')} "
            f"camera={meta.get('camera')} dup={res.get('duplicate')}")
        res.pop("path", None)
        return self._send(200, res)

    # -------------------------------------------------------------- device bridge (/bridge/*)
    def _bridge_auth(self) -> bool:
        exp = (BKEY.get() or {}).get("key")
        if not exp:
            self.close_connection = True
            self._send(503, {"error": "bridge not paired yet: run `kalecam bridge pair`"})
            return False
        if not B.key_matches(self.headers.get("X-Bridge-Key"), exp):
            self.close_connection = True
            self._send(401, {"error": "missing or invalid X-Bridge-Key"})
            return False
        return True

    def _bridge_get(self, path: str, u):
        if not self._bridge_auth():
            return
        try:
            bc = B.bridge_config(CFG.get())
            if path == "/bridge/config":
                pc = B.public_config(bc)
                pc["server_time"] = K.iso(B.now_b(bc))
                return self._send(200, pc)
            if path == "/bridge/poll":
                q = parse_qs(u.query)
                bridge = (q.get("bridge") or [""])[0]
                if not B.BRIDGE_RE.match(bridge):
                    return self._send(400, {"error": "missing or bad ?bridge=<id>"})
                try:
                    hold = float((q.get("hold") or [bc["poll_hold_s"]])[0])
                except ValueError:
                    return self._send(400, {"error": "bad hold"})
                end = time.time() + max(0.0, min(hold, 25.0))
                B.mark_poll(bridge)
                while True:
                    cmds = B.take(bridge, bc)
                    if cmds or time.time() >= end:
                        return self._send(200, cmds, extra={"X-Bridge-Config-Version": B.public_config(bc)["version"]})
                    time.sleep(0.5)
                    bc = B.bridge_config(CFG.get())
            return self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            log(f"bridge GET {path} error: {type(e).__name__}: {e}")
            return self._send(500, {"error": "internal error"})

    def _bridge_post(self, path: str):
        if path not in ("/bridge/result", "/bridge/heartbeat"):
            if not self._bridge_auth():
                return
            return self._send(404, {"error": "not found"})
        if not self._bridge_auth():
            return
        try:
            cl = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            cl = 0
        if cl > BRIDGE_MAX_BODY:
            self.close_connection = True
            return self._send(413, {"error": f"payload exceeds {BRIDGE_MAX_BODY} bytes"})
        try:
            body = self._read_body()
            if len(body) > BRIDGE_MAX_BODY:
                raise OverflowError
            obj = json.loads(body or b"null")
        except OverflowError:
            self.close_connection = True
            return self._send(413, {"error": f"payload exceeds {BRIDGE_MAX_BODY} bytes"})
        except ValueError as e:
            return self._send(400, {"error": f"body must be JSON ({type(e).__name__})"})
        try:
            bc = B.bridge_config(CFG.get())
            if path == "/bridge/result":
                code, res = B.record_result(obj)
            else:
                code, res = B.store_heartbeat(obj, bc)
            return self._send(code, res)
        except Exception as e:  # noqa: BLE001
            log(f"bridge POST {path} error: {type(e).__name__}: {e}")
            return self._send(500, {"error": "internal error"})

    def log_message(self, fmt, *args):
        ip = self.headers.get("CF-Connecting-IP", self.client_address[0]) if getattr(self, "headers", None) else self.client_address[0]
        line = fmt % args
        if "/poll" in line and " 200 " in line:
            return  # long-poll is noisy
        log(f"{ip} {line}")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64


def main():
    K.ensure_dirs()
    B.ensure_dirs()
    cfg = CFG.get()
    port = int(os.environ.get("PORT", cfg.get("port", 8765)))
    seed_seen_ids()
    srv = Server(("127.0.0.1", port), Handler)
    K.write_json_atomic(K.INSTANCE_PATH, {"instance": INSTANCE, "pid": os.getpid(), "port": port,
                                           "started_at": K.iso(K.now_local())})
    log(f"kalecam server {K.APP_VERSION} listening on 127.0.0.1:{port} instance={INSTANCE} "
        f"pillow={'yes' if Image else 'no'} paired={'yes' if expected_token() else 'no'} "
        f"bridge={'paired' if (BKEY.get() or {}).get('key') else 'unpaired'}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
