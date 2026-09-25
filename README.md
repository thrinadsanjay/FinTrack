# FinTracker

FinTracker is a production-oriented personal finance application built with FastAPI and MongoDB.  
It provides a server-rendered web app (Jinja2) plus JSON APIs for accounts, transactions, categories, recurring entries, and dashboard analytics.

## What This App Does

- User authentication: local username/password and Google OAuth2/OIDC
- Account management: savings, wallet, credit cards, and other account types
- Transaction management: credit, debit, and self-transfer flows
- Recurring workflows: scheduled recurring transaction materialization
- Analytics dashboard: balances, cashflow trends, top spending categories, alerts
- Admin Center: overview, users, support requests, and centralized runtime settings
- Support chat: user-to-admin live support conversations in Admin dashboard
- Telegram integration: user linking, OTP verification, transaction flow, and alerts
- Planning and intelligence (Phase 1): financial health, cash-flow forecast, safe to spend, net worth, credit-card command center, financial calendar, insights, import duplicate detection, and goals
- Assistant and automation (Phase 2): global search, security center, financial rules, conversational Telegram queries, optional Ask FinTracker, monthly review, and recommendations
- Audit logging for critical security and business actions

## Phase 1 — Planning and intelligence

Phase 1 adds calculated financial intelligence on top of existing records. It does not invent balances, bills, or transactions. Dimensions without enough data are marked unavailable.

### Features

- Financial Health (0–100) with equal-weighted available dimensions and a score history
- Cash-flow forecast (30/60/90 days) from current cash, recurring rules, card dues, and bank EMIs
- Safe to Spend = cash-like balances minus upcoming obligations and a visible 10% safety buffer
- Net worth = asset accounts minus credit-card outstanding (EMI principal is not added on top of card debt)
- Credit Card command center (aggregate of existing card/EMI data)
- Financial calendar (recurring, card dues, EMIs)
- Smart insights (rule-based, skipped when data is insufficient)
- Inbox duplicate detection with confidence, explanation, Skip / Keep both / Review
- Financial goals (manual; money is never moved automatically)

### Calculations

Pure math lives in `app/helpers/planning_math.py`. Orchestration is `app/services/planning.py`. Goals CRUD is `app/services/goals.py`.

- Cash (safe-to-spend / forecast start) sums `savings`, `current`, `cash`, and `wallet` only. Credit-card available limit is never spendable cash.
- Forecast **scheduled** = next stored occurrence. **Forecasted** = later dates implied by the same recurring rule. Historical estimates are excluded from the primary path.
- Health score averages only dimensions that have data. Bands: GOOD ≥ 80, FAIR ≥ 65, WATCH ≥ 50, otherwise RISK. No dimensions → INSUFFICIENT.
- Dashboard loads one planning overlay (`get_planning_overlay`) in parallel with the existing summary. It does not issue a separate client-side request per widget.

### New API endpoints

All require the existing session cookie (`get_current_user`):

- `GET /api/planning/dashboard`
- `GET /api/planning/health`
- `GET /api/planning/forecast`
- `GET /api/planning/safe-to-spend`
- `GET /api/planning/net-worth`
- `GET /api/planning/credit-cards`
- `GET /api/planning/calendar?year=&month=&day=`
- `GET /api/planning/insights`
- `GET /api/planning/goals`
- `POST /api/planning/goals`
- `PATCH /api/planning/goals/{id}`

### New HTML pages

- `/insights/health`, `/insights/forecast`, `/insights`
- `/planning/safe-to-spend`, `/planning/net-worth`, `/planning/calendar`, `/planning/goals`

Existing routes (`/`, `/accounts`, `/transactions`, `/recurring`, `/transaction-inbox`, `/admin`, `/profile`) are unchanged.

### Database

New collections (created on first write; indexes from `init_indexes()`):

- `financial_goals` — user goals
- `financial_health_snapshots` — daily health score upsert `(user_id, date_key)`
- `net_worth_snapshots` — daily net-worth upsert `(user_id, date_key)`

No migration script is required. Indexes are created at application startup.

### Telegram

Optional Phase 1 commands: `/forecast`, `/safetospend`, `/networth`, `/goals`.

### Testing

```bash
python3 -m unittest tests.test_planning_math tests.test_init_indexes tests.test_planning_overlay -q
python3 -m unittest discover -s tests -q
python3 -m compileall -q app
```

Health, forecast, safe-to-spend, net worth, calendar, insights, duplicates, and goals have unit coverage in `tests/test_planning_math.py`, including empty ledgers, negative balances, transfers (ignored for net worth), and credit-card vs bank EMI double-count guards.

## Phase 2 — Assistant and automation

