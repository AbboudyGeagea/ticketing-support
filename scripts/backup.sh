#!/bin/bash
# =============================================================================
# backup.sh — Daily PostgreSQL backup for Ticketing-Intermedic
#
# Dumps the PostgreSQL database from the running Docker container,
# compresses it, and keeps the last 30 days of backups.
#
# Schedule via cron (added automatically by deploy.sh):
#   0 2 * * * /home/support/ticketing-support/scripts/backup.sh >> /var/log/ticketing-backup.log 2>&1
#
# Manual run:
#   sudo /home/support/ticketing-support/scripts/backup.sh
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_DIR="/home/support/ticketing-support"
COMPOSE_FILE="${APP_DIR}/docker-compose.prod.yml"
BACKUP_DIR="/var/backups/ticketing"
DB_SERVICE="db"
DB_NAME="ticketing_db"
DB_USER="ticketing_user"
RETENTION_DAYS=30
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
BACKUP_FILE="${BACKUP_DIR}/ticketing_db_${TIMESTAMP}.sql.gz"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
log "=== Ticketing-Intermedic Database Backup ==="
log "Backup destination: ${BACKUP_DIR}"
log "Retention period  : ${RETENTION_DAYS} days"

# Ensure backup directory exists
mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

# Check Docker is running
docker info &>/dev/null || die "Docker is not running. Cannot perform backup."

# Check the db container is up
DB_STATUS="$(docker compose -f "${COMPOSE_FILE}" ps -q "${DB_SERVICE}" 2>/dev/null || true)"
if [[ -z "${DB_STATUS}" ]]; then
    die "Database container '${DB_SERVICE}' is not running. Aborting backup."
fi

# ---------------------------------------------------------------------------
# Perform backup
# ---------------------------------------------------------------------------
log "Starting pg_dump of '${DB_NAME}'..."

docker compose -f "${COMPOSE_FILE}" exec -T "${DB_SERVICE}" \
    pg_dump -U "${DB_USER}" -d "${DB_NAME}" --no-password \
    | gzip -9 > "${BACKUP_FILE}"

# Verify the backup file was created and is non-empty
if [[ ! -s "${BACKUP_FILE}" ]]; then
    die "Backup file is empty or was not created: ${BACKUP_FILE}"
fi

BACKUP_SIZE="$(du -sh "${BACKUP_FILE}" | cut -f1)"
log "Backup created: ${BACKUP_FILE} (${BACKUP_SIZE})"

# Generate SHA-256 checksum
sha256sum "${BACKUP_FILE}" > "${BACKUP_FILE}.sha256"
log "Checksum saved : ${BACKUP_FILE}.sha256"

# ---------------------------------------------------------------------------
# Rotate old backups (keep last RETENTION_DAYS days)
# ---------------------------------------------------------------------------
log "Rotating backups older than ${RETENTION_DAYS} days..."
DELETED_COUNT=0

while IFS= read -r -d '' old_file; do
    rm -f "${old_file}" "${old_file}.sha256" 2>/dev/null || true
    log "Deleted old backup: ${old_file}"
    (( DELETED_COUNT++ )) || true
done < <(find "${BACKUP_DIR}" -name "ticketing_db_*.sql.gz" -mtime "+${RETENTION_DAYS}" -print0)

if [[ "${DELETED_COUNT}" -gt 0 ]]; then
    log "Deleted ${DELETED_COUNT} old backup(s)."
else
    log "No old backups to delete."
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
TOTAL_BACKUPS="$(find "${BACKUP_DIR}" -name "ticketing_db_*.sql.gz" | wc -l)"
TOTAL_SIZE="$(du -sh "${BACKUP_DIR}" | cut -f1)"
log "Total backups on disk: ${TOTAL_BACKUPS} (${TOTAL_SIZE} total)"
log "=== Backup complete ==="

# ---------------------------------------------------------------------------
# Optional: To restore a backup, run:
#   zcat /var/backups/ticketing/ticketing_db_TIMESTAMP.sql.gz \
#     | docker compose -f /home/support/ticketing-support/docker-compose.prod.yml \
#         exec -T db psql -U ticketing_user -d ticketing_db
# ---------------------------------------------------------------------------
