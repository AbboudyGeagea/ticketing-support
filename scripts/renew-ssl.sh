#!/bin/bash
# =============================================================================
# renew-ssl.sh — Idempotent SSL renewal for support.intermedic.com
#
# Safe to run repeatedly (via cron, scripts/update.sh, or by hand) — does
# nothing when the cert is already valid. Consolidates the fixes needed to
# get renewal working reliably on this host:
#
#   1. certbot renews this cert via the standalone HTTP-01 challenge, which
#      needs port 80 free. nginx already holds it, so global hooks at
#      /etc/letsencrypt/renewal-hooks/{pre,post}/ stop/start nginx around
#      the challenge. This script (re)installs them if missing, so they
#      survive a fresh server or an accidental deletion.
#   2. nginx reads its cert from /etc/nginx/ssl/{cert,key}.pem — these MUST
#      be symlinks into the Let's Encrypt live directory, not static copies.
#      A successful certbot renewal is invisible to nginx otherwise (this is
#      what caused the cert to renew but the browser to still see the old
#      one). This script repairs the links if they've drifted.
#   3. After renewing, nginx workers take a moment to rotate onto the new
#      cert — this script verifies the live TLS handshake, not just the
#      file on disk, retrying briefly before giving up.
#
# Usage:
#   sudo scripts/renew-ssl.sh
# =============================================================================
set -euo pipefail

DOMAIN="support.intermedic.com"
LE_DIR="/etc/letsencrypt/live/${DOMAIN}"
CERT_PATH="${LE_DIR}/fullchain.pem"
KEY_PATH="${LE_DIR}/privkey.pem"
NGINX_SSL_DIR="/etc/nginx/ssl"
PRE_HOOK="/etc/letsencrypt/renewal-hooks/pre/stop-nginx.sh"
POST_HOOK="/etc/letsencrypt/renewal-hooks/post/start-nginx.sh"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "Run as root (sudo)."

# ---------------------------------------------------------------------------
# Step 1: Ensure certbot's pre/post hooks exist.
# ---------------------------------------------------------------------------
if [[ ! -x "${PRE_HOOK}" ]]; then
    log "Installing missing pre-hook: ${PRE_HOOK}"
    mkdir -p "$(dirname "${PRE_HOOK}")"
    cat > "${PRE_HOOK}" <<'EOF'
#!/bin/bash
systemctl stop nginx
EOF
    chmod +x "${PRE_HOOK}"
fi

if [[ ! -x "${POST_HOOK}" ]]; then
    log "Installing missing post-hook: ${POST_HOOK}"
    mkdir -p "$(dirname "${POST_HOOK}")"
    cat > "${POST_HOOK}" <<'EOF'
#!/bin/bash
systemctl start nginx
EOF
    chmod +x "${POST_HOOK}"
fi

# ---------------------------------------------------------------------------
# Step 2: Bail out early if there's no Let's Encrypt cert yet (self-signed,
# or not issued at all) — nothing here applies.
# ---------------------------------------------------------------------------
if [[ ! -f "${CERT_PATH}" || ! -f "${KEY_PATH}" ]]; then
    log "No Let's Encrypt cert found at ${LE_DIR} (self-signed or not yet issued) — nothing to do."
    exit 0
fi

# ---------------------------------------------------------------------------
# Step 3: Ensure nginx reads the cert via symlink, not a stale static copy.
# ---------------------------------------------------------------------------
mkdir -p "${NGINX_SSL_DIR}"
for pair in "cert.pem:${CERT_PATH}" "key.pem:${KEY_PATH}"; do
    name="${pair%%:*}"
    target="${pair#*:}"
    link="${NGINX_SSL_DIR}/${name}"
    if [[ "$(readlink -f "${link}" 2>/dev/null || true)" != "$(readlink -f "${target}")" ]]; then
        log "Fixing ${link} -> ${target} (was missing, a stale copy, or pointed elsewhere)"
        if [[ -e "${link}" && ! -L "${link}" ]]; then
            mv "${link}" "${link}.bak.$(date +%s)"
        fi
        ln -sf "${target}" "${link}"
    fi
done

# ---------------------------------------------------------------------------
# Step 4: Renew only if actually expired.
# ---------------------------------------------------------------------------
if openssl x509 -checkend 0 -noout -in "${CERT_PATH}" &>/dev/null; then
    log "Certificate valid until $(openssl x509 -enddate -noout -in "${CERT_PATH}" | cut -d= -f2). Nothing to do."
    exit 0
fi

log "Certificate EXPIRED — renewing..."
certbot renew --cert-name "${DOMAIN}" --non-interactive

# ---------------------------------------------------------------------------
# Step 5: Verify nginx is actually serving the new cert — workers take a
# moment to rotate after the post-hook restart, so retry briefly.
# ---------------------------------------------------------------------------
systemctl is-active --quiet nginx || systemctl start nginx

for i in 1 2 3 4 5; do
    if openssl s_client -connect localhost:443 -servername "${DOMAIN}" </dev/null 2>/dev/null \
        | openssl x509 -checkend 0 -noout &>/dev/null; then
        log "nginx is serving a valid certificate. Renewal complete."
        exit 0
    fi
    log "nginx still serving the old cert, waiting for workers to rotate (attempt ${i}/5)..."
    sleep 2
    systemctl reload nginx || true
done

die "nginx still serving an expired certificate after renewal. Check manually: openssl s_client -connect localhost:443 -servername ${DOMAIN}"
