"""The bridge's brain: command rules, timers, holds, offline fallback, pump interlock.

No network to the bot happens here (see service.py); only local plug/sensor I/O. Thread-safe:
every public method takes self.lock. State is persisted to state.json after each change, so a
restart keeps timers (a timed "on" still turns off), holds, executed command ids and the outbox.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import threading
import time

from . import VERSION
from . import config as C
from . import schedule as S
from . import sensors as SN
from .drivers import Driver, DriverError, make as make_driver

log = logging.getLogger("kalebridge")
EXECUTED_KEEP_S = 48 * 3600
EXECUTED_MAX = 2000
OUTBOX_MAX = 500


class DryRunDriver(Driver):
    """Stands in for a real driver in dry-run mode: remembers the requested state, touches nothing."""
    name = "dry-run"

    def __init__(self, real_desc: str):
        super().__init__({})
        self.real_desc, self.state = real_desc, False

    def get(self) -> bool:
        return self.state

    def set(self, on: bool) -> bool:
        self.state = bool(on)
        return self.state

    def describe(self) -> str:
        return f"dry-run (would use {self.real_desc})"


def _onoff(b) -> str | None:
    return None if b is None else ("on" if b else "off")


def parse_iso(s) -> float | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.astimezone()
    return t.timestamp()


class Engine:
    def __init__(self, p: dict | None = None, clock=time.time, dry_run: bool | None = None):
        self.p = p or C.paths()
        self.clock = clock
        self.lock = threading.RLock()
        self.cfg = C.load_config(self.p)
        self.settings = self.cfg["settings"]
        self.dry_run = bool(self.settings.get("dry_run")) if dry_run is None else bool(dry_run)
        self.started = clock()
        self.skew = 0.0
        self.cache = C.read_json(self.p["cache"], None)
        self.state = self._load_state()
        self.drivers: dict = {a: None for a in C.ALIASES}
        self.policy: dict = dict(C.DEFAULT_ALIASES["pump_policy"])
        self.alias_specs: dict = {a: None for a in C.ALIASES}
        self._aliases_mtime = None
        self._next_state_poll = 0.0
        self._next_pump_watch = 0.0
        self._timer_retry: dict = {}
        self._dirty = False
        self._last_save = 0.0
        self.reload_aliases(force=True)

    # ------------------------------------------------------------ state
    def _load_state(self) -> dict:
        st = C.read_json(self.p["state"], None) or {}
        base = {"v": 1, "current_url": None, "last_seq": 0, "last_contact_ts": None, "executed": {},
                "timers": {}, "last_cmd": {}, "holds": {}, "devices": {}, "outbox": [],
                "fallback": {"active": False, "since_ts": None, "desired": {}},
                "pump": {"last_dose_ts": None, "day": None, "day_total_s": 0}, "rendezvous": {}}
        for k, v in base.items():
            st.setdefault(k, v)
        return st

    def save(self) -> None:
        with self.lock:
            self.state.update({"pid": os.getpid(), "updated_ts": self.clock(), "version": VERSION,
                               "dry_run": self.dry_run, "started_ts": self.started})
            C.write_json_atomic(self.p["state"], self.state, 0o600)
            self._dirty = False
            self._last_save = self.clock()

    def now(self) -> float:
        return self.clock()

    def tz(self):
        return S.tzinfo((self.cache or {}).get("timezone"))

    def iso(self, ts: float | None = None) -> str:
        return dt.datetime.fromtimestamp(self.now() if ts is None else ts, self.tz()).isoformat(timespec="seconds")

    # ------------------------------------------------------------ aliases / drivers
    def reload_aliases(self, force: bool = False) -> None:
        try:
            m = self.p["aliases"].stat().st_mtime_ns
        except FileNotFoundError:
            m = None
        if not force and m == self._aliases_mtime:
            return
        self._aliases_mtime = m
        try:
            a = C.load_aliases(self.p)
        except ValueError as e:
            log.error("aliases.json rejected, keeping the previous bindings: %s", e)
            return
        drivers = {}
        for alias in C.ALIASES:
            spec = a.get(alias)
            if spec is None:
                drivers[alias] = None
                continue
            try:
                d = make_driver(spec)
                drivers[alias] = DryRunDriver(d.describe()) if self.dry_run else d
            except DriverError as e:
                log.error("alias %s: %s (treated as unbound)", alias, e)
                drivers[alias] = None
        with self.lock:
            for alias in C.ALIASES:  # keep simulated dry-run state across reloads
                old = self.drivers.get(alias)
                if isinstance(old, DryRunDriver) and isinstance(drivers[alias], DryRunDriver):
                    drivers[alias].state = old.state
            self.drivers, self.policy, self.alias_specs = drivers, a["pump_policy"], {k: a.get(k) for k in C.ALIASES}
        log.info("aliases: %s%s", ", ".join(f"{k}={'null' if v is None else v.describe()}" for k, v in drivers.items()),
                 " [DRY RUN]" if self.dry_run else "")

    def bound(self) -> list:
        return [a for a in C.ALIASES if self.drivers.get(a) is not None]

    def secrets(self) -> list:
        """Every secret value this process knows (for the log redaction filter)."""
        out = [self.cfg.get("key")]
        for spec in list(self.alias_specs.values()) + list((self.policy.get("sensors") or {}).values()):
            if isinstance(spec, dict):
                out += [spec.get(k) for k in ("password", "token")]
        return [s for s in out if isinstance(s, str) and len(s) >= 4]

    # ------------------------------------------------------------ plug I/O
    def read(self, alias: str):
        d = self.drivers.get(alias)
        if d is None:
            return None, "unbound"
        try:
            v = bool(d.get())
            self.state["devices"][alias] = _onoff(v)
            return v, None
        except DriverError as e:
            self.state["devices"][alias] = "error"
            return None, str(e)

    def switch(self, alias: str, on: bool, why: str):
        """Returns (read-back state or None, error or None). Updates last_cmd."""
        d = self.drivers.get(alias)
        if d is None:
            return None, "unbound"
        try:
            st = bool(d.set(on))
        except DriverError as e:
            self.state["devices"][alias] = "error"
            log.warning("switch %s %s (%s) FAILED: %s", alias, _onoff(on), why, e)
            return None, str(e)
        self.state["devices"][alias] = _onoff(st)
        self.state["last_cmd"][alias] = st  # the plug's real state is the new baseline
        self._dirty = True
        log.info("switch %s %s (%s) -> %s%s", alias, _onoff(on), why, _onoff(st), " [dry run]" if self.dry_run else "")
        if st != on:
            return st, f"read-back says {_onoff(st)} after switching {_onoff(on)}"
        return st, None

    # ------------------------------------------------------------ commands
    def handle(self, cmd) -> dict | None:
        with self.lock:
            cid = cmd.get("id") if isinstance(cmd, dict) else None
            if not isinstance(cid, str) or not C.CMD_ID_RE.match(cid):
                log.warning("ignoring a command without a valid id")
                return None
            prev = self.state["executed"].get(cid)
            if prev:
                log.info("command %s already executed (%s): re-sending the stored result, not switching",
                         cid, prev["result"]["status"])
                return dict(prev["result"])
            res = self._execute(cmd)
            res = {"id": cid, "status": res[0], "state": res[1], "error": res[2], "at": self.iso()}
            self.state["executed"][cid] = {"ts": self.now(), "result": res}
            self._prune_executed()
            log.info("command %s %s %s%s -> %s%s%s", cid, cmd.get("device"), cmd.get("action"),
                     f" {cmd['duration_s']}s" if cmd.get("duration_s") is not None else "", res["status"],
                     f" state={res['state']}" if res["state"] else "", f" ({res['error']})" if res["error"] else "")
            self.save()
            return dict(res)

    def _prune_executed(self) -> None:
        ex = self.state["executed"]
        cut = self.now() - EXECUTED_KEEP_S
        for k in [k for k, v in ex.items() if v.get("ts", 0) < cut]:
            ex.pop(k, None)
        if len(ex) > EXECUTED_MAX:
            for k in sorted(ex, key=lambda k: ex[k].get("ts", 0))[: len(ex) - EXECUTED_MAX]:
                ex.pop(k, None)

    def _execute(self, cmd: dict):
        device, action, dur = cmd.get("device"), cmd.get("action"), cmd.get("duration_s")
        exp = parse_iso(cmd.get("expires_at"))
        if exp is None:
            return "failed", None, "missing or unreadable expires_at"
        if self.now() + self.skew >= exp:
            return "expired", None, f"expired at {cmd.get('expires_at')}; not executed"
        if device not in C.ALIASES:
            return "failed", None, f"unknown device alias {str(device)[:20]!r}"
        if action not in C.ACTIONS:
            return "failed", None, f"unknown action {str(action)[:20]!r}"
        if self.drivers.get(device) is None:
            return "failed", None, f"alias '{device}' is not bound on this bridge (null in aliases.json); nothing switched"
        if action == "state":
            v, err = self.read(device)
            return ("failed", None, err) if err else ("done", _onoff(v), None)
        if dur is not None:
            if action != "on" or isinstance(dur, bool) or not isinstance(dur, (int, float)) or dur <= 0:
                return "failed", None, "duration_s must be a positive number and only with action 'on'"
            dur = int(dur)
        on = action == "on"
        h = self.state["holds"].get(device)
        if h:
            v, _ = self.read(device)
            return "held", _onoff(v), (f"manual change detected at {self.iso(h['since_ts'])}; not switching "
                                       f"until {self.iso(h['until_ts'])}")
        if device == "pump" and on:
            why = self.pump_preflight(dur)
            if why:
                return "failed", None, "pump refused: " + why
        if dur is not None:
            caps = [C.HARD_MAX_DURATION_S[device]]
            srv = ((self.cache or {}).get("max_duration_s") or {}).get(device)
            if isinstance(srv, int) and not isinstance(srv, bool):
                if srv <= 0:
                    return "failed", None, f"timed runs are disabled for {device} by the bot config"
                caps.append(srv)
            if device == "pump":
                caps.append(int(self.policy.get("max_run_s") or 0))
            cap = min(caps)
            if dur > cap:
                log.info("duration for %s capped from %ss to %ss", device, dur, cap)
                dur = cap
        st, err = self.switch(device, on, "command")
        if err:
            return "failed", _onoff(st), err
        if on and dur is not None:
            self.state["timers"][device] = {"off_ts": self.now() + dur, "cmd_id": cmd["id"], "duration_s": dur}
            if device == "pump":
                self._record_dose(dur)
        else:
            if self.state["timers"].pop(device, None):
                log.info("timer for %s cancelled by an explicit %s", device, action)
        return "done", _onoff(st), None

    # ------------------------------------------------------------ pump
    def _day(self) -> str:
        return dt.datetime.fromtimestamp(self.now(), self.tz()).date().isoformat()

    def _record_dose(self, dur: int) -> None:
        pu = self.state["pump"]
        if pu.get("day") != self._day():
            pu.update({"day": self._day(), "day_total_s": 0})
        pu["day_total_s"] = int(pu.get("day_total_s") or 0) + int(dur)
        pu["last_dose_ts"] = self.now()

    def pump_preflight(self, dur) -> str | None:
        pp = self.policy
        if self.cache is None:
            return "no bot config has been fetched yet"
        if not pp.get("enabled"):
            return "the pump is disabled on this bridge (aliases.json pump_policy.enabled is false)"
        missing = [n for n in SN.REQUIRED if n not in SN.configured(pp)]
        if missing:
            return ("local sensors missing in pump_policy.sensors: " + ", ".join(missing)
                    + " (a flag in a bot command is not a sensor)")
        if dur is None:
            return "pump runs must be timed (duration_s is required)"
        max_run = min(int(pp.get("max_run_s") or 0), C.HARD_MAX_DURATION_S["pump"])
        if max_run <= 0:
            return "pump_policy.max_run_s is 0"
        pu = self.state["pump"]
        last = pu.get("last_dose_ts")
        if last and self.now() - last < int(pp.get("min_interval_s") or 0):
            return f"last dose was {int(self.now() - last)}s ago (min_interval_s {pp.get('min_interval_s')})"
        used = int(pu.get("day_total_s") or 0) if pu.get("day") == self._day() else 0
        daily = min(int(pp.get("max_daily_s") or 0), C.HARD_MAX_PUMP_DAILY_S)
        if used + min(int(dur), max_run) > daily:
            return f"daily limit: {used}s used of {daily}s"
        bad = []
        for n in SN.REQUIRED:
            ok, detail = SN.check(n, pp["sensors"][n])
            if not ok:
                bad.append(detail)
        if bad:
            return "; ".join(bad)
        return None

    def pump_watch(self) -> None:
        """While the pump is (or may be) on, a bad float/leak reading turns it off at once."""
        if self.drivers.get("pump") is None:
            return
        running = self.state["devices"].get("pump") == "on" or "pump" in self.state["timers"]
        if not running:
            return
        sens = self.policy.get("sensors") or {}
        bad = []
        for n in ("float", "leak"):
            if isinstance(sens.get(n), dict):
                ok, detail = SN.check(n, sens[n])
                if not ok:
                    bad.append(detail)
        if bad:
            log.warning("PUMP INTERLOCK: %s -> pump off", "; ".join(bad))
            st, err = self.switch("pump", False, "interlock")
            if not err:
                self.state["timers"].pop("pump", None)

    # ------------------------------------------------------------ timers / holds / fallback
    def check_timers(self) -> None:
        now = self.now()
        for alias, t in list(self.state["timers"].items()):
            if now < t.get("off_ts", 0) or now < self._timer_retry.get(alias, 0):
                continue
            if self.drivers.get(alias) is None:
                log.error("timer for %s is due but the alias is no longer bound; dropping it", alias)
                self.state["timers"].pop(alias, None)
                self._dirty = True
                continue
            st, err = self.switch(alias, False, f"timer from {t.get('cmd_id')}")
            if err or st:
                self._timer_retry[alias] = now + 5
                log.warning("timer off for %s did not land; retrying in 5 s", alias)
            else:
                self.state["timers"].pop(alias, None)
                self._timer_retry.pop(alias, None)
            self._dirty = True

    def next_boundary(self, alias: str, ts: float) -> float:
        fb = (self.cache or {}).get("fallback") or {}
        nb = None
        try:
            if alias == "light" and fb.get("light"):
                nb = S.next_light_boundary(ts, fb["light"], self.tz())
            elif alias == "fan" and fb.get("fan"):
                nb = S.next_fan_boundary(ts, fb["fan"], self.tz())
        except (KeyError, ValueError, TypeError):
            nb = None
        return nb if nb else ts + int(self.settings.get("hold_max_s") or 14400)

    def poll_states(self) -> None:
        now = self.now()
        for alias in self.bound():
            v, err = self.read(alias)
            if err:
                continue
            expected = self.state["last_cmd"].get(alias)
            if expected is None or v == expected:
                continue
            self.state["last_cmd"][alias] = v
            self._dirty = True
            if alias in self.state["holds"]:
                continue
            until = self.next_boundary(alias, now)
            self.state["holds"][alias] = {"since_ts": now, "until_ts": until, "state": _onoff(v)}
            log.info("manual change on %s (now %s, bridge last set %s): holding until %s", alias, _onoff(v),
                     _onoff(expected), self.iso(until))

    def expire_holds(self) -> None:
        now = self.now()
        for alias, h in list(self.state["holds"].items()):
            if now >= h.get("until_ts", 0):
                self.state["holds"].pop(alias, None)
                self._dirty = True
                log.info("hold on %s ended", alias)

    def release_hold(self, alias: str) -> bool:
        with self.lock:
            if self.state["holds"].pop(alias, None):
                log.info("hold on %s released by the owner", alias)
                self.save()
                return True
            return False

    def offline_threshold(self) -> int:
        return int(self.settings.get("offline_threshold_s") or (self.cache or {}).get("offline_threshold_s") or 600)

    def fallback(self) -> None:
        now = self.now()
        fb = self.state["fallback"]
        last = self.state.get("last_contact_ts") or self.started
        offline = now - last > self.offline_threshold()
        if offline and not fb["active"]:
            fb.update({"active": True, "since_ts": now, "desired": {}})
            self._dirty = True
            log.warning("bot unreachable for %ds: FALLBACK active%s", now - last,
                        "" if self.cache else " (no bot config was ever fetched: leaving every switch where it is)")
        elif not offline and fb["active"]:
            fb.update({"active": False, "since_ts": None, "desired": {}})
            self._dirty = True
            log.info("bot reachable again: fallback off, KALE is back in control")
        if not fb["active"] or not self.cache:
            return
        conf = self.cache.get("fallback") or {}
        want = {}
        if self.drivers.get("pump") is not None:
            want["pump"] = False
        if self.drivers.get("light") is not None and conf.get("light"):
            want["light"] = S.light_on_at(now, conf["light"], self.tz())
        if self.drivers.get("fan") is not None and conf.get("fan"):
            want["fan"] = S.fan_on_at(now, conf["fan"], self.tz())
        for alias, w in want.items():
            if fb["desired"].get(alias) == w:
                continue
            if alias != "pump" and alias in self.state["holds"]:
                fb["desired"][alias] = w  # a person is in charge until the next boundary
                continue
            st, err = self.switch(alias, w, "fallback")
            if not err:
                fb["desired"][alias] = w
                if alias == "pump":
                    self.state["timers"].pop("pump", None)
            self._dirty = True

    def check_control_files(self) -> None:
        """`kalebridge release <alias>` drops a file here for the running service."""
        d = self.p["home"] / "control"
        if not d.is_dir():
            return
        for f in d.glob("release-*"):
            alias = f.name[len("release-"):]
            try:
                f.unlink()
            except OSError:
                pass
            if alias in C.ALIASES:
                self.release_hold(alias)

    def tick(self) -> None:
        with self.lock:
            now = self.now()
            self.reload_aliases()
            self.check_control_files()
            self.check_timers()
            self.expire_holds()
            if now >= self._next_state_poll:
                self._next_state_poll = now + max(1, int(self.settings.get("state_poll_s") or 30))
                self.poll_states()
            if now >= self._next_pump_watch:
                self._next_pump_watch = now + 2
                self.pump_watch()
            self.fallback()
            if self._dirty or now - self._last_save >= 60:  # periodic save doubles as a liveness stamp
                self.save()

    # ------------------------------------------------------------ bot contact
    def on_contact(self) -> None:
        with self.lock:
            first = self.state.get("last_contact_ts") is None
            self.state["last_contact_ts"] = self.now()  # persisted by the next periodic save (<= 60 s)
            if first:
                self.save()

    def set_cache(self, conf: dict) -> None:
        with self.lock:
            changed = (self.cache or {}).get("version") != conf.get("version")
            self.cache = conf
            C.write_json_atomic(self.p["cache"], conf, 0o600)
            st = parse_iso(conf.get("server_time"))
            if st:
                sk = st - self.now()
                self.skew = sk if abs(sk) > 30 else 0.0
                if self.skew:
                    log.warning("this computer's clock differs from the bot's by %ds; using the bot's time for "
                                "expiry checks (fix NTP)", int(sk))
            if changed:
                fb = conf.get("fallback") or {}
                log.info("bot config %s cached: light %s, fan %s, pump_enabled %s", conf.get("version"),
                         fb.get("light"), fb.get("fan"), conf.get("pump_enabled"))

    def heartbeat_payload(self) -> dict:
        with self.lock:
            b = self.bound()
            return {"bridge": self.cfg.get("bridge_id"), "version": VERSION + ("-dry" if self.dry_run else ""),
                    "devices": {a: self.state["devices"].get(a) or "unknown" for a in b},
                    "holds": {a: a in self.state["holds"] for a in b},
                    "fallback_active": bool(self.state["fallback"]["active"]),
                    "uptime_s": int(self.now() - self.started)}

    # outbox of results that could not be delivered yet
    def outbox_add(self, res: dict) -> None:
        with self.lock:
            ob = [r for r in self.state["outbox"] if r.get("id") != res.get("id")]
            ob.append(res)
            self.state["outbox"] = ob[-OUTBOX_MAX:]
            self.save()

    def outbox_items(self) -> list:
        with self.lock:
            return list(self.state["outbox"])

    def outbox_remove(self, cid: str) -> None:
        with self.lock:
            self.state["outbox"] = [r for r in self.state["outbox"] if r.get("id") != cid]
            self.save()
