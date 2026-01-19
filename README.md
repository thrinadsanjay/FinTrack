💰 Personal Finance Manager

A secure, modular, and production-ready personal finance management system built with FastAPI + MongoDB, supporting local & OAuth (Keycloak) authentication, audit logging, recurring transactions, and a clean service-first architecture.

✨ Features at a Glance

✅ Account management (Savings, Credit Cards, Wallets, Investments)
💸 Transactions (Credit / Debit / Transfer)
🔁 Recurring transactions (Loans, SIPs, Subscriptions)
🔐 Local login + Keycloak OAuth
🧾 Centralized audit logging (security & compliance ready)
🖥 Web UI (Jinja2) + REST APIs
🌍 Timezone-aware dashboards
⚙️ Clean, scalable architecture

🧱 Architecture Overview

This project follows strict separation of concerns.

Request
  ├── routers/        → API endpoints (JSON)
  ├── web/            → UI routes (HTML)
  ├── services/       → Business logic (CORE)
  ├── models/         → DB representations
  ├── schemas/        → API validation (Pydantic)
  ├── core/           → Shared utilities
  └── db/             → Database clients

🔑 Golden Rule

🚫 Routers never talk to the database
🚫 Web never contains business logic
✅ Services do all the work

📂 Folder Responsibilities
🚦 routers/ — API Layer

What it does

Defines REST endpoints

Validates input/output

Enforces authentication

What it never does

❌ No database access

❌ No business logic

Examples:

routers/
├── accounts.py
├── transactions.py
├── auth.py
├── categories.py
├── health.py

🖥 web/ — UI Layer

Purpose

HTML pages using Jinja2

Session-based auth

Calls services directly

Rules

❌ No database access

❌ No validation logic

Examples:

web/
├── home.py
├── accounts.py
├── transactions.py
├── auth.py

🧠 services/ — Business Logic (CORE)

This is the heart of the system ❤️

Responsibilities

Database access

Validations

Balance updates

Audit logging

OAuth verification

Examples:

services/
├── accounts.py
├── transactions.py
├── users.py
├── audit.py
├── keycloak.py
├── dashboard.py

🧾 models/ — Database Models

Internal MongoDB representations.

Rules

Used only by services

Mongo-specific (ObjectId allowed)

❌ No FastAPI imports

Examples:

models/
├── base.py        # PyObjectId
├── user.py
├── account.py

📐 schemas/ — API Schemas

Pydantic models for API input/output only.

Rules

JSON-friendly types only

❌ No ObjectId

❌ No DB logic

Examples:

schemas/
├── user.py
├── account.py
├── transactions.py

🧰 core/ — Shared Utilities

Pure helpers reused across the app.

Examples:

core/
├── guards.py      # edit / restore rules
├── security.py    # password hashing, TLS
├── time.py        # timezone helpers
├── config.py      # env config
├── startup.py     # bootstrap admin & categories
├── session.py     # session middleware
├── http.py        # HTTP clients

🗄 db/

MongoDB connection only.

db/
└── mongo.py

🔐 Authentication
🔑 Local Authentication

Username + password

Argon2 hashing

Forced password reset supported

🌐 OAuth (Keycloak)

ID Token verification

JWKS caching

DEV vs PROD handled centrally

No OAuth logic outside services

🧾 Audit Logging

Every critical action is logged:

✔ Login / Logout
✔ Account create / rename / delete
✔ Transaction create / edit / delete
✔ OAuth events

Audit logs are:

Append-only

Non-blocking (never crash the app)

Stored in audit_logs collection

🔁 Recurring Transactions

Designed for:

Loans

SIPs / Investments

Subscriptions

Features:

Frequency: daily / weekly / monthly / yearly

Interval support

Auto-posting ready

Scheduler-friendly schema

⚙️ Environment Setup
📄 .env Example
ENV=development

MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=finance

<<<<<<< HEAD
FT_SESSION_SECRET=supersecret

FT_KEYCLOAK_URL=https://keycloak.example.com
FT_KEYCLOAK_REALM=myrealm
FT_CLIENT_ID=finance-app

FT_APP_NAME=FinanceApp
FT_APP_VERSION=1.0.0
FT_BASE_URL=http://localhost:8000
=======
SESSION_SECRET=supersecret

KEYCLOAK_URL=https://keycloak.example.com
KEYCLOAK_REALM=myrealm
KEYCLOAK_CLIENT_ID=finance-app

APP_NAME=FinanceApp
APP_VERSION=1.0.0
APP_BASE_URL=http://localhost:8000
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271

▶️ Running the App
pip install -r requirements.txt
uvicorn app.main:app --reload


Health check:

GET /health

🧪 Debugging Guide
Problem	Check
Login issues	services/auth.py, services/keycloak.py
Balance mismatch	services/transactions.py
UI errors	web/*
API errors	routers/*
Permission errors	core/guards.py
Missing audit logs	services/audit.py
🛡 Design Principles

✔ Service-first logic
✔ Stateless business rules
✔ Explicit audit trails
✔ Easy to test & extend
✔ Safe for production

🚀 Future Enhancements

⏱ Background scheduler (APScheduler / Celery)

🧑‍💼 Admin audit dashboard

📊 CSV / Excel exports

💱 Multi-currency support

📉 Budgets & alerts

🏁 Final Note

This codebase is now:

🎯 Clean
🧠 Predictable
🛠 Debuggable
🚀 Production-ready

Refactoring before scaling was the right call 👏