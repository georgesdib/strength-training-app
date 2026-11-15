# PRODUCTION DEPLOYMENT — DERIVED ANALYTICS AND MCP CUTOVER

Status: executed on the home host on 2026-11-15 for Derived Analytics Milestones A-C, the
renumbered migrations, the C-1 units and the MCP service. The MCP unit was installed with the
host-adapted installer (§8) and is enabled.

## 1. Scope and decisions

- Release branch: `development`. llm-integration was merged into it on 2026-11-15 and the feature
  branch was retired; do not change the branch on the host without recording that decision.
- The production database already has migration 0060 (development's plank variants). Analytics are
  0061-0063; do not delete the 0060 row.
- MCP remains read-only. The maintenance worker writes only derived tables and build state.

## 2. Preconditions

- SSH access and sudo for service installation/restart.
- Web checkout: /home/dsh/strength-training-app.
- Verified database backup and a quiet training window.
- Optional intelligence dependencies in the release venv:

    cd /home/dsh/strength-training-app
    .venv/bin/pip install -e ".[intelligence]"

## 3. Backup (required)

    cd /home/dsh/strength-training-app
    mkdir -p backups
    python3 - <<'PY'
    import sqlite3
    src = sqlite3.connect("file:data/coach.db?mode=ro", uri=True)
    dst = sqlite3.connect("backups/coach-before-analytics-20261114.db")
    src.backup(dst)
    dst.close(); src.close()
    PY
    ls -lh backups/coach-before-analytics-20261114.db

Keep it until the build and a few reads are verified.

## 4. Deploy the code

    cd /home/dsh/strength-training-app
    git fetch --prune
    git checkout <release-branch>
    git pull --ff-only
    .venv/bin/python -m pip install -e ".[intelligence]"
    git log --oneline -1

If merging into development, do and push that merge from a development checkout first, then deploy
the resulting commit. Never deploy a dirty tree.

## 5. Apply migrations and restart the web service

    sudo systemctl restart strength-coach-web.service
    systemctl status strength-coach-web.service --no-pager
    journalctl -u strength-coach-web.service -n 50 --no-pager

Migrations run on database open. Verify:

    python3 - <<'PY'
    import sqlite3
    c = sqlite3.connect("file:data/coach.db?mode=ro", uri=True)
    print([r[0] for r in c.execute(
        "SELECT version FROM schema_migration WHERE version >= '0060' ORDER BY version")])
    print([r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND (name LIKE 'analytics%' OR name LIKE 'derived%') ORDER BY name")])
    c.close()
    PY

Expected: 0060, 0061, 0062, 0063 and the analytics/derived tables. If checksum verification fails,
stop and restore the backup; never edit migration history.

## 6. Build derived analytics (first production run)

Run while the web service is idle, ideally stopped:

    cd /home/dsh/strength-training-app
    sudo systemctl stop strength-coach-web.service
    .venv/bin/python -m strength_coach.cli --db data/coach.db analytics build
    sudo systemctl start strength-coach-web.service

Expect minutes on real history; it prints the family state and exits non-zero unless ready. Verify:

    curl -s http://127.0.0.1:8000/api/analytics/status | python3 -m json.tool

The core family must show ready: true, readiness: verified.

## 7. Install the C-1 maintenance worker

    sudo install -m 0644 deploy/strength-analytics-maintenance.service /etc/systemd/system/
    sudo install -m 0644 deploy/strength-analytics-maintenance.timer /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now strength-analytics-maintenance.timer
    systemctl list-timers strength-analytics-maintenance.timer
    sudo systemctl start strength-analytics-maintenance.service
    journalctl -u strength-analytics-maintenance.service -n 50 --no-pager

The web unit already contains the optional ExecStartPost run; if the service account cannot start
system units it is a no-op and the 15-minute timer is authoritative.

## 8. Enable the MCP service

The repository unit targets /opt/strength-training-app and user strength-intel. On this host the
checkout is /home/dsh/strength-training-app; `sudo deploy/install-intelligence-mcp.sh` renders the
unit with the real paths, checks the preconditions, stops a manual listener and installs it. The
manual steps below remain the reference for a dedicated-user deployment.

1. Enable intelligence in the service config (enabled: true); set bind_host/allowed_hosts for the
   trusted network. Loopback-only is the safe default.
2. Create a token once, where the unit expects it:

    sudo -u <service-user> /home/dsh/strength-training-app/.venv/bin/strength-coach       intelligence token create --label "Claude Desktop"       --tokens /etc/strength-coach/intelligence.local.yaml

3. Install and start:

    sudo install -m 0644 deploy/strength-intelligence-mcp.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now strength-intelligence-mcp.service
    systemctl status strength-intelligence-mcp.service --no-pager

4. Smoke-test through the real transport, token only in the environment:

    cd /home/dsh/strength-training-app
    STRENGTH_MCP_TOKEN=... .venv/bin/python tools/intelligence_benchmark.py       --mode http --url http://127.0.0.1:8765/mcp --db data/coach.db --runs 5 --warmup 1

Do not put the token on the command line or in shell history.

## 9. Verification checklist

- web service active; UI, history and progress pages work.
- 0060-0063 recorded; analytics/derived tables exist.
- core family ready: true, readiness: verified.
- C-1 timer active; one manual run succeeded and reports ready.
- MCP tools/list returns 10 tools; slow tools are callable.
- iOS/backend compatibility: bootstrap capabilities include `intelligence_read`; the app hides
  the Weekly review entry on an older server (capability absent). The weekly-review route returns
  200 with the envelope, and a stale app build still works because the field is additive.
- One fast and one slow tool return valid envelopes.
- MCP performs no source writes; worker writes only derived/build tables.
- Post-deployment HTTP benchmark recorded before drawing performance conclusions.

## 10. Rollback

- Disable MCP and C-1:
    sudo systemctl disable --now strength-intelligence-mcp.service strength-analytics-maintenance.timer
- Revert the checkout to the previous commit and restart the web service.
- Migrations are forward-only. If migration fails, stop the web service and restore the step-3
  backup; never delete migration rows or edit migration files.
- Derived tables are disposable and can be rebuilt with analytics build; source data is untouched.
- Partial failure: if the web service will not start after migrations, restore the step-3 backup
  and keep the old checkout; migrations are forward-only, so do not delete rows to "fix" a number.
  If the MCP unit installs but fails its smoke test, disable only that unit and keep the web
  service; intelligence is additive and its failure must not block training.
- If the timer was installed but the first analytics build failed, disable the timer, fix or
  report the build error, and leave consumers on their on-demand fallback.

## 11. Measured expectations and limitations

After the T-3 first pass, real MCP HTTP p95 on a copied production database was: overview 672 ms,
programme 278 ms, readiness 377 ms, session details 5,684 ms; fast tools 45-189 ms. Session details
is the only very_slow tool and is optional follow-up T-3a. These are 2026-11-14 measurements, not
guarantees; re-run the HTTP benchmark after deployment.

C-1 is installed and active: the timer last ran successfully on 2026-11-15 08:15 and the web unit
carries the `ExecStartPost` hook. The MCP service is installed, enabled and active from the same
checkout (all ten capabilities over Streamable HTTP); `deploy/install-intelligence-mcp.sh` renders
the host-adapted unit and is the repeatable path for this host.
