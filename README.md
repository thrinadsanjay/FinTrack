# FinTracker

FinTracker is a production-oriented personal finance application built with FastAPI and MongoDB.  
It provides a server-rendered web app (Jinja2) plus JSON APIs for accounts, transactions, categories, recurring entries, and dashboard analytics.

## What This App Does

- User authentication: local username/password and Keycloak OAuth2/OIDC
- Account management: savings, wallet, credit cards, and other account types
- Transaction management: credit, debit, and self-transfer flows
- Recurring workflows: scheduled recurring transaction materialization
- Analytics dashboard: balances, cashflow trends, top spending categories, alerts
- Audit logging for critical security and business actions

## System Architecture

The project is intentionally layered:

- `app/routers/`: API endpoints (JSON)
- `app/web/`: HTML page controllers
- `app/services/`: business logic and data access
- `app/core/`: shared config, middleware, security, helpers
- `app/db/`: MongoDB connection and index setup
- `app/frontend/`: templates and static assets

Rule of thumb: UI/API layers delegate to `services`; business logic does not live in routes.

## Tech Stack

- Python 3.10
- FastAPI + Uvicorn
- MongoDB (Motor async driver)
- Jinja2 templates
- APScheduler (recurring jobs)
- Keycloak OIDC integration

## Repository Layout

```text
FinTrack/
├── app/
│   ├── core/
│   ├── db/
│   ├── frontend/
│   ├── routers/
│   ├── schedulers/
│   ├── services/
│   └── web/
├── docker/
│   └── compose.yml
├── systemctl/
│   ├── FinTracker.service
│   ├── FinTracker_backend.service
│   └── deploy_app.sh
├── Dockerfile
├── requirements.txt
└── .env
```

## Environment Variables

`app/core/config.py` enforces required runtime variables at startup. Missing required values will fail app boot.

### Core App Variables

| Variable | Required | Default | Example | Purpose |
|---|---|---|---|---|
| `FT_MONGO_URI` | Yes | - | `mongodb://mongodb:27017` | MongoDB connection URI |
| `FT_MONGO_DB_NAME` | Yes | - | `finance` | MongoDB database name |
| `FT_ENV` | Yes | - | `production` | Runtime mode: `dev/development/prod/production` |
| `FT_KEYCLOAK_URL` | Yes | - | `https://sso.example.com` | Keycloak base URL |
| `FT_KEYCLOAK_REALM` | Yes | - | `fintracker` | Keycloak realm |
| `FT_CLIENT_ID` | Yes | - | `fintracker-web` | Keycloak OIDC client ID |
| `FT_SESSION_SECRET` | Yes | - | `replace-with-long-random-secret` | Session signing/encryption secret |
| `FT_APP_NAME` | Yes | - | `FinTracker` | Application display name |
| `FT_APP_VERSION` | Yes | - | `1.0.0` | Application version label |
| `FT_BASE_URL` | Yes | - | `https://fin.example.com` | Public base URL (OAuth callback construction) |

### Auth and Access Variables

| Variable | Required | Default | Example | Purpose |
|---|---|---|---|---|
| `FT_KEYCLOAK_ADMIN_ROLES` | No | `fintracker-admin,admin` | `fintracker-admin,platform-admin` | Comma-separated admin roles treated as app admins |
| `FT_KEYCLOAK_ADMIN_GROUPS` | No | `/fintracker-admin,fintracker-admin` | `/org/admins` | Comma-separated Keycloak groups treated as app admins |
| `FT_EXTERNAL_PASSWORD_RESET_URL` | No | `None` | `https://myaccount.google.com/security` | Optional external password reset URL for local users |

### Support and SMTP Variables

| Variable | Required | Default | Example | Purpose |
|---|---|---|---|---|
| `FT_SUPPORT_EMAIL` | No | `support@fintracker.local` | `support@example.com` | Default support email shown in Help/Support |
| `FT_SUPPORT_PHONE` | No | `+1-555-0100` | `+1-800-123-4567` | Default support phone shown in Help/Support |
| `FT_SMTP_HOST` | No | `None` | `smtp.sendgrid.net` | SMTP host |
| `FT_SMTP_PORT` | No | `None` | `587` | SMTP port |
| `FT_SMTP_USERNAME` | No | `None` | `apikey` | SMTP username/login |
| `FT_SMTP_FROM` | No | `None` | `no-reply@example.com` | Sender email address |
| `FT_SMTP_TLS` | No | `true` | `true` | Enable TLS for SMTP connections |

