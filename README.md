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

## Required Environment Variables

`app/core/config.py` requires the following variables at startup.
If any required variable is missing, app boot will fail.

### Core App Variables (Required)

| Variable | Required | Example | Purpose |
|---|---|---|---|
| `FT_MONGO_URI` | Yes | `mongodb://mongodb:27017` | MongoDB connection URI |
| `FT_MONGO_DB_NAME` | Yes | `finance` | MongoDB database name |
| `FT_ENV` | Yes | `production` | Environment mode (`dev/development/prod/production`) |
| `FT_KEYCLOAK_URL` | Yes | `https://sso.example.com` | Keycloak base URL |
| `FT_KEYCLOAK_REALM` | Yes | `fintracker` | Keycloak realm |
| `FT_CLIENT_ID` | Yes | `fintracker-web` | Keycloak client ID |
| `FT_SESSION_SECRET` | Yes | `replace-with-long-random-secret` | Session signing secret |
| `FT_APP_NAME` | Yes | `FinTracker` | FastAPI app title/UI label |
| `FT_APP_VERSION` | Yes | `1.0.0` | App version string |
| `FT_BASE_URL` | Yes | `https://fin.example.com` | Public app URL used for OAuth redirects |

### App Logging Variables (Optional)

| Variable | Default | Purpose |
|---|---|---|
| `FT_LOG_LEVEL` | `INFO` | Logging level |
| `FT_DEBUG_LOG` | `false` | Enables debug log behavior |
| `FT_LOG_DIR` | `logs` | Log directory |
| `FT_LOG_FILE` | `logs/app.log` | Log file path |

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
# Logging (optional)
# -------------------------------
FT_LOG_LEVEL=INFO
FT_DEBUG_LOG=false
FT_LOG_DIR=logs
FT_LOG_FILE=logs/app.log

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
