#!/usr/bin/env python3
"""Watchdog decision tests (stdlib unittest, no network, no real processes).

The server, the tunnel and the network are faked, so this runs anywhere in about a second and
never touches a live install (KALECAM_HOME is a throwaway temp directory).

Covers the "server first" rule: when the public tunnel check fails, the watchdog must check and
restart the local server BEFORE it restarts the tunnel, and must never sit waiting on tunnel
reachability while the server is down. Also covers the pinned cloudflared checksum.

  python3 tests/test_watchdog.py -v
"""
from __future__ import annotations

import hashlib
import io
import itertools
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import atexit, shutil  # noqa: E401
HOME = Path(tempfile.mkdtemp(prefix="kalecam-watchdog-test-"))
atexit.register(shutil.rmtree, HOME, True)
os.environ["KALECAM_HOME"] = str(HOME)
CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))
(HOME / "config.json").write_text(json.dumps({"port": 18799, "photo_root": str(HOME / "photos")}))
import kalecam_lib as K  # noqa: E402
import watchdog as W  # noqa: E402

URL = "https://alpha-bravo-charlie-delta.trycloudflare.com"
URL2 = "https://echo-foxtrot-golf-hotel.trycloudflare.com"


class World:
    """Fake server + tunnel + network. `events` records what the watchdog did, in order."""

    def __init__(self):
        self.server_up = True
        self.server_can_start = True
        self.tunnel_ok = True           # does the public URL reach the server?
        self.tunnel_ratelimited = False  # Cloudflare answers new quick tunnels with 429
        self.kill_server_on_tunnel_spawn = False
        self.instances = itertools.count(1)
        self.instance = f"inst-{next(self.instances)}"
        self.events: list[str] = []
        self.pids = itertools.count(1000)
        self.alive: dict[int, str] = {}
        self.slept = 0.0
        self.next_url = URL2

    # patched functions
    def server_health(self, port):
        return {"app": "kalecam", "instance": self.instance} if self.server_up else None

    def spawn(self, argv, logfile):
        pid = next(self.pids)
        if argv[-1].endswith("server.py"):
            self.events.append("start-server")
            if self.server_can_start:
                self.server_up = True
                self.instance = f"inst-{next(self.instances)}"
                self.alive[pid] = "server.py"
        else:
            self.events.append("start-tunnel")
            if self.tunnel_ratelimited:  # cloudflared exits at once
                Path(logfile).write_text("INF Requesting new quick Tunnel on trycloudflare.com...\n"
                                         "failed to request quick Tunnel: quick tunnel provisioning failed with status 429\n")
                return pid
            self.alive[pid] = "cloudflared"
            Path(logfile).write_text(f"INF |  {self.next_url}  |\nINF Registered tunnel connection\n")
            self.tunnel_ok = True
            if self.kill_server_on_tunnel_spawn:
                self.kill_server_on_tunnel_spawn = False
                self.server_up = False
        return pid

    def http_json(self, url, timeout=8.0):
        if "trycloudflare" in url:
            self.events.append("public-check")
            if not (self.tunnel_ok and self.server_up):
                raise OSError("unreachable")
        elif not self.server_up:
            raise OSError("connection refused")
        return {"app": "kalecam", "instance": self.instance}

    def sleep(self, s):
        self.slept += s

    def pid_alive(self, pid, name=None):
        return pid in self.alive and (name is None or name in self.alive[pid])

    def kill_pid(self, pid, name):
        self.events.append(f"kill-{'server' if 'server' in name else 'tunnel'}")
        self.alive.pop(pid, None)
        if "server" in name:
            self.server_up = False