### Logging, Scheduler, Bootstrap, AI

| Variable | Required | Default | Example | Purpose |
|---|---|---|---|---|
| `FT_LOG_LEVEL` | No | `INFO` | `DEBUG` | Base log level |
| `FT_DEBUG_LOG` | No | `false` | `true` | Forces debug logging when enabled |
| `FT_LOG_DIR` | No | `logs` | `/var/log/fintracker` | Log directory |
| `FT_LOG_FILE` | No | `logs/app.log` | `/var/log/fintracker/app.log` | Log file path |
| `SCHEDULER_RUN_TIME` | No | `5:41 AM IST` | `11:00 PM UTC` | Daily recurring-job runtime (parsed by scheduler helper) |
| `FT_DEFAULT_ADMIN_USERNAME` | No | `admin` | `admin` | Initial admin username on first boot |
| `FT_DEFAULT_ADMIN_PASSWORD` | No | `admin123` | `ChangeMeNow!` | Initial admin password on first boot |
| `FT_DEFAULT_ADMIN_EMAIL` | No | `admin@example.com` | `admin@example.com` | Initial admin email on first boot |
| `OPENAI_API_KEY` | No | `None` | `sk-...` | Required only if `/api/aichat` endpoint is used |

Notes:
- Admin UI Settings are saved in MongoDB (`app_settings` collection). Env vars above provide startup defaults/fallbacks.
- If you disable local admin bootstrap, ensure Keycloak admin role/group mapping is configured correctly.

### Docker Compose Companion Variables

These are not required by FastAPI itself, but are used by services in `docker/compose.yml`.

| Variable | Used By | Example | Purpose |
|---|---|---|---|
| `MONGO_INITDB_DATABASE` | `mongodb` | `finance` | Initial DB for Mongo container |
| `ME_CONFIG_MONGODB_SERVER` | `mongo-express` | `mongodb` | Mongo host for Mongo Express |
| `ME_CONFIG_MONGODB_PORT` | `mongo-express` | `27017` | Mongo port for Mongo Express |
| `ME_CONFIG_BASICAUTH_USERNAME` | `mongo-express` | `admin` | Mongo Express UI basic-auth username |
| `ME_CONFIG_BASICAUTH_PASSWORD` | `mongo-express` | `change-me` | Mongo Express UI basic-auth password |
| `ME_CONFIG_OPTIONS_EDITORTHEME` | `mongo-express` | `ambiance` | UI editor theme |

## Production `.env` Template

```dotenv
# -------------------------------
# Core App (required)
# -------------------------------
FT_MONGO_URI=mongodb://mongodb:27017
FT_MONGO_DB_NAME=finance
FT_ENV=production

FT_KEYCLOAK_URL=https://sso.example.com
FT_KEYCLOAK_REALM=fintracker
FT_CLIENT_ID=fintracker-web

FT_SESSION_SECRET=replace-with-a-long-random-secret
FT_APP_NAME=FinTracker
FT_APP_VERSION=1.0.0
FT_BASE_URL=https://fin.example.com

# -------------------------------
# Auth mapping (optional)
# -------------------------------
FT_KEYCLOAK_ADMIN_ROLES=fintracker-admin,admin
FT_KEYCLOAK_ADMIN_GROUPS=/fintracker-admin,fintracker-admin
FT_EXTERNAL_PASSWORD_RESET_URL=

# -------------------------------
# Support + SMTP (optional)
# -------------------------------
FT_SUPPORT_EMAIL=support@example.com
FT_SUPPORT_PHONE=+1-800-123-4567
FT_SMTP_HOST=
FT_SMTP_PORT=
FT_SMTP_USERNAME=
FT_SMTP_FROM=
FT_SMTP_TLS=true

# -------------------------------
# Logging + jobs (optional)
# -------------------------------
FT_LOG_LEVEL=INFO
FT_DEBUG_LOG=false
FT_LOG_DIR=logs
FT_LOG_FILE=logs/app.log
SCHEDULER_RUN_TIME=5:41 AM IST

# -------------------------------
# Bootstrap admin (optional)
# -------------------------------
FT_DEFAULT_ADMIN_USERNAME=admin
FT_DEFAULT_ADMIN_PASSWORD=admin123
FT_DEFAULT_ADMIN_EMAIL=admin@example.com

# -------------------------------
# AI chat (optional)
# -------------------------------
OPENAI_API_KEY=

# -------------------------------
# Docker helper services
# -------------------------------
MONGO_INITDB_DATABASE=finance
ME_CONFIG_MONGODB_SERVER=mongodb
ME_CONFIG_MONGODB_PORT=27017
ME_CONFIG_BASICAUTH_USERNAME=admin
ME_CONFIG_BASICAUTH_PASSWORD=change-me
ME_CONFIG_OPTIONS_EDITORTHEME=ambiance
```

