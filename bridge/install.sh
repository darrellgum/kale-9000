#!/bin/sh
# Install the reference bridge as a systemd service on Linux / Raspberry Pi OS.
#   sudo ./install.sh                 # runs as the user who called sudo
#   sudo ./install.sh --user pi       # or name the (unprivileged) user
#   sudo ./install.sh --uninstall     # remove the service and /opt/kalebridge (keeps your config)
set -eu
PREFIX=/opt/kalebridge
UNIT=/etc/systemd/system/kalebridge.service
HERE=$(cd "$(dirname "$0")" && pwd)
RUN_USER=${SUDO_USER:-}
UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --user) RUN_USER=$2; shift 2 ;;
    --uninstall) UNINSTALL=1; shift ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done
[ "$(id -u)" = 0 ] || { echo "run with sudo: sudo ./install.sh"; exit 1; }
if [ "$UNINSTALL" = 1 ]; then
  systemctl disable --now kalebridge 2>/dev/null || true
  rm -f "$UNIT" /usr/local/bin/kalebridge
  rm -rf "$PREFIX"
  systemctl daemon-reload
  echo "removed the service and $PREFIX (your config in ~/.config/kalebridge is kept)"
  exit 0
fi
[ -n "$RUN_USER" ] || { echo "say which user runs the bridge: sudo ./install.sh --user <name>"; exit 1; }
[ "$RUN_USER" != root ] || { echo "refusing to run the bridge as root; pick a normal user"; exit 1; }
getent passwd "$RUN_USER" >/dev/null || { echo "no such user: $RUN_USER"; exit 1; }
PY=$(command -v python3 || true)
[ -n "$PY" ] || { echo "python3 not found (sudo apt install python3)"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "python 3.9 or newer is needed"; exit 1; }
command -v systemctl >/dev/null || { echo "no systemd here: run it manually with: python3 $HERE/kalebridge.py run"; exit 1; }
USER_HOME=$(getent passwd "$RUN_USER" | cut -d: -f6)
CONFDIR="$USER_HOME/.config/kalebridge"

mkdir -p "$PREFIX"
rm -rf "$PREFIX/kalebridge"
cp -R "$HERE/kalebridge" "$HERE/kalebridge.py" "$HERE/bin" "$PREFIX/"
find "$PREFIX" -name __pycache__ -prune -exec rm -rf {} +
chown -R root:root "$PREFIX"
chmod -R go-w "$PREFIX"
ln -sf "$PREFIX/bin/kalebridge" /usr/local/bin/kalebridge

sudo -u "$RUN_USER" mkdir -p "$CONFDIR"
chmod 700 "$CONFDIR"

sed -e "s|@USER@|$RUN_USER|g" -e "s|@CONFDIR@|$CONFDIR|g" -e "s|@PREFIX@|$PREFIX|g" -e "s|@PYTHON@|$PY|g" \
  "$HERE/systemd/kalebridge.service.in" > "$UNIT"
chmod 644 "$UNIT"
systemctl daemon-reload
systemctl enable kalebridge >/dev/null
echo "installed: $PREFIX, command /usr/local/bin/kalebridge, service kalebridge (user $RUN_USER, config $CONFDIR)"
if [ -f "$CONFDIR/config.json" ]; then
  systemctl restart kalebridge
  echo "service (re)started. Logs: journalctl -u kalebridge -f"
else
  echo "next: as $RUN_USER run 'kalebridge pair', edit $CONFDIR/aliases.json, then: sudo systemctl start kalebridge"
fi
