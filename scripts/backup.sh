#!/bin/bash
# =============================================================================
# backup.sh — Weekly PostgreSQL backup → OneDrive via rclone
#
# Prerequisites (one-time setup):
#   1. apt install rclone
#   2. rclone config  →  create a remote named "onedrive"
#   3. Run scripts/install_backup_cron.sh  to register the weekly cron job
#
# Manual run:
#   sudo /home/support/ticketing-support/scripts/backup.sh
# =============================================================================
set -euo pipefail

APP_DIR="/home/support/ticketing-support"
BACKUP_DIR="/home/support/backups"
RETENTION_DAYS=30
RCLONE_REMOTE="onedrive:Backups/ticketing"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
FILENAME="ticketing_db_${TIMESTAMP}.sql.gz"
LOG_FILE="/var/log/ticketing-backup.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"; }
die() { log "ERROR: $*"; exit 1; }

log "=== Backup started ==="

# ---------------------------------------------------------------------------
# Load .env and parse DATABASE_URL
# ---------------------------------------------------------------------------
[[ -f "${APP_DIR}/.env" ]] || die ".env not found at ${APP_DIR}/.env"
set -a
# shellcheck disable=SC1091
source "${APP_DIR}/.env"
set +a

read -r DB_USER DB_PASS DB_HOST DB_PORT DB_NAME < <(
    python3 - <<'PYEOF'
import re, os, sys
url = os.environ.get("DATABASE_URL", "")
m = re.match(r"[^:]+://([^:]+):([^@]+)@([^:/]+):?(\d+)?/(\w+)", url)
if m:
    print(m.group(1), m.group(2), m.group(3), m.group(4) or "5432", m.group(5))
else:
    sys.exit(1)
PYEOF
) || die "Could not parse DATABASE_URL from .env"

log "Database: ${DB_NAME} on ${DB_HOST}:${DB_PORT} (user: ${DB_USER})"

# ---------------------------------------------------------------------------
# Dump and compress
# ---------------------------------------------------------------------------
mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

PGPASSWORD="${DB_PASS}" pg_dump \
    -h "${DB_HOST}" \
    -p "${DB_PORT}" \
    -U "${DB_USER}" \
    "${DB_NAME}" | gzip -9 > "${BACKUP_DIR}/${FILENAME}"

[[ -s "${BACKUP_DIR}/${FILENAME}" ]] || die "Backup file is empty — pg_dump may have failed"

SIZE=$(du -sh "${BACKUP_DIR}/${FILENAME}" | cut -f1)
log "Dump created: ${FILENAME} (${SIZE})"

# Checksum
sha256sum "${BACKUP_DIR}/${FILENAME}" > "${BACKUP_DIR}/${FILENAME}.sha256"
log "Checksum saved: ${FILENAME}.sha256"

# ---------------------------------------------------------------------------
# Upload to OneDrive
# ---------------------------------------------------------------------------
rclone copy "${BACKUP_DIR}/${FILENAME}" "${RCLONE_REMOTE}" \
    || die "rclone upload failed — check: rclone ls ${RCLONE_REMOTE}"
rclone copy "${BACKUP_DIR}/${FILENAME}.sha256" "${RCLONE_REMOTE}" || true
log "Uploaded to OneDrive: ${RCLONE_REMOTE}/${FILENAME}"

# ---------------------------------------------------------------------------
# Prune local backups older than retention period
# ---------------------------------------------------------------------------
DELETED=0
while IFS= read -r -d '' f; do
    rm -f "${f}" "${f}.sha256" 2>/dev/null || true
    log "Pruned: $(basename "${f}")"
    (( DELETED++ )) || true
done < <(find "${BACKUP_DIR}" -name "ticketing_db_*.sql.gz" -mtime "+${RETENTION_DAYS}" -print0)
log "Local cleanup done (${DELETED} file(s) older than ${RETENTION_DAYS} days removed)"

TOTAL=$(find "${BACKUP_DIR}" -name "ticketing_db_*.sql.gz" | wc -l)
TOTAL_SIZE=$(du -sh "${BACKUP_DIR}" | cut -f1)
log "Local backups on disk: ${TOTAL} (${TOTAL_SIZE} total)"
log "=== Backup complete ==="

# ---------------------------------------------------------------------------
# Restore instructions (for reference):
#   zcat /home/support/backups/ticketing_db_TIMESTAMP.sql.gz \
#     | psql -h localhost -U ticketing_user -d ticketing_db
# ---------------------------------------------------------------------------
