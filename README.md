# KALE 9000: a plant-care bot that watches your plants through a spare phone

KALE 9000 is a plant-care assistant in the style of HAL 9000 (she/her): calm, dry, and actually
useful. *"I'm sorry, Dave. I can't let you overwater that."* The jokes season the advice; they never
replace it.

This repository is the **code** behind the KALE 9000 Grok Bot template: the phone-camera system
("kalecam"), the photo rotation tool, plant profile templates, and an optional home bridge for smart
plugs. The bot's knowledge (plant diagnosis, growth stages, environment targets, onboarding) lives in
the template's skills, which are kept short; their full reference text (symptom tables, stage
targets, formulas) is in `reference/` and is installed to `/workspace/kalecam/reference/`. The bot
downloads and installs this code by itself.

```
 spare phone on a stand         the bot's own computer                     you
 ┌──────────────┐  photos      ┌────────────────────────────┐   advice    ┌─────┐
 │ web page     │ ───────────► │ kalecam server + watchdog  │ ──────────► │chat │
 │ (camera)     │ ◄─────────── │ photos, profiles, grow log │             └─────┘
 └──────────────┘  "take one   └────────────────────────────┘
                    now"               ▲ optional, beta
                              home bridge (Raspberry Pi) ──► smart plugs: light, fan, pump
```

- **No accounts, no app store.** The phone just opens a web page. The bot's computer is reached
  through a free Cloudflare "quick tunnel" (no login).
- **Private.** Photos go to the bot's own computer. Location data (EXIF) is removed on arrival. The
  link that pairs the phone works like a password, and address updates are encrypted.
- **Self-healing.** If the connection drops or the address changes, the bot and the phone find
  each other again on their own, and photos taken meanwhile are uploaded later.

## Quick start (with the Grok Bot template)

