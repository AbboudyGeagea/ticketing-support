#!/bin/bash
# =============================================================================
# deploy.sh — Full Ubuntu 22.04 LTS deployment for Ticketing-Intermedic
# Server: 192.168.70.104 (private/internal IP)
# Domain: support.intermedic.com
# Repo:   github.com/intermedic/ticketing-support
#
# Usage (run as root or with sudo):
#   chmod +x deploy.sh
#   sudo ./deploy.sh
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_NAME="ticketing-support"
APP_DIR="/home/support/ticketing-support"
REPO_URL="https://github.com/AbboudyGeagea/ticketing-support.git"
DOMAIN="support.intermedic.com"
NGINX_CONF_NAME="${DOMAIN}"
SUPPORT_EMAIL="informatics@intermedic.com"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: $*" >&2; }
die()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; exit 1; }

require_root() {
    [[ "$(id -u)" -eq 0 ]] || die "This script must be run as root (use sudo)."
}

# ---------------------------------------------------------------------------
# Step 0: Pre-flight checks
# ---------------------------------------------------------------------------
require_root
log "=== Starting deployment of ${APP_NAME} on Ubuntu 22.04 LTS ==="
log "Target directory : ${APP_DIR}"
log "Domain           : ${DOMAIN}"
log "Repo             : ${REPO_URL}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Update system packages
# ---------------------------------------------------------------------------
log "--- Step 1: Updating system packages ---"
apt-get update -y
apt-get upgrade -y
apt-get autoremove -y
apt-get autoclean -y
log "System packages updated."

# ---------------------------------------------------------------------------
# Step 2: Install prerequisites
# ---------------------------------------------------------------------------
log "--- Step 2: Installing prerequisites ---"
apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    openssl \
    ufw \
    cron

log "Prerequisites installed."

# ---------------------------------------------------------------------------
# Step 3: Install Docker Engine + Docker Compose plugin
# ---------------------------------------------------------------------------
log "--- Step 3: Installing Docker Engine ---"

if ! command -v docker &>/dev/null; then
    # Add Docker's official GPG key
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    # Add Docker apt repository
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu \
        $(lsb_release -cs) stable" \
        | tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Enable and start Docker
    systemctl enable docker
    systemctl start docker
    log "Docker installed and started."
else
    log "Docker already installed: $(docker --version)"
fi

# Verify docker compose plugin
docker compose version &>/dev/null || die "docker compose plugin not found after install."
log "Docker Compose: $(docker compose version)"

# ---------------------------------------------------------------------------
# Step 4: Install Nginx (host-level)
# ---------------------------------------------------------------------------
log "--- Step 4: Installing Nginx ---"
apt-get install -y nginx
systemctl enable nginx
systemctl start nginx
log "Nginx installed: $(nginx -v 2>&1)"

# ---------------------------------------------------------------------------
# Step 5: Install Certbot (DNS challenge — required for private/internal IPs)
# ---------------------------------------------------------------------------
log "--- Step 5: Installing Certbot ---"
# NOTE: The server IP 192.168.70.104 is private/internal.
# HTTP challenge (port 80) will NOT work — using DNS challenge instead.
apt-get install -y python3 python3-pip snapd
snap install --classic certbot 2>/dev/null || apt-get install -y certbot python3-certbot-nginx
# Install Cloudflare DNS plugin (used by setup-ssl.sh)
pip3 install certbot-dns-cloudflare 2>/dev/null || true
log "Certbot installed."

# ---------------------------------------------------------------------------
# Step 6: Configure UFW firewall
# ---------------------------------------------------------------------------
log "--- Step 6: Configuring UFW firewall ---"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    comment "SSH"
ufw allow 80/tcp    comment "HTTP (nginx + ACME challenge)"
ufw allow 443/tcp   comment "HTTPS"
# Port 5000 is NOT opened — gunicorn binds to 127.0.0.1:5000 only
ufw --force enable
log "UFW configured:"
ufw status verbose

# ---------------------------------------------------------------------------
# Step 7: Clone or update the repository
# ---------------------------------------------------------------------------
log "--- Step 7: Cloning repository ---"
if [[ -d "${APP_DIR}/.git" ]]; then
    log "Repo already exists at ${APP_DIR}, pulling latest..."
    git -C "${APP_DIR}" pull origin main
else
    git clone "${REPO_URL}" "${APP_DIR}"
    log "Repo cloned to ${APP_DIR}."
fi

# ---------------------------------------------------------------------------
# Step 8: Set up environment file
# ---------------------------------------------------------------------------
log "--- Step 8: Setting up .env file ---"
if [[ ! -f "${APP_DIR}/.env" ]]; then
    cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
    chmod 600 "${APP_DIR}/.env"
    warn "====================================================================="
    warn ".env created from .env.example — YOU MUST EDIT IT BEFORE CONTINUING."
    warn "Run: sudo nano ${APP_DIR}/.env"
    warn "Required values to set:"
    warn "  SECRET_KEY        — long random string (openssl rand -hex 32)"
    warn "  DB_PASSWORD       — strong database password"
    warn "  AZURE_TENANT_ID   — Azure AD tenant ID"
    warn "  AZURE_CLIENT_ID   — Azure AD app client ID"
    warn "  AZURE_CLIENT_SECRET — Azure AD app client secret"
    warn "  MAIL_PASSWORD     — SMTP app password for Office 365"
    warn "====================================================================="
    echo ""
    read -rp "Press ENTER after editing .env to continue deployment, or Ctrl+C to abort..."
