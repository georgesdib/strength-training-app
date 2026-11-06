#!/usr/bin/env bash
# Create the project virtualenv and install its dependencies.
#
# Run this from an extracted repository export. The archive itself is not extracted here
# because this script lives inside the archive; extract it first, then run this script.
#
#   ./setup-venv.sh                  # editable install with dev/test tools
#   ./setup-venv.sh --locked         # reproducible requirements.lock install
#   ./setup-venv.sh --python python3.12
#
# The script never activates the venv in your current shell; use
# "source .venv/bin/activate" afterwards if you want the strength-coach command on PATH.

set -euo pipefail

ROOT="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
MODE="dev"

usage() {
  cat <<'EOF'
Create .venv and install the repository dependencies.

Usage:
  ./setup-venv.sh [--locked] [--python PYTHON]

Options:
  --locked         Install requirements.lock, then the project without resolving
                   dependencies again. This matches CI more closely.
  --python PATH    Python interpreter to use (default: $PYTHON, then python3).
  -h, --help       Show this help.

After setup:
  source .venv/bin/activate
  ./run-web.sh --no-open
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --locked)
      MODE="locked"
      ;;
    --python)
      if [ "$#" -lt 2 ]; then
        echo "setup-venv: --python needs a value" >&2
        exit 2
      fi
      PYTHON="$2"
      shift
      ;;
    --python=*)
      PYTHON="${1#--python=}"
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "setup-venv: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "setup-venv: Python interpreter not found: $PYTHON" >&2
  exit 2
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating .venv with $PYTHON ..."
  "$PYTHON" -m venv .venv
else
  echo "Using existing .venv"
fi

if ! .venv/bin/python -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
  echo "setup-venv: Python 3.11 or newer is required" >&2
  exit 2
fi

echo "Upgrading pip ..."
.venv/bin/python -m pip install --upgrade pip

if [ "$MODE" = "locked" ]; then
  if [ ! -f requirements.lock ]; then
    echo "setup-venv: requirements.lock is missing" >&2
    exit 2
  fi
  echo "Installing pinned requirements ..."
  .venv/bin/python -m pip install -r requirements.lock
  echo "Installing project ..."
  .venv/bin/python -m pip install -e . --no-deps
else
  echo "Installing project with dev extras ..."
  .venv/bin/python -m pip install -e ".[dev]"
fi

if ! .venv/bin/strength-coach --help >/dev/null; then
  echo "setup-venv: strength-coach did not start correctly" >&2
  exit 1
fi

echo
echo "Ready: $ROOT/.venv"
echo "Mode:  $MODE"
echo "Next:  source .venv/bin/activate && ./run-web.sh --no-open"