## Deployment

### Option A: Docker Compose (Recommended)

From repository root:

```bash
docker compose -f docker/compose.yml up -d --build
```

Exposed ports:

- App: `8000`
- MongoDB: `27017`
- Mongo Express: `8081`

Stop stack:

```bash
docker compose -f docker/compose.yml down
```

### Option B: Native Uvicorn

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## CI/CD Pipeline (GitHub Actions)

This repository now includes: `.github/workflows/cicd.yml`

Flow implemented:

1. Push to `dev` or `dev/*` (or run manually via `workflow_dispatch` on a dev branch)
2. Auto-create/reuse a Pull Request from source branch to `main`
3. Compute next Test version using `FT_APP_VERSION` major/minor + existing `test-v*` tags
4. Wait for manual approval on `test` environment
5. Deploy source commit to Test over SSH and run health check (`curl` with retries)
6. Wait for manual approval on `production` environment
7. Merge the PR into `main`
8. Deploy merged `main` commit to Production

Behavior implemented:

- If `requirements.txt` changed, app container is rebuilt before restart
- If `requirements.txt` did not change, app container is only force-recreated
- `FT_APP_VERSION` is updated on remote `.env` during deployment
- Git tags are created automatically:
  - `test-v<version>` after successful Test deploy
  - `prod-v<version>` after successful Production deploy (tagged on merged `main` commit)

### GitHub Environment Setup (Required)

Create two GitHub Environments:

- `test`
- `production`

Add **required reviewers** for each environment to enforce approval gates.
GitHub sends approval request emails to those reviewers automatically.

For each environment, define:

Environment variables (`Variables`):

- `DEPLOY_HOST` (example: `test.example.com`)
- `DEPLOY_USER` (example: `deploy`)
- `DEPLOY_PORT` (default: `22`)
- `DEPLOY_PATH` (example: `/home/sanjay/Application/FinTrack`)
- `COMPOSE_FILE` (default: `docker/compose.yml`)
- `APP_SERVICE` (default: `backend`)
- `ENV_FILE` (default: `.env`)
- `CONTAINER_CLI` (example: `docker` or `podman`)
- `HEALTH_URL` (example: `http://localhost/health` or public HTTPS health endpoint)

Environment secrets (`Secrets`):

- `DEPLOY_SSH_KEY` (private key used by GitHub Actions for SSH deploy)

### Manual Trigger

Use workflow dispatch if you need:

- `deploy_ref`: deploy a specific commit/tag
- `force_rebuild`: rebuild app image even when `requirements.txt` is unchanged

## First Boot Behavior

On startup the app:

- Initializes MongoDB indexes
- Ensures default categories exist
- Ensures a default local admin user exists
- Starts the recurring scheduler (daily cron in UTC)

Default bootstrap admin credentials in source are:

- Username: `admin`
- Password: `admin123`

Change these immediately in production.

## Health and Operations

- Health endpoint: `GET /health`
- FastAPI docs: `/docs` (if enabled in your runtime settings)
- Scheduler runs recurring transaction job daily
- Service units are available in `systemctl/` for user-level systemd deployments

## Production Readiness Checklist

- Use a strong `FT_SESSION_SECRET` (at least 32 random bytes equivalent)
- Set `FT_ENV=production`
- Use HTTPS and set `FT_BASE_URL` to your public HTTPS URL
- Configure Keycloak client redirect URI to `${FT_BASE_URL}/callback`
- Keep `.env` out of version control and manage secrets externally
- Restrict MongoDB and Mongo Express exposure by network/firewall rules
- Enable regular MongoDB backups and restore drills
- Place app behind a reverse proxy (Nginx/Traefik/Caddy) with TLS

## Troubleshooting

- App fails at startup with settings validation:
  missing one or more required `FT_*` env variables
- OAuth login redirect issues:
  mismatch between `FT_BASE_URL`, Keycloak client settings, and callback URI
- Session/logout issues in production:
  verify consistent external URL, HTTPS termination, and secret stability
- Cannot connect to MongoDB:
  check `FT_MONGO_URI`, network reachability, and container/service status
