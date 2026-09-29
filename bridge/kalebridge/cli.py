"""kalebridge command line.

  kalebridge pair [BLOB | -] [--check]     paste the blob from `kalecam bridge pair` (prompted if omitted)
  kalebridge run [--dry-run] [-v]          the service (systemd runs this)
  kalebridge test <light|fan|pump> <on|off|state> [--dry-run] [--seconds N]   local only, no bot
  kalebridge status [--json] [--live]
  kalebridge release <alias>               end a manual-change hold now
  kalebridge config show | set <key> <value>
  kalebridge rendezvous                    read the relays now and show what they say (read-only)
  kalebridge version
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time

from . import VERSION, aesgcm
from . import config as C


def _die(msg: str, code: int = 2):
    print(f"kalebridge: {msg}", file=sys.stderr)
    sys.exit(code)


def _need_pairing(c: dict):
    if not c.get("key") or not c.get("url") or not c.get("bridge_id"):
        _die("not paired yet: run `kalebridge pair` with the blob from `kalecam bridge pair`")


def _age(ts):
    if not ts:
        return "never"
    s = int(time.time() - ts)
    return f"{s}s ago" if s < 120 else f"{s // 60}m ago" if s < 7200 else f"{s // 3600}h ago"


# ------------------------------------------------------------------ pair
def cmd_pair(a) -> int:
    p = C.paths()
    c = C.load_config(p)
    blob = a.blob
    if blob in (None, ""):
        blob = getpass.getpass("Paste the pairing blob (input hidden), then Enter: ")
    elif blob == "-":
        blob = sys.stdin.read()
    try:
        d = C.parse_blob(blob, allow_http=bool(c["settings"].get("allow_http_urls")))
    except ValueError as e:
        _die(str(e))
    new_key = d["key"] != c.get("key")
    c.update({"v": 1, "url": d["url"], "key": d["key"], "bridge_id": d["bridge_id"], "rv": d["rv"],
              "paired_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    C.ensure_home(p["home"])
    C.save_config(c, p)
    st = C.read_json(p["state"], None)
    if st is not None:  # the pasted URL wins; a new key also resets the replay counter
        st["current_url"] = None
        if new_key:
            st["last_seq"] = 0
        C.write_json_atomic(p["state"], st, 0o600)
    made = C.ensure_aliases(p)
    host = d["url"].split("://", 1)[1]
    print(f"paired: bridge id {d['bridge_id']}, bot {host}, key fingerprint {C.fingerprint(d['key'])}")
    print(f"config: {p['config']} (mode 600)")
    print(f"rendezvous relays: {', '.join(r[1] for r in d['rv']) if d['rv'] else 'none (re-pair after a bot URL change)'}")
    if made:
        print(f"aliases: {p['aliases']} created with light/fan/pump = null (edit it to bind your plugs)")
    if a.check:
        from .client import AuthError, BotClient, NetError
        try:
            conf = BotClient(d["url"], d["key"], d["bridge_id"]).config()
            print(f"check: OK, the bot answered (config version {conf.get('version')})")
        except AuthError:
            print("check: the bot rejected the key (401). Make a fresh blob with `kalecam bridge pair`.")
            return 1
        except NetError as e:
            print(f"check: could not reach the bot ({e}). The service will keep retrying.")
            return 1
    return 0


# ------------------------------------------------------------------ run
def cmd_run(a) -> int:
    from .engine import Engine
    from .service import Service, setup_logging
    p = C.paths()
    c = C.load_config(p)
    _need_pairing(c)
    C.ensure_aliases(p)
    eng = Engine(p, dry_run=True if a.dry_run else None)
    setup_logging(a.verbose, eng.secrets)
    return Service(eng).run()


# ------------------------------------------------------------------ test
def cmd_test(a) -> int:
    from .drivers import DriverError, make
    from .engine import DryRunDriver
    from . import sensors as SN
    p = C.paths()
    try:
        al = C.load_aliases(p)
    except ValueError as e:
        _die(str(e))
    spec = al.get(a.alias)
    if spec is None:
        print(f"{a.alias}: not bound (null in {p['aliases']}); nothing to test")
        return 1
    try:
        d = make(spec)
    except DriverError as e:
        _die(f"{a.alias}: {e}")
    desc = d.describe()
    if a.dry_run or C.load_config(p)["settings"].get("dry_run"):
        d = DryRunDriver(desc)
    print(f"{a.alias}: {d.describe()}")
    try:
        if a.action == "state":
            print(f"{a.alias} is {'on' if d.get() else 'off'}")
            return 0
        on = a.action == "on"
        if a.alias == "pump" and on:
            pp = al["pump_policy"]
            missing = [n for n in SN.REQUIRED if n not in SN.configured(pp)]
            if not pp.get("enabled") or missing:
                print("pump test refused: pump_policy.enabled must be true and float, leak and soil sensors "
                      f"must be listed (missing: {', '.join(missing) or 'none'})")
                return 1
            bad = [det for ok, det in (SN.check(n, pp["sensors"][n]) for n in ("float", "leak")) if not ok]
            if bad:
                print("pump test refused: " + "; ".join(bad))
                return 1
            secs = max(1, min(int(a.seconds), int(pp.get("max_run_s") or 1), C.HARD_MAX_DURATION_S["pump"]))
            print(f"pump on for {secs}s (Ctrl-C turns it off)")
            try:
                st = d.set(True)
                print(f"pump read-back: {'on' if st else 'off'}")
                end = time.time() + secs
                while time.time() < end:
                    time.sleep(0.5)
            finally:
                st = d.set(False)
                print(f"pump off, read-back: {'on' if st else 'off'}")
            return 0 if not st else 1
        st = d.set(on)
        print(f"{a.alias} switched {a.action}, read-back: {'on' if st else 'off'}")
        if a.alias != "pump":
            print("note: if the service is running it will see this as a manual change and hold this alias "
                  "until the next fallback boundary (`kalebridge release` ends it).")
        return 0 if st == on else 1
    except DriverError as e:
        print(f"{a.alias}: FAILED: {e}")
        return 1


# ------------------------------------------------------------------ status
def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def cmd_status(a) -> int:
    from .drivers import base as DB
    p = C.paths()
    c = C.load_config(p)
    st = C.read_json(p["state"], {}) or {}
    cache = C.read_json(p["cache"], None)
    try:
        al = C.load_aliases(p)
        al_err = None
    except ValueError as e:
        al, al_err = {}, str(e)
    running = _pid_alive(st.get("pid")) and time.time() - (st.get("updated_ts") or 0) < 120
    out = {
        "paired": bool(c.get("key")), "bridge_id": c.get("bridge_id"),
        "key_fingerprint": C.fingerprint(c["key"]) if c.get("key") else None,
        "paired_url": c.get("url"), "current_url": st.get("current_url") or c.get("url"),
        "rendezvous_relays": [r[1] for r in c.get("rv") or []], "last_seq": st.get("last_seq"),
        "service_running": running, "pid": st.get("pid") if running else None,
        "dry_run": st.get("dry_run", c["settings"].get("dry_run")),
        "last_contact": _age(st.get("last_contact_ts")), "fallback": st.get("fallback"),
        "devices": st.get("devices"), "holds": st.get("holds"), "timers": st.get("timers"),
        "outbox": len(st.get("outbox") or []), "rendezvous_last": st.get("rendezvous"),
        "bot_config_version": (cache or {}).get("version"), "bot_fallback": (cache or {}).get("fallback"),
        "aliases": {k: (None if al.get(k) is None else DB.redact(al[k])) for k in C.ALIASES} if al else None,
        "aliases_error": al_err, "pump_policy": al.get("pump_policy") if al else None,
        "aes_backend": aesgcm.backend(), "home": str(p["home"]), "version": VERSION,
    }
    if out["pump_policy"]:
        out["pump_policy"] = dict(out["pump_policy"], sensors={k: (None if v is None else DB.redact(v))
                                                               for k, v in (out["pump_policy"].get("sensors") or {}).items()})
    if a.live and al:
        from .drivers import DriverError, make
        live = {}
        for k in C.ALIASES:
            if al.get(k) is None:
                continue
            try:
                live[k] = "on" if make(al[k]).get() else "off"
            except DriverError as e:
                live[k] = f"error: {e}"
        out["live"] = live
    if a.json:
        print(json.dumps(out, indent=2))
        return 0
    print(f"kalebridge {VERSION}  home {out['home']}  crypto {out['aes_backend']}")
    if not out["paired"]:
        print("pairing:   NOT paired (kalebridge pair)")
    else:
        print(f"pairing:   bridge {out['bridge_id']}, key {out['key_fingerprint']}")
        print(f"bot:       {out['current_url']}" + ("" if out["current_url"] == out["paired_url"] else
                                                     f" (followed via rendezvous; paired with {out['paired_url']})"))
        print(f"relays:    {', '.join(out['rendezvous_relays']) or 'none'}; last accepted seq {out['last_seq'] or 0}")
    print(f"service:   {'RUNNING pid ' + str(out['pid']) if running else 'not running'}"
          f"{'  [DRY RUN]' if out['dry_run'] else ''}; last bot contact {out['last_contact']}")
    fb = out["fallback"] or {}
    print(f"fallback:  {'ACTIVE since ' + _age(fb.get('since_ts')) if fb.get('active') else 'off'}; "
          f"bot config {out['bot_config_version'] or 'never fetched'}")
    for k in C.ALIASES:
        b = (out["aliases"] or {}).get(k)
        line = f"  {k:5s}  " + ("unbound (null)" if b is None else f"{b.get('driver')} {b.get('host') or b.get('url') or ''}"
                                 + (f" ch{b['channel']}" if b.get("channel") is not None else ""))
        if b is not None:
            line += f"  state {(out['devices'] or {}).get(k) or '?'}"
            if (out["holds"] or {}).get(k):
                line += f"  HELD until {time.strftime('%H:%M', time.localtime(out['holds'][k]['until_ts']))}"
            if (out["timers"] or {}).get(k):
                line += f"  off-timer in {int(out['timers'][k]['off_ts'] - time.time())}s"
            if "live" in out:
                line += f"  live {out['live'].get(k)}"
        print(line)
    if al_err:
        print(f"aliases.json ERROR: {al_err}")
    pp = out["pump_policy"] or {}
    print(f"pump:      policy {'ENABLED' if pp.get('enabled') else 'disabled'}; sensors "
          f"{', '.join(k for k, v in (pp.get('sensors') or {}).items() if v) or 'none'}")
    if out["outbox"]:
        print(f"outbox:    {out['outbox']} result(s) waiting to be delivered")
    rl = out["rendezvous_last"] or {}
    if rl:
        print(f"rendezvous last read {rl.get('at')}: " + " ".join(
            f"{ch['label']}={ch.get('seq') if ch.get('ok') else 'x'}" for ch in rl.get("channels", [])))
    return 0


# ------------------------------------------------------------------ misc
def cmd_release(a) -> int:
    if a.alias not in C.ALIASES:
        _die("alias must be light, fan or pump")
    p = C.paths()
    d = p["home"] / "control"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"release-{a.alias}").write_text("")
    print(f"asked the running service to release the hold on {a.alias} (takes effect within a second)")
    return 0


def cmd_config(a) -> int:
    p = C.paths()
    c = C.load_config(p)
    if a.action == "show":
        print(json.dumps(c["settings"], indent=2))
        return 0
    if a.key not in C.DEFAULT_SETTINGS or a.value is None:
        _die(f"usage: kalebridge config set <key> <value>; keys: {', '.join(C.DEFAULT_SETTINGS)}")
    try:
        v = json.loads(a.value)
    except ValueError:
        v = a.value
    c["settings"][a.key] = v
    C.ensure_home(p["home"])
    C.save_config(c, p)
    print(f"{a.key} = {json.dumps(v)} (restart the service to apply)")
    return 0


def cmd_rendezvous(a) -> int:
    from . import rendezvous as R
    p = C.paths()
    c = C.load_config(p)
    _need_pairing(c)
    st = C.read_json(p["state"], {}) or {}
    d = R.discover(c["key"], c.get("rv") or [])
    for ch in d["channels"]:
        print(f"  {ch['label']:28s} " + (f"seq {ch['seq']} via {ch['via']} ({ch['valid']}/{ch['messages']} valid)"
                                         if ch["ok"] else f"nothing valid ({ch.get('error') or 'no messages'})"))
    b = d["best"]
    cur = st.get("current_url") or c.get("url")
    if not b:
        print("no valid rendezvous message found")
        return 1
    print(f"newest: seq {b['seq']} issued {b.get('issued_at')} url {b['url']}"
          + ("  (same as current)" if b["url"].rstrip("/") == cur else "  (DIFFERENT from current " + str(cur) + ")"))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kalebridge", description="KALE 9000 reference bridge")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("pair", help="store the pairing blob (mode 600)")
    p.add_argument("blob", nargs="?", help="the blob, or - to read stdin; omit to be prompted (keeps it out of shell history)")
    p.add_argument("--check", action="store_true", help="also contact the bot once")
    p.set_defaults(fn=cmd_pair)
    p = sp.add_parser("run", help="run the bridge service")
    p.add_argument("--dry-run", action="store_true", help="log commands, switch nothing")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_run)
    p = sp.add_parser("test", help="switch or read one alias locally (no bot involved)")
    p.add_argument("alias", choices=C.ALIASES)
    p.add_argument("action", choices=C.ACTIONS)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--seconds", type=int, default=5, help="pump only: run time before auto-off (default 5)")
    p.set_defaults(fn=cmd_test)
    p = sp.add_parser("status", help="pairing, service, fallback, holds, timers, aliases")
    p.add_argument("--json", action="store_true")
    p.add_argument("--live", action="store_true", help="also read every bound plug now")
    p.set_defaults(fn=cmd_status)
    p = sp.add_parser("release", help="end a manual-change hold now")
    p.add_argument("alias")
    p.set_defaults(fn=cmd_release)
    p = sp.add_parser("config", help="show or change settings")
    p.add_argument("action", choices=["show", "set"], nargs="?", default="show")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(fn=cmd_config)
    p = sp.add_parser("rendezvous", help="read the relays now (read-only)")
    p.set_defaults(fn=cmd_rendezvous)
    p = sp.add_parser("version")
    p.set_defaults(fn=lambda a: print(f"kalebridge {VERSION} (python {sys.version.split()[0]}, crypto {aesgcm.backend()})") or 0)
    a = ap.parse_args(argv)
    return int(a.fn(a) or 0)


if __name__ == "__main__":
    sys.exit(main())
