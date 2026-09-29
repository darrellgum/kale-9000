# Device bridge protocol (bot side)

The kalecam server can also talk to an optional **home bridge**: a small program on an always-on
computer in the owner's home (a Raspberry Pi, an old laptop) that switches the grow light, fan and
pump through local smart plugs. The bridge **dials out** to the bot, so nothing in the home is opened
to the internet. This file is the contract between the bot's server and any bridge.

A reference bridge (Shelly, Tasmota, older Kasa, Home Assistant, dummy) is in `bridge/` of the
release. It is **beta**: covered by automated tests against fake plugs, **not tested on real
hardware**.

## Where it runs

- Same stdlib server as the phone capture system: `/workspace/kalecam/server.py`, listening on
  `127.0.0.1:<port>` (default 8765) and published through a Cloudflare **quick tunnel**.
- Base URL: the current tunnel URL (`state/url.txt`, shown by `kalecam status`). **The quick-tunnel
  URL changes whenever cloudflared restarts.** The bridge follows it through its own encrypted
  rendezvous (below). Without that, run `kalecam bridge pair` again and paste the new blob on the
  bridge. With a stable hostname (for example a named Cloudflare tunnel), set
  `kalecam bridge config set public_base_url https://<host>`, and `pair` will use it.
- Code: `bridge_lib.py` (rules, queue, storage), `bridge_cli.py` (`kalecam bridge ...`), and the
  `/bridge/*` routes in `server.py`. Tests: `tests/test_bridge.py`.

## Auth

Every `/bridge/*` request must carry `X-Bridge-Key: <key>`. The key is a 256-bit random value
(base64url, 43 characters) stored in `secrets/bridge.json` (mode 600). It is separate from
the phone secret: the phone key does not open `/bridge/*`, and the bridge key does not open the phone
endpoints. The server compares it in constant time and never logs it.

| Case | Response |
|---|---|
| missing or wrong key | `401 {"error":"missing or invalid X-Bridge-Key"}` (connection closed) |
| server not paired yet | `503` |
| JSON body over 64 KB | `413` |

## Pairing

```bash
kalecam bridge pair [--bridge-id bridge-1] [--rotate-key]
```

This creates the key if it's missing, then writes `secrets/bridge-pairing.txt` (mode 600). The
file holds one line: **standard base64** (with padding) of
`{"url":"https://...","key":"...","bridge_id":"bridge-1","rv":[["n","https://ntfy.sh"],["n","https://ntfy.envs.net"],["t","https://textdb.online"]]}`.
`rv` (optional, ignore it if unused) lists the rendezvous relays. The bridge decodes it with
`base64 -d` / `base64.b64decode`. The CLI prints only the file path and a key fingerprint
(`sha256:<16 hex>`), never the key. Re-running `pair` keeps the key and refreshes the URL.
`--rotate-key` issues a new key, and the old key stops working at once.

## Endpoints

### `GET /bridge/poll?bridge=<id>[&hold=<s>]`
Long-poll. The server holds the request up to `poll_hold_s` (25 s, never more than 25). It returns as
soon as a command is queued for this bridge, or `[]` when the hold runs out. Response body is a JSON
**list** (up to 20 per poll):

```json
[{"id":"b202609282022367998b2","device":"fan","action":"on","duration_s":900,"expires_at":"2026-09-28T20:27:36-07:00"}]
```

- `device`: `light` | `fan` | `pump`. `action`: `on` | `off` | `state`.
- `duration_s` is present only for timed `on` commands.
- `expires_at` is ISO 8601 with the offset of the bridge `timezone` (see config). Commands expire after 5 min by default
  (the maximum is 1 h).
- `bridge` is required (`[A-Za-z0-9][A-Za-z0-9_.-]{0,31}`, otherwise `400`). By default a command goes
  to any bridge. `kalecam bridge send --bridge ID` targets one bridge.
- Response header `X-Bridge-Config-Version`: when it changes, re-fetch `/bridge/config`.
- Delivery: a returned command is marked *delivered*. If no result arrives within `redeliver_after_s`
  (120 s), it is handed out again, up to `max_attempts` (5), until it expires. **The bridge must be
  idempotent by `id`**: if it sees an id it has already executed, it should re-send the stored result
  and not switch again.