1. Import the KALE 9000 template into your Grok Bot and say hi.
2. KALE asks a few questions (what you're growing, where, whether you have a spare phone).
3. If you have a spare phone or tablet, KALE installs the camera system from this repository's
   latest release (it checks a pinned SHA-256 checksum first) and sends you a **pairing link in
   your private chat**.
4. Set up the phone as below. KALE takes a test photo to confirm it works.

That's it. KALE then reviews your plants once a day and only speaks up when something needs doing.

## Setting up the phone

Any phone or tablet from the last several years with a working camera and a browser works (Android
with Chrome is best; iPhone/iPad with Safari works too).

1. **Open the pairing link** KALE sent you, on the phone. (Or scan the QR code if KALE sent one.)
   Don't share the link: anyone who has it can send photos to your bot.
2. **Allow the camera** when the browser asks.
3. Work through the short **Phone prep** checklist on the page.
4. **Add it to the Home screen** (Chrome: ⋮ menu → *Add to Home screen* / *Install app*; Safari:
   Share → *Add to Home Screen*) and open KALE from that icon. It then opens full-screen and keeps
   working after the phone restarts the browser.
5. **Keep the screen on and the phone charging.** Browsers pause pages that are in the background
   or when the screen is off. Turn on *Stay awake while charging* (Android developer options) or set
   Auto-Lock to *Never* (iPhone), and leave KALE's page open in front. The page can dim its preview.
6. **Mount it** so it sees the plant the same way every time (a cheap phone clamp or tripod). If you
   can, lock focus/exposure by tapping and holding on the plant in the camera preview.
7. Tell KALE it's done. She takes a photo and shows you what she sees.

### Battery safety (please read)

A phone that sits at **100 % charge in a warm place** (a grow tent, a sunny window) ages its
battery fast and can make it **swell**. A swollen battery is a fire risk.

- If the phone has a charge limit (e.g. "Protect battery" / "Adaptive charging" / "Optimized
  charging" / 80 % limit), turn it on.
- Otherwise put the charger on a **smart plug** with a charge cycle, for example *on 1 hour, off
  2 hours*, so the battery cycles between roughly 50 % and 90 %. (KALE shows the phone's battery
  level and warns when it gets low.)
- Keep the phone out of direct light and away from heaters and water. Check it every week or two;
  if the case bulges, the screen lifts or the phone gets hot, unplug it and stop using it.

## Smart plugs (optional, beta)

With a small always-on computer at home (a Raspberry Pi is plenty) and local smart plugs (Shelly,
Tasmota, older TP-Link Kasa, or anything Home Assistant controls), KALE can switch the light, fan
and pump. The bridge only makes outgoing connections, so nothing in your home is opened to the
internet. It is **beta and not tested on real hardware yet**: see [`bridge/README.md`](bridge/README.md)
(safety notes included) and [`kalecam/docs/BRIDGE-PROTOCOL.md`](kalecam/docs/BRIDGE-PROTOCOL.md).

## Installing without the template (any Linux computer)

Needs Python 3.10+ with `venv`, `flock`/`setsid` (util-linux), and outbound HTTPS.

```bash
# download kale-9000-<version>.tar.gz from this repository's Releases page, then:
sha256sum kale-9000-1.0.1.tar.gz          # compare with the checksum on the release page
tar -xzf kale-9000-1.0.1.tar.gz && cd kale-9000-1.0.1
./install.sh                              # installs to /workspace/kalecam and starts it
/workspace/kalecam/kalecam pair --plant basil-01 --camera phone-1   # prints the pairing link (secret!)
```

Options: `--prefix DIR` (install location), `--port N` (local port, default 8765), `--photo-root DIR`
(default `/workspace/grow-photos`), `--timezone Area/City`. Keep it running by calling
`/workspace/kalecam/watchdog.sh --ensure-loop` every few minutes (cron, systemd timer, or a bot
routine) and at boot.

Everyday commands (run in `/workspace/kalecam`, e.g. `./kalecam status`):

```bash
kalecam status                   # is everything up? phone battery, last photo, warnings
kalecam capture --wait 90        # take a photo now; prints where it was saved
kalecam photos --plant basil-01  # newest photos
kalecam schedule set --interval 30 --start 06:00 --end 22:00
kalecam pair --rotate-secret     # lost the phone or leaked the link: new secret, re-pair
```

**Updating:** download the new release, check its checksum, and run its `install.sh` again. Your
settings, pairing and photos are kept, and the phone stays paired.

**Uninstalling:** `./install.sh --uninstall --yes` (photos are kept).

## What it depends on

Free services with no account and no uptime guarantee: Cloudflare quick tunnels
(`*.trycloudflare.com`) for the address, and ntfy.sh, ntfy.envs.net and textdb.online to pass the
(encrypted) address to the phone when it changes. The Python packages `cryptography`, `qrcode` and
`pillow` come from PyPI. `cloudflared` is downloaded from its official GitHub release, **pinned to
one version and checked against a SHA-256 checksum** before use.

## Repository layout

| Path | What it is |
|---|---|
| `install.sh` | Installer / upgrader / uninstaller |
| `kalecam/` | Everything installed on the bot's computer: capture server, watchdog, `kalecam` CLI, phone web app (`app/`), encrypted rendezvous, `rotate.py`, `profiles/`, `docs/`, `tests/`. Technical reference: [`kalecam/README.md`](kalecam/README.md) |
| `reference/` | Full reference text for the plant skills (diagnosis, growth stages, environment targets, onboarding); installed to `<prefix>/reference/` |
| `kalecam/docs/DESIGN.md` | How photos, profiles, reviews and the watchdog fit together |
| `bridge/` | Reference home bridge `kalebridge` for smart plugs (beta) |

Tests: see [`kalecam/README.md#tests`](kalecam/README.md#tests). All suites run in isolation and
never touch a running install.

## Security notes

- The pairing link and `pairing-qr.png` contain the secret. Share them only with yourself, privately.
- The bot's server listens only on `127.0.0.1`; the tunnel is the only way in, and every API call
  needs the key derived from the secret. The phone web page itself holds no secrets.
- Report security problems privately through GitHub's *Report a vulnerability* on this repository.

## License

MIT, see [LICENSE](LICENSE). Not affiliated with any film studio, HAL, or Cloudflare.
