# KALE 9000: system design

How plant photos get from a spare phone to the bot's own computer, how they're named and indexed, how they're thinned over time so the disk doesn't fill up, and how the bot turns them into care advice.

> Status: **implemented** (v1.0.0). Capture is the kalecam phone web app + quick-tunnel server described in §6 and in `../README.md` (technical reference).

---

## 1. Goals

1. Get regular, consistently framed photos of each plant with no daily effort from the owner.
2. Store them in a predictable layout the bot can reason about ("last 24 h of tomato-01", "same time 7 days ago").
3. Keep recent history at full resolution for diagnosis. Keep long history cheaply for trends and timelapses.
4. **Never lose milestone photos** (first true leaves, first flower, first fruit set, first ripe fruit, etc.).
5. Stay generic: no personal accounts, devices, or locations baked in. Everything is configured with placeholders.
6. Know **which plant is which** in every frame, and notice when a **new or unknown plant** shows up so it can be onboarded.

---

## 2. Directory layout (on the bot's own computer)

```
/workspace/kalecam/                         # the installed capture runtime (install.sh --prefix to change)
├── server.py, watchdog.sh, kalecam, ...    # see ../README.md
├── rotate.py                               # intake + rotation tool (§4)
├── profiles/PROFILE-TEMPLATE.md            # blank plant profile + EXAMPLE-grocery-basil.md
├── docs/                                   # this file, BRIDGE-PROTOCOL.md, daily-review-routine.md
├── config.json                             # port, photo_root, schedule, timezone ... (never shared)
└── secrets/, state/, logs/, venv/, bin/    # created at run time, never packaged
/workspace/grow-photos/                     # photo root (config "photo_root"; rotate.py: --root / $KALE_PHOTO_ROOT)
├── rotation-log.jsonl                      # one line per applied rotation run
├── <plant-id>/                             # e.g. tomato-01, basil-01 (lowercase, digits, - or _)
│   ├── index.jsonl                         # per-plant photo index (one JSON object per photo)
│   └── YYYY/MM/DD/
│       ├── HHMMSS-<camera>.jpg             # e.g. 143000-phone-1.jpg (the standard name)
│       ├── HHMMSS-<camera>.json            # optional sidecar metadata (same fields as the index)
│       └── HHMMSS-<camera>-1.jpg           # rare same-second collision
└── ...
/workspace/grow-log/<plant-id>.jsonl        # growth-stage log (growth-stage-tracker skill)
/workspace/grow-profiles/<plant-id>.md      # per-plant profile: targets, watch_list, camera regions
                                            # (plant-onboarding-interview skill)
```

- **Times in paths are bot-local time** (config `timezone`, else the computer's zone, resolved explicitly so a server started before the zone was set still names folders correctly). The owner thinks in local time, and "midday photo" only makes sense locally. The index stores full ISO 8601 timestamps **with UTC offset**, so the data stays unambiguous across DST changes. Photos taken while the phone was offline keep their real capture time.
- One folder per plant. The plant id comes from `kalecam capture --plant`, then `camera_plants` in the config, then the pairing link, then `default_plant`. If one camera frame covers several plants, either store the frame under each plant or use a group id like `pod-1` and list the plants in the profile. Each plant's profile records its `camera_regions` (which part of which camera's frame is that plant), so the review can crop to the right plant.
- A plant that hasn't been identified yet gets a temporary folder `new-<YYYYMMDD>-<n>/`. After onboarding assigns the permanent `<plant-id>`, point the camera at it (`kalecam config set camera_plants.<camera> <plant-id>`), copy the day-0 frame across with `rotate.py add --copy` and flag it keep-forever; the temporary folder then ages out through normal rotation.

## 3. Filename and metadata conventions

**Filename**: `HHMMSS-<camera>.jpg` inside `YYYY/MM/DD/`, for example `2026/05/05/120000-phone-1.jpg`. The capture server always writes this form (config `camera_suffix: true`), and `rotate.py add` does too when given `--source`. `rotate.py` also accepts plain `HHMMSS.jpg` (older/other sources), and `rotate.py flag --file .../HHMMSS.jpg` finds the `-<camera>` file when there is exactly one from that second. JPEG is preferred; PNG and WebP are accepted by `rotate.py`.

