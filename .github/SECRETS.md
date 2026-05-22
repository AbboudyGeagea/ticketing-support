# GitHub Secrets & Environment Variables

## Required GitHub Actions Secrets
Set these at: https://github.com/IntermedicHCIS/ticketing-support/settings/secrets/actions

| Secret | Description | Example |
|--------|-------------|---------|
| SERVER_HOST | Ubuntu server IP | 192.168.70.104 |
| SERVER_USER | SSH username | ubuntu |
| SERVER_SSH_KEY | Private SSH key (full content) | -----BEGIN OPENSSH PRIVATE KEY-----... |
| SERVER_PORT | SSH port | 22 |

## Required .env File Variables (on server at /opt/ticketing-support/.env)

| Variable | Description | Example |
|----------|-------------|---------|
| SECRET_KEY | Flask secret key — generate with `scripts/generate-secret-key.py` | a3f9d2c1e8b74... |
| FLASK_ENV | Application environment | production |
| FLASK_DEBUG | Enable Flask debug mode (must be 0 in production) | 0 |
| DATABASE_URL | PostgreSQL connection string | postgresql://ticketing_user:strongpassword@db:5432/ticketing_db |
| AZURE_TENANT_ID | Azure AD tenant ID for Microsoft Graph API | xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx |
| AZURE_CLIENT_ID | Azure app (client) ID | xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx |
| AZURE_CLIENT_SECRET | Azure app client secret | your-azure-app-client-secret |
| O365_MAILBOX | Office 365 mailbox to poll for incoming tickets | informatics@intermedic.com |
| MAIL_SERVER | SMTP server for outbound email | smtp.office365.com |
| MAIL_PORT | SMTP port | 587 |
| MAIL_USE_TLS | Enable TLS for SMTP | true |
| MAIL_USERNAME | SMTP login username | informatics@intermedic.com |
| MAIL_PASSWORD | SMTP app password | your-smtp-app-password |
| MAIL_DEFAULT_SENDER | From address for outbound mail | informatics@intermedic.com |
| APP_BASE_URL | Public URL of the application | https://support.intermedic.com |
| ITEMS_PER_PAGE | Pagination page size | 25 |
| EMAIL_POLL_INTERVAL_SECONDS | How often to check the mailbox for new tickets | 60 |

## Notes

- Copy `.env.example` to `.env` on the server and fill in all values before first deploy.
- Never commit `.env` to version control — it is listed in `.gitignore`.
- Rotate `SECRET_KEY` and `AZURE_CLIENT_SECRET` periodically; changing `SECRET_KEY` will invalidate all active user sessions.
- The `SERVER_SSH_KEY` secret must be the **private** key of an SSH key pair whose **public** key is listed in `~/.ssh/authorized_keys` on the deploy user's account on `192.168.70.104`.
