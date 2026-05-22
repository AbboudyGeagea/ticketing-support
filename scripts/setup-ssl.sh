#!/bin/bash
# =============================================================================
# setup-ssl.sh — SSL certificate setup for support.intermedic.com
#
# IMPORTANT: The server IP 192.168.70.104 is a PRIVATE/INTERNAL IP.
# Let's Encrypt HTTP challenge (port 80) requires a publicly reachable server.
# Since this server is on a private network, use ONE of the options below:
#
#   Option A: Let's Encrypt via DNS challenge
#             Works on private IPs. Requires access to your DNS provider API.
#             Supports Cloudflare and manual DNS.
#
#   Option B: Self-signed certificate
#             Works immediately on any network.
#             Browsers will show a security warning (add exception or deploy
#             your internal CA cert to client machines).
#
# Usage:
#   chmod +x setup-ssl.sh
#   sudo ./setup-ssl.sh
# =============================================================================
set -euo pipefail

DOMAIN="support.intermedic.com"
EMAIL="informatics@intermedic.com"
SSL_DIR="/etc/nginx/ssl"
LETSENCRYPT_LIVE="/etc/letsencrypt/live/${DOMAIN}"

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: $*" >&2; }
die()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "This script must be run as root (use sudo)."

# ---------------------------------------------------------------------------
# Create SSL directory
# ---------------------------------------------------------------------------
mkdir -p "${SSL_DIR}"
chmod 700 "${SSL_DIR}"

# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  SSL Certificate Setup for ${DOMAIN}"
echo "============================================================"
echo ""
echo "  NOTE: Server IP 192.168.70.104 is PRIVATE — HTTP challenge won't work."
echo ""
echo "  Option A: Let's Encrypt via DNS challenge (recommended for production)"
echo "            Requires your DNS to be managed via Cloudflare or manual entry."
echo ""
echo "  Option B: Self-signed certificate (use for internal/testing; browsers warn)"
echo ""
read -rp "Enter option [A/B]: " SSL_OPTION
SSL_OPTION="${SSL_OPTION^^}"  # uppercase

# =============================================================================
# OPTION A: Let's Encrypt — DNS Challenge
# =============================================================================
if [[ "${SSL_OPTION}" == "A" ]]; then
    log "=== Option A: Let's Encrypt DNS Challenge ==="

    # Install certbot if not present
    if ! command -v certbot &>/dev/null; then
        log "Installing certbot..."
        snap install --classic certbot || apt-get install -y certbot
        ln -sf /snap/bin/certbot /usr/bin/certbot 2>/dev/null || true
    fi

    echo ""
    echo "  Choose DNS challenge method:"
    echo "  1) Cloudflare DNS plugin (automated, requires Cloudflare API token)"
    echo "  2) Manual DNS challenge (you add the TXT record yourself)"
    echo ""
    read -rp "Enter method [1/2]: " DNS_METHOD

    # -------------------------------------------------------------------------
    # Option A1: Cloudflare DNS plugin
    # -------------------------------------------------------------------------
    if [[ "${DNS_METHOD}" == "1" ]]; then
        log "--- DNS Challenge via Cloudflare plugin ---"

        # Install certbot-dns-cloudflare
        if ! pip3 show certbot-dns-cloudflare &>/dev/null 2>&1; then
            pip3 install certbot-dns-cloudflare
        fi

        CLOUDFLARE_CREDS="/etc/letsencrypt/cloudflare.ini"

        if [[ ! -f "${CLOUDFLARE_CREDS}" ]]; then
            echo ""
            echo "  You need a Cloudflare API Token with DNS:Edit permission."
            echo "  Create one at: https://dash.cloudflare.com/profile/api-tokens"
            echo ""
            read -rp "  Enter your Cloudflare API Token: " CF_TOKEN
            [[ -n "${CF_TOKEN}" ]] || die "Cloudflare API token cannot be empty."

            cat > "${CLOUDFLARE_CREDS}" <<EOF
