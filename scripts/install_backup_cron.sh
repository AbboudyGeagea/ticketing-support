#!/bin/bash
# =============================================================================
# install_backup_cron.sh — Register the weekly backup cron job (run once)
#
# Usage:
#   sudo /home/support/ticketing-support/scripts/install_backup_cron.sh
# =============================================================================
set -euo pipefail

SCRIPT="/home/support/ticketing-support/scripts/backup.sh"
LOG="/var/log/ticketing-backup.log"
CRON_ENTRY="0 2 * * 0 ${SCRIPT} >> ${LOG} 2>&1"
MARKER="/etc/cron.d/ticketing-backup"

[[ "$(id -u)" -eq 0 ]] || { echo "Run as root (sudo)."; exit 1; }
[[ -f "${SCRIPT}" ]] || { echo "backup.sh not found at ${SCRIPT}"; exit 1; }

chmod +x "${SCRIPT}"
touch "${LOG}"

if crontab -l 2>/dev/null | grep -qF "${SCRIPT}"; then
    echo "Cron job already registered — nothing to do."
else
    (crontab -l 2>/dev/null; echo "${CRON_ENTRY}") | crontab -
    echo "Cron job registered: every Sunday at 02:00 AM"
    echo "  ${CRON_ENTRY}"
fi

echo ""
echo "To verify:  crontab -l"
echo "To test:    sudo ${SCRIPT}"
echo "Logs:       tail -f ${LOG}"
