"""`kalecam bridge ...` subcommands (local only; talks to files, never to the network).

  kalecam bridge pair [--bridge-id bridge-1] [--rotate-key]
  kalecam bridge send <light|fan|pump> <on|off|state> [--duration S] [--expires S] [--wait N] [--bridge ID]
  kalecam bridge status [--json]
  kalecam bridge config show | set <key> <value>
  kalecam bridge cancel [ID | --all]
  kalecam bridge publish [--force]      (encrypted rendezvous for the bridge; the watchdog does this)
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import bridge_lib as B
import kalecam_lib as K


def _age(s):
    if s is None:
        return "never"
    return f"{s}s ago" if s < 120 else f"{s // 60}m ago" if s < 7200 else f"{s // 3600}h ago"


# ------------------------------------------------------------------ pair
def cmd_pair(a) -> int:
    bc = B.bridge_config()
    url = bc.get("public_base_url") or K.current_url()
    if not url:
        sys.exit("no public URL: set `kalecam bridge config set public_base_url https://...` or start the tunnel")
    existing = B.load_key() or {}
    bid = a.bridge_id or existing.get("bridge_id") or "bridge-1"
    if not B.BRIDGE_RE.match(bid):
        sys.exit("bridge id must be letters, digits, '.', '_' or '-' (max 32)")
    d, created = B.ensure_key(bid, rotate=a.rotate_key)
    rv = []
    try:  # relay list for the bridge's encrypted rendezvous (topics are derived from the key)
        import bridge_rendezvous as BRV
        rv = BRV.blob_rv(K.load_config())
    except Exception as e:  # noqa: BLE001
        print(f"warning: rendezvous relays not added to the blob ({type(e).__name__})")
    path = B.write_pairing_file(url, d["key"], d["bridge_id"], rv)
    B.log_event("paired", bridge_id=d["bridge_id"], key_fingerprint=B.fingerprint(d["key"]),
                new_key=bool(created or a.rotate_key), url_source="public_base_url" if bc.get("public_base_url") else "quick_tunnel")
    print(f"pairing file: {path}")
    print(f"key fingerprint: {B.fingerprint(d['key'])}  ({'NEW key' if created else 'existing key'}, bridge id {d['bridge_id']})")
    if not bc.get("public_base_url"):
        print("note: the URL inside is the current quick-tunnel URL and changes when the tunnel restarts. "
              + ("The bridge follows new URLs through the encrypted rendezvous (relays: "
                 + ", ".join(r[1] for r in rv) + "); the watchdog publishes them." if rv else
                 "No rendezvous relays are configured, so re-run `kalecam bridge pair` after a restart."))
    return 0


# ------------------------------------------------------------------ rendezvous publish
def cmd_publish(a) -> int:
    import bridge_rendezvous as BRV
    cfg = K.load_config()
    res = BRV.maybe_publish(cfg, K.current_url(), force=a.force)
    if res is None:
        st = BRV.status()
        print("nothing to publish (not paired, no URL, no relays, or already up to date; use --force)"
              + (f"; last seq {st.get('seq')}" if st.get("seq") else ""))
        return 0
    return 0 if any(v["ok"] for v in res["results"].values()) else 1


def rendezvous_line() -> str | None:
    try:
        import bridge_rendezvous as BRV
        st = BRV.status()
    except Exception:  # noqa: BLE001
        return None
    if not st.get("seq"):
        return None
    ch = st.get("channels", {})
    ok = [k for k, v in ch.items() if not v.get("error")]
    bad = [k for k, v in ch.items() if v.get("error")]
    return (f"rendezvous (bridge): seq {st['seq']} url {st.get('url')} ok {len(ok)}/{len(ch)}"
            + (f" failing {bad}" if bad else ""))


# ------------------------------------------------------------------ send
def cmd_send(a) -> int:
    try:
        c = B.queue(a.device, a.action, a.duration, a.expires, bridge=a.bridge, source="cli")
    except ValueError as e:
        print(json.dumps({"rejected": str(e)}))
        return 3
    out = {"queued": c["id"], "device": c["device"], "action": c["action"], "expires_at": c["expires_at"]}
    if c.get("duration_s") is not None:
        out["duration_s"] = c["duration_s"]
    if c.get("duration_capped_from") is not None:
        out["duration_capped_from"] = c["duration_capped_from"]
    print(json.dumps(out))
    if not a.wait:
        return 0
    end = time.time() + a.wait
    while time.time() < end:
        st, r = B.command_status(c["id"])
        if st == "done":
            res = r.get("result") or {}
            print(json.dumps({"id": c["id"], "status": r.get("status"), "state": res.get("state"),
                              "error": r.get("error"), "at": res.get("at"), "closed_by": r.get("closed_by")}))
            return 0 if r.get("status") == "done" else 1
        time.sleep(0.3)
    st, r = B.command_status(c["id"])
    print(json.dumps({"id": c["id"], "status": f"timeout ({st})",
                      "hint": "bridge offline? see `kalecam bridge status`; the command stays queued until it expires"}))
    return 2


# ------------------------------------------------------------------ status
def cmd_status(a) -> int:
    s = B.status()
    if a.json:
        print(json.dumps(s, indent=2))
        return 0
    print(f"bridge key: {'paired, fingerprint ' + s['key_fingerprint'] + ', bridge id ' + str(s['bridge_id']) if s['paired'] else 'NOT paired (kalecam bridge pair)'}")
    print(f"public url: {s['public_base_url'] or '(quick tunnel) ' + str(K.current_url())}; config version {s['config_version']}")
    rl = rendezvous_line()
    if rl:
        print(rl)
    if not s["bridges"]:
        print("bridges:    none has connected yet")
    for b, i in s["bridges"].items():
        if "heartbeat_age_s" in i:
            print(f"bridge {b}: {'ONLINE' if i['online'] else 'OFFLINE'}, heartbeat {_age(i['heartbeat_age_s'])}, "
                  f"last poll {_age(i['last_poll_age_s'])}, version {i['version']}, uptime {i['uptime_s']}s, "
                  f"fallback_active {i['fallback_active']}")
            print(f"   devices {json.dumps(i['devices'])}  holds {json.dumps(i['holds'])}")
        else:
            print(f"bridge {b}: no heartbeat yet, last poll {_age(i['last_poll_age_s'])}")
    print(f"pending:    {len(s['pending'])}" + "".join(f"\n   {c['id']} {c['device']} {c['action']}"
                                                         + (f" {c['duration_s']}s" if c.get('duration_s') else "")
                                                         + f" expires {c['expires_at']}" for c in s["pending"]))
    print(f"delivered:  {len(s['delivered'])} awaiting result" + "".join(
        f"\n   {c['id']} {c['device']} {c['action']} attempts {c.get('attempts')}" for c in s["delivered"]))
    print("recent results:")
    for c in s["recent"]:
        r = c.get("result") or {}
        print(f"   {c['id']} {c['device']} {c['action']} -> {c['status']}"
              + (f" state={r.get('state')}" if r.get("state") else "")
              + (f" error={c.get('error')}" if c.get("error") else "") + f" ({c.get('closed_by')})")
    return 0


def summary_line() -> str | None:
    """One line for `kalecam status`."""
    s = B.status(recent=0)
    if not s["paired"] and not s["bridges"]:
        return None
    parts = []
    for b, i in s["bridges"].items():
        if "heartbeat_age_s" in i:
            parts.append(f"{b} {'online' if i['online'] else 'OFFLINE'} (heartbeat {_age(i['heartbeat_age_s'])}, "
                         f"fallback {i['fallback_active']})")
        else:
            parts.append(f"{b} no heartbeat yet")
    return (f"bridge:    {'; '.join(parts) or 'paired, never connected'}; pending {len(s['pending'])}, "
            f"awaiting result {len(s['delivered'])}")


# ------------------------------------------------------------------ config
def cmd_config(a) -> int:
    if a.action == "show":
        print(json.dumps(B.bridge_config(), indent=2))
        return 0
    if a.key is None or a.value is None:
        sys.exit("usage: kalecam bridge config set <key> <value>   (dotted keys, JSON values)")
    top = a.key.split(".")[0]
    if top not in B.DEFAULT_BRIDGE_CONFIG:
        sys.exit(f"unknown bridge config key {top!r}; known: {', '.join(B.DEFAULT_BRIDGE_CONFIG)}")
    try:
        val = json.loads(a.value)
    except ValueError:
        val = a.value
    if a.key == "fallback.light":
        try:
            val = B.parse_light_schedule(val)
        except ValueError as e:
            sys.exit(str(e))
    over = K.read_json(K.CONFIG_PATH, {}) or {}
    bover = dict(over.get("bridge") or {})
    d = bover
    parts = a.key.split(".")
    for p in parts[:-1]:  # defaults fill in the rest via deep_merge
        d[p] = dict(d[p]) if isinstance(d.get(p), dict) else {}
        d = d[p]
    d[parts[-1]] = val
    merged = K.deep_merge(B.DEFAULT_BRIDGE_CONFIG, bover)
    try:
        B.validate_bridge_config(merged)
    except ValueError as e:
        sys.exit(f"rejected: {e}")
    over["bridge"] = bover
    K.save_config_overrides(over)
    B.log_event("config_set", key=a.key, value=val, config_version=B.public_config(merged)["version"])
    print(f"bridge.{a.key} = {json.dumps(val)}  (config version {B.public_config(merged)['version']})")
    return 0


def cmd_cancel(a) -> int:
    if not a.all and not a.id:
        sys.exit("give a command id or --all")
    print(f"cancelled {B.cancel(a.id, a.all)} pending bridge command(s)")
    return 0


# ------------------------------------------------------------------ argparse
def add_parser(sp) -> None:
    bp = sp.add_parser("bridge", help="home device bridge (light/fan/pump switches)")
    bsp = bp.add_subparsers(dest="bridge_cmd", required=True)
    p = bsp.add_parser("pair"); p.add_argument("--bridge-id"); p.add_argument("--rotate-key", action="store_true")
    p.set_defaults(fn=cmd_pair)
    p = bsp.add_parser("send"); p.add_argument("device"); p.add_argument("action")
    p.add_argument("--duration", type=int, help="seconds; 'on' only, bridge turns it off afterwards")
    p.add_argument("--expires", type=int, help="seconds from now (default bridge.default_expires_s)")
    p.add_argument("--wait", type=float, default=0, help="block up to N s for the result")
    p.add_argument("--bridge", help="target bridge id (default: any bridge)")
    p.set_defaults(fn=cmd_send)
    p = bsp.add_parser("status"); p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_status)
    p = bsp.add_parser("config"); p.add_argument("action", choices=["show", "set"], nargs="?", default="show")
    p.add_argument("key", nargs="?"); p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_config)
    p = bsp.add_parser("cancel"); p.add_argument("id", nargs="?"); p.add_argument("--all", action="store_true")
    p.set_defaults(fn=cmd_cancel)
    p = bsp.add_parser("publish", help="publish the bridge URL to the encrypted rendezvous relays now")
    p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_publish)
    _ = argparse  # keep import for type hints/tools
