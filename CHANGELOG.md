# Changelog

## 1.0.1 (2026-09-29)

- **Skill reference in the release**: new `reference/` folder with the full text of the four plant
  skills (`plant-photo-diagnosis.md`, `growth-stage-tracker.md`, `grow-environment-targets.md`,
  `plant-onboarding-interview.md`): symptom tables, stage durations and targets, lookalikes,
  toxicity list, formulas. The template's skills are now slim and point here.
- **Installer**: `install.sh` copies `reference/` to `<prefix>/reference/` (default
  `/workspace/kalecam/reference/`) on install, on upgrade, and with `--no-start`.
- **Profile template**: `profiles/PROFILE-TEMPLATE.md` now has the `light_environment` block
  (setting, light, schedule, estimated DLI, `heat_welcome`, climate, sources) after `location`,
  matching the onboarding skill.
- **Clear tunnel errors**: when Cloudflare rate-limits new quick tunnels (HTTP 429) the watchdog says so
  in its log and in `kalecam status` (and keeps retrying once per run); `kalecam pair` explains what to
  do when there is no public address yet.
- `kalecam status` prints `n/a` instead of `None` for fields a camera hasn't reported yet.

## 1.0.0 (2026-09-29)

First public release.

- **kalecam capture runtime**: phone web app (PWA) + stdlib upload/command/heartbeat server behind a
  Cloudflare quick tunnel, encrypted rendezvous on ntfy.sh / ntfy.envs.net / textdb.online, `kalecam`
  CLI (capture, status, schedule, config, pair, photos), self-healing watchdog.
- **Installer** `install.sh`: install, upgrade in place (keeps config, secrets, pairing, photos),
  uninstall. Default location `/workspace/kalecam`, port 8765 (both configurable).
- **Watchdog heals the server first**: when the public tunnel check fails, the local server is checked
  and restarted before the tunnel is touched, the same tunnel is re-checked (URL kept), and the watchdog
  never waits on tunnel reachability while the server is down. The background loop also notices a
  dead server within ~10 s even while earlier passes were failing.
- **cloudflared pinned** to 2026.9.3 with per-architecture SHA-256 (linux amd64/arm64), verified on
  every download; mismatches are refused. Overridable in `config.json`.
- **Timezone fix**: photo folders and file names use the bot's local zone (config `timezone`, `TZ`,
  `/etc/timezone`, `/etc/localtime`), resolved explicitly, not the zone the process started with.
  `rotate.py` resolves the zone the same way.
- **Bridge timezone fix**: the bridge config/fallback schedule now falls back to the bot's config
  `timezone` before the computer's zone (it ignored it before, so a bot with an explicit timezone
  sent the bridge the wrong zone).
- **Filename convention** `YYYY/MM/DD/HHMMSS-<camera>.jpg` everywhere: `rotate.py add` names files
  that way by default, `rotate.py flag` accepts a bare `HHMMSS.jpg` when it is unambiguous.
- **Rendezvous retry backoff**: a relay that failed is retried after 1, 2, 4 … 15 min (15 min at once
  after HTTP 429) instead of on every watchdog pass, so a rate-limited relay isn't hammered.
- **Commands lost to a reloading page** are handed once more to the phone's next poll after 8 s
  (previously only after 120 s).
- **Tests isolated from live installs**: `test_server.py` starts its own server with a temp photo root
  (and an optional temporary tunnel), `e2e_test.py` runs in a throwaway copy with its own port, secrets
  and tunnel, new `test_watchdog.py` covers heal ordering and the checksum pin.
- **Reference home bridge** `kalebridge` 0.1.0 (beta, not tested on real hardware): Shelly Gen1/Gen2,
  Tasmota, older Kasa, Home Assistant, dummy; offline fallback schedule; encrypted rendezvous.
- Docs: plain-language README with phone setup and battery safety, `DESIGN.md` describing the real
  system, generic `BRIDGE-PROTOCOL.md`.
