#!/usr/bin/env python3
"""End-to-end: the real bot server (kalecam/server.py) on a SPARE port with a throwaway KALECAM_HOME,
the reference bridge as a subprocess with a throwaway KALEBRIDGE_HOME, fake plugs/sensors on
127.0.0.1, and fake ntfy/textdb relays (the bot's real publisher writes to them).

    python3 tests/test_integration.py -v
    KALECAM_CODE=/path/to/kalecam KB_TEST_PORT=18791 python3 tests/test_integration.py

Never touches the live server (8765), live state, secrets or photos. The bridge runs with
KALEBRIDGE_PURE_AES=1 so the stdlib-only AES-GCM path is what gets exercised.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

REF = Path(__file__).resolve().parents[1]
CAPTURE = Path(os.environ.get("KALECAM_CODE", REF.parent / "kalecam"))
sys.path.insert(0, str(REF))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import FakeRelay, FakeSensor, FakeShellyGen1, FakeShellyGen2, FakeTasmota  # noqa: E402

PORT = int(os.environ.get("KB_TEST_PORT", "18791"))
PORT2 = PORT + 1
assert 8765 not in (PORT, PORT2), "never test against the live port"
BOTPY = str(CAPTURE / "venv" / "bin" / "python") if (CAPTURE / "venv" / "bin" / "python").exists() else sys.executable
TMP = Path(tempfile.mkdtemp(prefix="kb-integ-"))
KHOME = TMP / "kalecam-home"
BHOME = TMP / "bridge-home"
BLOG = TMP / "bridge.log"
OUTPUTS: list = []
LIGHT_PW = "light-digest-pw-9d1"
FAN_PW = "tasmota-pw-44x"


def wait_for(pred, timeout=20.0, step=0.25, msg="condition"):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = pred()
            if last:
                return last
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(step)
    raise AssertionError(f"timed out waiting for {msg} (last={last!r})")


def kalecam(*args, timeout=60):
    r = subprocess.run([BOTPY, str(CAPTURE / "kalecam_cli.py"), *args], capture_output=True, text=True,
                       timeout=timeout, env={**os.environ, "KALECAM_HOME": str(KHOME)})
    OUTPUTS.append(r.stdout + r.stderr)
    return r


def kb(*args, stdin=None, timeout=60):
    r = subprocess.run([sys.executable, str(REF / "kalebridge.py"), *args], capture_output=True, text=True,
                       input=stdin, timeout=timeout,
                       env={**os.environ, "KALEBRIDGE_HOME": str(BHOME), "KALEBRIDGE_PURE_AES": "1"})
    OUTPUTS.append(r.stdout + r.stderr)
    return r


def send(device, action, duration=None, wait=25):
    args = ["bridge", "send", device, action, "--wait", str(wait)]
    if duration:
        args += ["--duration", str(duration)]
    r = kalecam(*args, timeout=wait + 20)
    lines = [json.loads(x) for x in r.stdout.splitlines() if x.startswith("{")]
    return lines[-1] if lines else {"raw": r.stdout + r.stderr}


def server_hb():
    p = KHOME / "state" / "bridge" / "heartbeats" / "ref-1.json"
    return json.loads(p.read_text()) if p.exists() else None


def bstate():
    return json.loads((BHOME / "state.json").read_text())


def cmd_record(cid):
    for st in ("done", "delivered", "pending"):
        p = KHOME / "state" / "bridge" / "commands" / st / f"{cid}.json"
        if p.exists():
            return st, json.loads(p.read_text())
    return None, None


def local_hhmm(delta_min):
    from zoneinfo import ZoneInfo
    return (dt.datetime.now(ZoneInfo("America/New_York")) + dt.timedelta(minutes=delta_min)).strftime("%H:%M")


class Integration(unittest.TestCase):
    server = None
    bridge = None

    # ------------------------------------------------------------ fixtures
    @classmethod
    def start_server(cls, port):
        cls.stop_server()
        cls.server = subprocess.Popen([BOTPY, str(CAPTURE / "server.py")],
                                      env={**os.environ, "PORT": str(port), "KALECAM_HOME": str(KHOME)},
                                      stdout=open(TMP / f"server-{port}.log", "ab"), stderr=subprocess.STDOUT)
        wait_for(lambda: json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2).read())["ok"],
                 15, msg=f"server on {port}")

    @classmethod
    def stop_server(cls):
        if cls.server and cls.server.poll() is None:
            cls.server.terminate()
            cls.server.wait(10)
        cls.server = None

    @classmethod
    def start_bridge(cls):
        cls.bridge = subprocess.Popen([sys.executable, str(REF / "kalebridge.py"), "run", "-v"],
                                      env={**os.environ, "KALEBRIDGE_HOME": str(BHOME), "KALEBRIDGE_PURE_AES": "1"},
                                      stdout=open(BLOG, "ab"), stderr=subprocess.STDOUT)

    @classmethod
    def kill_bridge(cls, sig=signal.SIGKILL):
        if cls.bridge and cls.bridge.poll() is None:
            cls.bridge.send_signal(sig)
            cls.bridge.wait(10)
        cls.bridge = None

    @classmethod
    def setUpClass(cls):
        cls.light = FakeShellyGen2(password=LIGHT_PW)
        cls.fan = FakeTasmota(user="admin", password=FAN_PW)
        cls.pump = FakeShellyGen1()
        cls.s_float, cls.s_leak, cls.s_soil = FakeSensor("ok"), FakeSensor("dry"), FakeSensor(20)
        cls.ntfy, cls.textdb = FakeRelay("ntfy"), FakeRelay("textdb")
        KHOME.mkdir(parents=True)
        (KHOME / "config.json").write_text(json.dumps({
            "port": PORT, "photo_root": str(TMP / "photos"), "timezone": "America/New_York",
            "rendezvous": [{"type": "ntfy", "base": cls.ntfy.url}, {"type": "textdb", "base": cls.textdb.url}],
            "bridge": {"public_base_url": f"http://127.0.0.1:{PORT}"}}))
        cls.start_server(PORT)

    @classmethod
    def tearDownClass(cls):
        cls.kill_bridge(signal.SIGTERM)
        cls.stop_server()
        for f in (cls.light, cls.fan, cls.pump, cls.s_float, cls.s_leak, cls.s_soil, cls.ntfy, cls.textdb):
            f.close()
        if os.environ.get("KB_KEEP_TMP") != "1":
            shutil.rmtree(TMP, ignore_errors=True)
        else:
            print(f"\nkept {TMP}", file=sys.stderr)

    def write_aliases(self, pump=None, policy=None):
        a = {"light": {"driver": "shelly_gen2", "host": self.light.host, "password": LIGHT_PW},
             "fan": {"driver": "tasmota", "host": self.fan.host, "password": FAN_PW},
             "pump": pump,
             "pump_policy": policy or {"enabled": False, "max_run_s": 4, "max_daily_s": 60, "min_interval_s": 0,
                                       "sensors": {"float": None, "leak": None, "soil": None}}}
        p = BHOME / "aliases.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(a, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
        time.sleep(1.5)  # the service reloads aliases.json on its next tick

    def sensors(self):
        return {"float": {"type": "http_json", "url": self.s_float.url, "path": "reading.value", "ok_when": "ok"},
                "leak": {"type": "http_json", "url": self.s_leak.url, "path": "reading.value", "ok_when": "dry"},
                "soil": {"type": "http_json", "url": self.s_soil.url, "path": "reading.value", "ok_below": 35}}

    # ------------------------------------------------------------ tests (run in order)
    def test_01_pairing(self):
        r = kalecam("bridge", "pair", "--bridge-id", "ref-1")
        self.assertEqual(r.returncode, 0, r.stderr)
        blob = (KHOME / "secrets" / "bridge-pairing.txt").read_text().strip()
        type(self).key = json.loads(__import__("base64").b64decode(blob))["key"]
        self.assertIn("rv", json.loads(__import__("base64").b64decode(blob)))
        self.assertNotEqual(kb("pair", "bm90IGEgYmxvYg==").returncode, 0)  # garbage rejected
        # the blob's URL is http://127.0.0.1 (test only): refused until allowed
        r = kb("pair", "-", stdin=blob)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("https", r.stderr)
        for k, v in (("allow_http_urls", "true"), ("heartbeat_s", "2"), ("offline_threshold_s", "15"),
                     ("state_poll_s", "1"), ("poll_hold_s", "2"), ("backoff_max_s", "2"),
                     ("rendezvous_min_interval_s", "2"), ("hold_max_s", "8"), ("request_timeout_s", "5")):
            self.assertEqual(kb("config", "set", k, v).returncode, 0)
        r = kb("pair", "-", "--check", stdin=blob)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("fingerprint sha256:", r.stdout)
        self.assertIn("check: OK", r.stdout)
        self.assertEqual(stat.S_IMODE((BHOME / "config.json").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((BHOME / "aliases.json").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(BHOME.stat().st_mode), 0o700)
        al = json.loads((BHOME / "aliases.json").read_text())
        self.assertEqual((al["light"], al["fan"], al["pump"]), (None, None, None))
        # same fingerprint on both sides
        self.assertIn(r.stdout.split("fingerprint ")[1].split()[0], kalecam("bridge", "status").stdout)

    def test_02_start_and_heartbeat(self):
        self.write_aliases()
        self.start_bridge()
        hb = wait_for(lambda: (server_hb() or {}).get("devices") == {"light": "off", "fan": "off"} and server_hb(),
                      20, msg="first heartbeat with bound devices")
        self.assertEqual(hb["holds"], {"light": False, "fan": False})
        self.assertFalse(hb["fallback_active"])
        self.assertEqual(hb["version"], "0.1.0")
        self.assertTrue((BHOME / "config-cache.json").exists())

    def test_03_poll_and_result(self):
        r = send("fan", "on")
        self.assertEqual((r.get("status"), r.get("state")), ("done", "on"), r)
        self.assertTrue(self.fan.on[0])
        st, rec = cmd_record(r["id"])
        self.assertEqual((st, rec["closed_by"]), ("done", "bridge"))
        type(self).fan_cmd = r["id"]
        r = send("light", "state")
        self.assertEqual((r.get("status"), r.get("state")), ("done", "off"), r)

    def test_04_unbound_alias(self):
        self.assertEqual(kalecam("bridge", "config", "set", "pump_enabled", "true").returncode, 0)
        self.assertEqual(kalecam("bridge", "config", "set", "max_duration_s.pump", "30").returncode, 0)
        r = send("pump", "on", duration=5)
        self.assertEqual(r.get("status"), "failed", r)
        self.assertIn("not bound", r.get("error") or "")
        self.assertEqual(self.pump.set_calls, 0)

    def test_05_expired(self):
        now = time.time()
        cid = "b" + time.strftime("%Y%m%d%H%M%S") + "e0e0e0"
        past = dt.datetime.fromtimestamp(now - 30).astimezone().isoformat(timespec="seconds")
        c = {"id": cid, "bridge": "*", "device": "fan", "action": "off", "expires_at": past, "expires_ts": now + 300,
             "created_at": past, "created_ts": now, "source": "test", "attempts": 0, "status": "pending"}
        calls = self.fan.set_calls
        (KHOME / "state" / "bridge" / "commands" / "pending" / f"{cid}.json").write_text(json.dumps(c))
        rec = wait_for(lambda: cmd_record(cid)[0] == "done" and cmd_record(cid)[1], 15, msg="expired result")
        self.assertEqual((rec["status"], rec["closed_by"]), ("expired", "bridge"))
        self.assertEqual(self.fan.set_calls, calls)
        self.assertTrue(self.fan.on[0])

    def test_06_idempotency(self):
        cid = self.fan_cmd
        st, rec = cmd_record(cid)
        calls = self.fan.set_calls
        rec.update({"status": "pending", "expires_ts": time.time() + 300,
                    "expires_at": dt.datetime.fromtimestamp(time.time() + 300).astimezone().isoformat(timespec="seconds")})
        for k in ("result", "closed_by", "finished_at", "error"):
            rec.pop(k, None)
        (KHOME / "state" / "bridge" / "commands" / "done" / f"{cid}.json").unlink()
        (KHOME / "state" / "bridge" / "commands" / "pending" / f"{cid}.json").write_text(json.dumps(rec))
        rec2 = wait_for(lambda: cmd_record(cid)[0] == "done" and cmd_record(cid)[1], 15, msg="re-sent result")
        self.assertEqual((rec2["status"], rec2["closed_by"], rec2["result"]["state"]), ("done", "bridge", "on"))
        self.assertEqual(self.fan.set_calls, calls, "a repeated id must not switch again")
        self.assertIn("already executed", BLOG.read_text())

    def test_07_duration_timer_survives_restart(self):
        r = send("light", "on", duration=6)
        self.assertEqual((r.get("status"), r.get("state")), ("done", "on"), r)
        self.kill_bridge(signal.SIGKILL)
        t = bstate()["timers"]["light"]
        self.assertEqual(t["cmd_id"], r["id"])
        wait_for(lambda: time.time() > t["off_ts"] + 1, 10, msg="timer due")
        self.assertTrue(self.light.on[0], "nobody turned it off while the bridge was down")
        self.start_bridge()
        wait_for(lambda: not self.light.on[0], 10, msg="light off after restart")
        wait_for(lambda: "light" not in bstate()["timers"], 5, msg="timer cleared")

    def test_08_manual_change_hold(self):
        wait_for(lambda: server_hb() and server_hb()["devices"].get("light") == "off", 10, msg="hb light off")
        self.light.on[0] = True  # someone pressed the button on the plug
        wait_for(lambda: (server_hb() or {}).get("holds", {}).get("light") is True, 10, msg="hold in heartbeat")
        calls = self.light.set_calls
        r = send("light", "off")
        self.assertEqual((r.get("status"), r.get("state")), ("held", "on"), r)
        self.assertEqual(self.light.set_calls, calls)
        self.assertTrue(self.light.on[0])
        # no light schedule on the bot -> hold lasts hold_max_s (8 s in this test)
        wait_for(lambda: "light" not in bstate()["holds"], 15, msg="hold expiry")
        r = send("light", "off")
        self.assertEqual((r.get("status"), r.get("state")), ("done", "off"), r)

    def test_09_pump_refusal_chain(self):
        pump = {"driver": "shelly_gen1", "host": self.pump.host}
        pol = {"enabled": False, "max_run_s": 4, "max_daily_s": 60, "min_interval_s": 0,
               "sensors": {"float": None, "leak": None, "soil": None}}
        self.write_aliases(pump=pump, policy=pol)
        r = send("pump", "on", duration=10)
        self.assertEqual(r.get("status"), "failed", r)
        self.assertIn("disabled on this bridge", r.get("error") or "")
        self.write_aliases(pump=pump, policy=dict(pol, enabled=True))
        r = send("pump", "on", duration=10)
        self.assertIn("not a sensor", r.get("error") or "")
        self.assertEqual(self.pump.set_calls, 0)
        self.write_aliases(pump=pump, policy=dict(pol, enabled=True, sensors=self.sensors()))
        self.s_float.value = "low"
        r = send("pump", "on", duration=10)
        self.assertIn("float=low", r.get("error") or "")
        self.s_float.value = "ok"
        r = send("pump", "on", duration=10)
        self.assertEqual((r.get("status"), r.get("state")), ("done", "on"), r)
        self.assertEqual(bstate()["timers"]["pump"]["duration_s"], 4)  # capped by max_run_s
        wait_for(lambda: not self.pump.on[0], 10, msg="pump timer off")
        r = send("pump", "on", duration=10)
        self.assertEqual(r.get("status"), "done", r)
        self.s_leak.value = "wet"
        wait_for(lambda: not self.pump.on[0], 6, msg="leak interlock")
        r = send("pump", "on", duration=3)
        self.assertIn("leak=wet", r.get("error") or "")
        self.s_leak.value = "dry"

    def test_10_offline_fallback(self):
        self.assertEqual(kalecam("bridge", "config", "set", "fallback.light",
                                 f"{local_hhmm(-60)}-{local_hhmm(60)}").returncode, 0)
        self.assertEqual(kalecam("bridge", "config", "set", "fallback.fan", '{"on_min":1,"off_min":0}').returncode, 0)
        ver = json.loads(kalecam("bridge", "status", "--json").stdout)["config_version"]
        wait_for(lambda: json.loads((BHOME / "config-cache.json").read_text())["version"] == ver, 15, msg="config refresh")
        self.assertEqual(send("fan", "off").get("status"), "done")
        self.assertFalse(self.light.on[0])
        self.pump.on[0] = True  # a pump left running (manually): fallback must turn it off regardless
        self.stop_server()
        t0 = time.time()
        wait_for(lambda: bstate()["fallback"]["active"], 30, msg="fallback active")
        self.assertGreaterEqual(time.time() - t0, 10)  # not before the threshold (15 s since last contact)
        wait_for(lambda: self.light.on[0] and self.fan.on[0] and not self.pump.on[0], 5, msg="fallback states")
        self.start_server(PORT)
        wait_for(lambda: not bstate()["fallback"]["active"], 20, msg="fallback off after reconnect")
        wait_for(lambda: server_hb() and server_hb()["fallback_active"] is False
                 and time.time() - server_hb()["received_ts"] < 5, 10, msg="heartbeat after reconnect")

    def test_11_rendezvous_after_url_change(self):
        self.stop_server()
        self.assertEqual(kalecam("bridge", "config", "set", "public_base_url", f"http://127.0.0.1:{PORT2}").returncode, 0)
        self.start_server(PORT2)
        r = kalecam("bridge", "publish", "--force")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("bridge rendezvous published", r.stdout)
        wait_for(lambda: bstate().get("current_url") == f"http://127.0.0.1:{PORT2}", 40, msg="bridge follows new URL")
        self.assertGreater(bstate()["last_seq"], 0)
        self.assertIn("switched to the bot's new address", BLOG.read_text())
        r = send("fan", "off")
        self.assertEqual((r.get("status"), r.get("state")), ("done", "off"), r)
        wait_for(lambda: time.time() - server_hb()["received_ts"] < 5, 10, msg="heartbeat on new URL")
        st = kb("status")
        self.assertIn(f"127.0.0.1:{PORT2}", st.stdout)
        self.assertIn("followed via rendezvous", st.stdout)

    def test_12_local_test_and_status(self):
        r = kb("test", "fan", "state")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("fan is off", r.stdout)
        r = kb("test", "fan", "on", "--dry-run")
        self.assertIn("dry-run", r.stdout)
        self.assertFalse(self.fan.on[0])
        r = kb("status", "--json", "--live")
        j = json.loads(r.stdout)
        self.assertTrue(j["service_running"])
        self.assertEqual(j["live"]["fan"], "off")
        self.assertEqual(j["aliases"]["light"]["password"], "***")

    def test_99_secrets_never_leak(self):
        self.kill_bridge(signal.SIGTERM)
        blobs = [BLOG.read_text()] + OUTPUTS + [(BHOME / "state.json").read_text(),
                                                 (BHOME / "config-cache.json").read_text()]
        blobs += [p.read_text() for p in (KHOME / "logs").glob("*")] if (KHOME / "logs").exists() else []
        blobs += [p.read_text() for p in TMP.glob("server-*.log")]
        for s in (self.key, LIGHT_PW, FAN_PW):
            for b in blobs:
                self.assertNotIn(s, b)
        self.assertIn(self.key, (BHOME / "config.json").read_text())  # it is stored (mode 600) ...
        self.assertIn("stopping", BLOG.read_text())                     # ... and SIGTERM exits cleanly


if __name__ == "__main__":
    unittest.main(failfast=True)
