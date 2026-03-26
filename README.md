# FinTracker

FinTracker is a production-oriented personal finance application built with FastAPI and MongoDB.  
It provides a server-rendered web app (Jinja2) plus JSON APIs for accounts, transactions, categories, recurring entries, and dashboard analytics.

## What This App Does

- User authentication: local username/password and Keycloak OAuth2/OIDC
- Account management: savings, wallet, credit cards, and other account types
- Transaction management: credit, debit, and self-transfer flows
- Recurring workflows: scheduled recurring transaction materialization
- Analytics dashboard: balances, cashflow trends, top spending categories, alerts
- Admin Center: overview, users, support requests, and centralized runtime settings
- Support chat: user-to-admin live support conversations in Admin dashboard
- Telegram integration: user linking, OTP verification, transaction flow, and alerts
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

Admin UI settings use environment variables as startup defaults. Values saved from the Admin UI are stored in MongoDB and override these defaults at runtime.

Only the minimum runtime fields needed for a normal production setup should be treated as mandatory. All integration and optional service fields can be omitted without blocking app startup.

| Key | Possible value/type | Required/Optional | Description |
|---|---|---|---|
| `FT_MONGO_URI` | MongoDB URI string, e.g. `mongodb://mongodb:27017` | Required | MongoDB connection URI used by the app. |
| `FT_MONGO_DB_NAME` | Database name string, e.g. `fintracker` | Required | MongoDB database name. |
| `FT_SESSION_SECRET` | Long random secret string | Required | Session signing/encryption secret. Replace the default before production use. |
| `FT_ENV` | `development`, `dev`, `production`, `prod` | Optional | Runtime mode. Defaults to `development`. |
| `FT_APP_NAME` | String, e.g. `FinTracker` | Optional | Application display name. |
| `FT_APP_VERSION` | Version string, e.g. `1.0.0` | Optional | Version label shown in the UI. |
| `FT_BASE_URL` | URL string, e.g. `https://fin.example.com` | Optional | Public base URL used for links and webhook defaults. |
| `FT_EXTERNAL_PASSWORD_RESET_URL` | URL string | Optional | External password reset link shown to users when configured. |
| `FT_KEYCLOAK_URL` | URL string | Optional | Keycloak base URL. Leave blank if not using Keycloak. |
| `FT_KEYCLOAK_REALM` | String | Optional | Keycloak realm name. |
| `FT_CLIENT_ID` | String | Optional | Keycloak OIDC client ID. |
| `FT_KEYCLOAK_ADMIN_ROLES` | Comma-separated roles | Optional | Roles treated as app admins. |
| `FT_KEYCLOAK_ADMIN_GROUPS` | Comma-separated groups | Optional | Groups treated as app admins. |
| `FT_AUTH_ENABLED` | `true` / `false` | Optional | Enables the authentication integration section defaults. |
| `FT_AUTH_PROVIDER` | `keycloak`, `local`, or custom string | Optional | Default auth provider shown in admin settings. |
| `FT_AUTH_ALLOW_LOCAL_LOGIN` | `true` / `false` | Optional | Controls whether local login is allowed by default. |
| `FT_APP_LOGO_URL` | URL or static path string | Optional | Default logo URL shown in the admin application settings. |
| `FT_SUPPORT_EMAIL` | Email string | Optional | Default support email. |
| `FT_SUPPORT_PHONE` | Phone string | Optional | Default support phone. |
| `FT_MAINTENANCE_MODE` | `true` / `false` | Optional | Default maintenance-mode state. |
| `FT_MAINTENANCE_MESSAGE` | Free text string | Optional | Default maintenance message. |
| `FT_SMTP_ENABLED` | `true` / `false` | Optional | Default SMTP enabled state. |
| `FT_SMTP_HOST` | Hostname string | Optional | SMTP host. |
| `FT_SMTP_PORT` | Integer, e.g. `587` | Optional | SMTP port. |
| `FT_SMTP_USERNAME` | String | Optional | SMTP username/login. |
| `FT_SMTP_PASSWORD` | String | Optional | SMTP password. |
| `FT_SMTP_FROM` | Email string | Optional | Default sender email address. |
| `FT_SMTP_TLS` | `true` / `false` | Optional | Enable TLS for SMTP connections. |
| `FT_TELEGRAM_ENABLED` | `true` / `false` | Optional | Default Telegram integration enabled state. |
| `FT_TELEGRAM_BOT_USERNAME` | Telegram username string | Optional | Default Telegram bot username. |
| `FT_TELEGRAM_BOT_TOKEN` | Bot token string | Optional | Default Telegram bot token. |
| `FT_TELEGRAM_WEBHOOK_URL` | URL string | Optional | Default Telegram webhook URL. |
| `FT_TELEGRAM_WEBHOOK_SECRET` | Secret string | Optional | Default Telegram webhook secret. |
| `FT_TELEGRAM_POLLING_ENABLED` | `true` / `false` | Optional | Enables polling fallback by default. |
| `FT_PUSH_ENABLED` | `true` / `false` | Optional | Default push integration enabled state. |
| `FT_PUSH_VAPID_PUBLIC_KEY` | Key string | Optional | Firebase Web Push certificate public key used for browser token registration. |
| `FT_PUSH_FIREBASE_API_KEY` | String | Optional | Firebase web config API key. |
| `FT_PUSH_FIREBASE_AUTH_DOMAIN` | Domain string | Optional | Firebase auth domain. |
| `FT_PUSH_FIREBASE_PROJECT_ID` | String | Optional | Firebase project ID. |
| `FT_PUSH_FIREBASE_STORAGE_BUCKET` | String | Optional | Firebase storage bucket. |
| `FT_PUSH_FIREBASE_MESSAGING_SENDER_ID` | Numeric/string sender ID | Optional | Firebase messaging sender ID. |
| `FT_PUSH_FIREBASE_APP_ID` | String | Optional | Firebase app ID. |
| `FT_PUSH_FIREBASE_MEASUREMENT_ID` | String | Optional | Firebase measurement ID. |
| `FT_PUSH_FIREBASE_SERVICE_ACCOUNT_JSON` | JSON string | Optional | Firebase service-account JSON for server-side messaging. |
| `FT_DB_ENABLED` | `true` / `false` | Optional | Default database settings panel enabled state. |
| `FT_BACKUP_ENABLED` | `true` / `false` | Optional | Default backup automation enabled state. |
| `FT_BACKUP_PROVIDER` | `filesystem` | Optional | Default backup provider. |
| `FT_BACKUP_SCHEDULE_CRON` | Cron string, e.g. `0 2 * * *` | Optional | Default backup schedule. |
| `FT_BACKUP_RETENTION_DAYS` | Integer/string, e.g. `7` | Optional | Default backup retention days. |
| `FT_BACKUP_DESTINATION` | Filesystem path string | Optional | Default backup destination path. |
| `FT_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | Optional | Base log level. |
| `FT_DEBUG_LOG` | `true` / `false` | Optional | Enables verbose debug logging. |
| `FT_LOG_DIR` | Path string | Optional | Base log directory (default `/fintracker/logs`). |
| `FT_LOG_FILE` | Path string | Optional | Application/system log file path. |
| `FT_AUDIT_LOG_FILE` | Path string | Optional | Audit log file path. |
| `FT_TELEGRAM_LOG_FILE` | Path string | Optional | Telegram webhook/polling log file path. |
| `FT_SCHEDULER_LOG_FILE` | Path string | Optional | Scheduler and job-run log file path. |
| `FT_ERROR_LOG_FILE` | Path string | Optional | Error-only log file path (all components). |
| `FT_LOG_MAX_BYTES` | Integer bytes, e.g. `10485760` | Optional | Max size per log file before rotation. |
| `FT_LOG_BACKUP_COUNT` | Integer, e.g. `10` | Optional | Number of rotated files to retain. |
| `SCHEDULER_RUN_TIME` | Time string like `5:41 AM IST` | Optional | Daily recurring-job runtime. |
| `FT_NOTIFICATION_ALERT_INTERVAL_SECONDS` | Integer seconds, e.g. `300` | Optional | Alert sweep interval for background notifications. |
| `FT_DEFAULT_ADMIN_USERNAME` | String | Optional | Initial admin username on first boot. |
| `FT_DEFAULT_ADMIN_PASSWORD` | String | Optional | Initial admin password on first boot. |
| `FT_DEFAULT_ADMIN_EMAIL` | Email string | Optional | Initial admin email on first boot. |
| `OPENAI_API_KEY` | API key string | Optional | Required only if AI chat features are used. |
| `CURRENT_VERSION` | Version string | Optional | CI/CD-managed currently deployed version. |
| `PREVIOUS_VERSION` | Version string | Optional | CI/CD-managed rollback version. |
| `MONGO_INITDB_DATABASE` | String | Optional | Docker helper variable for Mongo initialization. |
| `ME_CONFIG_MONGODB_SERVER` | Host string | Optional | Docker helper variable for Mongo Express. |
| `ME_CONFIG_MONGODB_PORT` | Port string/integer | Optional | Docker helper variable for Mongo Express. |
| `ME_CONFIG_BASICAUTH_USERNAME` | String | Optional | Mongo Express basic-auth username. |
| `ME_CONFIG_BASICAUTH_PASSWORD` | String | Optional | Mongo Express basic-auth password. |
| `ME_CONFIG_OPTIONS_EDITORTHEME` | Theme string | Optional | Mongo Express UI theme. |

Notes:
- `.env` is for local/runtime secrets and machine-specific values.
- `.env.example` is the Git-safe template to commit to GitLab.
- Admin UI settings are saved in MongoDB (`app_settings` collection). Environment variables only provide startup defaults/fallbacks.
- Production should always override the default `FT_SESSION_SECRET` and use real database values.

## Production `.env` Template

Use [.env.example](./.env.example) as the committed template for GitLab and environment onboarding.

```dotenv
# Copy .env.example to .env and replace example values with real secrets.
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

