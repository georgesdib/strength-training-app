#!/usr/bin/env bash
# Thin wrapper so the lanes work without GNU make (make is absent on the ODROID image).
#   ./check.sh          fast lane for the files changed vs HEAD
#   ./check.sh full     exactly what CI runs
#   ./check.sh docs     regenerate generated doc blocks, then check them
#   ./check.sh lint     ruff on changed files
#   ./check.sh install-hook
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || PY=python
exec "$PY" tools/check.py "$@"
