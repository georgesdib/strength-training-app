#!/usr/bin/env bash
# Launch the strength-coach local web UI.
#
#   ./run-web.sh                 # http://127.0.0.1:8000, opens a browser
#   ./run-web.sh --no-open       # same, without opening a browser
#   ./run-web.sh --port 8001     # another port
#   ./run-web.sh --db other.db   # another athlete database
#   ./run-web.sh --help          # wrapper help plus every `strength-coach web` option
#
# The UI binds 127.0.0.1 and has no authentication: it must never be exposed on a network
# (AGENTS.md). Non-loopback --host values are refused rather than forwarded.

set -euo pipefail

usage() {
  cat <<'EOF'
Launch the strength-coach local web UI.

Usage: ./run-web.sh [--no-open] [options passed to `strength-coach web`]

  --no-open        do not open a browser (default: open)
  --port N         port to bind (default 8000)
  --db PATH        database to serve (default data/coach.db)
  -h, --help       show this help and the full option list

The server binds 127.0.0.1 only and has no authentication. Any other option is
passed through, so `--host` is accepted only for loopback addresses.
EOF
}

# Resolve the repository root even when the script is invoked through a symlink.
if [ -z "${BASH_VERSION:-}" ]; then
  echo "run-web: run this with bash (./run-web.sh), not sh" >&2
  exit 1
fi
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P -- "$(dirname -- "$SOURCE")" && pwd)"
  SOURCE="$(readlink -- "$SOURCE")"
  case "$SOURCE" in
    /*) ;;
    *) SOURCE="$DIR/$SOURCE" ;;
  esac
done
ROOT="$(cd -P -- "$(dirname -- "$SOURCE")" && pwd)"
cd "$ROOT"

OPEN_BROWSER="${OPEN_BROWSER:-1}"
SHOW_HELP=0
expect_host=0
expect_db=0
ARGS=()
# `--db` is a global option in the CLI, so it must precede the `web` subcommand.
DB_ARGS=()

refuse_host() {
  echo "run-web: refusing --host $1: the UI is local-only (bind 127.0.0.1)" >&2
  exit 2
}

for arg in "$@"; do
  if [ "$expect_host" = 1 ]; then
    case "$arg" in
      127.0.0.1 | localhost | ::1) ;;
      *) refuse_host "$arg" ;;
    esac
    ARGS+=("$arg")
    expect_host=0
    continue
  fi
  if [ "$expect_db" = 1 ]; then
    DB_ARGS=(--db "$arg")
    expect_db=0
    continue
  fi
  case "$arg" in
    -h | --help)
      usage
      SHOW_HELP=1
      ARGS+=("$arg")
      ;;
    --db)
      expect_db=1
      ;;
    --db=*)
      DB_ARGS=("$arg")
      ;;
    --no-open)
      OPEN_BROWSER=0
      ;;
    --open)
      OPEN_BROWSER=1
      ;;
    --host)
      expect_host=1
      ARGS+=("$arg")
      ;;
    --host=*)
      value="${arg#--host=}"
      case "$value" in
        127.0.0.1 | localhost | ::1) ARGS+=("$arg") ;;
        *) refuse_host "$value" ;;
      esac
      ;;
    *)
      ARGS+=("$arg")
      ;;
  esac
done

if [ "$expect_host" = 1 ]; then
  echo "run-web: --host needs a value" >&2
  exit 2
fi
if [ "$expect_db" = 1 ]; then
  echo "run-web: --db needs a value" >&2
  exit 2
fi

# Pick the interpreter: an explicit $PYTHON, then the project venv, then PATH.
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in "$ROOT/.venv/bin/python" python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON="$candidate"
      break
    fi
  done
fi
if [ -z "$PYTHON" ]; then
  echo "run-web: no Python found; install Python 3.11+ (or create .venv)" >&2
  exit 1
fi

# Import the CLI, not just the package: the check must catch missing runtime dependencies
# (pandas, numpy, PyYAML) before the server fails with a traceback.
if ! "$PYTHON" -c 'import sys, strength_coach.cli; assert sys.version_info >= (3, 11)' 2>/dev/null; then
  echo "run-web: $PYTHON cannot import strength_coach (needs Python 3.11+ and the project's dependencies)." >&2
  echo "         from this directory: $PYTHON -m pip install -e ." >&2
  exit 1
fi

if [ "$OPEN_BROWSER" = 1 ] && [ "$SHOW_HELP" = 0 ]; then
  ARGS+=(--open)
fi

exec "$PYTHON" -m strength_coach.cli "${DB_ARGS[@]}" web "${ARGS[@]}"