- Commands that expire before delivery are never sent (the server marks them `expired`). The rules are
  checked again at delivery. For example, a pump command queued while the pump was enabled is
  `rejected` and not sent if the pump has been disabled since.

### `POST /bridge/result`
```json
{"id":"b202609282022367998b2","status":"done","state":"on","error":null,"at":"2026-09-28T20:22:40-07:00"}
```
- `status`: `done` | `failed` | `expired` | `held`. `state` is a short string or null. `error` is a
  string or null (truncated to 500 characters).
- `200 {"ok":true,"id":...,"status":...}`. A repeated result for the same id returns
  `200 {"ok":true,"duplicate":true}`, and the first result wins. An unknown id returns `404`. A bad
  body returns `400`.
- A late result for a command the server already expired or failed is accepted: the bridge's word wins,
  and the server's status is kept as `server_status`.

### `POST /bridge/heartbeat` (every `heartbeat_s` = 60 s)
```json
{"bridge":"bridge-1","version":"0.1","devices":{"light":"on","fan":"off"},"holds":{"light":false,"fan":true},"fallback_active":false,"uptime_s":3600}
```
The latest heartbeat per bridge is stored with a receive timestamp and appended to the log. Response:
`{"ok":true,"config_version":"...","server_time":"..."}`. A bridge counts as offline for KALE after
`offline_threshold_s` (600 s) without a heartbeat.

### `GET /bridge/config`
```json
{"timezone":"Europe/Berlin","poll_hold_s":25,"heartbeat_s":60,"offline_threshold_s":600,
 "pump_enabled":false,"max_duration_s":{"light":64800,"fan":3600,"pump":0},
 "fallback":{"light":null,"fan":{"on_min":15,"off_min":15},"pump":"off"},
 "aliases":["light","fan","pump"],"version":"47793694112f","server_time":"..."}
```
- `fallback.light`: `null` means no photoperiod has been chosen, so the bridge leaves the light alone.
  When set, it is `{"on":"HH:MM","off":"HH:MM"}` in `timezone`. It is on from `on` to `off` and wraps
  past midnight if `off < on`.
- `fallback.fan`: `{"on_min":15,"off_min":15}` cycle, or `null` (leave it alone).
- `fallback.pump` is always `"off"`.
- `max_duration_s`: server-side caps (the bridge should also enforce its own hard ceilings).
- `version` changes whenever any of these values changes.

## Rendezvous for the bridge (URL changes)

The phone's rendezvous is keyed from the phone secret, which a bridge must never hold. The bridge gets
its own channels, keyed from the bridge key it already has, so nothing extra is pasted. Publisher:
`bridge_rendezvous.py`, called by the watchdog after the phone publish (errors there never
affect the phone path) and by `kalecam bridge publish [--force]`. It publishes when the URL changes,
when the key changes, when a channel failed last time, and every `republish_s` (1 h). State:
`state/bridge/publish-state.json`.

```
ikm     = base64url-decode(bridge key)                     (32 bytes)
aes key = HKDF-SHA256(ikm, salt="kalecam-bridge-v1", info="bridge-rendezvous", 32)
topic   = HKDF-SHA256(ikm, salt, info="bridge-topic:<ntfy|textdb>:<relay host>", 26 bytes),
          each byte -> "A-Za-z0-9"[byte % 62]
message = "kc1." + base64url(iv[12] || AES-256-GCM(json payload)), AAD "kalecam-bridge-rendezvous-v1"
payload = {"v":1,"url":"https://...","issued_at":"...","seq":N}   (seq strictly increasing)
```

The URL published is `bridge.public_base_url` if set, else the quick-tunnel URL. The bridge accepts a
message only if `seq` is higher than the last one it accepted, the URL is an https origin, and the new URL
answers an authenticated `GET /bridge/config`. Rotating the key (`pair --rotate-key`) rotates the
topics and the AES key too. Reference reader: `bridge/kalebridge/rendezvous.py` in the release.

## Server-side rules when queueing (`kalecam bridge send`)

- Unknown alias or action: rejected (CLI exit code 3, nothing queued).
- `pump` (any action) while `pump_enabled` is false: rejected.
- `duration_s` is only allowed with `on` and must be > 0. It is **capped** at `max_duration_s[alias]`
  (the command records `duration_capped_from`). A cap of 0 means timed runs are rejected.