Phase 2 sits on Phase 1. It does not replace guided Telegram transaction entry, merchant_rules categorization, or the existing chat widget.

### Features

- **Global search** (`Ctrl/Cmd+K`) across transactions, accounts, merchants, recurring, credit-card activity, bills, EMIs, goals, and permission-scoped support records
- **Security Center** (`/security`): password/passkey/Google/Telegram status, active sessions, last login, security audit events. Sign out other sessions. Never displays passwords, tokens, or OAuth secrets
- **Financial rules** (`/settings/automations`): conditions and actions (categorize, notify, Telegram notify, mark for review, insight). Enable/disable, priority, execution history. No automatic money transfers. Loop guards and daily snapshot dedupe
- **Conversational Telegram**: existing commands plus natural-language questions (balance, spending, forecast, safe-to-spend, net worth, cards, goals, bills, health). Linked `telegram_chat_id` only; ambiguous multi-user links are rejected
- **Ask FinTracker** (`/insights/ask`): optional. Uses controlled tools, not raw database access
- **AI explanations** on Insights: explain calculated facts; if the ledger cannot show a cause, say so
- **Monthly financial review** (`/insights/review`): deterministic numbers plus optional narrative
- **Recommendations**: evidence-based, optional, non-prescriptive, not regulated advice

### Which integrations are required

| Feature | Requires |
|---|---|
| Core app, search, security center, rules, monthly numbers, recommendations | MongoDB + session auth only |
| Telegram commands and conversational queries | Telegram bot configured (Admin → Telegram, or `FT_TELEGRAM_*`) |
| Telegram rule notifications | Telegram linked on the user profile **and** bot enabled |
| Ask FinTracker, AI explanations, monthly narrative | `OPENAI_API_KEY` (optional `FT_OPENAI_MODEL`, default `gpt-4o-mini`) |
| Push copies of notifications | FCM / `FT_PUSH_*` when push is enabled |
| Email | SMTP (`FT_SMTP_*`) when enabled |

AI is never mandatory. Missing or invalid API keys leave calculated pages working.

### AI privacy model

The model never receives the full database, passwords, session tokens, OAuth secrets, Telegram bot tokens, or other users’ records. Each tool call is authorized for the signed-in `user_id` in application code. Payloads are sanitized (`app/helpers/ai_privacy.py`) and clipped. The model cannot run Mongo queries.

Documented tools: `get_balance`, `get_transactions`, `get_spending_by_category`, `get_cash_flow`, `get_forecast`, `get_safe_to_spend`, `get_net_worth`, `get_credit_cards`, `get_upcoming_bills`, `get_goals`, `get_financial_health`.

### Telegram

Preserved: `/start` `/help` `/addtransaction` `/last5` `/balance` `/summary` `/cancel` plus Phase 1 `/forecast` `/safetospend` `/networth` `/goals`.

Also: “How much can I spend?”, “How much did I spend on food this month?”, “How are my credit cards?”, “What's my net worth?”, “What's my balance?”.

Quick transaction text such as `100 swiggy order from kotak` still starts the guided confirm flow.

### API endpoints (session cookie)

- `GET /api/search?q=`
- `GET/POST/PATCH/DELETE /api/rules`, `POST /api/rules/{id}/toggle`, `GET /api/rules/runs`
- `POST /api/security/sessions/revoke-others`
- `GET /api/ai/status`, `POST /api/ai/ask`, `POST /api/ai/explain`, `GET /api/ai/review`, `GET /api/ai/recommendations`

Mutating AI/rules/security APIs require `X-CSRF-Token`.

### HTML pages

- `/security`
- `/settings/automations`
- `/insights/ask`
- `/insights/review`

### Database

Indexes created at startup (`init_indexes()`). New collections:

- `auth_sessions` — login session metadata (`sid`, method, last seen, revoked_at). Cookie still holds the signed session
- `financial_rules` — user automations
- `financial_rule_runs` — execution history

`users.session_epoch` is incremented when other sessions are signed out. Legacy cookies without `epoch` remain valid until the first revoke.

No separate migration script.

### Testing

