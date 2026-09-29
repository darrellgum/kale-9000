# kalecam: zero-account phone → bot photo capture (KALE 9000)

Technical reference for the capture runtime. For setup in plain language, see the top-level
[README](../README.md). Installed location: `/workspace/kalecam/` (configurable).

An old phone runs a web page (a PWA) that takes plant photos on a schedule or when the bot asks,
and uploads them to the bot's computer. No accounts anywhere: no app store, no Google, no Cloudflare
login, no ngrok. The computer has no inbound ports, so it's reached through a **Cloudflare quick
tunnel** (free, no account). The tunnel's URL changes whenever it restarts, so the new address is
published, **encrypted**, on public no-signup message boards (**ntfy.sh**, **ntfy.envs.net**,
**textdb.online**), where the phone finds it again.

> KALE 9000 is watching. (Politely. Mostly the basil.)

## Contents

| File | What it is |
|---|---|
| `server.py` | Upload/command/heartbeat/config server plus the PWA, on `127.0.0.1:8765` (stdlib only; uses Pillow to check JPEGs if it's installed) |
| `watchdog.sh` / `watchdog.py` | Idempotent self-healing: server, tunnel, cloudflared binary, rendezvous publishing |
| `kalecam` (`kalecam_cli.py`) | Local CLI for the bot: capture, status, schedule, config, pair, photos |
| `rendezvous.py` | Publishes and reads the encrypted address on ntfy and textdb channels |
| `kalecam_lib.py` | Shared paths, config, HKDF key derivation, AES-GCM, command queue |
| `bridge_lib.py` / `bridge_cli.py` | Home device bridge (`/bridge/*` API + `kalecam bridge ...`); see `docs/BRIDGE-PROTOCOL.md` |
| `bridge_rendezvous.py` | Encrypted rendezvous for the device bridge (publish side; channels keyed from the bridge key) |
| `app/` | The PWA: `index.html`, `app.js`, `db.js` (IndexedDB), `sw.js` (service worker), manifest, icons |
| `config.example.json` | Default settings (`config.json` is created from it on first run) |
| `rotate.py` | Photo rotation/intake tool: keeps recent photos, thins old ones to one per day, protects milestones (see `docs/DESIGN.md`) |
| `profiles/` | `PROFILE-TEMPLATE.md` and a worked example, used by the plant-onboarding skill |
| `docs/` | `DESIGN.md` (how the whole system fits together), `BRIDGE-PROTOCOL.md` (device-bridge API), `daily-review-routine.md` |
| `tests/` | all isolated from a live install: `test_server.py` (API, own server + temp photo root), `test_bridge.py` (bridge API), `test_watchdog.py` (heal ordering, cloudflared pin), `test_rotate.py`, `e2e_test.py` (headless Chrome + fake camera, real tunnel failovers, in a throwaway copy) |
| `secrets/` (0700) | `pairing.json` (secret + topics) and `pairing-url.txt`; `bridge.json` (bridge key) and `bridge-pairing.txt`; all 0600 |
| `state/`, `logs/`, `bin/` | Runtime state, logs, and the downloaded `cloudflared` |
| `pairing-qr.png` (0600) | QR code for pairing. **It contains the secret.** |

## Architecture

```
 phone (browser PWA)                                 bot computer (no inbound ports)
 ───────────────────                                 ───────────────────────────────
  camera → JPEG ≤3.5 MB → IndexedDB queue ─POST /upload──┐
  long-poll GET /poll (holds 25 s) ◄── commands ─────────┤   Cloudflare quick tunnel
  POST /heartbeat every 60 s (battery, queue, ...) ──────┼──► https://<random>.trycloudflare.com
  GET /config (schedule, capture settings) ──────────────┘        │ (cloudflared, outbound only)
                                                                  ▼
                                                    server.py 127.0.0.1:8765
                                                      ├─ /workspace/grow-photos/<plant>/YYYY/MM/DD/HHMMSS-<camera>.jpg
                                                      ├─ <plant>/index.jsonl  (same format as rotate.py)
                                                      ├─ state/commands/{pending,delivered,done}/  ◄── kalecam capture
                                                      └─ state/heartbeats/<camera>.json            ──► kalecam status
  on repeated failure:                              watchdog (every 150 s + bot routine):
  GET ntfy.sh / ntfy.envs.net / textdb.online  ◄──── publish AES-GCM({url, issued_at, seq})
  decrypt → newest seq → verify /healthz → switch     when the URL changes, when a channel failed, and hourly
```

### Endpoints (all phone-facing API endpoints need `X-Upload-Key`)

| Endpoint | Purpose |
|---|---|
| `POST /upload` | multipart (`photo` + fields) or raw `image/jpeg` with headers. Fields/headers: `plant_id`/`X-Plant-Id`, `camera`/`X-Camera`, `captured_at`/`X-Captured-At` (ISO 8601), `trigger`/`X-Trigger` (`schedule`, `command`, `manual`), `cmd_id`, `photo_id` (used for de-duplication), `queued`. 25 MB cap. EXIF/XMP (GPS, device) is stripped. Saved atomically and appended to `index.jsonl`. |
| `GET /poll?camera=X&hold=25` | Long-poll. Returns `{"cmd":"capture","id":...,"settings":{...}}` as soon as a command is queued, or `{"cmd":null}` after the hold time. Includes `config_version` so the phone reloads `/config` when it changes. |
| `POST /heartbeat` | JSON: battery `{level, charging}`, `temperature_c` (always null; no browser exposes it), queue, last capture/upload, visibility, wake lock, camera and resolution, API/page origin, errors, rendezvous status, storage use |
| `GET /config` | Schedule, capture settings, heartbeat interval, migrate mode, timezone, version |
| `GET /app`, `/app/*` | The PWA (no key needed; it holds no secrets) |
| `GET /healthz` | `{"ok":true,"app":"kalecam","instance":...}`. The watchdog checks the instance id end to end. |

### Device bridge endpoints (need `X-Bridge-Key`, a separate key from the phone's)

A home bridge service dials out to this server to switch the tent's `light`,
`fan` and (later) `pump`. It uses `GET /bridge/poll?bridge=<id>` (long-poll, returns a JSON list),
`POST /bridge/result`, `POST /bridge/heartbeat` and `GET /bridge/config` (fallback schedule and limits).
State lives in `state/bridge/`, with an append-only `state/bridge/bridge-log.jsonl`. The CLI is
`kalecam bridge pair|send|status|config|cancel`. Full contract: `docs/BRIDGE-PROTOCOL.md`. The pairing
blob (`secrets/bridge-pairing.txt`) contains the quick-tunnel URL, which changes when the tunnel
restarts. The blob also lists the rendezvous relays (`"rv"`), and the watchdog publishes the bridge URL
to its own encrypted channels, keyed from the bridge key (`bridge_rendezvous.py`), so a bridge that
implements the read side (the reference bridge in `bridge/` of the release) follows URL changes on its
own. Otherwise re-run `kalecam bridge pair`, or set `kalecam bridge config set public_base_url https://<stable host>`.

The server binds only to 127.0.0.1. WebSocket isn't used; long-polling is enough and works through quick
tunnels (quick tunnels don't support SSE).

### Where photos go

`/workspace/grow-photos/<plant-id>/YYYY/MM/DD/HHMMSS-<camera>.jpg`, with `-1`, `-2`, ... on same-second
collisions. Times in paths are this computer's local time (from the phone's `captured_at`, so photos
queued offline keep their real capture time). Index rows use the `docs/DESIGN.md` / `rotate.py` fields
(`file, ts, plant, source, bytes, status, milestone, keep, quality, best`) plus `trigger, cmd_id, photo_id,
received_at, queued, width, height, sha256, app_version`. `rotate.py` keeps unknown fields. Uploads wait
up to 20 s while `rotate.py` holds `.rotate.lock`.

The plant id comes from, in order: `kalecam capture --plant`, then `camera_plants` in the config
(`kalecam config set camera_plants.phone-1 basil-01`, no re-pairing needed), then the plant id in the
pairing link, then `default_plant`.

## What changes, when, and how each side heals

| Event | What changes | Who notices | Healing |
|---|---|---|---|
| Server crash | nothing external | watchdog (`/healthz` on localhost; the loop notices a dead process within ~10 s) | restarts `server.py` (same URL). **Server first:** whenever the public check fails, the watchdog checks the local server before it blames the tunnel, restarts the server if needed and re-checks the same tunnel, and never waits on tunnel reachability while the server is down. The phone queues photos meanwhile and retries with backoff. |
| cloudflared dies / tunnel broken | **tunnel URL** | watchdog loop: a dead process is noticed within ~10 s. A tunnel that's alive but broken fails the end-to-end `GET https://<url>/healthz` check (it must return this server's instance id) on the next full pass (≤150 s). | starts a new quick tunnel, waits for DNS (checked over DNS-over-HTTPS so this machine's resolver doesn't cache "no such host"), verifies it end to end, then publishes the new URL to every channel |
| cloudflared binary missing/broken | - | watchdog (`cloudflared --version`) | re-downloads the **pinned** release (`CLOUDFLARED_VERSION` in `watchdog.py`, linux amd64/arm64) from GitHub, **refuses it unless its sha256 matches the pinned value**, and checks that it runs |
| Machine reboot | everything stopped, URL gone | the bot's routine runs `watchdog.sh --ensure-loop` | starts the server and tunnel, publishes, and restarts the background loop. (No cron/systemd on this box, so the routine is the reboot hook.) |
| Channel publish failed | - | watchdog (per-channel state) | retries only the failed channels on the next pass |
| Pairing QR/link | contains the tunnel URL | watchdog | `pairing-qr.png` and `secrets/pairing-url.txt` are **regenerated on every URL change** (a QR for a dead URL can't be opened), so always show the current file |
| Quiet period | caches expire (ntfy keeps ~12 h) | watchdog | republishes every hour even when nothing changed |
| Phone can't reach the server | - | page: 3 failures or 45 s without success | reads all channels in parallel, decrypts, takes the highest `seq`, requires `seq` > last accepted, https only, and checks `/healthz` on the new URL before switching. It keeps capturing and queueing the whole time and drains the queue oldest first afterwards. Channel reads back off 15 s → 30 s max. Backoff sleeps end as soon as a new address is found. |
| Page reloaded on a dead origin | - | service worker | serves the cached app shell (network-first with 5 s timeout, falls back to cache on errors/5xx such as Cloudflare's 530); the app then reads its saved state |
| Browser Background Sync (Android Chrome) | - | service worker | can upload queued photos even with the page closed (`sync` event) |

### The origin problem and the choice made (`migrate` setting)

A camera page must be HTTPS, and the only no-account HTTPS origin available here is the tunnel itself,
which **changes with every tunnel restart**. Browsers key camera permission, localStorage, IndexedDB and
service workers **per origin**. Two strategies are implemented:

* **`sticky` (default, recommended).** The page stays on the origin it was first opened on (from the QR
  code) and only moves its **API base** to the new tunnel URL, making cross-origin requests (the server
  sends CORS `*`). The camera permission, storage, queue and home-screen icon stay valid, so **nobody
  has to tap "Allow camera" again** after a URL change. If the page is reloaded after its own origin
  died, the service worker serves the cached shell. Tested: reload on a dead origin (HTTP 530) worked.
* **`navigate`.** When a new URL is found, the page first uploads its offline queue to the new URL
  (IndexedDB is per origin, so photos left behind would be stranded), then goes to
  `https://<new>/app#<pairing blob>&seq=..&slot=..`. The fragment carries the pairing to the new
  origin and is never sent to any server. The page strips it from the address bar right away. Downside:
  **a new origin means a new camera prompt** on Android Chrome and on iOS unless Safari's camera setting
  is "Allow", so a person may have to tap Allow after each tunnel change. If a stale home-screen icon
  opens an old origin, the SW-cached shell there sees the newer API address and navigates to it.

Switch with `kalecam config set migrate navigate|sticky` (the phone picks it up within one poll).

**Stable no-account origin?** I checked the options: GitHub Pages, Netlify, Cloudflare Pages, surge
and neocities all need accounts. Netlify Drop without an account deletes the site after about an hour.
Paste and HTML-preview sites either serve `text/plain` or sandbox the page in iframes without camera
access. localtunnel (`loca.lt --subdomain`) can give a named subdomain without an account, but it shows
a browser interstitial and is unreliable. IPFS gateways change origin with every content change and
need pinning. So the most robust no-account choice is the tunnel origin plus a service worker, used in
`sticky` mode: the first origin acts as a permanent, SW-backed "installation" even after its tunnel is
gone.

## Security model

* **One secret** (32 random bytes) is made at pairing. It lives in `secrets/pairing.json` (0600), in
  `pairing-qr.png` / `secrets/pairing-url.txt` (0600), and in the phone's localStorage. It's carried in
  the **URL fragment** (`#...`), which browsers never send to servers, so Cloudflare, ntfy and textdb
  never see it.
* Two keys are derived with **HKDF-SHA256** (salt `kalecam-v1`):
  * `auth` → the `X-Upload-Key` token. Sent over TLS, compared in constant time. Cloudflare terminates
    TLS, so the tunnel operator could technically see this token and the photos; it **cannot** see the
    rendezvous key.
  * `rendezvous` → AES-256-GCM key. It never leaves the two devices.
* **Rendezvous payload** `{v, url, issued_at, seq}` is AES-256-GCM encrypted with a fresh 96-bit IV per
  message, AAD `kalecam-rendezvous-v1`, published as `kc1.<base64url(iv|ciphertext|tag)>`. The GCM tag
  authenticates it: without the key nobody can read the URL or forge a message. **Replay:** the phone
  accepts only a `seq` greater than the last one it accepted (seq = max(previous+1, unix ms)). It also
  requires `https://` and a matching `/healthz` before switching. Tested: random `kc1.` data,
  bit-flipped ciphertext, and an authentic but older message were all rejected.
* **Topic names** are 26 random alphanumerics (about 155 bits), one per channel, made at pairing.
  Someone who learns a topic can read ciphertext, spam the ntfy topic, or overwrite the textdb value.
  That's a denial of service on one channel only (three independent channels), never a forgery.
* The tunnel hostname isn't secret. Everything except `/app` static files and `/healthz` needs the key.
  The server listens on 127.0.0.1 only. Commands the phone will run are limited to
  `capture`/`reload`/`refresh_config`.
* EXIF (GPS, device model) is stripped at intake. Canvas-encoded JPEGs from the page have none anyway.
* Logs never contain the secret or token (`kalecam pair --quiet` keeps the link off the terminal).
* **Rotate** (lost phone, leaked QR): `kalecam pair --rotate-secret`, then re-pair the phone. The old
  key stops working at once.

## Setup

Requires Linux with Python 3.10+ (with `venv`), `flock`/`setsid` (util-linux) and outbound HTTPS. No accounts.
From the unpacked release:

```bash
./install.sh                              # -> /workspace/kalecam; options: --prefix --port --photo-root --timezone
cd /workspace/kalecam
./kalecam pair --plant <plant-id> --camera phone-1     # writes pairing-qr.png, prints the link (SECRET)
```

`install.sh` copies the code, creates `config.json` from `config.example.json`, and runs
`watchdog.sh --ensure-loop`, which builds the venv (PyPI: cryptography, qrcode, pillow), downloads the
pinned cloudflared, starts the server, tunnel and background loop, and publishes the address. Re-running
it with a newer release upgrades in place and keeps config, secrets, state and the paired phone.

On the phone: open the link (or scan `pairing-qr.png`), allow the camera, work through the **Phone prep**
checklist, tap **Fullscreen**, mount the phone, and plug it in.

There is no cron or systemd on a bot's computer, so a bot routine runs this every few minutes (it is
also the reboot hook):

```bash
/workspace/kalecam/watchdog.sh --ensure-loop
```

For a second phone: `kalecam pair --camera phone-2 --plant <id>` (same secret, different camera name).

## CLI (for the bot)

```bash
kalecam capture [phone-1|all] [--wait 90] [--plant ID] [--settings '{"jpeg_max_bytes":2000000}']
                                   # prints {"id","status":"done","file":"/workspace/grow-photos/..."}
kalecam status [--json] [--check]  # server/tunnel/watchdog/rendezvous + per-camera heartbeat, battery,
                                   # queue, last capture, warnings (stale, low battery, not visible)
kalecam schedule show | set --interval 30 --start 06:00 --end 22:00 [--on|--off]
kalecam config get [key] | set key value     # e.g. migrate sticky, heartbeat_s 60, capture.keep_camera_open false,
                                             #      camera_plants.phone-1 basil-01, dim_preview true
kalecam photos [--plant ID] [-n 5]
kalecam pair [--plant ID] [--camera NAME] [--rotate-secret] [--quiet]
kalecam reload [camera]            # ask the page to reload itself
kalecam cancel [ID|--all]
kalecam publish [--force]          # one watchdog pass, forcing a republish
kalecam rendezvous                 # read back + decrypt all channels (shows seq/url per channel)
kalecam bridge pair [--bridge-id bridge-1]          # bridge key + secrets/bridge-pairing.txt (prints path + fingerprint only)
kalecam bridge send fan on --duration 900 --wait 30 # queue a switch command; --wait prints the result
kalecam bridge status | config show | config set fallback.light 06:00-22:00 | cancel --all
kalecam bridge publish [--force]                   # publish the bridge URL to its rendezvous relays now (the watchdog does this)
```

The schedule runs on the phone, in the computer's timezone (sent in `/config`), in slots of
`interval_min` between `start` and `end` (`start == end` means all day). The phone keeps capturing
while offline. Commands wait in `state/commands/pending/` until the phone polls. A delivered command
that isn't completed within 120 s is handed out again (up to 3 tries). The phone ignores command ids it
has already run.

## Rendezvous services (tested 2026-09-28)

| Channel | Read | CORS | Retention | Limits (anonymous) | Notes |
|---|---|---|---|---|---|
| ntfy.sh | `GET /<topic>/json?poll=1&since=all` | `Access-Control-Allow-Origin: *` (preflight OK) | messages cached **12 h** (`expires` = time+43200) | 250 messages/day per IP; 60-request burst, refill 1 per 5 s | Some networks can't complete TLS to ntfy.sh. The watchdog then falls back to **plain HTTP for publishing** (payload is encrypted and authenticated; only the topic is exposed). Phones read over HTTPS. |
| ntfy.envs.net | same API | `*` | 12 h | 17,280 messages/day per IP | community server, backup |
| textdb.online | `GET /<key>` (text/plain) | `*` | single value, deleted after **30 days** with no read/update | 500 writes/day per IP, reads unlimited | different software and operator, survives more than 12 h of silence; "for testing" per its docs |

Also worked but not used by default: ntfy.adminforge.de and ntfy.hostux.net (add them to `rendezvous` in
the config **before** pairing). jsonblob.com was blocked (Cloudflare 403) from datacenter IPs, and
extendsclass needs an API key. With hourly republishing, usage is about 25 messages/day per channel.

## Tests

Every suite is isolated: none of them touches a running install's port, photos, state or secrets.

```bash
venv/bin/python tests/test_server.py [--public]   # API checks: own server on :18767, temp photo root
                                                  # (--public: also through a temporary quick tunnel)
venv/bin/python tests/test_bridge.py              # bridge API: own server on :18766, temp KALECAM_HOME
python3 tests/test_watchdog.py                    # heal ordering (server first) + cloudflared pin; no network
python3 tests/test_rotate.py                      # rotation policy (downscale checks need Pillow)
venv/bin/pip install -r requirements-test.txt     # playwright (uses the system Chrome), zxing-cpp
venv/bin/python tests/e2e_test.py                 # headless Chrome + fake camera + 3 real failovers (~4 min)
```

`e2e_test.py` copies the code to a temp directory with its own port (18795), photo root, secrets and
quick tunnel, runs there and tears it down. It covers pairing via the link, capture on command, timed
captures, heartbeats, forged/tampered/replayed rendezvous messages, failover in `navigate` mode,
failover in `sticky` mode with the cloudflared binary deleted (pinned re-download plus a reload on the
dead origin served by the service worker), and a reboot simulation. Results go to
`test-results/e2e-isolated/`. (`--live` runs it in place instead; that rewrites the schedule and
needs a re-pair afterwards, so don't use it on a phone you rely on.)

## Troubleshooting

* `kalecam status --check`. Look at `logs/watchdog.log`, `logs/server.log`, `logs/cloudflared.log`.
* **Phone says "Reconnecting"**: run `./watchdog.sh` once, then `kalecam rendezvous`. All channels
  should show the current URL and seq. The phone retries channel reads every 15 to 60 s. The page's
  Settings has "Check for a new server address".
* **"Pairing key rejected"**: the secret was rotated. Re-scan the new QR.
* **Camera prompt on every URL change**: you're in `navigate` mode. Use `sticky`, or on iOS set
  Settings → Apps → Safari → Camera → Allow.
* **Heartbeat stale / `visible: false`**: the page is in the background or the screen is off. Browsers
  throttle or freeze hidden tabs. Keep it in front, with the screen on and the phone charging.
* **Tunnel won't come up**: quick-tunnel creation can be rate-limited. After 3 failed attempts in a
  row the watchdog waits 1, 2, 4 ... up to 15 min between attempts. Successful restarts don't count.
  Check `logs/cloudflared.log`.
* **Editing `watchdog.sh` while the loop runs**: bash reads scripts as it goes, so write a new file
  and `mv` it over the old one (never edit in place), or stop the loop first.
* **Port 8765 in use**: change `port` in `config.json`, stop the other program, and run the watchdog.
* **New tunnel hostname "doesn't resolve"** on the bot machine: some resolvers cache "no such host" if
  the name was looked up before it existed. The watchdog checks through DNS-over-HTTPS and connects by
  IP, so it isn't affected.

## Known limitations

* Quick tunnels have no SLA or uptime guarantee and a 200 in-flight request cap. The URL changes on
  every restart. Measured recovery after killing cloudflared: watchdog healed and published in
  8–15 s, and the page was back online in 33–36 s. A full "reboot" (everything killed) took 21 s to
  restore and the page was back in 35 s. A tunnel that's alive but broken can take up to one full
  pass (150 s) to notice.
* The web platform can't read battery **temperature**. `getBattery()` exists only on Chromium browsers
  (not iOS Safari or Firefox), so battery shows `n/a` there.
* Browsers throttle or suspend background tabs. The page must stay in the foreground with the screen
  on. Wake Lock needs a visible page (iOS 16.4+ in Safari; home-screen apps on iOS only from 18.4).
  Otherwise use Auto-Lock Never or Stay awake while charging.
* Screen orientation lock works only in fullscreen / installed PWAs on Android. iOS doesn't support it
  (lock rotation in Control Center).
* Web pages can't set screen brightness. "Dim" is a black overlay.
* `ImageCapture.takePhoto()` (full sensor resolution) is Chromium-only. Other browsers use the video
  frame (often 1080p–4K).
* In `sticky` mode the first origin's storage holds the secret. If that trycloudflare hostname were ever
  re-issued to someone else (random 4-word names, very unlikely) and the phone reloaded, a malicious
  service-worker update could read it. Rotate the secret if in doubt.
* ntfy caches only 12 h, and all channels are free community services that may rate-limit or disappear.
  Three independent channels plus hourly republishing reduce that risk. Edit `rendezvous` and re-pair to
  change channels.
* The pairing QR code is version ~16 (dense). Show it at a decent size.