To find photos, use `kalecam photos --plant <id> -n 5` (newest first, full paths) or read `index.jsonl`; don't guess names.

**Index entry** (`index.jsonl`, appended at intake, updated by rotation):

```json
{
  "file": "2026/05/05/120000-phone-1.jpg",
  "ts": "2026-05-05T12:00:00-07:00",
  "plant": "tomato-01",
  "source": "phone-1",
  "bytes": 512344,
  "status": "active",
  "milestone": null,
  "keep": false,
  "quality": "good",
  "best": false,
  "trigger": "schedule",
  "width": 4032, "height": 3024,
  "light": "grow-light",
  "sensors": {"t_c": 24.1, "rh": 62}
}
```

| Field | Meaning |
|---|---|
| `file` | Path relative to the plant folder (primary key) |
| `ts` | Capture time, ISO 8601 with offset |
| `source` | Camera name, e.g. `phone-1`, `webcam-top`. **Never** a serial number, account, or location. |
| `status` | `active`, `pruned` (deleted by rotation), `trashed` (moved to trash dir) |
| `milestone` | Milestone name, or null. Non-null means keep forever. |
| `keep` | `true` means keep forever even without a milestone (e.g., a good problem-and-fix "before" photo) |
| `quality` | `good` / `usable` / `unusable`, set by the photo-diagnosis quality check |
| `best` | `true` means preferred as that day's representative photo |
| `trigger` | `schedule`, `command` (`kalecam capture`), `manual` (button on the phone) — written by the server |
| `light` | `grow-light` / `white` / `daylight` / `dark` (helps choose color-reliable frames) |
| `sensors` | Optional sensor snapshot nearest to the capture time. **Not filled automatically**: kalecam has no sensor feed. If a thermo-hygrometer display is in frame, the bot can read it from the photo; otherwise the owner reports readings |
| `downscaled` | Set by rotation once the file has been downscaled |

The server also writes `cmd_id, photo_id, received_at, queued, sha256, app_version`. `rotate.py` keeps unknown fields.

**Sidecar** `HHMMSS-<camera>.json` is optional and uses the same fields. Rotation merges index and sidecar values, with the sidecar winning.

**Privacy**: phone photos can carry **GPS and device info in EXIF**. The capture server strips EXIF/XMP at intake (`strip_exif: true`). Downscaled files from `rotate.py` are saved without EXIF.

---

## 4. Rotation policy

Implemented by `rotate.py` (Python 3, stdlib only. Pillow is optional and used only for downscaling).

| Photo age (calendar days, today = 0) | What's kept |
|---|---|
| **0 … N−1** (default **N = 7**) | **Everything**, full size |
| **N … D−1** (default **D = 30**) | **One photo per day**, full size |
| **≥ D** | **One photo per day**, **downscaled** to max edge 1600 px (JPEG q85). Set `--downscale-after-days 0` to disable. |
| Any age, `milestone` set or `keep: true` | **Kept forever, never downscaled** |

**Choosing the one photo per day**, in priority order:
1. `best: true` (set by the daily review, e.g. the white-light frame or the clearest shot)
2. Quality: `good` > `usable` > unknown > `unusable`
3. Closest to the target time (`--target-time`, default `12:00`; set it to the middle of the photoperiod or the time of the daily white-light frame)
4. Earliest

Safety features:
- **Dry run by default.** Nothing changes without `--apply`.
- `--trash-dir <path>` moves pruned files there instead of deleting them. Recommended for the first few weeks.
- A lock file stops two rotations from running at once. Index and sidecar rewrites are atomic.
- Idempotent: running it twice does nothing the second time.
- Files that don't match the naming pattern (notes, videos) are ignored.
- Each applied run appends a summary line to `rotation-log.jsonl`.

### Usage

