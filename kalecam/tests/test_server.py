#!/usr/bin/env python3
"""Server/API tests. ISOLATED: starts its OWN server.py on a spare port (default 18767) with
KALECAM_HOME and photo_root in a throwaway temp directory, so a live install (its port, photos,
state and secrets) is never touched.

  venv/bin/python tests/test_server.py              local checks only
  venv/bin/python tests/test_server.py --public     also through a temporary quick tunnel
                                                    (uses bin/cloudflared of this install, or
                                                    downloads the pinned one into the temp dir)
  KALECAM_TEST_PORT=18777 venv/bin/python tests/test_server.py

Uses plant id `kalecam-test` and camera `test-cam`. Never prints the pairing secret or auth token."""
import atexit, io, json, os, re, shutil, signal, subprocess, sys, tempfile, time, threading, urllib.request, urllib.error, uuid
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("KALECAM_TEST_PORT", "18767"))
TMP = Path(tempfile.mkdtemp(prefix="kalecam-server-test-"))
HOME = TMP / "home"
PHOTOS = TMP / "photos"
HOME.mkdir()
(HOME / "app").symlink_to(CODE / "app")
(HOME / "config.json").write_text(json.dumps({"port": PORT, "photo_root": str(PHOTOS), "rendezvous": []}))
os.environ["KALECAM_HOME"] = str(HOME)
sys.path.insert(0, str(CODE))
import kalecam_lib as K  # noqa: E402  (after KALECAM_HOME is set)
from PIL import Image  # noqa: E402

PLANT = "kalecam-test"
cfg = K.load_config()
assert Path(cfg["photo_root"]) == PHOTOS and PHOTOS.is_relative_to(TMP), "test must use its temp photo root"
K.ensure_pairing(cfg)
TOKEN = K.auth_token(K.load_pairing())
PROCS = []


def _cleanup():
    for pr in PROCS:
        try:
            os.killpg(pr.pid, signal.SIGTERM)
        except Exception:
            pass
    for pr in PROCS:
        try:
            pr.wait(timeout=10)
        except Exception:
            pass
    shutil.rmtree(TMP, ignore_errors=True)


atexit.register(_cleanup)


def _start_server():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=2)
        sys.exit(f"port {PORT} is already in use; set KALECAM_TEST_PORT to a free port")
    except urllib.error.URLError:
        pass
    log = open(TMP / "server.log", "ab")
    pr = subprocess.Popen([sys.executable, str(CODE / "server.py")], cwd=HOME, stdout=log, stderr=subprocess.STDOUT,
                          env={**os.environ, "KALECAM_HOME": str(HOME)}, start_new_session=True)
    PROCS.append(pr)
    for _ in range(60):
        time.sleep(0.25)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=2) as r:
                return json.loads(r.read())["instance"]
        except Exception:
            pass
    sys.exit("test server did not start: " + (TMP / "server.log").read_text()[-800:])