## Telegram Transaction Flow

Users can add one-time transactions from Telegram using a guided flow that mirrors the UI:

1. Type selection (`Income` / `Expense` / `Transfer`)
2. Category selection (based on selected type)
3. Subcategory selection (based on selected category)
4. Source account selection
5. Target account selection (for transfer only)
6. Mode, amount, description, confirm

It also supports quick natural-language parsing.  
Example: `100 swiggy order from kotak` -> bot infers likely type/category/subcategory/account/mode and asks for confirmation before saving.

### Prerequisites

1. In Admin > Settings > Telegram Integration:
   - Enable Telegram
   - Set `Bot Username`
   - Set `Bot Token`
   - Set `Webhook URL` (`https://<public-domain>/api/telegram/webhook`) for webhook mode
2. User must link Telegram from Profile > Register Telegram.
3. Configure delivery mode:

Webhook mode (public HTTPS):

- Use Admin buttons: `Set Webhook`, `Check Webhook`, `Delete Webhook`
- `Set Webhook` now configures a webhook secret token for request verification.
- Or CLI:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -d "url=https://<YOUR_DOMAIN>/api/telegram/webhook"
```

Polling fallback mode (LAN/dev):

- Enable `Polling Fallback (LAN Dev)` in Telegram Integration and Save.
- Ensure webhook is deleted (use `Delete Webhook`) because Telegram does not allow webhook + polling together.

### Telegram Alerts

When Telegram is enabled and user is linked, selected in-app alerts are mirrored to Telegram:

- Transactions scheduled for today
- Low balance warnings / balance threshold alerts
- Insufficient funds / recurring failures

Delivery is driven by background sweep interval:

- `FT_NOTIFICATION_ALERT_INTERVAL_SECONDS` (default `300`)

### Telegram Commands

- `/start` -> start/help prompt
- `/help` -> available features and usage
- `/addtransaction` or `Add Transaction` -> guided transaction flow
- `/last5` -> last 5 transactions
- `/balance` -> total + per-account balances
- `/summary` -> current month income/expense summary
- `/cancel` -> cancel active Telegram transaction flow

## Admin Settings Overview

Admin > Settings includes runtime-configurable modules:

- Application (name, logo URL/upload, support contacts, debug, maintenance mode/message)
- SMTP (with test mail action)
- Telegram (bot username/token, webhook URL/actions, polling health widget, broadcast)
- Push Notifications
- Authentication integration
- Database settings
- Backup settings

Security and behavior notes:

- Secrets are write-only in UI (SMTP password, Telegram bot token are hidden on read).
- Existing secrets are retained when those fields are left blank on save.
- Maintenance mode enforces read-only behavior for most write operations.

### User Commands

- `/start` or `/help` -> show bot help and quick actions
- `Add Transaction` or `/addtransaction` -> start flow
- `Cancel` or `/cancel` -> cancel in-progress flow


## CI/CD Pipeline (GitHub Actions)

FinTracker now includes a branch-based GitHub Actions pipeline aligned to your requested flow:

- `Enhancements`: active development branch
- `Dev`: protected release branch that triggers production deployment after merge

### CI workflow

Workflow: `/.github/workflows/ci.yml`

Triggers:

- push to `Enhancements`
- pull requests targeting `Dev`

Checks executed:

- install Python dependencies
- run critical lint validation with `ruff`
- run Python compile validation
- run `pytest`

### Manual approval before merge

PR approval is enforced in GitHub Branch Protection, not inside a workflow file. For the `Dev` branch, configure:

- require pull requests before merging
- require at least 1 approval
- require status checks to pass (`FinTracker CI`)
- optionally restrict direct pushes to `Dev`

GitHub will handle reviewer notifications automatically once branch protection and reviewer rules are configured.

### CD workflow

Workflow: `/.github/workflows/cd.yml`

Trigger:

- push to `Dev`
- optional manual run via `workflow_dispatch`

Deployment flow implemented:

1. detect release bump from merged commit messages
2. connect to the production server via SSH
3. fetch and checkout the latest `Dev` ref on the server
4. update `.env` with `CURRENT_VERSION`, `PREVIOUS_VERSION`, and `FT_APP_VERSION`
5. run `docker compose pull`
6. run `docker compose down --remove-orphans`
7. run `docker compose up -d --build --remove-orphans`
8. wait for startup
9. run `/health` retry checks
10. rollback automatically if health checks fail

### Rollback workflow

Workflow: `/.github/workflows/rollback.yml`

Trigger:

- manual `workflow_dispatch`

It uses the last saved deployment state on the server and restores the previous Git ref and version markers.

### Versioning rules

Version bump is computed from commit messages pushed into `Dev`:

- `BREAKING:` -> major bump
- `feat:` -> minor bump
- `fix:` -> patch bump
- anything else -> patch bump

Examples:

- `v1.2.3` + `fix: update alert formatting` -> `v1.2.4`
- `v1.2.3` + `feat: add support request metrics` -> `v1.3.0`
- `v1.2.3` + `BREAKING: change auth model` -> `v2.0.0`

### Required GitHub configuration

Repository secrets:

- `SSH_HOST`
- `SSH_USER`
- `SSH_KEY`

Optional email notification secrets:

- `EMAIL_SMTP_HOST`
- `EMAIL_SMTP_PORT` (optional, defaults to `587`)
- `EMAIL_SMTP_USERNAME`
- `EMAIL_SMTP_PASSWORD`
- `EMAIL_FROM`
- `EMAIL_TO`
- `EMAIL_SMTP_SECURE` (optional, use `true` for SMTPS or `false` for STARTTLS)

If these email secrets are configured, GitHub Actions will send notifications for:

- CI failures on `Enhancements` and PR validation
- successful production deployments to `Dev`
- failed production deployments where rollback was attempted
- manual rollback success or failure

Repository or environment variables:

- `DEPLOY_PATH`

Recommended production server prerequisites:

- repository already cloned at `DEPLOY_PATH`
- Docker Engine and Docker Compose plugin installed
- production `.env` file already present
- deploy user permitted to run `docker compose`

### Scripts used by the pipeline

- [`scripts/deploy.sh`](/home/sanjay/Application/FinTrack/scripts/deploy.sh)
- [`scripts/health_check.sh`](/home/sanjay/Application/FinTrack/scripts/health_check.sh)
- [`scripts/rollback.sh`](/home/sanjay/Application/FinTrack/scripts/rollback.sh)
- [`scripts/version.sh`](/home/sanjay/Application/FinTrack/scripts/version.sh)

These scripts are idempotent, write deployment progress to `deployments.log`, and perform automatic rollback when health checks fail.


### End-to-end validation checklist

Use this sequence to validate the pipeline after configuring GitHub secrets and branch protection:

1. Configure repository secrets:
   - `SSH_HOST`, `SSH_USER`, `SSH_KEY`
   - optional email secrets if you want notifications
2. Configure repository variable:
   - `DEPLOY_PATH`
3. Protect the `Dev` branch in GitHub:
   - require pull request before merge
   - require at least one approval
   - require status check `FinTracker CI`
4. Verify the production server:
   - repo exists at `DEPLOY_PATH`
   - `.env` exists
   - `docker compose` works for the deploy user
   - `http://localhost/health` returns success when the app is healthy
