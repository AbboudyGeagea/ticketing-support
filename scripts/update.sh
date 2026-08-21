#!/bin/bash
# =============================================================================
# update.sh — Update Ticketing-Intermedic (no Docker)
#
# Pulls the latest code, installs dependencies, runs migrations,
# and restarts the systemd services.
#
# Usage:
#   sudo /home/support/ticketing-support/scripts/update.sh
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — adjust service names if yours differ
# ---------------------------------------------------------------------------
APP_DIR="/home/support/ticketing-support"
VENV="${APP_DIR}/venv"
# Space-separated list of systemd services to restart (skip silently if not found)
WEB_SERVICE="intermedic-desk"
WORKER_SERVICES="celery-worker celery-beat"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "Run as root (sudo)."

log "=== Starting update of Ticketing-Intermedic ==="

# ---------------------------------------------------------------------------
# Step 1: Pull latest code
# ---------------------------------------------------------------------------
log "--- Step 1: Pulling latest code ---"
cd "${APP_DIR}"
git fetch origin
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git pull origin "${BRANCH}"
log "Updated to: $(git rev-parse --short HEAD)"

# ---------------------------------------------------------------------------
# Step 2: Install / update Python dependencies
# ---------------------------------------------------------------------------
log "--- Step 2: Installing Python dependencies ---"
"${VENV}/bin/pip" install --quiet -r requirements.txt
log "Dependencies up to date."

# ---------------------------------------------------------------------------
# Step 3: Run database migrations
# ---------------------------------------------------------------------------
log "--- Step 3: Running database migrations ---"
cd "${APP_DIR}"
FLASK_APP=wsgi:app "${VENV}/bin/flask" db upgrade
log "Migrations complete."

# ---------------------------------------------------------------------------
# Step 4: Run seed scripts (each runs only once, tracked by marker files)
# ---------------------------------------------------------------------------
log "--- Step 4: Running seed scripts ---"
SEEDS_DONE_DIR="${APP_DIR}/.seeds_done"
mkdir -p "${SEEDS_DONE_DIR}"
for seed in "${APP_DIR}"/scripts/seed_*.py; do
    [[ -f "$seed" ]] || continue
    name="$(basename "$seed")"
    marker="${SEEDS_DONE_DIR}/${name}.done"
    if [[ -f "$marker" ]]; then
        log "Skipping (already ran): ${name}"
        continue
    fi
    log "Running seed: ${name}"
    FLASK_APP=wsgi:app "${VENV}/bin/python" "$seed" \
        && touch "$marker" \
        || log "WARNING: ${name} failed — will retry next run."
done
log "Seed scripts complete."

# ---------------------------------------------------------------------------
# Step 5: Fix upload folder ownership (script runs as root, gunicorn runs as support)
# ---------------------------------------------------------------------------
log "--- Step 5: Fixing uploads folder ownership ---"
mkdir -p "${APP_DIR}/uploads"
chown -R support:support "${APP_DIR}/uploads"
log "Uploads folder ownership set."

# ---------------------------------------------------------------------------
# Step 6: Renew SSL certificate if expired
# All the renewal logic (hook install, nginx symlink repair, expiry check,
# renew, verify) lives in scripts/renew-ssl.sh so update.sh, cron, and a
# manual run all go through the same, self-healing path.
# ---------------------------------------------------------------------------
log "--- Step 6: Checking SSL certificate ---"
if [[ -x "${APP_DIR}/scripts/renew-ssl.sh" ]]; then
    "${APP_DIR}/scripts/renew-ssl.sh" || log "WARNING: renew-ssl.sh failed — check output above."
else
    log "WARNING: scripts/renew-ssl.sh not found or not executable — skipping SSL check."
fi

# ---------------------------------------------------------------------------
# Step 7: Restart web service
# ---------------------------------------------------------------------------
log "--- Step 7: Restarting web service (${WEB_SERVICE}) ---"
systemctl restart "${WEB_SERVICE}"
log "${WEB_SERVICE} restarted."

# ---------------------------------------------------------------------------
# Step 8: Restart background worker services (if they exist)
# ---------------------------------------------------------------------------
log "--- Step 8: Restarting worker services ---"
for svc in ${WORKER_SERVICES}; do
    if systemctl is-enabled --quiet "${svc}" 2>/dev/null; then
        systemctl restart "${svc}"
        log "Restarted: ${svc}"
    else
        log "Skipping ${svc} (not enabled)."
    fi
done

# ---------------------------------------------------------------------------
# Step 9: Health check
# ---------------------------------------------------------------------------
log "--- Step 9: Health check ---"
MAX_WAIT=60
ELAPSED=0
until curl -sf http://127.0.0.1:5000/health &>/dev/null; do
    if [[ "${ELAPSED}" -ge "${MAX_WAIT}" ]]; then
        die "App did not respond after ${MAX_WAIT}s. Check: journalctl -u ${WEB_SERVICE} -n 50"
    fi
    log "Waiting... (${ELAPSED}s/${MAX_WAIT}s)"
    sleep 5
    (( ELAPSED += 5 )) || true
done
log "Health check passed."

# ---------------------------------------------------------------------------
# Step 10: Reload nginx if config changed
# ---------------------------------------------------------------------------
log "--- Step 10: Reloading nginx ---"
NGINX_SOURCE="${APP_DIR}/nginx/sites-available/support.intermedic.com"
NGINX_DEST="/etc/nginx/sites-available/support.intermedic.com"
if [[ -f "${NGINX_SOURCE}" ]]; then
    cp "${NGINX_SOURCE}" "${NGINX_DEST}"
    nginx -t && systemctl reload nginx
    log "Nginx reloaded."
else
    log "No nginx config change."
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
log "=== Update complete: $(git -C "${APP_DIR}" log -1 --oneline) ==="