def _start_tunnel(instance):
    import watchdog as W  # KALECAM_HOME is the temp dir, so its paths are the temp ones
    live_bin = CODE / "bin" / "cloudflared"
    if live_bin.exists():
        W.K.BIN.mkdir(parents=True, exist_ok=True)
        (W.K.BIN / "cloudflared").symlink_to(live_bin)
    if not W.ensure_cloudflared(cfg):
        sys.exit("no cloudflared available for --public")
    cf_log = TMP / "cloudflared.log"
    pr = subprocess.Popen([str(W.CLOUDFLARED), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
                          stdout=open(cf_log, "ab"), stderr=subprocess.STDOUT, start_new_session=True)
    PROCS.append(pr)
    url = None
    for _ in range(90):
        time.sleep(1)
        txt = cf_log.read_text(errors="replace")
        m = W.URL_RE.search(txt)
        url = m.group(0) if m else None
        if url and "Registered tunnel connection" in txt:
            break
    if not url:
        sys.exit("temporary tunnel did not come up")
    for _ in range(24):
        if W.e2e_ok(url, instance, tries=1, fresh=True):
            return url
        time.sleep(5)
    sys.exit(f"temporary tunnel not reachable: {url}")


INSTANCE = _start_server()
BASES = [f"http://127.0.0.1:{PORT}"] + ([_start_tunnel(INSTANCE)] if "--public" in sys.argv else [])
print(f"isolated test server on :{PORT}, temp photo root under {TMP}")
results = []


def req(base, path, data=None, headers=None, method=None, timeout=40):
    h = {"User-Agent": "kalecam-test", **(headers or {})}
    r = urllib.request.Request(base + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def jpeg(w=1600, h=1200, exif_gps=False):
    im = Image.new("RGB", (w, h), (30, 120, 40))
    for x in range(0, w, 40):
        for y in range(0, h, 40):
            im.putpixel((x, y), (255, 255, 255))
    b = io.BytesIO()
    if exif_gps:
        ex = Image.Exif(); ex[0x010F] = "TestMaker"; ex[0x8825] = {1: "N", 2: (37.0, 1.0, 2.0)}
        im.save(b, "JPEG", quality=90, exif=ex.tobytes())
    else:
        im.save(b, "JPEG", quality=90)
    return b.getvalue()


def multipart(fields, photo):
    bnd = "----kalecam" + uuid.uuid4().hex
    out = b""
    for k, v in fields.items():
        out += f"--{bnd}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    out += f"--{bnd}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"p.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode() + photo + b"\r\n"
    out += f"--{bnd}--\r\n".encode()
    return out, f"multipart/form-data; boundary={bnd}"


for base in BASES:
    tag = "local" if "127.0.0.1" in base else "public"
    A = {"X-Upload-Key": TOKEN}
    s, h, b = req(base, "/healthz"); check(f"[{tag}] healthz", s == 200 and json.loads(b)["app"] == "kalecam")
    s, h, b = req(base, "/config"); check(f"[{tag}] /config without key -> 401", s == 401, s)
    s, h, b = req(base, "/config", headers={"X-Upload-Key": "x" * 43}); check(f"[{tag}] /config wrong key -> 401", s == 401, s)
    s, h, b = req(base, "/config", headers=A); c = json.loads(b)
    check(f"[{tag}] /config with key", s == 200 and "schedule" in c and "version" in c, f"tz={c.get('timezone')} v={c.get('version')}")
    s, h, b = req(base, "/upload", data=b"x", headers={"Content-Type": "image/jpeg"}); check(f"[{tag}] upload without key -> 401", s == 401, s)
    s, h, b = req(base, "/upload", method="OPTIONS", headers={"Origin": "https://other.example", "Access-Control-Request-Method": "POST",
                                                              "Access-Control-Request-Headers": "x-upload-key,x-plant-id"})
    check(f"[{tag}] CORS preflight", s == 204 and h.get("Access-Control-Allow-Origin") == "*" and "X-Upload-Key" in h.get("Access-Control-Allow-Headers", ""), s)
    s, h, b = req(base, "/app"); check(f"[{tag}] GET /app serves page", s == 200 and b"KALE 9000 is watching" in b and "text/html" in h.get("Content-Type", ""))
    s, h, b = req(base, "/app/sw.js"); check(f"[{tag}] sw.js + Service-Worker-Allowed", s == 200 and h.get("Service-Worker-Allowed") == "/app")
    s, h, b = req(base, "/app/manifest.webmanifest"); check(f"[{tag}] manifest", s == 200 and json.loads(b)["start_url"] == "/app")
    # heartbeat
    hb = {"camera": "test-cam", "battery": {"level": 0.81, "charging": True}, "queue": 0, "app_version": "test"}
    s, h, b = req(base, "/heartbeat", data=json.dumps(hb).encode(), headers={**A, "Content-Type": "application/json"})
    saved = K.read_json(K.HB_DIR / "test-cam.json", {})
    check(f"[{tag}] heartbeat stored", s == 200 and saved.get("battery", {}).get("level") == 0.81)
    # raw upload with headers
    pid = str(uuid.uuid4())
    data = jpeg()
    hdr = {**A, "Content-Type": "image/jpeg", "X-Plant-Id": PLANT, "X-Camera": "test-cam", "X-Trigger": "test",
           "X-Captured-At": K.iso(K.now_local()), "X-Photo-Id": pid}
    s, h, b = req(base, "/upload", data=data, headers=hdr); j = json.loads(b)
    f = Path(cfg["photo_root"]) / PLANT / j.get("file", "missing")
    check(f"[{tag}] raw upload stored in layout", s == 200 and f.exists() and j["file"].count("/") == 3 and j["file"].endswith("-test-cam.jpg"), j.get("file"))
    s, h, b = req(base, "/upload", data=data, headers=hdr); j2 = json.loads(b)
    check(f"[{tag}] same photo_id -> duplicate, not stored twice", s == 200 and j2.get("duplicate") is True)
    # multipart with fields + EXIF stripping
    # a fixed-offset timestamp one hour ago (the server rejects >30 days old); expect the bot-local path
    import datetime as _dt
    _cap = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=1)).replace(microsecond=0).astimezone(_dt.timezone(_dt.timedelta(hours=-7)))
    _want = K.to_local(_cap).strftime("%Y/%m/%d/%H%M%S")
    body, ct = multipart({"plant_id": PLANT, "camera": "test-cam", "trigger": "test-mp", "captured_at": _cap.isoformat(),
                          "photo_id": str(uuid.uuid4())}, jpeg(exif_gps=True))
    s, h, b = req(base, "/upload", data=body, headers={**A, "Content-Type": ct}); j = json.loads(b)
    f = Path(cfg["photo_root"]) / PLANT / j.get("file", "missing")
    exif = Image.open(f).getexif() if f.exists() else {"missing": 1}
    check(f"[{tag}] multipart upload + captured_at used for path", s == 200 and j["file"].startswith(_want), j.get("file"))
    check(f"[{tag}] EXIF (GPS/device) stripped", len(exif) == 0, f"exif tags left={len(exif)}")
    idx = [json.loads(l) for l in (Path(cfg["photo_root"]) / PLANT / "index.jsonl").read_text().splitlines()]
    row = [r for r in idx if r["file"] == j["file"]][-1]
    check(f"[{tag}] index.jsonl row", row["trigger"] == "test-mp" and row["source"] == "test-cam" and row["plant"] == PLANT and row["width"] == 1600, {k: row[k] for k in ("ts", "trigger", "bytes", "width", "height")})
    s, h, b = req(base, "/upload", data=b"notajpeg" * 10, headers={**A, "Content-Type": "image/jpeg"}); check(f"[{tag}] non-JPEG -> 422", s == 422, s)
    s, h, b = req(base, "/upload", data=jpeg(), headers={**A, "Content-Type": "image/jpeg", "X-Plant-Id": "../etc"}); check(f"[{tag}] bad plant id -> 400", s == 400, s)
    if tag == "local":
        import http.client
        hc = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
        hc.putrequest("POST", "/upload"); hc.putheader("X-Upload-Key", TOKEN); hc.putheader("Content-Type", "image/jpeg")
        hc.putheader("Content-Length", str(26 * 1024 * 1024)); hc.endheaders()
        s = hc.getresponse().status; hc.close(); check(f"[{tag}] 26 MB declared -> 413 before reading body", s == 413, s)
    # long-poll: empty hold
    t0 = time.time(); s, h, b = req(base, "/poll?camera=test-cam&hold=6", headers=A); dt = time.time() - t0
    check(f"[{tag}] long-poll holds when idle", s == 200 and json.loads(b)["cmd"] is None and 5.5 < dt < 12, f"{dt:.1f}s")
    # long-poll: command arrives mid-hold, then complete it with an upload
    got = {}
    def poller():
        t = time.time(); st, _, bb = req(base, "/poll?camera=test-cam&hold=20", headers=A); got.update(json.loads(bb)); got["dt"] = time.time() - t
    th = threading.Thread(target=poller); th.start(); time.sleep(2)
    c = K.queue_command("test-cam", "capture", {}, PLANT); th.join()
    check(f"[{tag}] command delivered via long-poll immediately", got.get("id") == c["id"] and got.get("cmd") == "capture" and got["dt"] < 6, f"{got.get('dt', 0):.1f}s")
    s, h, b = req(base, "/upload", data=jpeg(), headers={**A, "Content-Type": "image/jpeg", "X-Camera": "test-cam", "X-Cmd-Id": c["id"],
                                                          "X-Trigger": "command", "X-Photo-Id": str(uuid.uuid4())})
    st, cc = K.command_status(c["id"])
    check(f"[{tag}] command marked done with file path", st == "done" and cc.get("file", "").startswith(cfg["photo_root"]), cc.get("file"))

    if tag == "local":
        # a command handed to a poll whose page then died is handed ONCE to the next poll
        g1, g2 = {}, {}
        def p1():
            st, _, bb = req(base, "/poll?camera=test-cam&hold=4", headers=A); g1.update(json.loads(bb))
        th = threading.Thread(target=p1); th.start(); time.sleep(1)
        c = K.queue_command("test-cam", "capture", {}, PLANT); th.join()
        t = time.time(); st, _, bb = req(base, "/poll?camera=test-cam&hold=20", headers=A); g2.update(json.loads(bb)); d2 = time.time() - t
        check(f"[{tag}] lost delivery handed once to the next poll", g1.get("id") == c["id"] and g2.get("id") == c["id"] and d2 < 15, f"{d2:.1f}s")
        t = time.time(); st, _, bb = req(base, "/poll?camera=test-cam&hold=10", headers=A); g3 = json.loads(bb); d3 = time.time() - t
        check(f"[{tag}] ...but only once", g3.get("cmd") is None and d3 > 9, f"{d3:.1f}s")
        s, h, b = req(base, "/upload", data=jpeg(), headers={**A, "Content-Type": "image/jpeg", "X-Camera": "test-cam", "X-Cmd-Id": c["id"],
                                                              "X-Trigger": "command", "X-Photo-Id": str(uuid.uuid4())})
        check(f"[{tag}] redelivered command completes", K.command_status(c["id"])[0] == "done")

ok = sum(1 for r in results if r[1]); print(f"\n{ok}/{len(results)} passed")
out = CODE / "test-results"; out.mkdir(exist_ok=True)
(out / "server-tests.json").write_text(json.dumps([{"test": n, "pass": p, "detail": str(d)} for n, p, d in results], indent=1))
sys.exit(0 if ok == len(results) else 1)