```bash
# Store an incoming image (moves it; --copy to copy) and index it
R=/workspace/kalecam/rotate.py
python3 $R add --plant tomato-01 --file /tmp/upload.jpg --source webcam-top \
    --ts 2026-05-05T12:00:00-07:00 --sensors '{"t_c":24.1,"rh":62}'    # -> 2026/05/05/120000-webcam-top.jpg

# Mark a photo as a milestone (keep forever)
python3 $R flag --plant tomato-01 --file 2026/05/05/120000-phone-1.jpg --milestone first_flower

# Preview rotation, then apply it
python3 $R rotate
python3 $R rotate --apply --trash-dir /workspace/grow-photos-trash

# Options: --root, --plant, --keep-full-days 7, --target-time 12:00,
#          --downscale-after-days 30, --max-edge 1600, --jpeg-quality 85, --json
```

Test: `python3 tests/test_rotate.py` generates about 180 dummy images across two plants and checks the recent-day window, one-per-day thinning, milestone protection (index and sidecar), skipping `unusable` frames, multi-camera names, downscaling (when Pillow is present), trash-dir mode, index updates, and idempotency.

---

## 5. Disk budget estimate

Capture recommendation: **one photo every 30–60 min during lights-on only** (frames in the dark are useless), plus **one daily white-light frame** for color checks. **~1920×1080 (2 MP) is enough for routine diagnosis.** Ask the owner for full-resolution close-ups when needed.

Typical JPEG sizes: 1080p ≈ 0.3–0.6 MB. 12 MP phone photo ≈ 3–5 MB. 1600 px downscaled ≈ 0.2–0.5 MB. Real sizes depend on scene detail and compression.

| Per plant | 1080p @ 0.5 MB, 16 photos/day | 12 MP @ 4 MB, 16 photos/day |
|---|---|---|
| Last 7 days (all photos) | 7 × 16 × 0.5 ≈ **56 MB** | 7 × 16 × 4 ≈ **450 MB** |
| Days 8–30 (1/day, full size) | 23 × 0.5 ≈ 12 MB | 23 × 4 ≈ 92 MB |
| Days 31–365 (1/day, downscaled ~0.4 MB) | 335 × 0.4 ≈ 134 MB | ≈ 134 MB |
| Milestones (~20/plant, full size) | ≈ 10 MB | ≈ 80 MB |
| **Steady state, one plant-year** | **≈ 0.2 GB** | **≈ 0.75 GB** |

With 4 plants, that's about **1 GB/year at 1080p** or **3 GB/year at 12 MP**. The 7-day full window is the main cost at high resolution, so reduce resolution or frequency before shrinking the window. Also leave headroom for timelapse renders (usually small, ~5–50 MB each).

---

## 6. Capture: the kalecam phone camera

The camera side doesn't know anything about plants. It is a web app (PWA) on a spare phone or tablet, served by the bot's own computer. No accounts anywhere (no app store, no Cloudflare login).

```
 phone: browser PWA  ──HTTPS──►  Cloudflare quick tunnel (random https://<words>.trycloudflare.com)
   camera → JPEG → IndexedDB queue → POST /upload            │ cloudflared, outbound only
   long-poll GET /poll ◄── commands (kalecam capture)        ▼
   POST /heartbeat (battery, queue, visibility)      server.py on 127.0.0.1:<port> (default 8765)
   GET /config (schedule, capture settings)            writes photos + index.jsonl itself (§2, §3)
 when the server can't be reached:                  watchdog (background loop + a bot routine)
   read ntfy.sh / ntfy.envs.net / textdb.online  ◄──  publishes AES-GCM({url, seq}) when the URL changes
   decrypt → newest seq → verify /healthz → switch     and hourly
```