# Cloudflare API token for certbot DNS challenge
dns_cloudflare_api_token = ${CF_TOKEN}
EOF
            chmod 600 "${CLOUDFLARE_CREDS}"
            log "Cloudflare credentials saved to ${CLOUDFLARE_CREDS}"
        else
            log "Using existing Cloudflare credentials at ${CLOUDFLARE_CREDS}"
        fi

        log "Requesting certificate via Cloudflare DNS challenge..."
        certbot certonly \
            --dns-cloudflare \
            --dns-cloudflare-credentials "${CLOUDFLARE_CREDS}" \
            --dns-cloudflare-propagation-seconds 60 \
            --email "${EMAIL}" \
            --agree-tos \
            --no-eff-email \
            -d "${DOMAIN}"

        log "Certificate issued via Cloudflare DNS challenge."

    # -------------------------------------------------------------------------
    # Option A2: Manual DNS challenge
    # -------------------------------------------------------------------------
    elif [[ "${DNS_METHOD}" == "2" ]]; then
        log "--- DNS Challenge — Manual (you add the TXT record) ---"
        echo ""
        echo "  You will be asked to add a TXT record to your DNS."
        echo "  Go to your DNS provider's control panel and add the record when prompted."
        echo "  Wait for DNS propagation (1–5 minutes) before pressing ENTER."
        echo ""

        certbot certonly \
            --manual \
            --preferred-challenges dns \
            --email "${EMAIL}" \
            --agree-tos \
            --no-eff-email \
            -d "${DOMAIN}"

        log "Certificate issued via manual DNS challenge."

    else
        die "Invalid DNS method selected. Choose 1 or 2."
    fi

    # -------------------------------------------------------------------------
    # Link Let's Encrypt certs to /etc/nginx/ssl/
    # -------------------------------------------------------------------------
    log "Linking Let's Encrypt certs to ${SSL_DIR}/"
    ln -sf "${LETSENCRYPT_LIVE}/fullchain.pem" "${SSL_DIR}/cert.pem"
    ln -sf "${LETSENCRYPT_LIVE}/privkey.pem"   "${SSL_DIR}/key.pem"
    log "Cert symlinks created:"
    ls -la "${SSL_DIR}/"

    # Update nginx site config to use Let's Encrypt cert paths
    NGINX_CONF="/etc/nginx/sites-available/${DOMAIN}"
    if [[ -f "${NGINX_CONF}" ]]; then
        log "Updating nginx config to use Let's Encrypt cert paths..."
        # Comment out self-signed lines, uncomment Let's Encrypt lines
        sed -i \
            -e "s|#   ssl_certificate     /etc/letsencrypt|    ssl_certificate     /etc/letsencrypt|" \
            -e "s|#   ssl_certificate_key /etc/letsencrypt|    ssl_certificate_key /etc/letsencrypt|" \
            -e "s|^    ssl_certificate     /etc/nginx/ssl|    # ssl_certificate     /etc/nginx/ssl|" \
            -e "s|^    ssl_certificate_key /etc/nginx/ssl|    # ssl_certificate_key /etc/nginx/ssl|" \
            "${NGINX_CONF}" 2>/dev/null || warn "Could not auto-update nginx config. Edit ${NGINX_CONF} manually."
    fi

    # Set up auto-renewal hook to reload nginx
    RENEWAL_HOOK_DIR="/etc/letsencrypt/renewal-hooks/post"
    mkdir -p "${RENEWAL_HOOK_DIR}"
    cat > "${RENEWAL_HOOK_DIR}/reload-nginx.sh" <<'HOOK'
#!/bin/bash
systemctl reload nginx
HOOK
    chmod +x "${RENEWAL_HOOK_DIR}/reload-nginx.sh"
    log "Nginx reload hook installed for auto-renewal."

    # Test renewal
    log "Testing certbot renewal (dry run)..."
    certbot renew --dry-run
    log "Auto-renewal test passed."

# =============================================================================
# OPTION B: Self-signed certificate
# =============================================================================
elif [[ "${SSL_OPTION}" == "B" ]]; then
    log "=== Option B: Self-signed certificate ==="
    echo ""
    echo "  Generating self-signed certificate for ${DOMAIN}"
    echo "  Valid for: 10 years"
    echo "  Location:  ${SSL_DIR}/cert.pem and key.pem"
    echo ""
    echo "  NOTE: Browsers will show a security warning."
    echo "  To suppress the warning, either:"
    echo "    - Deploy this cert (or an internal CA cert) to your clients' trust stores"
    echo "    - Use Option A (DNS challenge) if you have public DNS for this domain"
    echo ""

    openssl req -x509 \
        -nodes \
        -newkey rsa:4096 \
        -days 3650 \
        -keyout "${SSL_DIR}/key.pem" \
        -out    "${SSL_DIR}/cert.pem" \
        -subj   "/C=LB/ST=Beirut/L=Beirut/O=Intermedic/OU=IT/CN=${DOMAIN}" \
        -addext "subjectAltName=DNS:${DOMAIN},IP:192.168.70.104"

    chmod 600 "${SSL_DIR}/key.pem"
    chmod 644 "${SSL_DIR}/cert.pem"

    log "Self-signed certificate generated:"
    openssl x509 -in "${SSL_DIR}/cert.pem" -noout -subject -dates
    log "Cert files:"
    ls -la "${SSL_DIR}/"

else
    die "Invalid option '${SSL_OPTION}'. Choose A or B."
fi

# =============================================================================
# Validate and reload nginx
# =============================================================================
log "Validating nginx configuration..."
nginx -t
log "Reloading nginx..."
systemctl reload nginx
log "Nginx reloaded successfully."

echo ""
echo "============================================================"
echo "  SSL setup complete!"
echo "============================================================"
echo ""
echo "  Certificate : ${SSL_DIR}/cert.pem"
echo "  Private key : ${SSL_DIR}/key.pem"
echo "  Domain      : ${DOMAIN}"
echo ""
echo "  Test with:"
echo "    curl -k https://${DOMAIN}/health"
echo "    openssl s_client -connect ${DOMAIN}:443 -servername ${DOMAIN}"
echo ""
if [[ "${SSL_OPTION}" == "B" ]]; then
    echo "  To add this cert to Ubuntu client trust store:"
    echo "    sudo cp ${SSL_DIR}/cert.pem /usr/local/share/ca-certificates/${DOMAIN}.crt"
    echo "    sudo update-ca-certificates"
    echo ""
fi
echo "============================================================"