- `expires_at` defaults to now + `default_expires_s` (300 s). `--expires` is capped at `max_expires_s`
  (3600 s).
- There is no HTTP endpoint for queueing commands. Only the local CLI (KALE) can queue them.

## CLI

```bash
kalecam bridge pair [--bridge-id bridge-1] [--rotate-key]
kalecam bridge send <light|fan|pump> <on|off|state> [--duration S] [--expires S] [--wait N] [--bridge ID]
      # prints {"queued":id,...}. With --wait it blocks for the result and prints
      # {"id","status","state","error","at"}. Exit 0 = done, 1 = failed/held/expired, 2 = timeout, 3 = rejected
kalecam bridge status [--json]   # heartbeat age + online/offline, devices, holds, fallback_active,
                                 # pending / awaiting-result commands, recent results
kalecam bridge config show
kalecam bridge config set <key> <value>   # dotted keys, JSON values, validated before saving
      # e.g. fallback.light 06:00-22:00 | fallback.light null | max_duration_s.fan 1800
      #      pump_enabled false | public_base_url https://kale.example.com | fallback.fan.on_min 10
kalecam bridge cancel [ID | --all]        # pending commands only
kalecam bridge publish [--force]          # publish the bridge URL to the rendezvous relays now
```
`kalecam status` also shows a one-line bridge summary.

## Config fields (`config.json` → `"bridge"`, overrides of the defaults in `bridge_lib.py`)

| key | default | meaning |
|---|---|---|
| `public_base_url` | `null` | stable URL for `pair`; null = current quick-tunnel URL |
| `timezone` | auto (config `timezone`, else this computer's zone) | zone for `expires_at` and the fallback schedule; always sent as a concrete name |
| `poll_hold_s` | 25 | long-poll hold (1..25) |
| `heartbeat_s` | 60 | expected heartbeat interval (told to the bridge) |
| `offline_threshold_s` | 600 | offline after this long without a heartbeat; also the bridge's fallback trigger |
| `redeliver_after_s` | 120 | re-send a delivered command if no result arrives |
| `max_attempts` | 5 | deliveries before the server marks it `failed` |
| `default_expires_s` / `max_expires_s` | 300 / 3600 | command lifetime |
| `pump_enabled` | `false` | pump commands are rejected while false |
| `max_duration_s` | light 64800, fan 3600, pump 0 | cap on `duration_s` |
| `fallback` | light null, fan 15/15, pump "off" | offline behavior for the bridge |

The server re-reads `config.json` when it changes, so no restart is needed.

## Storage and logs (no secrets)

- `state/bridge/commands/{pending,delivered,done}/<id>.json`: command records with the full
  history (attempts, delivered_at, result, closed_by).
- `state/bridge/heartbeats/<bridge>.json` (latest) and `<bridge>.lastpoll`.
- `state/bridge/bridge-log.jsonl`: append-only events (`queued`, `delivered`, `redelivered`,
  `requeued`, `result`, `result_duplicate`, `expired`, `failed`, `rejected`, `cancelled`, `heartbeat`,
  `config_set`, `paired`). The file rotates at 20 MB to `bridge-log-<timestamp>.jsonl`, and nothing is
  deleted.
- Request lines are in `logs/server.log`. Successful `/bridge/poll` lines are suppressed as
  noise, like `/poll`.

## What a bridge must do (summary of the contract)

1. Load the pairing blob (keep it mode 600). Long-poll `/bridge/poll?bridge=<id>` in a loop and back off on
   errors (cap about 60 s). Treat `401` as "re-pair needed" and stop hammering.
2. For each command: if `expires_at` has passed, report `expired`. If the alias is unbound, report
   `failed`. If the alias is held, report `held`. Otherwise switch it and report `done` or `failed` with
   the read-back `state`. For `duration_s`, keep a persisted off-timer.
3. Heartbeat every 60 s with aliased devices only, holds, `fallback_active` and `uptime_s`.
4. Fetch `/bridge/config` at start-up and whenever `X-Bridge-Config-Version` / `config_version`
   changes. Cache it on disk. When KALE has been unreachable for more than `offline_threshold_s`, apply
   `fallback`. With no cached config ever, leave every switch where it is.
5. After a tunnel restart, polls fail until the bridge reads the new URL from the rendezvous (above),
   gets a new blob, or a stable hostname is set.
