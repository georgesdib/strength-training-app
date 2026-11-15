#!/usr/bin/env bash
# Install (or remove) the read-only Strength Intelligence MCP service for THIS checkout.
#
#   sudo deploy/install-intelligence-mcp.sh              # install or update the unit
#   sudo deploy/install-intelligence-mcp.sh --uninstall  # disable and remove it
#        deploy/install-intelligence-mcp.sh --print      # render the unit; no root needed
#
# The repository unit (deploy/strength-intelligence-mcp.service) targets /opt and a dedicated
# strength-intel user. This host keeps the checkout under /home and has no such user, so the
# installer renders the same hardening with the real checkout, service user and paths. It never
# reads or writes the token itself.
#
# Override the derived paths with MCP_USER, MCP_CONFIG, MCP_TOKENS or MCP_DB if needed.

set -euo pipefail

UNIT_NAME=strength-intelligence-mcp.service
UNIT_PATH="/etc/systemd/system/${UNIT_NAME}"

ROOT="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

MODE=install
for argument in "$@"; do
  case "$argument" in
    --print) MODE=print ;;
    --uninstall) MODE=uninstall ;;
    -h | --help)
      sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown argument: $argument (try --help)" >&2
      exit 2
      ;;
  esac
done

# The service must not run as root. Prefer the user who invoked sudo, then the checkout owner.
# stat differs between GNU and BSD; the installer is exercised on macOS as well as Linux.
checkout_owner() {
  stat -c %U "$1" 2>/dev/null || stat -f %Su "$1" 2>/dev/null || id -un
}
SERVICE_USER="${MCP_USER:-${SUDO_USER:-}}"
if [ -z "$SERVICE_USER" ] || [ "$SERVICE_USER" = root ]; then
  SERVICE_USER="$(checkout_owner "$ROOT")"
fi
SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
USER_HOME="$(getent passwd "$SERVICE_USER" 2>/dev/null | cut -d: -f6 || true)"
if [ -z "$USER_HOME" ]; then
  USER_HOME="$(python3 -c 'import pwd, sys; print(pwd.getpwnam(sys.argv[1]).pw_dir)' "$SERVICE_USER" 2>/dev/null || true)"
  [ -n "$USER_HOME" ] || USER_HOME="${HOME:-/tmp}"
fi
CONFIG="${MCP_CONFIG:-$USER_HOME/.config/strength-coach/intelligence.v1.yaml}"
TOKENS="${MCP_TOKENS:-$ROOT/config/intelligence.local.yaml}"
DB="${MCP_DB:-$ROOT/data/coach.db}"
DB_DIR="$(dirname "$DB")"

TZ_VALUE="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
[ -n "$TZ_VALUE" ] || TZ_VALUE="$(cat /etc/timezone 2>/dev/null || echo UTC)"

BIND_HOST="$(sed -n 's/^bind_host:[[:space:]]*//p' "$CONFIG" 2>/dev/null | head -1 || true)"
BIND_HOST="${BIND_HOST:-127.0.0.1}"
BIND_PORT="$(sed -n 's/^bind_port:[[:space:]]*//p' "$CONFIG" 2>/dev/null | head -1 || true)"
BIND_PORT="${BIND_PORT:-8765}"
CHECK_HOST="$BIND_HOST"
[ "$CHECK_HOST" = "0.0.0.0" ] && CHECK_HOST=127.0.0.1

render_unit() {
  cat <<EOF
[Unit]
Description=Strength Intelligence MCP server (read-only)
Documentation=file:$ROOT/docs/INTELLIGENCE-DEPLOYMENT.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$ROOT
Environment=HOME=$USER_HOME
Environment=PATH=$ROOT/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=TZ=$TZ_VALUE
# --db is a global CLI option: it must precede the subcommand or argparse rejects the unit.
ExecStart=$ROOT/.venv/bin/strength-coach --db $DB intelligence serve --config $CONFIG --tokens $TOKENS
Restart=on-failure
RestartSec=5
TimeoutStopSec=20

# The service needs read access only. ProtectHome=read-only keeps the /home checkout readable
# while PYTHONDONTWRITEBYTECODE stops Python from writing __pycache__ beside it.
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=read-only
# A read-only SQLite connection still needs to create/map the WAL -shm/-wal files beside a
# WAL-mode database. Keep the rest of the filesystem read-only but allow this directory.
ReadWritePaths=$DB_DIR
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
LockPersonality=true
RestrictSUIDSGID=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
EOF
}

