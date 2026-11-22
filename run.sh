#!/usr/bin/env bash
# FacebookDiary launcher.
# Usage: facebookdiary [search words]   -> the diary window (optionally starting with that search)
#        facebookdiary --import [folder] -> (re)build the index from the Facebook export zip(s)
#        facebookdiary --check           -> headless regression checks
set -euo pipefail
HERE="$(dirname "$(readlink -f "$0")")"
PY="${FACEBOOKDIARY_PYTHON:-python3}"
case "${1:-}" in
  --check) shift; QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" exec "$PY" "$HERE/_facebookdiary_check.py" "$@" ;;
  *)       exec "$PY" "$HERE/facebookdiary.py" "$@" ;;
esac
