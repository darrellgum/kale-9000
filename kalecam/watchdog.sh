#!/usr/bin/env bash
# kalecam watchdog wrapper. Idempotent; safe to run every few minutes and after a reboot.
#   ./watchdog.sh                 one check/heal pass (skips if another pass is running)
#   ./watchdog.sh --ensure-loop   one pass, then make sure the background loop is running
#   ./watchdog.sh --loop          run forever (every $KALECAM_WATCHDOG_INTERVAL s, default 150)
#   extra flags are passed to watchdog.py (--force-publish, --restart-tunnel)
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1
mkdir -p state logs
INTERVAL="${KALECAM_WATCHDOG_INTERVAL:-150}"

ensure_venv() {
  if ! venv/bin/python -c "import cryptography, qrcode" >/dev/null 2>&1; then
    echo "$(date +%FT%T%z) (re)creating venv" >> logs/watchdog.log
    python3 -m venv venv && venv/bin/pip install -q -r requirements.txt >> logs/watchdog.log 2>&1
  fi
}

case "${1:-}" in
  --loop)
    exec 9>state/watchdog-loop.lock
    flock -n 9 || { echo "watchdog loop already running"; exit 0; }
    echo $$ > state/watchdog-loop.pid
    pid_of() { grep -o "\"$1\": [0-9]*" state/watchdog-state.json 2>/dev/null | grep -o '[0-9]*$'; }
    while true; do
      "$DIR/watchdog.sh" --quiet 9>&- >> logs/watchdog-loop.out 2>&1
      # full pass every $INTERVAL s; in between, a cheap 10 s check for a dead server/cloudflared process
      for ((i = 0; i < INTERVAL; i += 10)); do
        sleep 10 9>&-
        s=$(pid_of server_pid); c=$(pid_of cloudflared_pid)
        # the server was fine at the last pass and has died since: heal it now (server first)
        if grep -q '"server_ok": true' state/watchdog-state.json 2>/dev/null && { [ -z "$s" ] || ! kill -0 "$s" 2>/dev/null; }; then break; fi
        grep -q '"last_run_ok": true' state/watchdog-state.json 2>/dev/null || continue  # failing: wait for the next full pass
        if [ -z "$s" ] || [ -z "$c" ] || ! kill -0 "$s" 2>/dev/null || ! kill -0 "$c" 2>/dev/null; then break; fi
      done
    done
    ;;
  --ensure-loop)
    shift
    ensure_venv
    flock -n -E 75 state/watchdog.lock venv/bin/python watchdog.py "$@"; rc=$?
    [ "$rc" = 75 ] && { echo "another watchdog pass is running; skipped this one"; rc=0; }
    if flock -n state/watchdog-loop.lock true; then
      setsid nohup "$DIR/watchdog.sh" --loop >/dev/null 2>&1 < /dev/null &
      sleep 0.5
      echo "started watchdog loop (pid $(cat state/watchdog-loop.pid 2>/dev/null || echo '?'), every ${INTERVAL}s)"
    else
      echo "watchdog loop running (pid $(cat state/watchdog-loop.pid 2>/dev/null || echo '?'))"
    fi
    exit $rc
    ;;
  *)
    ensure_venv
    flock -n -E 75 state/watchdog.lock venv/bin/python watchdog.py "$@"; rc=$?
    [ "$rc" = 75 ] && { echo "another watchdog pass is running; skipped this one"; exit 0; }
    exit $rc
    ;;
esac
