#!/bin/bash
set -euo pipefail
echo "Initializing git repository..."
git init
git config user.email "informatics@intermedic.com"
git config user.name "Intermedic Informatics"
git remote add origin https://github.com/intermedic/ticketing-support.git
git add .
git commit -m "Initial commit: Intermedic Support Desk ticketing system

Full-stack Python/Flask ticketing system with:
- Multi-hospital support
- Agent and customer portals
- Office 365 email-to-ticket integration
- Task management with reminders
- ECharts dashboard
- Docker + Nginx + PostgreSQL deployment"

echo ""
echo "Repository initialized. Next steps:"
echo "1. Create the repository at https://github.com/intermedic/ticketing-support"
echo "2. Run: git push -u origin main"
echo "3. Add GitHub Actions secrets (see below)"
echo ""
echo "Required GitHub Secrets:"
echo "  SERVER_HOST = 192.168.70.104"
echo "  SERVER_USER = ubuntu (or your deploy user)"
echo "  SERVER_SSH_KEY = (private key content)"
echo "  SERVER_PORT = 22"
