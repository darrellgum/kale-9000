#!/bin/sh
# Run every test suite. The integration test needs the bot code (../kalecam) and uses ports
# 18791-18792 plus throwaway temp dirs; it never touches a live server.
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
for t in test_drivers test_engine test_rendezvous test_integration; do
  echo "== $t"
  "$PY" "tests/$t.py" "$@"
done