class WatchdogOrderTest(unittest.TestCase):
    def setUp(self):
        self.w = w = World()
        self._saved = {}
        for mod, name, val in [(W, "server_health", w.server_health), (W, "spawn", w.spawn),
                               (W, "http_json", w.http_json), (W, "doh_a", lambda host: ["203.0.113.7"]),  # TEST-NET address
                               (W, "healthz_via_ip", lambda url, ip, timeout=10.0: w.http_json(url + "/healthz")),
                               (W, "kill_pid", w.kill_pid), (W, "ensure_cloudflared", lambda cfg=None: True),
                               (W.K, "pid_alive", w.pid_alive), (W.time, "sleep", w.sleep)]:
            self._saved[(mod, name)] = getattr(mod, name)
            setattr(mod, name, val)
        K.ensure_dirs()
        K.URL_PATH.write_text(URL + "\n")
        self.cfg = K.load_config()
        self.st = {"cloudflared_pid": 1, "server_pid": 2}
        w.alive.update({1: "cloudflared", 2: "server.py"})

    def tearDown(self):
        for (mod, name), val in self._saved.items():
            setattr(mod, name, val)

    def run_pass(self):
        srv = W.Server(self.cfg, self.st)
        if not srv.ensure():
            return srv, None, False
        url, ok = W.ensure_tunnel(self.cfg, self.st, srv)
        return srv, url, ok

    def test_healthy_nothing_restarted(self):
        srv, url, ok = self.run_pass()
        self.assertTrue(ok)
        self.assertEqual(url, URL)
        self.assertNotIn("start-tunnel", self.w.events)
        self.assertNotIn("start-server", self.w.events)

    def test_server_killed_mid_pass_restarts_server_not_tunnel(self):
        """The live incident: the server dies after the local check, so the public check fails.
        The watchdog must restart the SERVER and keep the working tunnel (same URL)."""
        srv = W.Server(self.cfg, self.st)
        self.assertTrue(srv.ensure())
        self.w.server_up = False            # killed between the server check and the tunnel check
        self.w.alive.pop(2)
        url, ok = W.ensure_tunnel(self.cfg, self.st, srv)
        self.assertTrue(ok, self.w.events)
        self.assertEqual(url, URL, "tunnel URL must not change when only the server died")
        self.assertIn("start-server", self.w.events)
        self.assertNotIn("start-tunnel", self.w.events)
        self.assertNotIn("kill-tunnel", self.w.events)

    def test_server_down_and_unstartable_leaves_tunnel_alone_without_waiting(self):
        srv = W.Server(self.cfg, self.st)
        self.assertTrue(srv.ensure())
        self.w.server_up = False
        self.w.server_can_start = False
        self.w.alive.pop(2)
        t0 = self.w.slept
        url, ok = W.ensure_tunnel(self.cfg, self.st, srv)
        self.assertFalse(ok)
        self.assertNotIn("start-tunnel", self.w.events)
        self.assertNotIn("kill-tunnel", self.w.events)
        self.assertNotIn("public-check", self.w.events[self.w.events.index("start-server"):])
        self.assertLess(self.w.slept - t0, 30, "must not wait on the tunnel while the server is down")

    def test_tunnel_broken_server_healthy_restarts_tunnel(self):
        self.w.tunnel_ok = False
        srv, url, ok = self.run_pass()
        self.assertTrue(ok, self.w.events)
        self.assertEqual(url, URL2)
        self.assertIn("start-tunnel", self.w.events)
        self.assertNotIn("start-server", self.w.events)

    def test_server_dies_while_waiting_for_new_tunnel(self):
        """Server killed while the watchdog waits for a new tunnel: heal the server at once
        instead of polling the public URL for up to two minutes."""
        self.w.tunnel_ok = False
        self.w.kill_server_on_tunnel_spawn = True
        srv, url, ok = self.run_pass()
        self.assertTrue(ok, self.w.events)
        ev = self.w.events
        self.assertEqual(ev.count("start-tunnel"), 1, ev)
        i_tun = ev.index("start-tunnel")
        self.assertIn("start-server", ev[i_tun:], ev)
        # no public check between the server dying and the server restart
        i_srv = ev.index("start-server", i_tun)
        self.assertNotIn("public-check", ev[i_tun:i_srv], ev)
        self.assertLess(self.w.slept, 60, f"waited {self.w.slept}s")

    def test_tunnel_process_dead_starts_tunnel(self):
        self.w.alive.pop(1)
        srv, url, ok = self.run_pass()
        self.assertTrue(ok)
        self.assertIn("start-tunnel", self.w.events)

    def test_quick_tunnel_rate_limit_reported_then_cleared(self):
        self.w.alive.pop(1)
        self.w.tunnel_ratelimited = True
        srv, url, ok = self.run_pass()
        self.assertFalse(ok)
        self.assertIn("429", self.st.get("tunnel_error", ""))
        self.assertNotIn("start-server", self.w.events)  # server was fine; not touched
        self.w.tunnel_ratelimited = False
        srv, url, ok = self.run_pass()
        self.assertTrue(ok)
        self.assertNotIn("tunnel_error", self.st)