```bash
python3 -m unittest tests.test_search_parse tests.test_rules_math tests.test_telegram_intents tests.test_phase2_helpers tests.test_ai_tools tests.test_planning_math tests.test_planning_overlay -q
python3 -m unittest discover -s tests -q
python3 -m compileall -q app
```

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
- Google OAuth2/OIDC integration

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
│   ├── FinTracker_app.service
│   └── deploy_app.sh
├── Dockerfile
├── requirements.txt
└── .env
```

## Environment Variables

Admin UI settings use environment variables as startup defaults. Values saved from the Admin UI are stored in MongoDB and override these defaults at runtime.

Only the minimum runtime fields needed for a normal production setup should be treated as mandatory. Integration fields are required only when that integration is enabled.

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
| `FT_GOOGLE_CLIENT_ID` | String | Required when Google sign-in is enabled | Google OAuth client ID. |
| `FT_GOOGLE_CLIENT_SECRET` | String | Required when Google sign-in is enabled | Google OAuth client secret for the authorization-code exchange. |
| `FT_GOOGLE_ADMIN_EMAILS` | Comma-separated emails | Optional | Google account emails treated as app admins. |
| `FT_AUTH_ENABLED` | `true` / `false` | Optional | Enables the authentication integration section defaults. |
| `FT_AUTH_PROVIDER` | `google`, `local`, or custom string | Optional | Default auth provider shown in admin settings. |
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
| `FT_BACKUP_SCHEDULE_TIME` | `HH:MM`, e.g. `02:00` | Optional | Default backup schedule time. |
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
| `OPENAI_API_KEY` | API key string | Optional | Required only for Ask FinTracker, AI explanations, and monthly-review narrative. |
| `FT_OPENAI_MODEL` | Model name string | Optional | OpenAI model id. Defaults to `gpt-4o-mini`. |
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

Minimum production values:
- Always set `FT_MONGO_URI`, `FT_MONGO_DB_NAME`, and `FT_SESSION_SECRET`.
- Set `FT_GOOGLE_CLIENT_ID` and `FT_GOOGLE_CLIENT_SECRET` when Google sign-in is enabled.
- Set `FT_DEFAULT_ADMIN_PASSWORD` before first production startup.

## Production `.env` Template

Use [.env.example](./.env.example) as the committed template for GitLab and environment onboarding.

```dotenv
# Copy .env.example to .env and replace example values with real secrets.
```

## Deployment

### Production server

Servers don't use this branch. They clone `main`, which holds only `README.md`, `docker-compose.yml` (pulls `automationbuilder/fintracker` from Docker Hub, plus MongoDB and mongo-express) and `env.example`. Those files are maintained here under [`deploy/`](deploy/) and `env.example`, and are published to `main` automatically. See [`deploy/README.md`](deploy/README.md).

### Option A: Docker Compose (development)

Builds the image locally and bind-mounts `app/` with auto-reload.

From repository root:

```bash
cp env.example .env
# edit .env and replace placeholder secrets and URLs
docker compose -f docker/compose.yml up -d --build
```

Default services started:

- App: `8000`
- MongoDB: `27017`

Optional tools profile:

```bash
docker compose -f docker/compose.yml --profile tools up -d
```

That additionally starts Mongo Express on `8081`.

Persistent data is stored in Docker named volumes:

- `mongodb_data`
- `app_logs`
- `app_backups`

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
- `/forecast` -> 30/60/90 day scheduled cash forecast
- `/safetospend` -> safe-to-spend amount
- `/networth` -> assets, liabilities, net worth
- `/goals` -> active financial goals
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

Full guide: [`docs/CICD.md`](docs/CICD.md) — secrets, variables, server preparation, branch protection, rollback, test procedure.

- Push a `feature/*` (or `fix/*`, `bugfix/*`, `hotfix/*`, `chore/*`) branch → **CI** runs lint, tests and a Docker build, then opens a PR into `Development`.
- A reviewed, approved PR merged into `Development` that changes the image (`app/**`, `Dockerfile`, `.dockerignore`, `requirements.txt`) → **Release FinTracker** bumps the patch version (git tags `vX.Y.Z`), pushes `automationbuilder/fintracker:X.Y.Z` and `:latest`, and deploys over SSH (`docker pull` + `docker compose up -d --no-deps fintracker`), verifying `/health` reports the new version.
- Changes to `deploy/README.md`, `deploy/docker-compose.yml` or `env.example` → **Publish deployment bundle to main** (no image build). README, docs and tests changes trigger neither.
- **Rollback FinTracker** (manual) redeploys any earlier version; failed deploys also restore the previous image automatically.

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
- Configure the Google OAuth redirect URI to `${FT_BASE_URL}/callback`
- Set `FT_GOOGLE_CLIENT_ID` and `FT_GOOGLE_CLIENT_SECRET` from the same Google OAuth client
- Keep `.env` out of version control and manage secrets externally
- Restrict MongoDB and Mongo Express exposure by network/firewall rules
- Enable regular MongoDB backups and restore drills
- Place app behind a reverse proxy (Nginx/Traefik/Caddy) with TLS

## Troubleshooting

- App fails at startup with settings validation:
  missing one or more required `FT_*` env variables
- OAuth login redirect issues:
  mismatch between `FT_BASE_URL`, Google OAuth client settings, and callback URI
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
