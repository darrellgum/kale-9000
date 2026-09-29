#!/usr/bin/env python3
"""Engine unit tests with a fake clock and dummy/fake plugs (no bot, no network to the internet)."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import FakeSensor, FakeShellyGen2  # noqa: E402
from kalebridge import config as C  # noqa: E402
from kalebridge.engine import Engine  # noqa: E402

TZ = "America/New_York"


def cfg_cache(light=None, fan=None, pump_enabled=True, max_pump=120):
    return {"timezone": TZ, "poll_hold_s": 25, "heartbeat_s": 60, "offline_threshold_s": 600,
            "pump_enabled": pump_enabled, "max_duration_s": {"light": 64800, "fan": 3600, "pump": max_pump},
            "fallback": {"light": light, "fan": fan, "pump": "off"}, "aliases": ["light", "fan", "pump"],
            "version": "v-" + json.dumps([light, fan, pump_enabled])[:20]}


class Clock:
    def __init__(self, t):
        self.t = float(t)

    def __call__(self):
        return self.t


def local_ts(y, mo, d, h, mi, s=0):
    from zoneinfo import ZoneInfo
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=ZoneInfo(TZ)).timestamp()


class Base(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="kb-engine-"))
        self.p = C.paths(self.home)
        C.save_config({"url": "https://example.invalid", "key": "k" * 43, "bridge_id": "test-1", "rv": [],
                       "settings": {"hold_max_s": 3600}}, self.p)
        self.clock = Clock(local_ts(2026, 9, 28, 12, 0))
        self.plugs = {}

    def bind(self, aliases: dict, policy=None):
        a = dict(C.DEFAULT_ALIASES)
        a.update(aliases)
        if policy:
            a["pump_policy"] = policy
        C.write_json_atomic(self.p["aliases"], a)

    def fake(self, name):
        f = FakeShellyGen2()
        self.plugs[name] = f
        return {"driver": "shelly_gen2", "host": f.host}

    def engine(self, cache=None, **kw):
        if cache is not None:
            C.write_json_atomic(self.p["cache"], cache)
        e = Engine(self.p, clock=self.clock, **kw)
        return e

    def cmd(self, cid, device, action, dur=None, exp_in=300):
        c = {"id": cid, "device": device, "action": action,
             "expires_at": dt.datetime.fromtimestamp(self.clock.t + exp_in).astimezone().isoformat(timespec="seconds")}
        if dur is not None:
            c["duration_s"] = dur
        return c

    def tearDown(self):
        for f in self.plugs.values():
            f.close()


class CommandTest(Base):
    def test_on_off_state_and_result_shape(self):
        self.bind({"fan": self.fake("fan")})
        e = self.engine(cfg_cache())
        r = e.handle(self.cmd("c1", "fan", "on"))
        self.assertEqual((r["id"], r["status"], r["state"], r["error"]), ("c1", "done", "on", None))
        self.assertTrue(r["at"])
        self.assertTrue(self.plugs["fan"].on[0])
        self.assertEqual(e.handle(self.cmd("c2", "fan", "state"))["state"], "on")
        self.assertEqual(e.handle(self.cmd("c3", "fan", "off"))["state"], "off")

    def test_expired_is_not_executed(self):
        self.bind({"fan": self.fake("fan")})
        e = self.engine(cfg_cache())
        r = e.handle(self.cmd("c1", "fan", "on", exp_in=-1))
        self.assertEqual(r["status"], "expired")
        self.assertEqual(self.plugs["fan"].set_calls, 0)

    def test_unbound_alias_fails_and_switches_nothing(self):
        self.bind({"fan": self.fake("fan")})
        e = self.engine(cfg_cache())
        r = e.handle(self.cmd("c1", "light", "on"))
        self.assertEqual(r["status"], "failed")
        self.assertIn("not bound", r["error"])
        self.assertEqual(self.plugs["fan"].set_calls, 0)

    def test_idempotent_by_id(self):
        self.bind({"fan": self.fake("fan")})
        e = self.engine(cfg_cache())
        r1 = e.handle(self.cmd("c1", "fan", "on"))
        self.plugs["fan"].on[0] = False  # even if the plug changed, a repeated id must not switch again
        r2 = e.handle(self.cmd("c1", "fan", "on"))
        self.assertEqual(r1, r2)
        self.assertEqual(self.plugs["fan"].set_calls, 1)
        # survives a restart
        e2 = self.engine()
        self.assertEqual(e2.handle(self.cmd("c1", "fan", "on")), r1)
        self.assertEqual(self.plugs["fan"].set_calls, 1)

    def test_duration_timer_persists_across_restart(self):
        self.bind({"fan": self.fake("fan")})
        e = self.engine(cfg_cache())
        r = e.handle(self.cmd("c1", "fan", "on", dur=900))
        self.assertEqual(r["status"], "done")
        self.assertIn("fan", json.loads(self.p["state"].read_text())["timers"])
        del e  # "crash"
        self.clock.t += 901
        e2 = self.engine()
        e2.tick()
        self.assertFalse(self.plugs["fan"].on[0])
        self.assertNotIn("fan", e2.state["timers"])

    def test_duration_capped_by_bot_config_and_hard_ceiling(self):
        self.bind({"fan": self.fake("fan")})
        e = self.engine(cfg_cache())
        e.handle(self.cmd("c1", "fan", "on", dur=99999))
        self.assertEqual(e.state["timers"]["fan"]["duration_s"], 3600)

    def test_explicit_off_cancels_timer(self):
        self.bind({"fan": self.fake("fan")})
        e = self.engine(cfg_cache())
        e.handle(self.cmd("c1", "fan", "on", dur=60))
        e.handle(self.cmd("c2", "fan", "off"))
        self.assertNotIn("fan", e.state["timers"])

    def test_plug_error_reports_failed(self):
        self.bind({"fan": {"driver": "dummy", "fail": "offline"}})
        e = self.engine(cfg_cache())
        r = e.handle(self.cmd("c1", "fan", "on"))
        self.assertEqual(r["status"], "failed")
        self.assertIn("simulated failure", r["error"])

    def test_bad_inputs(self):
        self.bind({"fan": self.fake("fan")})
        e = self.engine(cfg_cache())
        self.assertIsNone(e.handle({"device": "fan", "action": "on"}))
        self.assertEqual(e.handle(self.cmd("c1", "heater", "on"))["status"], "failed")
        self.assertEqual(e.handle(self.cmd("c2", "fan", "toggle"))["status"], "failed")
        self.assertEqual(e.handle(self.cmd("c3", "fan", "off", dur=5))["status"], "failed")
        c = self.cmd("c4", "fan", "on")
        c["expires_at"] = "tomorrow"
        self.assertEqual(e.handle(c)["status"], "failed")

    def test_dry_run_switches_nothing(self):
        self.bind({"fan": self.fake("fan")})
        e = self.engine(cfg_cache(), dry_run=True)
        r = e.handle(self.cmd("c1", "fan", "on"))
        self.assertEqual((r["status"], r["state"]), ("done", "on"))
        self.assertEqual(self.plugs["fan"].set_calls, 0)
        self.assertEqual(self.plugs["fan"].requests, [])
        self.assertTrue(e.heartbeat_payload()["version"].endswith("-dry"))


class HoldTest(Base):
    def test_manual_change_holds_until_boundary(self):
        self.bind({"light": self.fake("light")})
        # light schedule 06:00-22:00; now 12:00 -> next boundary 22:00
        e = self.engine(cfg_cache(light={"on": "06:00", "off": "22:00"}))
        e.handle(self.cmd("c1", "light", "on"))
        self.plugs["light"].on[0] = False  # someone pressed the button
        e.tick()
        self.assertIn("light", e.state["holds"])
        self.assertEqual(e.state["holds"]["light"]["until_ts"], local_ts(2026, 9, 28, 22, 0))
        hb = e.heartbeat_payload()
        self.assertEqual(hb["holds"], {"light": True})
        calls = self.plugs["light"].set_calls
        r = e.handle(self.cmd("c2", "light", "on"))
        self.assertEqual((r["status"], r["state"]), ("held", "off"))
        self.assertEqual(self.plugs["light"].set_calls, calls)
        self.assertEqual(e.handle(self.cmd("c3", "light", "state"))["status"], "done")  # reads are fine
        self.clock.t = local_ts(2026, 9, 28, 22, 0, 1)
        e.tick()
        self.assertNotIn("light", e.state["holds"])
        self.assertEqual(e.handle(self.cmd("c4", "light", "on"))["status"], "done")

    def test_hold_without_schedule_uses_hold_max(self):
        self.bind({"fan": self.fake("fan")})
        e = self.engine(cfg_cache(fan=None))
        e.handle(self.cmd("c1", "fan", "off"))
        self.plugs["fan"].on[0] = True
        e.tick()
        self.assertEqual(e.state["holds"]["fan"]["until_ts"], self.clock.t + 3600)

    def test_fan_hold_ends_at_cycle_boundary(self):
        self.bind({"fan": self.fake("fan")})
        self.clock.t = local_ts(2026, 9, 28, 12, 7)
        e = self.engine(cfg_cache(fan={"on_min": 15, "off_min": 15}))
        e.handle(self.cmd("c1", "fan", "off"))
        self.plugs["fan"].on[0] = True
        e.tick()
        self.assertEqual(e.state["holds"]["fan"]["until_ts"], local_ts(2026, 9, 28, 12, 15))

    def test_no_hold_before_any_command(self):
        self.bind({"fan": self.fake("fan")})
        e = self.engine(cfg_cache())
        self.plugs["fan"].on[0] = True
        e.tick()
        self.assertEqual(e.state["holds"], {})

    def test_release(self):
        self.bind({"fan": self.fake("fan")})
        e = self.engine(cfg_cache())
        e.handle(self.cmd("c1", "fan", "off"))
        self.plugs["fan"].on[0] = True
        e.tick()
        (self.home / "control").mkdir()
        (self.home / "control" / "release-fan").write_text("")
        e.tick()
        self.assertEqual(e.state["holds"], {})

    def test_timer_off_still_runs_during_hold(self):
        self.bind({"fan": self.fake("fan")})
        e = self.engine(cfg_cache())
        e.handle(self.cmd("c1", "fan", "on", dur=60))
        self.plugs["fan"].on[0] = False
        e.tick()
        self.plugs["fan"].on[0] = True
        self.clock.t += 61
        e.tick()
        self.assertFalse(self.plugs["fan"].on[0])


class FallbackTest(Base):
    def test_no_config_ever_leaves_everything(self):
        self.bind({"light": self.fake("light"), "fan": self.fake("fan")})
        self.plugs["light"].on[0] = True
        e = self.engine(None)
        self.clock.t += 601
        e.tick()
        self.assertTrue(e.state["fallback"]["active"])
        self.assertEqual(self.plugs["light"].set_calls + self.plugs["fan"].set_calls, 0)
        self.assertTrue(e.heartbeat_payload()["fallback_active"])

    def test_fallback_after_10_minutes(self):
        self.bind({"light": self.fake("light"), "fan": self.fake("fan"), "pump": self.fake("pump")})
        self.plugs["pump"].on[0] = True
        e = self.engine(cfg_cache(light={"on": "06:00", "off": "22:00"}, fan={"on_min": 15, "off_min": 15}))
        e.on_contact()
        self.clock.t += 599
        e.tick()
        self.assertFalse(e.state["fallback"]["active"])
        self.clock.t = local_ts(2026, 9, 28, 12, 10, 30)  # 10.5 min since contact; fan cycle pos 10 -> on
        e.tick()
        self.assertTrue(e.state["fallback"]["active"])
        self.assertTrue(self.plugs["light"].on[0])
        self.assertTrue(self.plugs["fan"].on[0])
        self.assertFalse(self.plugs["pump"].on[0])
        self.clock.t = local_ts(2026, 9, 28, 12, 15, 5)  # fan off phase
        e.tick()
        self.assertFalse(self.plugs["fan"].on[0])
        self.clock.t = local_ts(2026, 9, 28, 22, 0, 5)  # lights out
        e.tick()
        self.assertFalse(self.plugs["light"].on[0])
        e.on_contact()
        e.tick()
        self.assertFalse(e.state["fallback"]["active"])

    def test_light_null_schedule_left_alone(self):
        self.bind({"light": self.fake("light")})
        e = self.engine(cfg_cache(light=None, fan=None))
        self.clock.t += 700
        e.tick()
        self.assertTrue(e.state["fallback"]["active"])
        self.assertEqual(self.plugs["light"].set_calls, 0)

    def test_fallback_respects_hold(self):
        self.bind({"light": self.fake("light")})
        e = self.engine(cfg_cache(light={"on": "06:00", "off": "22:00"}))
        e.on_contact()
        e.handle(self.cmd("c1", "light", "on"))
        self.plugs["light"].on[0] = False
        e.tick()
        self.clock.t += 700
        e.tick()
        self.assertTrue(e.state["fallback"]["active"])
        self.assertFalse(self.plugs["light"].on[0])  # the person's choice stands until 22:00

    def test_overnight_schedule(self):
        from kalebridge import schedule as S
        tz = S.tzinfo(TZ)
        sched = {"on": "20:00", "off": "08:00"}
        self.assertTrue(S.light_on_at(local_ts(2026, 9, 28, 23, 0), sched, tz))
        self.assertTrue(S.light_on_at(local_ts(2026, 9, 29, 7, 59), sched, tz))
        self.assertFalse(S.light_on_at(local_ts(2026, 9, 29, 8, 0), sched, tz))
        self.assertEqual(S.next_light_boundary(local_ts(2026, 9, 28, 23, 0), sched, tz), local_ts(2026, 9, 29, 8, 0))


class PumpTest(Base):
    def sensors(self, float_v="ok", leak_v="dry", soil_v=20):
        self.fs = {"float": FakeSensor(float_v), "leak": FakeSensor(leak_v), "soil": FakeSensor(soil_v)}
        for f in self.fs.values():
            self.plugs["sensor-" + str(f.port)] = f
        return {"float": {"type": "http_json", "url": self.fs["float"].url, "path": "reading.value", "ok_when": "ok"},
                "leak": {"type": "http_json", "url": self.fs["leak"].url, "path": "reading.value", "ok_when": "dry"},
                "soil": {"type": "http_json", "url": self.fs["soil"].url, "path": "reading.value", "ok_below": 35}}

    def policy(self, enabled=True, sensors=None, **kw):
        p = {"enabled": enabled, "max_run_s": 60, "max_daily_s": 300, "min_interval_s": 3600,
             "sensors": sensors or {"float": None, "leak": None, "soil": None}}
        p.update(kw)
        return p

    def test_refused_when_policy_disabled(self):
        self.bind({"pump": self.fake("pump")}, self.policy(enabled=False, sensors=self.sensors()))
        e = self.engine(cfg_cache())
        r = e.handle(self.cmd("c1", "pump", "on", dur=10))
        self.assertEqual(r["status"], "failed")
        self.assertIn("disabled on this bridge", r["error"])
        self.assertEqual(self.plugs["pump"].set_calls, 0)

    def test_refused_without_sensors(self):
        self.bind({"pump": self.fake("pump")}, self.policy(enabled=True))
        e = self.engine(cfg_cache())
        r = e.handle(self.cmd("c1", "pump", "on", dur=10))
        self.assertIn("not a sensor", r["error"])
        self.assertEqual(self.plugs["pump"].set_calls, 0)

    def test_refused_untimed_and_bad_sensor(self):
        self.bind({"pump": self.fake("pump")}, self.policy(sensors=self.sensors(float_v="low")))
        e = self.engine(cfg_cache())
        self.assertIn("timed", e.handle(self.cmd("c1", "pump", "on"))["error"])
        r = e.handle(self.cmd("c2", "pump", "on", dur=10))
        self.assertIn("float=low", r["error"])
        self.assertEqual(self.plugs["pump"].set_calls, 0)

    def test_runs_capped_then_interval_and_leak_interlock(self):
        self.bind({"pump": self.fake("pump")}, self.policy(sensors=self.sensors()))
        e = self.engine(cfg_cache())
        r = e.handle(self.cmd("c1", "pump", "on", dur=500))
        self.assertEqual(r["status"], "done")
        self.assertEqual(e.state["timers"]["pump"]["duration_s"], 60)  # max_run_s
        self.fs["leak"].value = "wet"
        self.clock.t += 3
        e.tick()
        self.assertFalse(self.plugs["pump"].on[0])
        self.assertNotIn("pump", e.state["timers"])
        self.fs["leak"].value = "dry"
        r = e.handle(self.cmd("c2", "pump", "on", dur=10))
        self.assertIn("min_interval", r["error"])

    def test_pump_off_always_allowed(self):
        self.bind({"pump": self.fake("pump")}, self.policy(enabled=False))
        self.plugs["pump"].on[0] = True
        e = self.engine(cfg_cache())
        self.assertEqual(e.handle(self.cmd("c1", "pump", "off"))["status"], "done")
        self.assertFalse(self.plugs["pump"].on[0])

    def test_no_bot_config_refuses_pump(self):
        self.bind({"pump": self.fake("pump")}, self.policy(sensors=self.sensors()))
        e = self.engine(None)
        self.assertIn("no bot config", e.handle(self.cmd("c1", "pump", "on", dur=5))["error"])


class HeartbeatTest(Base):
    def test_only_bound_aliases(self):
        self.bind({"fan": self.fake("fan")})
        e = self.engine(cfg_cache())
        e.tick()
        hb = e.heartbeat_payload()
        self.assertEqual(set(hb), {"bridge", "version", "devices", "holds", "fallback_active", "uptime_s"})
        self.assertEqual(hb["devices"], {"fan": "off"})
        self.assertEqual(hb["holds"], {"fan": False})
        self.assertEqual(hb["bridge"], "test-1")


if __name__ == "__main__":
    unittest.main()
