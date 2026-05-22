# /etc/nginx/sites-available/support.intermedic.com
# Ubuntu host-level nginx config for Ticketing-Intermedic
#
# Enable with:
#   sudo ln -s /etc/nginx/sites-available/support.intermedic.com \
#              /etc/nginx/sites-enabled/support.intermedic.com
#   sudo nginx -t && sudo systemctl reload nginx

# Upstream definition for gunicorn running in Docker
upstream ticketing_app {
    server 127.0.0.1:5000 fail_timeout=0;
    keepalive 32;
}

# HTTP — redirect all traffic to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name support.intermedic.com;

    # Allow Let's Encrypt HTTP challenge (only needed if using HTTP challenge)
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS — main application
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name support.intermedic.com;

    # SSL certificate paths
    # Option A: Let's Encrypt (set up via scripts/setup-ssl.sh)
    #   ssl_certificate     /etc/letsencrypt/live/support.intermedic.com/fullchain.pem;
    #   ssl_certificate_key /etc/letsencrypt/live/support.intermedic.com/privkey.pem;
    #
    # Option B: Self-signed (set up via scripts/setup-ssl.sh — used for internal/private networks)
    ssl_certificate     /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;

    # Modern SSL configuration (Mozilla Intermediate compatibility)
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # OCSP stapling (only effective with a real CA cert; skip for self-signed)
    # ssl_stapling on;
    # ssl_stapling_verify on;
    # resolver 8.8.8.8 8.8.4.4 valid=300s;
    # resolver_timeout 5s;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; img-src 'self' data:; font-src 'self' data:; connect-src 'self';" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;

    server_tokens off;
    client_max_body_size 10m;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_buffers 16 8k;
    gzip_http_version 1.1;
    gzip_min_length 256;
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/json
        application/javascript
        application/x-javascript
        application/xml
        application/xml+rss
        application/xhtml+xml
        application/vnd.ms-fontobject
        application/x-font-ttf
        font/opentype
        image/svg+xml
        image/x-icon;

    # Logging
    access_log /var/log/nginx/support.intermedic.com.access.log combined;
    error_log  /var/log/nginx/support.intermedic.com.error.log warn;

    # Main application proxy
    location / {
        proxy_pass         http://ticketing_app;
        proxy_http_version 1.1;
        proxy_set_header   Connection "";
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   X-Forwarded-Host $host;
        proxy_read_timeout 120s;
        proxy_connect_timeout 10s;
        proxy_send_timeout 120s;
        proxy_buffering    on;
        proxy_buffer_size  8k;
        proxy_buffers      8 8k;
        proxy_busy_buffers_size 16k;
    }

    # Static files — served via proxy but with aggressive caching
    location /static/ {
        proxy_pass         http://ticketing_app;
        proxy_set_header   Host $host;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        expires            7d;
        add_header         Cache-Control "public, max-age=604800, immutable";
        add_header         Vary "Accept-Encoding";
    }

    # Health check endpoint — no auth, no log noise
    location /health {
        proxy_pass         http://ticketing_app;
        proxy_set_header   Host $host;
        access_log         off;
    }

    # Deny access to hidden files (e.g. .env, .git)
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }
}
