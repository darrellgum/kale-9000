#!/usr/bin/env python3
"""kalecam - local-only control CLI for the phone camera (talks to files, never to the network
except `pair`/`publish`/`rendezvous`/`watchdog`).

  kalecam capture [CAMERA|all] [--wait 90] [--plant ID] [--settings JSON]
  kalecam status [--json] [--check]
  kalecam schedule show | set [--interval MIN] [--start HH:MM] [--end HH:MM] [--on|--off]
  kalecam config get [KEY] | set KEY VALUE        (dotted keys, JSON values)
  kalecam pair [--plant ID] [--camera NAME] [--rotate-secret] [--quiet]
  kalecam photos [--plant ID] [-n 5]
  kalecam cancel [ID|--all]
  kalecam reload [CAMERA]                          (ask the page to reload itself)
  kalecam publish [--force]                        (push the address to the rendezvous now)
  kalecam rendezvous                               (read back + decrypt every channel)
  kalecam watchdog [...]                           (one watchdog pass)
  kalecam bridge pair|send|status|config|cancel    (home device bridge, see bridge_cli.py)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kalecam_lib as K  # noqa: E402


def age(ts: float | None) -> str:
    if ts is None:
        return "never"
    s = int(time.time() - ts)
    return f"{s}s ago" if s < 120 else f"{s // 60}m ago" if s < 7200 else f"{s // 3600}h ago"


def iso_ts(s: str | None) -> float | None:
    if not s:
        return None
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def known_cameras() -> list[str]:
    cams = {p.stem for p in K.HB_DIR.glob("*.json")} | {p.name[:-9] for p in K.HB_DIR.glob("*.lastpoll")}
    return sorted(cams)


# ------------------------------------------------------------------ capture
def cmd_capture(a) -> int:
    cfg = K.load_config()
    targets = [a.camera or cfg["default_camera"]]
    if targets[0] in ("all", "*"):
        targets = known_cameras() or [cfg["default_camera"]]
    settings = json.loads(a.settings) if a.settings else {}
    cmds = [K.queue_command(cam, "capture", settings, a.plant) for cam in targets]
    for c in cmds:
        print(json.dumps({"queued": c["id"], "camera": c["camera"]}))
    if not a.wait:
        return 0
    end = time.time() + a.wait
    pending = {c["id"] for c in cmds}
    rc = 0
    while pending and time.time() < end:
        for cid in list(pending):
            st, c = K.command_status(cid)
            if st == "done":
                pending.discard(cid)
                out = {"id": cid, "status": c.get("status"), "camera": c.get("camera"), "file": c.get("file"),
                       "bytes": c.get("bytes"), "done_at": c.get("done_at")}
                print(json.dumps(out))
                rc |= 0 if c.get("status") == "done" else 1
        time.sleep(0.5)
    for cid in pending:
        st, c = K.command_status(cid)
        print(json.dumps({"id": cid, "status": f"timeout ({st})",
                          "hint": "phone offline? check `kalecam status`; the command stays queued"}))
        rc = 2
    return rc


# ------------------------------------------------------------------ status
def gather_status(check: bool) -> dict:
    cfg = K.load_config()
    wd = K.read_json(K.WATCHDOG_STATE, {}) or {}
    ps = K.read_json(K.PUBLISH_STATE, {}) or {}
    out: dict = {"now": K.iso(K.now_local())}
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{cfg['port']}/healthz", timeout=3) as r:
            out["server"] = json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        out["server"] = {"ok": False, "error": str(e)}
    url = K.current_url()
    out["tunnel"] = {"url": url, "cloudflared_pid": wd.get("cloudflared_pid"),
                     "cloudflared_alive": K.pid_alive(wd.get("cloudflared_pid"), "cloudflared"),
                     "started_at": wd.get("cloudflared_started_at")}
    if check and url:
        try:
            with urllib.request.urlopen(url + "/healthz", timeout=10) as r:
                j = json.loads(r.read())
            out["tunnel"]["public_ok"] = j.get("instance") == out["server"].get("instance")
        except Exception as e:  # noqa: BLE001
            out["tunnel"]["public_ok"] = False
            out["tunnel"]["public_error"] = str(e)
    loop_pid = None
    try:
        loop_pid = int((K.STATE / "watchdog-loop.pid").read_text())
    except (OSError, ValueError):
        pass
    out["watchdog"] = {"last_run_at": wd.get("last_run_at"), "last_run_ok": wd.get("last_run_ok"),
                       "loop_pid": loop_pid, "loop_alive": K.pid_alive(loop_pid, "watchdog.sh")}
    out["rendezvous"] = {"seq": ps.get("seq"), "url_published": ps.get("url"),
                         "channels": {k: {"last_ok_at": v.get("last_ok_at"), "error": v.get("error"),
                                          "via": v.get("via")} for k, v in ps.get("channels", {}).items()}}
    cams = {}
    for cam in known_cameras() or [cfg["default_camera"]]:
        hb = K.read_json(K.HB_DIR / f"{cam}.json", None)
        lp = K.HB_DIR / f"{cam}.lastpoll"
        info = {"last_poll": lp.read_text().strip() if lp.exists() else None,
                "last_poll_age_s": int(time.time() - lp.stat().st_mtime) if lp.exists() else None}
        if hb:
            info.update({"heartbeat_at": hb.get("received_at"),
                         "heartbeat_age_s": int(time.time() - hb.get("received_ts", 0)),
                         "battery": hb.get("battery"), "temperature_c": hb.get("temperature_c"),
                         "queue": hb.get("queue"), "last_capture": hb.get("last_capture"),
                         "last_upload": hb.get("last_upload"), "app_version": hb.get("app_version"),
                         "visible": hb.get("visible"), "wake_lock": hb.get("wake_lock"),
                         "camera_label": hb.get("camera_label"), "resolution": hb.get("resolution"),
                         "api_base": hb.get("api_base"), "page_origin": hb.get("page_origin"),
                         "errors": hb.get("errors")})
            warn = []
            if info["heartbeat_age_s"] > 3 * int(cfg.get("heartbeat_s", 60)) + 30:
                warn.append("heartbeat stale (phone offline, page closed or tab in background)")
            b = hb.get("battery") or {}
            if isinstance(b.get("level"), (int, float)) and b["level"] < 0.2 and not b.get("charging"):
                warn.append("battery low and not charging")
            if hb.get("visible") is False:
                warn.append("page not visible: browser will throttle it")
            if (hb.get("queue") or 0) > 5:
                warn.append(f"{hb.get('queue')} photos queued on the phone")
            info["warnings"] = warn
        cams[cam] = info
    out["cameras"] = cams
    out["pending_commands"] = [K.read_json(p, {}) .get("id") for p in sorted((K.CMD_DIR / "pending").glob("*.json"))]
    out["delivered_commands"] = [K.read_json(p, {}).get("id") for p in sorted((K.CMD_DIR / "delivered").glob("*.json"))]
    root = Path(cfg["photo_root"])
    plants = {}
    if root.exists():
        for idx in sorted(root.glob("*/index.jsonl")):
            last = None
            with idx.open() as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("received_at"):
                        last = r
            if last:
                plants[idx.parent.name] = {"file": str(idx.parent / last["file"]), "ts": last.get("ts"),
                                           "trigger": last.get("trigger"), "source": last.get("source")}
    out["last_photo"] = plants
    out["schedule"] = cfg["schedule"]
    out["migrate"] = cfg.get("migrate")
    return out


def cmd_status(a) -> int:
    s = gather_status(a.check)
    if a.json:
        print(json.dumps(s, indent=2))
        return 0
    srv = s["server"]
    print(f"server:    {'UP' if srv.get('ok') else 'DOWN'}" + (f" (instance {srv.get('instance')}, up {srv.get('uptime_s')}s)" if srv.get("ok") else f" {srv.get('error')}"))
    t = s["tunnel"]
    pub = "" if "public_ok" not in t else (" public:OK" if t["public_ok"] else f" public:FAIL")
    print(f"tunnel:    {'UP' if t['cloudflared_alive'] else 'DOWN'} {t['url']}{pub}")
    w = s["watchdog"]
    print(f"watchdog:  loop {'running pid ' + str(w['loop_pid']) if w['loop_alive'] else 'NOT running'}; last run {w['last_run_at']} ok={w['last_run_ok']}")
    r = s["rendezvous"]
    print(f"rendezvous: seq {r['seq']}")
    for k, v in r["channels"].items():
        print(f"   {k:28s} last ok {v['last_ok_at']}" + (f"  ERROR {v['error']}" if v["error"] else "") + (f" via {v['via']}" if v.get('via') not in (None, 'https') else ""))
    sch = s["schedule"]
    print(f"schedule:  {'every ' + str(sch['interval_min']) + ' min ' + sch['start'] + '-' + sch['end'] if sch['enabled'] else 'OFF'}; migrate={s['migrate']}")
    for cam, c in s["cameras"].items():
        if "heartbeat_age_s" not in c:
            print(f"camera {cam}: no heartbeat yet (phone not paired/connected)"
                  + (f", last poll {c['last_poll_age_s']}s ago" if c.get("last_poll_age_s") is not None else ""))
            continue
        b = c.get("battery") or {}
        bl = f"{round(b['level'] * 100)}%{' charging' if b.get('charging') else ''}" if isinstance(b.get("level"), (int, float)) else "n/a"
        print(f"camera {cam}: heartbeat {c.get('heartbeat_age_s', 'never')}s ago, last poll {c.get('last_poll_age_s')}s ago, "
              f"battery {bl}, temp {c.get('temperature_c') or 'n/a'}, queue {c.get('queue')}, last capture {c.get('last_capture')}, "
              f"app {c.get('app_version')}, wake lock {c.get('wake_lock')}")
        for wmsg in c.get("warnings", []):
            print(f"   WARNING: {wmsg}")
    if s["pending_commands"] or s["delivered_commands"]:
        print(f"commands:  pending {s['pending_commands']} delivered {s['delivered_commands']}")
    for p, l in s["last_photo"].items():
        print(f"last photo {p}: {l['ts']} ({l['trigger']}, {l['source']}) {l['file']}")
    try:
        import bridge_cli
        line = bridge_cli.summary_line()
        if line:
            print(line)
    except Exception as e:  # noqa: BLE001
        print(f"bridge:    status unavailable ({type(e).__name__}: {e})")
    return 0


# ------------------------------------------------------------------ schedule / config
def _set_dotted(d: dict, key: str, val) -> None:
    parts = key.split(".")
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = val


def cmd_schedule(a) -> int:
    cfg = K.load_config()
    over = K.read_json(K.CONFIG_PATH, {}) or {}
    if a.action == "set":
        sch = dict(cfg["schedule"])
        if a.interval is not None:
            if a.interval < 1:
                sys.exit("interval must be >= 1 minute")
            sch["interval_min"] = a.interval
        for k in ("start", "end"):
            v = getattr(a, k)
            if v is not None:
                h, m = map(int, v.split(":"))
                assert 0 <= h < 24 and 0 <= m < 60
                sch[k] = f"{h:02d}:{m:02d}"
        if a.on:
            sch["enabled"] = True
        if a.off:
            sch["enabled"] = False
        over["schedule"] = sch
        K.save_config_overrides(over)
        cfg = K.load_config()
    print(json.dumps(cfg["schedule"]))
    return 0


def cmd_config(a) -> int:
    cfg = K.load_config()
    if a.action == "get":
        v = cfg
        for p in (a.key.split(".") if a.key else []):
            v = v[p]
        print(json.dumps(v, indent=2))
        return 0
    over = K.read_json(K.CONFIG_PATH, {}) or {}
    try:
        val = json.loads(a.value)
    except ValueError:
        val = a.value
    if a.key == "migrate" and val not in ("sticky", "navigate"):
        sys.exit("migrate must be 'sticky' or 'navigate'")
    _set_dotted(over, a.key, val)
    K.save_config_overrides(over)
    print(f"{a.key} = {json.dumps(val)}")
    return 0


# ------------------------------------------------------------------ pair
def cmd_pair(a) -> int:
    cfg = K.load_config()
    plant = a.plant or cfg["default_plant"]
    camera = a.camera or cfg["default_camera"]
    if not K.PLANT_RE.match(plant) or not K.CAMERA_RE.match(camera):
        sys.exit("bad plant id or camera name")
    pairing, created = K.ensure_pairing(cfg, rotate=a.rotate_secret)
    url = K.current_url()
    if not url or a.rotate_secret or created:
        subprocess.run([str(K.BASE / "watchdog.sh"), "--quiet", "--force-publish"] if url else
                       [str(K.BASE / "watchdog.sh"), "--quiet"], check=False)
        url = K.current_url()
    if not url:
        sys.exit("no tunnel URL yet; check logs/watchdog.log")
    link, version = K.write_pairing_qr(pairing, url, plant, camera)
    print(f"QR code: {K.QR_PATH}  (version {version}, contains the pairing secret; chmod 600)")
    print("The watchdog refreshes this QR/link automatically whenever the tunnel URL changes.")
    print(f"plant={plant} camera={camera}  secret {'NEW' if created or a.rotate_secret else 'existing'}")
    if a.quiet:
        print(f"pairing URL: {url}/app#<secret pairing blob>  (full link in {K.PAIRING_URL_PATH})")
    else:
        print("pairing URL (contains the secret; open it on the phone or scan the QR):")
        print(link)
    return 0


# ------------------------------------------------------------------ misc
def cmd_photos(a) -> int:
    cfg = K.load_config()
    root = Path(cfg["photo_root"])
    plants = [a.plant] if a.plant else sorted(p.parent.name for p in root.glob("*/index.jsonl"))
    for pl in plants:
        idx = root / pl / "index.jsonl"
        if not idx.exists():
            continue
        rows = []
        for line in idx.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
        for r in rows[-a.n:]:
            print(json.dumps({"plant": pl, "path": str(root / pl / r["file"]), "ts": r.get("ts"),
                              "trigger": r.get("trigger"), "source": r.get("source"), "bytes": r.get("bytes"),
                              "queued": r.get("queued"), "size": f"{r.get('width')}x{r.get('height')}"}))
    return 0


def cmd_cancel(a) -> int:
    n = 0
    for p in (K.CMD_DIR / "pending").glob("*.json"):
        if a.all or p.stem == a.id:
            p.unlink()
            n += 1
    print(f"cancelled {n} pending command(s)")
    return 0


def cmd_reload(a) -> int:
    cfg = K.load_config()
    c = K.queue_command(a.camera or cfg["default_camera"], "reload")
    print(json.dumps({"queued": c["id"], "cmd": "reload"}))
    return 0


def cmd_publish(a) -> int:
    return subprocess.call([str(K.BASE / "watchdog.sh")] + (["--force-publish"] if a.force else []))


def cmd_rendezvous(a) -> int:
    import rendezvous as RV
    pairing = K.load_pairing()
    if not pairing:
        sys.exit("not paired")
    for c in pairing["channels"]:
        r = RV.read_one(c, pairing)
        lat = r.get("latest") or {}
        print(json.dumps({"channel": RV.channel_label(c), "ok": r.get("ok"), "via": r.get("via"),
                          "messages": r.get("messages"), "valid": r.get("valid"), "seq": lat.get("seq"),
                          "url": lat.get("url"), "issued_at": lat.get("issued_at"), "error": r.get("error")}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="kalecam", description="KALE 9000 phone camera control (local only)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("capture"); p.add_argument("camera", nargs="?"); p.add_argument("--wait", type=float, default=0)
    p.add_argument("--plant"); p.add_argument("--settings"); p.set_defaults(fn=cmd_capture)
    p = sp.add_parser("status"); p.add_argument("--json", action="store_true"); p.add_argument("--check", action="store_true"); p.set_defaults(fn=cmd_status)
    p = sp.add_parser("schedule"); p.add_argument("action", choices=["show", "set"], nargs="?", default="show")
    p.add_argument("--interval", type=int); p.add_argument("--start"); p.add_argument("--end")
    p.add_argument("--on", action="store_true"); p.add_argument("--off", action="store_true"); p.set_defaults(fn=cmd_schedule)
    p = sp.add_parser("config"); p.add_argument("action", choices=["get", "set"]); p.add_argument("key", nargs="?"); p.add_argument("value", nargs="?")
    p.set_defaults(fn=cmd_config)
    p = sp.add_parser("pair"); p.add_argument("--plant"); p.add_argument("--camera"); p.add_argument("--rotate-secret", action="store_true")
    p.add_argument("--quiet", action="store_true", help="don't print the secret link (it's saved in secrets/)"); p.set_defaults(fn=cmd_pair)
    p = sp.add_parser("photos"); p.add_argument("--plant"); p.add_argument("-n", type=int, default=5); p.set_defaults(fn=cmd_photos)
    p = sp.add_parser("cancel"); p.add_argument("id", nargs="?"); p.add_argument("--all", action="store_true"); p.set_defaults(fn=cmd_cancel)
    p = sp.add_parser("reload"); p.add_argument("camera", nargs="?"); p.set_defaults(fn=cmd_reload)
    p = sp.add_parser("publish"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_publish)
    p = sp.add_parser("rendezvous"); p.set_defaults(fn=cmd_rendezvous)
    p = sp.add_parser("watchdog"); p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(fn=lambda a: subprocess.call([str(K.BASE / "watchdog.sh")] + a.rest))
    import bridge_cli
    bridge_cli.add_parser(sp)
    a = ap.parse_args()
    if a.cmd == "config" and a.action == "set" and (a.key is None or a.value is None):
        ap.error("config set KEY VALUE")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
