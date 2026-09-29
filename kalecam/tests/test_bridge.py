#!/usr/bin/env python3
"""Device-bridge API tests (stdlib unittest) with a fake bridge client.

Starts its OWN server.py on a different port (default 18766) with KALECAM_HOME pointing at a
throwaway temp directory, so the live server (8765), live state, photos and secrets are untouched.

  venv/bin/python tests/test_bridge.py            [-v]
  KALECAM_TEST_PORT=18777 KALECAM_TEST_SERVER=/path/server.py venv/bin/python tests/test_bridge.py

Never prints the bridge key; the last test asserts it never reaches logs/state/CLI output.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("KALECAM_TEST_PORT", "18766"))
SERVER = os.environ.get("KALECAM_TEST_SERVER", str(CODE / "server.py"))
assert PORT != 8765, "never test against the live port"
HOME = Path(tempfile.mkdtemp(prefix="kalecam-bridge-test-"))
os.environ["KALECAM_HOME"] = str(HOME)
sys.path.insert(0, str(CODE))
import kalecam_lib as K  # noqa: E402  (after KALECAM_HOME is set)
import bridge_lib as B  # noqa: E402

BASE_URL = f"http://127.0.0.1:{PORT}"
OUTPUTS: list[str] = []  # every CLI/server output, scanned for the key at the end


def cli(*args, timeout=60) -> subprocess.CompletedProcess:
    r = subprocess.run([sys.executable, str(CODE / "kalecam_cli.py"), *args], capture_output=True, text=True,
                       timeout=timeout, env={**os.environ, "KALECAM_HOME": str(HOME)})
    OUTPUTS.append(r.stdout + r.stderr)
    return r


def http(method, path, body=None, headers=None, timeout=40):
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    h = {"User-Agent": "fake-bridge/0.1", **({"Content-Type": "application/json"} if data is not None else {}),
         **(headers or {})}
    req = urllib.request.Request(BASE_URL + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, dict(r.headers), (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, dict(e.headers), json.loads(raw)
        except ValueError:
            return e.code, dict(e.headers), raw


class FakeBridge:
    """Minimal stand-in for the home bridge: speaks exactly the handoff protocol."""

    def __init__(self, key: str, bridge_id: str = "bridge-1"):
        self.key, self.id = key, bridge_id
        self.h = {"X-Bridge-Key": key}

    def poll(self, hold=None, timeout=40):
        q = f"/bridge/poll?bridge={self.id}" + ("" if hold is None else f"&hold={hold}")
        return http("GET", q, headers=self.h, timeout=timeout)

    def result(self, cid, status="done", state="on", error=None):
        return http("POST", "/bridge/result", {"id": cid, "status": status, "state": state, "error": error,
                                               "at": dt.datetime.now().astimezone().isoformat(timespec="seconds")},
                    headers=self.h)

    def heartbeat(self, devices=None, holds=None, fallback_active=False, uptime_s=42):
        return http("POST", "/bridge/heartbeat", {"bridge": self.id, "version": "0.1",
                                                  "devices": devices or {"light": "off", "fan": "on"},
                                                  "holds": holds or {"light": False, "fan": True},
                                                  "fallback_active": fallback_active, "uptime_s": uptime_s},
                    headers=self.h)

    def config(self):
        return http("GET", "/bridge/config", headers=self.h)


class BridgeAPITest(unittest.TestCase):
    proc = None

    @classmethod
    def setUpClass(cls):
        (HOME / "photos").mkdir(parents=True)
        cfg = dict(K.DEFAULT_CONFIG, port=PORT, photo_root=str(HOME / "photos"), rendezvous=[],
                   bridge={"public_base_url": BASE_URL, "redeliver_after_s": 2})
        K.write_json_atomic(K.CONFIG_PATH, cfg)
        K.ensure_dirs()
        cls.phone_token = K.auth_token(K.ensure_pairing(K.load_config())[0])  # phone pairing, for regression checks
        r = cli("bridge", "pair", "--bridge-id", "bridge-1")
        assert r.returncode == 0, r.stderr
        cls.pair_out = r.stdout
        cls.key = B.load_key()["key"]
        cls.slog = open(HOME / "test-server.log", "wb")
        cls.proc = subprocess.Popen([sys.executable, SERVER], env={**os.environ, "PORT": str(PORT), "KALECAM_HOME": str(HOME)},
                                    stdout=cls.slog, stderr=subprocess.STDOUT)
        for _ in range(60):
            try:
                if http("GET", "/healthz", timeout=2)[0] == 200:
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        else:
            raise RuntimeError("test server did not start")
        cls.fb = FakeBridge(cls.key)

    @classmethod
    def tearDownClass(cls):
        if cls.proc:
            cls.proc.terminate()
            cls.proc.wait(10)
        cls.slog.close()
        if os.environ.get("KALECAM_TEST_KEEP") != "1":
            shutil.rmtree(HOME, ignore_errors=True)

    def setUp(self):
        for st in ("pending", "delivered"):
            for p in (B.BCMD_DIR / st).glob("*.json"):
                p.unlink()

    def send(self, *args):
        r = cli("bridge", "send", *args)
        out = [json.loads(line) for line in r.stdout.splitlines() if line.strip().startswith("{")]
        return r, out

    # ---------------------------------------------------------------- pairing
    def test_00_pairing_file(self):
        self.assertIn(str(B.PAIRING_TXT), self.pair_out)
        self.assertIn("fingerprint", self.pair_out)
        self.assertNotIn(self.key, self.pair_out)
        for p in (B.PAIRING_TXT, B.KEY_PATH):
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600, p)
        blob = json.loads(base64.b64decode(B.PAIRING_TXT.read_text().strip()))
        self.assertEqual(set(blob), {"url", "key", "bridge_id"})
        self.assertEqual(blob["url"], BASE_URL)  # public_base_url wins over the quick-tunnel URL
        self.assertEqual(blob["bridge_id"], "bridge-1")
        self.assertEqual(blob["key"], self.key)
        r = cli("bridge", "pair")  # idempotent: same key
        self.assertEqual(r.returncode, 0)
        self.assertEqual(B.load_key()["key"], self.key)
        self.assertIn("existing key", r.stdout)

    # ---------------------------------------------------------------- auth
    def test_01_auth_reject(self):
        cases = [("GET", "/bridge/config", None), ("GET", "/bridge/poll?bridge=bridge-1&hold=0", None),
                 ("POST", "/bridge/heartbeat", {"bridge": "bridge-1"}), ("POST", "/bridge/result", {"id": "x", "status": "done"})]
        for method, path, body in cases:
            for hdr in ({}, {"X-Bridge-Key": "wrong"}, {"X-Bridge-Key": self.key[:-1] + ("A" if self.key[-1] != "A" else "B")},
                        {"X-Bridge-Key": self.phone_token}, {"X-Upload-Key": self.key}, {"X-Upload-Key": self.phone_token}):
                s, _, b = http(method, path, body, headers=hdr)
                self.assertEqual(s, 401, (method, path, list(hdr)))
        # and the bridge key does not open the phone endpoints
        self.assertEqual(http("GET", "/config", headers={"X-Upload-Key": self.key})[0], 401)
        self.assertEqual(http("GET", "/poll?camera=x&hold=0", headers={"X-Bridge-Key": self.key})[0], 401)

    def test_02_config_fetch(self):
        s, h, c = self.fb.config()
        self.assertEqual(s, 200)
        self.assertIsNone(c["fallback"]["light"])
        self.assertEqual(c["fallback"]["fan"], {"on_min": 15, "off_min": 15})
        self.assertEqual(c["fallback"]["pump"], "off")
        self.assertIs(c["pump_enabled"], False)
        self.assertEqual(c["max_duration_s"], {"light": 64800, "fan": 3600, "pump": 0})
        self.assertEqual(c["offline_threshold_s"], 600)
        self.assertEqual(c["timezone"], K.detect_timezone() or "UTC")
        self.assertEqual(c["aliases"], ["light", "fan", "pump"])
        self.assertTrue(c["version"])
        self.assertIsNotNone(dt.datetime.fromisoformat(c["server_time"]).utcoffset())

    def test_03_config_cli_set_persists(self):
        v0 = self.fb.config()[2]["version"]
        r = cli("bridge", "config", "set", "fallback.light", "06:00-22:00")
        self.assertEqual(r.returncode, 0, r.stderr)
        c = self.fb.config()[2]
        self.assertEqual(c["fallback"]["light"], {"on": "06:00", "off": "22:00"})
        self.assertNotEqual(c["version"], v0)
        self.assertEqual(K.read_json(K.CONFIG_PATH)["bridge"]["fallback"]["light"], {"on": "06:00", "off": "22:00"})
        self.assertEqual(c["fallback"]["fan"], {"on_min": 15, "off_min": 15})  # siblings untouched
        for bad in (("fallback.pump", "on"), ("fallback.light", "25:00-06:00"), ("nonsense", "1"),
                    ("max_duration_s.fan", "-5"), ("pump_enabled", "maybe"), ("poll_hold_s", "90")):
            self.assertNotEqual(cli("bridge", "config", "set", *bad).returncode, 0, bad)
        self.assertEqual(cli("bridge", "config", "set", "fallback.light", "null").returncode, 0)
        c = self.fb.config()[2]
        self.assertIsNone(c["fallback"]["light"])
        self.assertEqual(c["version"], v0)
        self.assertIn('"light": null', cli("bridge", "config", "show").stdout)

    # ---------------------------------------------------------------- long-poll
    def test_04_longpoll_timeout_returns_empty(self):
        t = time.time()
        s, h, b = self.fb.poll(hold=3)
        self.assertEqual((s, b), (200, []))
        self.assertTrue(2.5 < time.time() - t < 6, time.time() - t)
        self.assertIn("X-Bridge-Config-Version", h)

    def test_05_longpoll_default_hold_about_25s(self):
        t = time.time()
        s, _, b = self.fb.poll(timeout=40)
        el = time.time() - t
        self.assertEqual((s, b), (200, []))
        self.assertTrue(24 <= el < 29, el)

    def test_06_poll_needs_bridge_id(self):
        self.assertEqual(http("GET", "/bridge/poll?hold=0", headers=self.fb.h)[0], 400)
        self.assertEqual(http("GET", "/bridge/poll?bridge=../x&hold=0", headers=self.fb.h)[0], 400)

    # ---------------------------------------------------------------- delivery
    def test_07_command_delivery(self):
        got = {}

        def poller():
            t = time.time()
            got["resp"] = self.fb.poll(hold=20)
            got["dt"] = time.time() - t
        th = threading.Thread(target=poller)
        th.start()
        time.sleep(1.5)
        r, out = self.send("fan", "on", "--duration", "900")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        th.join()
        s, _, cmds = got["resp"]
        self.assertEqual(s, 200)
        self.assertLess(got["dt"], 5, "should return as soon as a command is queued")
        self.assertEqual(len(cmds), 1)
        c = cmds[0]
        self.assertEqual(set(c), {"id", "device", "action", "duration_s", "expires_at"})
        self.assertEqual((c["id"], c["device"], c["action"], c["duration_s"]), (out[0]["queued"], "fan", "on", 900))
        exp = dt.datetime.fromisoformat(c["expires_at"])
        from zoneinfo import ZoneInfo
        self.assertEqual(exp.utcoffset(), dt.datetime.now(ZoneInfo(K.detect_timezone() or "UTC")).utcoffset())
        self.assertTrue(250 < exp.timestamp() - time.time() <= 300)  # default 5 min
        self.assertEqual(B.command_status(c["id"])[0], "delivered")
        self.assertEqual(self.fb.poll(hold=0)[2], [])  # not handed out twice right away

    def test_08_no_duration_key_when_absent_and_state_action(self):
        self.send("light", "state")
        cmds = self.fb.poll(hold=2)[2]
        self.assertEqual(len(cmds), 1)
        self.assertEqual(set(cmds[0]), {"id", "device", "action", "expires_at"})
        self.assertEqual(cmds[0]["action"], "state")

    def test_09_bridge_targeting(self):
        self.send("fan", "off", "--bridge", "other-bridge")
        self.assertEqual(self.fb.poll(hold=1)[2], [])
        cmds = FakeBridge(self.key, "other-bridge").poll(hold=1)[2]
        self.assertEqual(len(cmds), 1)

    def test_10_redeliver_without_result(self):
        _, out = self.send("fan", "off")
        cid = out[0]["queued"]
        self.assertEqual([c["id"] for c in self.fb.poll(hold=1)[2]], [cid])
        time.sleep(2.6)  # redeliver_after_s = 2 in the test config
        self.assertEqual([c["id"] for c in self.fb.poll(hold=1)[2]], [cid])
        self.assertEqual(B.command_status(cid)[1]["attempts"], 2)

    # ---------------------------------------------------------------- results
    def test_11_result_roundtrip(self):
        _, out = self.send("light", "on")
        cid = out[0]["queued"]
        self.fb.poll(hold=1)
        s, _, b = self.fb.result(cid, "done", "on")
        self.assertEqual((s, b["ok"], b["status"]), (200, True, "done"))
        st, c = B.command_status(cid)
        self.assertEqual((st, c["status"], c["result"]["state"], c["closed_by"]), ("done", "done", "on", "bridge"))
        s, _, b = self.fb.result(cid, "failed", "off")
        self.assertEqual((s, b.get("duplicate")), (200, True))  # first result wins
        self.assertEqual(B.command_status(cid)[1]["status"], "done")
        self.assertEqual(self.fb.result("b00000000000000abcdef")[0], 404)
        self.assertEqual(http("POST", "/bridge/result", {"id": cid, "status": "bogus"}, headers=self.fb.h)[0], 400)
        self.assertEqual(http("POST", "/bridge/result", b"not json", headers=self.fb.h)[0], 400)

    def test_12_send_wait_prints_result(self):
        p = subprocess.Popen([sys.executable, str(CODE / "kalecam_cli.py"), "bridge", "send", "fan", "on", "--wait", "20"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={**os.environ, "KALECAM_HOME": str(HOME)})
        cmds = self.fb.poll(hold=10)[2]
        self.assertEqual(len(cmds), 1)
        self.assertEqual(self.fb.result(cmds[0]["id"], "held", "off", "manual hold on fan")[0], 200)
        so, se = p.communicate(timeout=30)
        OUTPUTS.append(so + se)
        lines = [json.loads(line) for line in so.splitlines()]
        self.assertEqual(lines[-1]["status"], "held")
        self.assertEqual(lines[-1]["state"], "off")
        self.assertEqual(lines[-1]["error"], "manual hold on fan")
        self.assertEqual(p.returncode, 1)  # non-"done" result -> exit 1

    # ---------------------------------------------------------------- expiry
    def test_13_expired_not_delivered(self):
        _, out = self.send("fan", "on", "--expires", "1")
        cid = out[0]["queued"]
        time.sleep(1.5)
        self.assertEqual(self.fb.poll(hold=1)[2], [])
        st, c = B.command_status(cid)
        self.assertEqual((st, c["status"], c["closed_by"]), ("done", "expired", "server"))

    def test_14_expired_reported_by_bridge_and_late_result(self):
        _, out = self.send("fan", "off", "--expires", "2")
        cid = out[0]["queued"]
        self.fb.poll(hold=1)
        s, _, _ = self.fb.result(cid, "expired", None)
        self.assertEqual(s, 200)
        self.assertEqual(B.command_status(cid)[1]["status"], "expired")
        # delivered, then server expires it for lack of a result; a late bridge result still wins
        _, out = self.send("fan", "off", "--expires", "1")
        cid = out[0]["queued"]
        self.fb.poll(hold=0)
        time.sleep(1.3)
        self.fb.poll(hold=0)  # triggers maintenance
        self.assertEqual(B.command_status(cid)[1]["status"], "expired")
        self.assertEqual(self.fb.result(cid, "done", "off")[0], 200)
        c = B.command_status(cid)[1]
        self.assertEqual((c["status"], c["server_status"]), ("done", "expired"))

    # ---------------------------------------------------------------- validation
    def test_15_pump_rejected_while_disabled(self):
        for args in (("pump", "on"), ("pump", "off"), ("pump", "state"), ("pump", "on", "--duration", "10")):
            r, out = self.send(*args)
            self.assertEqual(r.returncode, 3, args)
            self.assertIn("pump", out[0]["rejected"])
        self.assertEqual(list((B.BCMD_DIR / "pending").glob("*.json")), [])
        with self.assertRaises(ValueError):
            B.queue("pump", "on")
        # enabled -> queued; disabled again before delivery -> rejected at delivery, never sent
        self.assertEqual(cli("bridge", "config", "set", "pump_enabled", "true").returncode, 0)
        r, out = self.send("pump", "off")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(cli("bridge", "config", "set", "pump_enabled", "false").returncode, 0)
        self.assertEqual(self.fb.poll(hold=1)[2], [])
        c = B.command_status(out[0]["queued"])[1]
        self.assertEqual(c["status"], "rejected")

    def test_16_unknown_alias_and_bad_action(self):
        for args in (("heater", "on"), ("door", "off"), ("fan", "toggle"), ("fan", "off", "--duration", "5"),
                     ("fan", "on", "--duration", "0")):
            r, out = self.send(*args)
            self.assertEqual(r.returncode, 3, args)
        self.assertEqual(list((B.BCMD_DIR / "pending").glob("*.json")), [])

    def test_17_duration_cap(self):
        r, out = self.send("fan", "on", "--duration", "99999")
        self.assertEqual(r.returncode, 0)
        self.assertEqual((out[0]["duration_s"], out[0]["duration_capped_from"]), (3600, 99999))
        r, out = self.send("light", "on", "--duration", "100000")
        self.assertEqual(out[0]["duration_s"], 64800)
        cmds = {c["device"]: c for c in self.fb.poll(hold=1)[2]}
        self.assertEqual(cmds["fan"]["duration_s"], 3600)
        self.assertEqual(cmds["light"]["duration_s"], 64800)
        r, out = self.send("fan", "on", "--expires", "999999")
        exp = dt.datetime.fromisoformat(out[0]["expires_at"]).timestamp()
        self.assertLessEqual(exp - time.time(), 3600 + 2)  # max_expires_s

    # ---------------------------------------------------------------- heartbeat + status
    def test_18_heartbeat_storage_and_status(self):
        s, _, b = self.fb.heartbeat(devices={"light": "off", "fan": "on"}, holds={"light": False, "fan": True},
                                    fallback_active=True, uptime_s=3600)
        self.assertEqual(s, 200)
        self.assertEqual(b["config_version"], self.fb.config()[2]["version"])
        hb = K.read_json(B.BHB_DIR / "bridge-1.json")
        self.assertEqual(hb["devices"], {"light": "off", "fan": "on"})
        self.assertEqual(hb["holds"], {"light": False, "fan": True})
        self.assertIs(hb["fallback_active"], True)
        self.assertEqual((hb["uptime_s"], hb["version"]), (3600, "0.1"))
        self.assertLess(time.time() - hb["received_ts"], 5)
        self.assertIn('"event":"heartbeat"', B.BLOG.read_text())
        out = cli("bridge", "status").stdout
        self.assertIn("bridge bridge-1: ONLINE", out)
        self.assertIn('"fan": true', out)
        self.assertIn("fallback_active True", out)
        j = json.loads(cli("bridge", "status", "--json").stdout)
        self.assertTrue(j["bridges"]["bridge-1"]["online"])
        self.assertEqual(http("POST", "/bridge/heartbeat", {"bridge": ""}, headers=self.fb.h)[0], 400)
        self.assertEqual(http("POST", "/bridge/heartbeat", b"x" * 70000, headers=self.fb.h)[0], 413)

    def test_19_phone_endpoints_unaffected(self):
        A = {"X-Upload-Key": self.phone_token}
        self.assertEqual(http("GET", "/config", headers=A)[0], 200)
        self.assertEqual(http("POST", "/heartbeat", {"camera": "test-cam", "queue": 0}, headers=A)[0], 200)
        s, _, b = http("GET", "/poll?camera=test-cam&hold=1", headers=A)
        self.assertEqual((s, b["cmd"]), (200, None))
        self.assertEqual(http("GET", "/app")[0] in (200, 404), True)

    def test_99_key_never_leaks(self):
        self.slog.flush()
        texts = {"server log": (HOME / "test-server.log").read_text(errors="replace"), "cli output": "\n".join(OUTPUTS),
                 "config.json": K.CONFIG_PATH.read_text()}
        for p in (HOME / "state").rglob("*"):
            if p.is_file():
                texts[str(p)] = p.read_text(errors="replace")
        for name, t in texts.items():
            self.assertNotIn(self.key, t, name)
        log = [json.loads(line) for line in B.BLOG.read_text().splitlines()]
        events = {r["event"] for r in log}
        self.assertTrue({"queued", "delivered", "result", "heartbeat", "expired"} <= events, events)


if __name__ == "__main__":
    unittest.main(verbosity=2)
