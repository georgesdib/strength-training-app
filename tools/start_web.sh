#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec .venv/bin/python -m strength_coach.cli --db data/coach.db web --host 0.0.0.0 --port 8000