if [ "$MODE" = print ]; then
  if [ "$SERVICE_USER" = root ]; then
    echo "warning: no non-root service user could be derived; set MCP_USER" >&2
  fi
  render_unit
  exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "this installer must run as root: sudo $0" >&2
  exit 1
fi

if [ "$MODE" = uninstall ]; then
  systemctl disable --now "$UNIT_NAME" 2>/dev/null || true
  rm -f "$UNIT_PATH"
  systemctl daemon-reload
  echo "removed $UNIT_PATH"
  exit 0
fi

# --- preconditions ---------------------------------------------------------------------
if [ "$SERVICE_USER" = root ]; then
  echo "refusing to run the MCP service as root; set MCP_USER or invoke with sudo" >&2
  exit 1
fi
[ -x "$ROOT/.venv/bin/strength-coach" ] || {
  echo "$ROOT/.venv/bin/strength-coach is missing; create the venv and install the project" >&2
  exit 1
}
"$ROOT/.venv/bin/python" -c 'import mcp' 2>/dev/null || {
  echo "the optional transport dependency is missing; run:" >&2
  echo "  $ROOT/.venv/bin/pip install -e '$ROOT[intelligence]'" >&2
  exit 1
}
[ -r "$CONFIG" ] || { echo "config not found: $CONFIG" >&2; exit 1; }
grep -Eq '^[[:space:]]*enabled:[[:space:]]*true[[:space:]]*$' "$CONFIG" || {
  echo "$CONFIG does not set enabled: true; the server would refuse to start" >&2
  exit 1
}
[ -r "$TOKENS" ] || { echo "token file not found: $TOKENS" >&2; exit 1; }
[ -r "$DB" ] || { echo "database not found: $DB" >&2; exit 1; }
if command -v runuser >/dev/null 2>&1; then
  for path in "$CONFIG" "$TOKENS" "$DB"; do
    runuser -u "$SERVICE_USER" -- test -r "$path" || {
      echo "$SERVICE_USER cannot read $path; fix ownership before installing" >&2
      exit 1
    }
  done
else
  echo "warning: runuser unavailable; skipped the service-user read check" >&2
fi
if [ "$BIND_HOST" = "0.0.0.0" ]; then
  echo "warning: bind_host is 0.0.0.0; bind a specific address (docs/INTELLIGENCE-DEPLOYMENT.md §9)" >&2
fi

# --- stop a manual listener so the unit can own the port -------------------------------
PIDS="$(ss -ltnpH "sport = :$BIND_PORT" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u || true)"
for pid in $PIDS; do
  if tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q 'intelligence serve'; then
    echo "stopping manual MCP process $pid"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    kill -0 "$pid" 2>/dev/null && kill -TERM "$pid" 2>/dev/null || true
  else
    echo "port $BIND_PORT is held by another process ($pid); refusing to install" >&2
    exit 1
  fi
done

# --- install ---------------------------------------------------------------------------
systemctl stop "$UNIT_NAME" 2>/dev/null || true
install -m 0644 /dev/stdin "$UNIT_PATH" <<< "$(render_unit)"
systemctl daemon-reload
systemctl enable "$UNIT_NAME" >/dev/null
systemctl restart "$UNIT_NAME"

for _ in $(seq 1 40); do
  ss -ltnH "sport = :$BIND_PORT" 2>/dev/null | grep -q . && break
  sleep 0.5
done

if ! systemctl is-active --quiet "$UNIT_NAME"; then
  echo "the unit did not stay active; recent journal:" >&2
  journalctl -u "$UNIT_NAME" -n 40 --no-pager >&2 || true
  exit 1
fi

echo
echo "installed $UNIT_PATH"
echo "  user:    $SERVICE_USER"
echo "  config:  $CONFIG"
echo "  tokens:  $TOKENS"
echo "  database: $DB"
echo "  endpoint: http://$BIND_HOST:$BIND_PORT/mcp  (bearer token required)"
echo
systemctl --no-pager --full status "$UNIT_NAME" | head -8 || true
echo
echo "unauthenticated check (401 means reachable and token-gated):"
curl -s -o /dev/null -w '  HTTP %{http_code}\n' "http://$CHECK_HOST:$BIND_PORT/mcp" || true
echo "logs: journalctl -u $UNIT_NAME -f"
