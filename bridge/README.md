# KALE 9000 reference bridge (beta)

> **Beta. Not tested on real hardware.** The drivers and the full bot ↔ bridge path pass automated
> tests against fake Shelly/Tasmota/Kasa devices and a real kalecam server, but no one has run this
> release against physical plugs yet. Start with the `dummy` driver, then one low-risk plug (a fan),
> and watch it for a few days before trusting it with a light or a pump. Report problems on GitHub.

A small program that lets your KALE 9000 plant-care bot switch the grow tent's **light**, **fan** and
(only if you set it up with sensors) **pump**, using ordinary Wi-Fi smart plugs in your home.

- It runs on a computer that is always on in your home: a Raspberry Pi, an old laptop, a home server.
- It **dials out** to the bot over HTTPS and asks "anything for me?" about every 25 seconds. Nothing
  on your home network is opened to the internet. No router or port-forwarding changes.
- It talks to your plugs **locally** on your Wi-Fi. It needs **no cloud account** of any kind: not
  for the plugs, not for the bridge, not for the bot connection.
- Standard Python 3.9+ only. Nothing to `pip install`.
- If the bot can't be reached for 10 minutes, it keeps the tent running on its own with the last
  schedule the bot gave it (see [What happens when...](#what-happens-when)).

```
  KALE 9000 (cloud)  <--- HTTPS, outbound only ---  this bridge (your Pi)  --- Wi-Fi --->  smart plugs
```

---

## 1. What hardware works

| Plug family | Driver name | Account needed? | Notes |
|---|---|---|---|
| **Shelly Gen2 / Plus / Pro / Gen3** (Plus Plug US/UK/IT/S, Plus 1, Plus 1PM, Pro 2...) | `shelly_gen2` | No | Recommended. Optional password (digest auth) supported. |
| **Shelly Gen1** (Shelly 1, 1PM, 2.5, Plug, Plug S) | `shelly_gen1` | No | Optional password (basic auth) supported. |
| **Tasmota** (any plug/relay flashed with Tasmota, e.g. many Athom, Sonoff, Gosund) | `tasmota` | No | Optional web password supported. Multi-relay strips: set `channel`. |
| **TP-Link Kasa, older firmware** (HS100/103/105/110, KP115, HS300, KP303...) | `kasa` | No (for the bridge) | **Experimental.** Only plugs that still answer the old local protocol on port 9999. Newer Kasa firmware ("KLAP") needs TP-Link cloud credentials and is **not supported**. |
| **Home Assistant** (anything HA can switch: Zigbee, Z-Wave, Matter, ...) | `homeassistant` | No cloud account; needs a local HA long-lived token | Optional. Uses your HA on your LAN. |
| **Dummy** | `dummy` | No | Switches nothing. For practice and dry runs. |

**Not supported:** plugs that only work through a vendor cloud (most Tuya/Smart Life, Meross, Govee,
Wyze, Amazon/Google-branded plugs), and other plugs without a documented local API. If Home Assistant can control them
locally, use the `homeassistant` driver.

Tip: when you first set up a plug, give it a **fixed IP address** (a "DHCP reservation" in your router),
so its address never changes. Shelly and Tasmota plugs can be set up from their own built-in web page
without any account. Set a device password if the plug offers one, and put it in `aliases.json`.

**The computer:** any always-on Linux machine with Python 3.9 or newer (Raspberry Pi OS Bullseye or
newer is fine; a Pi Zero 2 W is plenty). It must be on the same network as the plugs.
Windows and macOS: it runs fine by hand (`python3 kalebridge.py run`), but there is no installer or
auto-start for them; you'd set that up yourself (Task Scheduler / launchd). On Windows, install the
`tzdata` package (`py -m pip install tzdata`) or the fallback schedule uses the computer's local time.

---

## 2. Safety first (please read)

Software can fail. Plugs can stick. Wi-Fi drops. Set things up so that **a failure is boring, not
dangerous.**

**Plug ratings**
- Check the plug's rating (printed on it, e.g. "15 A / 1800 W" or "10 A / 2300 W"). Keep the
  continuous load at **no more than 80%** of that rating (e.g. no more than 1440 W on a 15 A / 1800 W plug).
- LED grow lights and motors pull a short surge when they turn on. Use a plug rated well above the
  label wattage, and prefer plugs rated for "inductive" or "motor" loads for fans and pumps.
- Don't plug heaters or humidifiers into a small plug unless its rating clearly covers them.
- Don't chain power strips. Keep plugs and cords off the floor of the tent and away from water.
  Use a GFCI/RCD-protected outlet anywhere near water.

**Pump (watering) safety.** The bridge **refuses the pump** until you deliberately turn it on in
`aliases.json` *and* list three sensors it can read on your network: a reservoir **float**, a
**leak** sensor, and a **soil** moisture reading. A "the soil is dry" flag inside a message from the
bot is **not** a sensor, and the bridge will never treat it as one. Even then:
- Every pump run must be timed. The bridge caps each run (`max_run_s`, and never more than 10 minutes),
  caps the daily total (`max_daily_s`, never more than 30 minutes), and enforces a gap between runs
  (`min_interval_s`).
- While the pump runs, the bridge re-checks the float and leak sensors every 2 seconds and cuts the
  pump if either reads bad or can't be read.
- **Also use hardware protection that doesn't depend on any software:** a float switch wired in series
  with the pump so it physically can't run dry or overfill, a drip tray, and ideally a reservoir that
  holds *less* water than the tray can catch.
- Keep a **manual off**: know which plug to pull, or put a physical switch in line.
- Test the whole setup with a bucket before it goes near your plants.

When in doubt, leave `pump` as `null`. Light and fan work fine without it.

---

## 3. Step-by-step setup (Raspberry Pi / Linux)

You'll need about 20 minutes. Commands go in a terminal on the Pi.

**Step 1: Copy the bridge onto the Pi.** Download the release tarball from the project's GitHub
Releases page, unpack it, and put its `bridge` folder on the Pi, for example as
`~/kalebridge` (USB stick, `scp`, or download). Then:

```bash
cd ~/kalebridge
python3 kalebridge.py version        # should print "kalebridge 0.1.0 (python 3.x, crypto ...)"
```

**Step 2: Get your pairing blob from the bot.** Ask the bot for a bridge pairing blob. (Bot owners run
`kalecam bridge pair`; the blob is in `/workspace/kalecam/secrets/bridge-pairing.txt` on the bot's computer.) It's one long line of
letters. Treat it like a password: it contains the key that lets the bridge talk to your bot.

**Step 3: Pair.**

```bash
python3 kalebridge.py pair --check
```

Paste the blob when asked (the input is hidden so it doesn't end up in your shell history), press Enter.
You should see `paired: bridge id ..., key fingerprint sha256:...` and `check: OK`. The fingerprint is the
same one the bot shows in `kalecam bridge status`, so you can compare them without revealing the key.
This creates `~/.config/kalebridge/` (only you can read it) with `config.json` and `aliases.json`.

**Step 4: Tell the bridge which plug is which.** Open `~/.config/kalebridge/aliases.json` in an editor
(`nano ~/.config/kalebridge/aliases.json`). Every alias starts as `null` (unbound: commands for it fail
and nothing is switched). Fill in the ones you have, for example:

```json
{
  "light": {"driver": "shelly_gen2", "host": "device-50.lan", "password": "your-shelly-password"},
  "fan":   {"driver": "tasmota", "host": "device-51.lan"},
  "pump":  null
}
```

More examples for every driver (channels, passwords, Home Assistant) are in
`examples/aliases.example.json`.

**Step 5: Test each plug by hand.** This talks only to the plug, not to the bot:

```bash
python3 kalebridge.py test light state
python3 kalebridge.py test light on
python3 kalebridge.py test light off
python3 kalebridge.py test fan on
python3 kalebridge.py test fan off
```

Want to rehearse without touching anything? Add `--dry-run`.

**Step 6: Do a dry run with the bot (optional).** `python3 kalebridge.py run --dry-run` connects to the
bot and logs every command it *would* carry out, but switches nothing. Ask the bot to turn the fan on,
watch the log, then press Ctrl-C.

**Step 7: Install it as a service** so it starts on boot and restarts if it ever crashes:

```bash
sudo ./install.sh                  # installs to /opt/kalebridge, runs as YOUR user (never root)
sudo systemctl start kalebridge
journalctl -u kalebridge -f        # live log; Ctrl-C to stop watching
```

After installing, the command is simply `kalebridge` (e.g. `kalebridge status`).
No sudo? See `systemd/kalebridge-user.service` for a per-user service.

**Step 8: Check it end to end.** `kalebridge status` should say `RUNNING` and show a recent
"last bot contact". The bot sees the bridge as online in `kalecam bridge status`.

---

## 4. Everyday use

```bash
kalebridge status            # pairing, bot address, running?, fallback, holds, timers, each plug
kalebridge status --live     # ...and read every plug right now
kalebridge release light     # end a "manual change" hold now (see below)
kalebridge test fan state    # read one plug directly
kalebridge config show       # settings
kalebridge config set dry_run true   # then: sudo systemctl restart kalebridge
kalebridge rendezvous        # show what the address relays currently say (read-only)
journalctl -u kalebridge -n 100
```

Changes to `aliases.json` are picked up automatically within a second; no restart needed.

**Updating:** replace the folder with the new version and run `sudo ./install.sh` again (your config
is kept). **Uninstalling:** `sudo ./install.sh --uninstall` (config in `~/.config/kalebridge` is
kept; delete it yourself if you want).

---

## 5. What happens when...

| Situation | What the bridge does |
|---|---|
| The bot says "fan on" | Switches the plug, reads it back, reports `done` with the real state (or `failed` with the reason). |
| "fan on for 15 minutes" | Turns it on and keeps its own off-timer **on disk**. Even if the Pi reboots or the bot disappears, the fan goes off on time (immediately after the restart if the time already passed). |
| A command arrives too late (past its `expires_at`) | Doesn't run it; reports `expired`. |
| The same command arrives twice (the bot re-sends after 2 minutes without a result) | Doesn't switch again; re-sends the first result. |
| An alias is `null` (unbound) | Reports `failed`, switches nothing. |
| **Someone presses the plug's button or uses its app** | The bridge notices (it checks the plugs every 30 s) that the plug no longer matches what it last set, and starts a **hold**: bot commands for that plug return `held` and do nothing, so the bot never fights a person. The hold ends at the next fallback-schedule change for that plug (light on/off time, fan cycle change), or after 4 hours if there's no schedule. `kalebridge release <alias>` ends it early. Holds are reported to the bot. Reading a held plug ("state") still works. |
| **The bot is unreachable for 10 minutes** | Fallback, using the last schedule the bot sent (saved on disk): the light follows the photoperiod if one was ever set, otherwise stays as it is; the fan runs 15 minutes on / 15 off (if bound); the pump goes off. Holds are respected (except the pump turning off). When the bot is back, the bot is in charge again. If the bridge has *never* received a schedule, it leaves every switch exactly where it is. |
| The bot's address changes (its tunnel restarted) | After 3 failed attempts, the bridge reads the bot's new address from encrypted notes on public relays (ntfy.sh, ntfy.envs.net, textdb.online), checks that the new address really is your bot (it must accept your key), and switches. No re-pairing. Retries back off to at most once a minute. |
| The bot rejects the key (it was changed on the bot) | Logs "re-pair needed" and retries every 5 minutes. Get a new blob and run `kalebridge pair` again. |
| Pump command, pump not fully set up | Refused (`failed`), with the reason: disabled, sensors missing, not timed, too soon, daily limit, or a sensor says no. |

The relays only ever see an encrypted blob under a random-looking topic name; they can't read the
address, and nobody without your key can forge one (the bridge also refuses any address that doesn't
answer with your key, and never goes back to an older one).

---

## 6. Reference

### Files (`~/.config/kalebridge/`, or `$KALEBRIDGE_HOME`)

| File | What | Secret? |
|---|---|---|
| `config.json` | pairing (bot URL, key, bridge id, relays) + your settings | **yes**, mode 600 |
| `aliases.json` | which plug is light/fan/pump, device passwords, pump policy | **yes**, mode 600 |
| `state.json` | timers, holds, recent command ids, current bot address, last relay sequence number | no (mode 600 anyway) |
| `config-cache.json` | last fallback schedule and limits from the bot | no |

The key and device passwords are never written to logs or printed (status shows `***`).

### Alias fields

| Field | Used by | Meaning |
|---|---|---|
| `driver` | all | `shelly_gen2`, `shelly_gen1`, `tasmota`, `kasa`, `homeassistant`, `dummy` |
| `host` | Shelly, Tasmota, Kasa | IP or hostname on your LAN (e.g. `device-50.lan` or the address your router shows for the plug, or `http://...`; Kasa accepts `ip:port`) |
| `channel` | Shelly (0-based), Tasmota (1-based relay number), Kasa strips (0-based outlet) | leave out for single plugs |
| `user`, `password` | Shelly, Tasmota | optional device login (Shelly Gen2 user is always `admin`) |
| `url`, `token`, `entity_id` | Home Assistant | e.g. `http://homeassistant.local:8123`, a long-lived token, `switch.tent_fan` |
| `timeout_s` | all | per-request timeout (default 5) |
| `state_file`, `initial`, `fail` | dummy | remember state in a file / start state / simulate a failure |

### Pump policy (in `aliases.json`)

```json
"pump_policy": {
  "enabled": false,
  "max_run_s": 30, "max_daily_s": 180, "min_interval_s": 3600,
  "sensors": {
    "float": {"type": "http_json", "url": "http://device-60.lan/rpc/Input.GetStatus?id=0", "path": "state", "ok_when": true},
    "leak":  {"type": "http_json", "url": "http://device-61.lan/status", "path": "flood", "ok_when": false},
    "soil":  {"type": "http_json", "url": "http://device-62.lan/json", "path": "moisture", "ok_below": 35}
  }
}
```

A sensor is `http_json` (any device on your LAN that answers JSON; `path` is a dotted path into it,
like `sensors.0.value`) or `file` (a file some other program keeps updated). The rule is `ok_when`
(exact value), `ok_below` or `ok_above` (numbers). "ok" means *safe to pump*: float = water present,
leak = dry, soil = dry enough to water. A sensor that can't be read counts as not ok.

### Settings (`kalebridge config set <key> <value>`)

| Key | Default | Meaning |
|---|---|---|
| `dry_run` | `false` | log commands, switch nothing |
| `poll_hold_s` | 25 | long-poll length (max 25) |
| `heartbeat_s` | bot's (60) | heartbeat interval |
| `offline_threshold_s` | bot's (600) | offline time before fallback |
| `state_poll_s` | 30 | how often plugs are read (manual-change detection) |
| `backoff_max_s` | 60 | retry backoff cap |
| `rendezvous_after_failures` | 3 | failed polls before reading the relays |
| `rendezvous_min_interval_s` | 60 | minimum gap between relay reads (grows to 5 min in a long outage) |
| `hold_max_s` | 14400 | hold length when there's no schedule boundary |
| `request_timeout_s` | 15 | timeout for calls to the bot |
| `allow_http_urls` | `false` | testing only: accept `http://127.0.0.1` bot URLs |

---

## 7. Troubleshooting

- **`check: could not reach the bot`**: is the Pi online? Is the bot running? If the bot's address
  changed since the blob was made, the running service will find it through the relays; or get a fresh blob.
- **`401` / "re-pair needed"**: the bot's bridge key was rotated. Get a new blob, `kalebridge pair`.
- **A plug shows `error`**: `kalebridge test <alias> state` shows the exact error. Check the IP (did it
  change? use a DHCP reservation), the password, and that the Pi and plug are on the same network.
- **Commands come back `held`**: someone changed that plug by hand; see holds above. `kalebridge release <alias>`.
- **Fallback turned the light on at the wrong time**: the schedule is in the bot's timezone. Make sure
  the Pi's clock is right (`timedatectl`); the bridge warns in the log if its clock is more than 30 s off.
- **Kasa plug doesn't answer**: it probably has the newer firmware that needs a TP-Link account. Use a
  Shelly or Tasmota plug instead.

---

## 8. For developers

- Code: `kalebridge/` (`cli.py`, `service.py` = network loop, `engine.py` = rules/timers/holds/fallback/pump,
  `rendezvous.py` + `aesgcm.py` = relay reading and stdlib AES-256-GCM, `drivers/` = one module per plug type,
  `sensors.py`, `schedule.py`, `config.py`). Add a driver: subclass `drivers.base.Driver` (`get()`, `set(on)`
  returning the read-back state; raise `DriverError`), register it in `drivers/__init__.py`.
- Protocol: `X-Bridge-Key` header; `GET /bridge/poll?bridge=<id>`, `POST /bridge/result`,
  `POST /bridge/heartbeat`, `GET /bridge/config`. Full contract: `kalecam/docs/BRIDGE-PROTOCOL.md` in the release.
- Rendezvous (bot publishes, bridge reads): key and topics are derived from the bridge key with
  HKDF-SHA256 (salt `kalecam-bridge-v1`); messages are `kc1.` + base64url(IV ‖ AES-256-GCM), AAD
  `kalecam-bridge-rendezvous-v1`, payload `{v, url, issued_at, seq}`. See the docstring in
  `kalebridge/rendezvous.py`. The relay list comes from the pairing blob (`rv`).
- Tests: `./run_tests.sh` (driver tests with fake plug servers, engine tests with a fake clock,
  AES-GCM against NIST vectors, relay reading, and an end-to-end test against the real bot server on
  ports 18791-18792 with throwaway directories). `KALEBRIDGE_LIVE_NTFY=1 python3 tests/test_rendezvous.py`
  also does one real publish/read on ntfy.sh with a throwaway key. `KALEBRIDGE_PURE_AES=1` forces the
  built-in AES even if `cryptography` is installed.