5. Create a small test commit on `Enhancements` using a conventional message:
   - `fix: validate ci pipeline`
6. Push to `Enhancements` and confirm `FinTracker CI` passes.
7. Open a PR from `Enhancements` to `Dev` and confirm approval is required.
8. Approve and merge the PR.
9. Confirm `FinTracker CD` starts automatically on push to `Dev`.
10. On the production server, verify deployment state:
    - `.env` updated with `CURRENT_VERSION` and `PREVIOUS_VERSION`
    - `deployments.log` contains the new deployment entry
    - containers restarted successfully
11. Confirm application health:
    - `curl http://localhost/health`
    - open the app in browser and check login/dashboard manually
12. If email secrets were configured, confirm the success notification arrived.

### Rollback validation

To validate rollback without breaking the live system permanently:

1. Trigger the manual workflow `FinTracker Rollback` from GitHub Actions.
2. Confirm the workflow succeeds.
3. Confirm the server returns to the previously deployed ref/version.
4. Check `deployments.log` for rollback entries.
5. If email secrets were configured, confirm rollback notification arrived.

### Useful server checks

Run these on the production server when troubleshooting:

```bash
cd "$DEPLOY_PATH"
git rev-parse --short HEAD
cat .env | grep -E '^(CURRENT_VERSION|PREVIOUS_VERSION|FT_APP_VERSION)='
docker compose -f docker/compose.yml ps
curl -fsS http://localhost/health
tail -n 50 deployments.log
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

## FCM Push Setup and Test

Push Notifications uses Firebase Cloud Messaging (FCM) only.

### Configure FCM in Admin

1. Open `Admin -> Settings -> Push Notifications`.
2. Set `Enabled = true`.
4. Fill Firebase Web config values:
   - `Firebase API Key`
   - `Firebase Auth Domain`
   - `Firebase Project ID`
   - `Firebase Storage Bucket`
   - `Firebase Messaging Sender ID`
   - `Firebase App ID`
   - `Firebase Measurement ID` (optional)
5. Fill `VAPID Public Key`.
6. Fill `Firebase Service Account JSON` (full service account JSON content).
7. Save settings.

### Test FCM delivery

1. Login in browser as a user and allow notification permission.
2. Open any app page once so token registration runs.
3. Go to `Admin -> Settings -> Push Notifications`.
4. Click `Test Push`.
5. Verify success toast and browser/device notification.

If delivery fails, validate:

- Notification permission is granted
- Runtime has `firebase-admin` installed
- Service account JSON is valid and from same Firebase project
- VAPID public key belongs to the same Firebase project