- **Pairing**: `kalecam pair --plant <id> --camera <name>` makes a link (and `pairing-qr.png`) that carries the pairing secret in the URL fragment. The secret derives the upload key and the rendezvous encryption key. **The link is a password**: give it to the owner privately, never post it. `kalecam pair --rotate-secret` revokes it.
- **Schedule**: runs on the phone (`kalecam schedule set --interval 30 --start 06:00 --end 22:00`), in the bot's timezone. Photos taken offline are queued on the phone and uploaded later with their real capture time.
- **On demand**: `kalecam capture [camera] --wait 90` queues a command that the phone picks up through its long-poll; it prints the stored file path.
- **Health**: `kalecam status` shows server, tunnel, rendezvous and per-camera heartbeat, battery, queue and warnings.
- **Self-healing** (`watchdog.sh`): checks the local server first, then the tunnel end to end (`/healthz` through the public URL must return this server's instance id). A dead server is restarted before the tunnel is ever touched, so the URL only changes when the tunnel itself is broken. A new tunnel URL is published encrypted to three free relays, where the phone finds it. cloudflared is a pinned release, checked by sha256. There is no cron/systemd on a bot's computer, so a bot routine runs `watchdog.sh --ensure-loop` every few minutes; that is also the reboot hook.
- **Phone practicalities**: browsers throttle background tabs, so the page stays in front with the screen on (Wake Lock, dimmed preview option) and the phone on a charger. Lock focus/exposure if possible and fix the mount so framing is consistent. **Battery safety**: a phone kept at 100% in a warm grow space can swell. Use the phone's charge limit if it has one, or put the charger on a smart plug with a charge cycle (e.g. on 1 h, off 2 h), and inspect the phone regularly.
- **Sensors**: kalecam has no sensor input. Put a cheap thermo-hygrometer with a display in frame and the bot can read it from photos, or ask the owner for readings. The optional home bridge (`BRIDGE-PROTOCOL.md`, reference implementation in the release's `bridge/`, beta) can switch light/fan/pump plugs and report simple sensors.

Other capture sources (a webcam script, an IP-camera snapshot) can feed the same layout with `rotate.py add --source <camera>`.

---

## 7. Profiles and new-plant detection

The photo pipeline doesn't know anything about plants. The **daily review** connects photos to profiles:

1. For each plant with `status: active`, load `/workspace/grow-profiles/<plant-id>.md`. Its `targets` are checked against the sensor snapshot, its `watch_list` feeds the photo diagnosis, and its `camera_regions` say where to look in each frame.
2. **New or unknown plants**: if a frame shows plant material outside every known camera region, a known region shows a plant that no longer matches its profile, or a folder has photos but no profile, the review runs identification (plant-photo-diagnosis Step 1b) and starts the **plant-onboarding-interview** skill. It doesn't raise an alarm; it sends one friendly onboarding message.
3. **Provisional profiles** (`confirmed_by_owner: no`) are used normally but reported as provisional. The review asks for confirmation once, in its next message, then leaves it.
4. **No profile yet** (onboarding in progress): diagnose with the first-principles fallback and alert only on urgent findings.

## 8. Daily flow

1. The phone uploads frames on its schedule; the server stores and indexes them (§2, §3). The bot can ask for a fresh frame any time with `kalecam capture`.
2. The **daily plant review routine** (see `daily-review-routine.md`) runs once a day in the evening. It checks `kalecam status`, loads each plant's profile, diagnoses the day's photos against the profile's targets and watch_list, notices new or unknown plants and starts onboarding, compares with earlier days, updates the growth-stage log, sets `best`/`quality`/`milestone` flags, then runs `rotate.py rotate --apply`.
3. The **capture watchdog routine** runs `watchdog.sh --ensure-loop` every 5 minutes and tells the owner once per outage if it can't heal.
4. The owner hears from the bot only if action is needed, a milestone happened, or a new plant needs onboarding.

## 9. Open decisions
- Whether to delete pruned photos or use `--trash-dir` (and for how long).
- Whether to add a longer-term tier later (e.g., one photo per week after 1 year).
- How to mark camera regions: a plain description only, or fractional x, y, w, h boxes the review can crop to automatically.
- A stable hostname (named tunnel) instead of quick tunnels, for owners who have a Cloudflare account.
