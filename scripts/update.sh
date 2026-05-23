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
# Step 4: Restart web service
# ---------------------------------------------------------------------------
log "--- Step 4: Restarting web service (${WEB_SERVICE}) ---"
systemctl restart "${WEB_SERVICE}"
log "${WEB_SERVICE} restarted."

# ---------------------------------------------------------------------------
# Step 5: Restart background worker services (if they exist)
# ---------------------------------------------------------------------------
log "--- Step 5: Restarting worker services ---"
for svc in ${WORKER_SERVICES}; do
    if systemctl is-enabled --quiet "${svc}" 2>/dev/null; then
        systemctl restart "${svc}"
        log "Restarted: ${svc}"
    else
        log "Skipping ${svc} (not enabled)."
    fi
done

# ---------------------------------------------------------------------------
# Step 6: Health check
# ---------------------------------------------------------------------------
log "--- Step 6: Health check ---"
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
# Step 7: Reload nginx if config changed
# ---------------------------------------------------------------------------
log "--- Step 7: Reloading nginx ---"
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
