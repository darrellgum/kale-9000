#!/usr/bin/env bash
# KALE 9000 installer. Copies the capture runtime (kalecam/) to PREFIX and starts it.
# Safe to re-run: an existing install keeps its config.json, pairing secrets, state, logs, venv
# and cloudflared binary, so the phone stays paired. Re-running with a newer release upgrades it.
#
#   ./install.sh                       install/upgrade to /workspace/kalecam and start it
#   ./install.sh --prefix DIR          install somewhere else (default: $KALECAM_PREFIX or /workspace/kalecam)
#   ./install.sh --port 8765           local server port (default 8765; only used on this computer)
#   ./install.sh --photo-root DIR      where photos go (default /workspace/grow-photos)
#   ./install.sh --timezone ZONE       e.g. Europe/Berlin (default: auto-detect from this computer)
#   ./install.sh --no-start            copy files only
#   ./install.sh --uninstall --yes     stop it and delete PREFIX (photos are kept)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/kalecam"
PREFIX="${KALECAM_PREFIX:-/workspace/kalecam}"
PORT="" PHOTO_ROOT="" TZNAME="" START=1 UNINSTALL=0 YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --photo-root) PHOTO_ROOT="$2"; shift 2 ;;
    --timezone) TZNAME="$2"; shift 2 ;;
    --no-start) START=0; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --yes) YES=1; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done
PREFIX="${PREFIX%/}"
VERSION="$(cat "$HERE/VERSION" 2>/dev/null || echo unknown)"

state_pid() {  # state_pid <key>: a pid recorded by the watchdog
  grep -o "\"$1\": [0-9]*" "$PREFIX/state/watchdog-state.json" 2>/dev/null | grep -o '[0-9]*$' || true
}
pid_is() {  # pid_is <pid> <text>: pid alive and its command line contains text
  [ -n "$1" ] && [ -r "/proc/$1/cmdline" ] && tr '\0' ' ' < "/proc/$1/cmdline" | grep -qF -- "$2"
}
stop_pid() { pid_is "$1" "$2" && kill "$1" 2>/dev/null || true; }

if [ "$UNINSTALL" = 1 ]; then
  [ -f "$PREFIX/watchdog.sh" ] || { echo "no kalecam install at $PREFIX"; exit 1; }
  [ "$YES" = 1 ] || { echo "this stops kalecam and deletes $PREFIX (secrets, state, logs; photos are kept). Re-run with --yes"; exit 2; }
  stop_pid "$(cat "$PREFIX/state/watchdog-loop.pid" 2>/dev/null || true)" "$PREFIX/watchdog.sh"
  stop_pid "$(state_pid server_pid)" "$PREFIX/server.py"
  stop_pid "$(state_pid cloudflared_pid)" "$PREFIX/bin/cloudflared"
  sleep 1
  rm -rf -- "$PREFIX"
  echo "uninstalled $PREFIX (photos kept)"
  exit 0
fi

# ------------------------------------------------------------------ prerequisites
[ -f "$SRC/server.py" ] || { echo "run this from the unpacked KALE 9000 release (kalecam/ not found next to install.sh)" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "python 3.10 or newer is required" >&2; exit 1; }
python3 -c 'import venv, ensurepip' 2>/dev/null || { echo "python3 venv support is missing (Debian/Ubuntu: sudo apt-get install -y python3-venv)" >&2; exit 1; }
for t in flock setsid; do command -v "$t" >/dev/null || { echo "$t is required (util-linux)" >&2; exit 1; }; done
case "$(uname -m)" in x86_64|amd64|aarch64|arm64) ;; *) echo "warning: no pinned cloudflared for $(uname -m); install cloudflared yourself as $PREFIX/bin/cloudflared" >&2 ;; esac

# ------------------------------------------------------------------ copy code
UPGRADE=0; [ -f "$PREFIX/watchdog.sh" ] && UPGRADE=1
OLD_VERSION="$(cat "$PREFIX/VERSION" 2>/dev/null || echo none)"
mkdir -p "$PREFIX"
changed=0
while IFS= read -r -d '' f; do
  rel="${f#"$SRC"/}"
  case "$rel" in config.json|state/*|secrets/*|logs/*|venv/*|bin/*|test-results/*|*/__pycache__/*|__pycache__/*|pairing-qr*.png) continue ;; esac
  dest="$PREFIX/$rel"
  mkdir -p "$(dirname "$dest")"
  if [ -f "$dest" ] && cmp -s "$f" "$dest"; then continue; fi
  # write a new file and rename it into place: a running bash loop keeps reading its old copy
  cp -p "$f" "$dest.new.$$" && mv -f "$dest.new.$$" "$dest"
  changed=$((changed + 1))
done < <(find "$SRC" -type f -print0)
cp "$HERE/VERSION" "$PREFIX/VERSION.new.$$" && mv -f "$PREFIX/VERSION.new.$$" "$PREFIX/VERSION"
for d in README.md LICENSE CHANGELOG.md; do [ -f "$HERE/$d" ] && cp "$HERE/$d" "$PREFIX/docs/$d" 2>/dev/null || true; done
chmod 755 "$PREFIX/watchdog.sh" "$PREFIX/watchdog.py" "$PREFIX/kalecam" "$PREFIX/kalecam_cli.py" "$PREFIX/server.py" "$PREFIX/rotate.py"
mkdir -p "$PREFIX/state" "$PREFIX/logs"; mkdir -p -m 700 "$PREFIX/secrets"; chmod 700 "$PREFIX/secrets"

# ------------------------------------------------------------------ config
python3 - "$PREFIX" "$PORT" "$PHOTO_ROOT" "$TZNAME" <<'PY'
import json, sys
from pathlib import Path
prefix, port, root, tz = sys.argv[1:5]
cfgp = Path(prefix) / "config.json"
cfg = json.loads(cfgp.read_text()) if cfgp.exists() else json.loads((Path(prefix) / "config.example.json").read_text())
if port:
    cfg["port"] = int(port)
if root:
    cfg["photo_root"] = root
if tz:
    from zoneinfo import ZoneInfo
    ZoneInfo(tz)  # raises if the name is unknown
    cfg["timezone"] = tz
tmp = cfgp.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2) + "\n")
tmp.replace(cfgp)
print(f"config: port {cfg['port']}, photos in {cfg['photo_root']}, timezone {cfg.get('timezone') or 'auto'}")
PY

if [ "$UPGRADE" = 1 ]; then
  echo "upgraded $PREFIX: $OLD_VERSION -> $VERSION ($changed files changed)"
else
  echo "installed KALE 9000 $VERSION to $PREFIX"
fi
[ "$START" = 1 ] || { echo "not started (--no-start). Start with: $PREFIX/watchdog.sh --ensure-loop"; exit 0; }

# ------------------------------------------------------------------ (re)start
if [ "$UPGRADE" = 1 ] && [ "$changed" -gt 0 ]; then
  # load the new code: restart the loop and the server. The tunnel keeps running, so the
  # public address (and the paired phone) stays the same.
  stop_pid "$(cat "$PREFIX/state/watchdog-loop.pid" 2>/dev/null || true)" "$PREFIX/watchdog.sh"
  stop_pid "$(state_pid server_pid)" "$PREFIX/server.py"
  sleep 1
fi
echo "starting (first run creates a Python venv and downloads cloudflared; about a minute)..."
"$PREFIX/watchdog.sh" --ensure-loop || true
echo
"$PREFIX/kalecam" status || true