else
    log ".env already exists, skipping copy."
fi

# ---------------------------------------------------------------------------
# Step 9: Build and start Docker containers
# ---------------------------------------------------------------------------
log "--- Step 9: Building and starting Docker containers ---"
cd "${APP_DIR}"
docker compose -f docker-compose.prod.yml pull --ignore-buildable
docker compose -f docker-compose.prod.yml build --no-cache web
docker compose -f docker-compose.prod.yml up -d
log "Containers started:"
docker compose -f docker-compose.prod.yml ps

# ---------------------------------------------------------------------------
# Step 10: Set up Nginx site config
# ---------------------------------------------------------------------------
log "--- Step 10: Configuring Nginx site ---"
NGINX_AVAILABLE="/etc/nginx/sites-available/${NGINX_CONF_NAME}"
NGINX_ENABLED="/etc/nginx/sites-enabled/${NGINX_CONF_NAME}"

cp "${APP_DIR}/nginx/sites-available/${NGINX_CONF_NAME}" "${NGINX_AVAILABLE}"

# Disable the default nginx site if enabled
if [[ -f /etc/nginx/sites-enabled/default ]]; then
    rm -f /etc/nginx/sites-enabled/default
    log "Removed default nginx site."
fi

# Enable our site
if [[ ! -L "${NGINX_ENABLED}" ]]; then
    ln -s "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
    log "Nginx site enabled."
fi

# Create certbot webroot directory for future HTTP challenges
mkdir -p /var/www/certbot

# Validate nginx config (may fail if SSL certs don't exist yet — that's OK at this stage)
nginx -t 2>/dev/null || warn "Nginx config test failed — likely because SSL certs are not set up yet. This is expected. Run scripts/setup-ssl.sh next."

# ---------------------------------------------------------------------------
# Step 11: SSL Certificate Setup
# ---------------------------------------------------------------------------
log "--- Step 11: SSL Certificate Setup ---"
warn "The server IP (192.168.70.104) is PRIVATE — Let's Encrypt HTTP challenge won't work."
warn "You must use either:"
warn "  Option A: DNS challenge (requires access to your DNS provider/Cloudflare)"
warn "  Option B: Self-signed certificate (works immediately, browser will show warning)"
warn ""
warn "Run the SSL setup script:"
warn "  sudo ${APP_DIR}/scripts/setup-ssl.sh"
echo ""

# ---------------------------------------------------------------------------
# Step 12: Set up cron for certbot renewal
# ---------------------------------------------------------------------------
log "--- Step 12: Setting up certbot auto-renewal cron ---"
CRON_JOB="0 3 * * * certbot renew --quiet --post-hook 'systemctl reload nginx'"
CRON_FILE="/etc/cron.d/certbot-renew"

echo "${CRON_JOB}" > "${CRON_FILE}"
chmod 644 "${CRON_FILE}"
log "Certbot renewal cron installed at ${CRON_FILE}."

# ---------------------------------------------------------------------------
# Step 13: Set up backup cron
# ---------------------------------------------------------------------------
log "--- Step 13: Setting up database backup cron ---"
chmod +x "${APP_DIR}/scripts/backup.sh"
BACKUP_CRON="0 2 * * * ${APP_DIR}/scripts/backup.sh >> /var/log/ticketing-backup.log 2>&1"
BACKUP_CRON_FILE="/etc/cron.d/ticketing-backup"

echo "${BACKUP_CRON}" > "${BACKUP_CRON_FILE}"
chmod 644 "${BACKUP_CRON_FILE}"
log "Backup cron installed at ${BACKUP_CRON_FILE}."

# ---------------------------------------------------------------------------
# Make update script executable
# ---------------------------------------------------------------------------
chmod +x "${APP_DIR}/scripts/update.sh"
chmod +x "${APP_DIR}/scripts/setup-ssl.sh"

# ---------------------------------------------------------------------------
# Final: Post-deployment checklist
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  DEPLOYMENT COMPLETE — Post-Deployment Checklist"
echo "============================================================"
echo ""
echo "  [ ] 1. Edit .env if not done:   sudo nano ${APP_DIR}/.env"
echo "  [ ] 2. Set up SSL certificate:  sudo ${APP_DIR}/scripts/setup-ssl.sh"
echo "  [ ] 3. Reload nginx after SSL:  sudo nginx -t && sudo systemctl reload nginx"
echo "  [ ] 4. Verify app is running:   curl -k https://${DOMAIN}/health"
echo "  [ ] 5. Check container logs:    docker compose -f ${APP_DIR}/docker-compose.prod.yml logs -f"
echo "  [ ] 6. Add DNS A record:        ${DOMAIN} -> 192.168.70.104 (internal DNS)"
echo "  [ ] 7. Test from a client:      https://${DOMAIN}"
echo "  [ ] 8. Create admin user:       docker compose -f ${APP_DIR}/docker-compose.prod.yml exec web flask create-admin"
echo ""
echo "  Backup script:     ${APP_DIR}/scripts/backup.sh (runs daily at 02:00)"
echo "  Update script:     ${APP_DIR}/scripts/update.sh"
echo "  Nginx logs:        /var/log/nginx/${DOMAIN}.access.log"
echo "  Support email:     ${SUPPORT_EMAIL}"
echo ""
echo "============================================================"
