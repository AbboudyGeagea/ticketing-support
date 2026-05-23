#!/bin/bash
# =============================================================================
# update.sh — Zero-downtime update for Ticketing-Intermedic
#
# Pulls the latest code from Git, rebuilds the web container, and restarts
# it without downtime (postgres keeps running throughout).
#
# Usage:
#   sudo /home/support/ticketing-support/scripts/update.sh
#
# For a rollback, pin a specific git tag:
#   sudo git -C /home/support/ticketing-support checkout v1.2.3
#   sudo /home/support/ticketing-support/scripts/update.sh
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_DIR="/home/support/ticketing-support"
COMPOSE_FILE="${APP_DIR}/docker-compose.prod.yml"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "This script must be run as root (use sudo)."

log "=== Starting zero-downtime update of Ticketing-Intermedic ==="

# ---------------------------------------------------------------------------
# Step 1: Pull latest code
# ---------------------------------------------------------------------------
log "--- Step 1: Pulling latest code from Git ---"
cd "${APP_DIR}"
git fetch origin
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
log "Current branch: ${CURRENT_BRANCH}"
git pull origin "${CURRENT_BRANCH}"
log "Git pull complete. Current commit: $(git rev-parse --short HEAD)"

# ---------------------------------------------------------------------------
# Step 2: Build new web image
# ---------------------------------------------------------------------------
log "--- Step 2: Building new web image ---"
docker compose -f "${COMPOSE_FILE}" build web
log "Web image built successfully."

# ---------------------------------------------------------------------------
# Step 3: Replace the web container
# ---------------------------------------------------------------------------
log "--- Step 3: Restarting web container ---"
# Stop and remove old container first so the port is freed before the new one starts
docker compose -f "${COMPOSE_FILE}" stop web
docker compose -f "${COMPOSE_FILE}" rm -f web
# flask db upgrade runs automatically inside the container on startup (see docker-compose command)
docker compose -f "${COMPOSE_FILE}" up -d --no-deps web
log "Web container restarted."

# ---------------------------------------------------------------------------
# Step 5: Health check
# ---------------------------------------------------------------------------
log "--- Step 4: Waiting for health check ---"
MAX_WAIT=60
ELAPSED=0
until docker compose -f "${COMPOSE_FILE}" exec -T web curl -sf http://localhost:5000/health &>/dev/null; do
    if [[ "${ELAPSED}" -ge "${MAX_WAIT}" ]]; then
        die "Health check failed after ${MAX_WAIT}s. Check logs: docker compose -f ${COMPOSE_FILE} logs web"
    fi
    log "Waiting for app to become healthy... (${ELAPSED}s/${MAX_WAIT}s)"
    sleep 5
    (( ELAPSED += 5 )) || true
done
log "Health check passed."

# ---------------------------------------------------------------------------
# Step 6: Remove dangling Docker images to free disk space
# ---------------------------------------------------------------------------
log "--- Step 5: Cleaning up dangling Docker images ---"
docker image prune -f
log "Cleanup complete."

# ---------------------------------------------------------------------------
# Step 7: Reload nginx config in case it changed
# ---------------------------------------------------------------------------
log "--- Step 6: Reloading nginx ---"
NGINX_AVAILABLE="/etc/nginx/sites-available/support.intermedic.com"
NGINX_SOURCE="${APP_DIR}/nginx/sites-available/support.intermedic.com"

if [[ -f "${NGINX_SOURCE}" ]]; then
    cp "${NGINX_SOURCE}" "${NGINX_AVAILABLE}"
    nginx -t && systemctl reload nginx
    log "Nginx config updated and reloaded."
else
    log "No nginx config update needed."
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
log "=== Update complete ==="
log "Commit: $(git -C "${APP_DIR}" log -1 --oneline)"
log "Status:"
docker compose -f "${COMPOSE_FILE}" ps
