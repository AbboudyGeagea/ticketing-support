#!/bin/bash
# =============================================================================
# setup-services.sh — One-time install of systemd services
#
# Installs the web, celery-worker, and celery-beat systemd services.
# Run once after first deployment, then use update.sh for subsequent updates.
#
# Usage:
#   sudo /home/support/ticketing-support/scripts/setup-services.sh
# =============================================================================
set -euo pipefail

APP_DIR="/home/support/ticketing-support"
SCRIPTS_DIR="${APP_DIR}/scripts"
SYSTEMD_DIR="/etc/systemd/system"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "Run as root (sudo)."

log "Installing systemd service files..."

for svc in celery-worker celery-beat; do
    src="${SCRIPTS_DIR}/${svc}.service"
    dst="${SYSTEMD_DIR}/${svc}.service"
    [[ -f "${src}" ]] || die "Missing: ${src}"
    cp "${src}" "${dst}"
    log "  Installed ${dst}"
done

systemctl daemon-reload

log "Enabling and starting services..."
for svc in celery-worker celery-beat; do
    systemctl enable "${svc}"
    systemctl start "${svc}"
    log "  ${svc}: $(systemctl is-active ${svc})"
done

log ""
log "=== Done. Check status with: ==="
log "  sudo systemctl status celery-worker"
log "  sudo systemctl status celery-beat"
log "  sudo journalctl -u celery-worker -n 30 --no-pager"
log "  sudo journalctl -u celery-beat -n 30 --no-pager"