class PublishBackoffTest(unittest.TestCase):
    def test_failed_channel_backoff(self):
        import rendezvous as RV
        ch = {}
        RV.note_failure(ch, "HTTPError: HTTP Error 503")
        now = ch["error_ts"]
        self.assertFalse(RV.retry_due(ch, now + 30))
        self.assertTrue(RV.retry_due(ch, now + 61))
        RV.note_failure(ch, "HTTPError: HTTP Error 503")
        self.assertFalse(RV.retry_due(ch, ch["error_ts"] + 90))
        RV.note_failure(ch, "HTTPError: HTTP Error 429: Too Many Requests")
        self.assertFalse(RV.retry_due(ch, ch["error_ts"] + 600), "429 must back off 15 min")
        self.assertTrue(RV.retry_due(ch, ch["error_ts"] + 901))
        self.assertTrue(RV.retry_due({"error": None}))


class CloudflaredPinTest(unittest.TestCase):
    def test_pins_present(self):
        for arch in ("amd64", "arm64"):
            self.assertRegex(W.CLOUDFLARED_SHA256[arch], r"^[0-9a-f]{64}$")
        self.assertRegex(W.CLOUDFLARED_VERSION, r"^\d{4}\.\d+\.\d+$")

    def test_checksum_mismatch_rejected(self):
        saved = (W.urllib.request.urlopen, W.platform.machine, W.CLOUDFLARED)
        calls = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            calls.append(req.full_url)
            return Resp(b"#!/bin/sh\necho cloudflared evil\n")
        try:
            W.urllib.request.urlopen = fake_urlopen
            W.platform.machine = lambda: "x86_64"
            W.CLOUDFLARED = HOME / "bin" / "cloudflared-test"
            self.assertFalse(W.ensure_cloudflared({}))
            self.assertFalse(W.CLOUDFLARED.exists())
            self.assertIn(f"/releases/download/{W.CLOUDFLARED_VERSION}/cloudflared-linux-amd64", calls[0])
            self.assertNotIn("latest", calls[0])
        finally:
            W.urllib.request.urlopen, W.platform.machine, W.CLOUDFLARED = saved

    def test_unsupported_arch_refuses(self):
        saved = (W.urllib.request.urlopen, W.platform.machine, W.CLOUDFLARED)
        try:
            W.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no download"))
            W.platform.machine = lambda: "armv7l"
            W.CLOUDFLARED = HOME / "bin" / "cloudflared-test2"
            self.assertFalse(W.ensure_cloudflared({}))
        finally:
            W.urllib.request.urlopen, W.platform.machine, W.CLOUDFLARED = saved

    def test_config_override(self):
        v, arch, sha = W.cloudflared_pin({"cloudflared": {"version": "2099.1.1", "sha256": {"amd64": "ab" * 32, "arm64": "cd" * 32}}})
        self.assertEqual(v, "2099.1.1")
        v2, _, sha2 = W.cloudflared_pin({"cloudflared": {"version": "2099.1.1"}})
        self.assertIsNone(sha2, "a different version without its own checksums must not reuse the pinned ones")


if __name__ == "__main__":
    unittest.main()
