# FinTracker — deployment

This branch holds only what a server needs to run FinTracker:

| File | Purpose |
|---|---|
| `docker-compose.yml` | MongoDB, mongo-express and FinTracker. The app image is pulled from Docker Hub (`automationbuilder/fintracker`); nothing is built here. |
| `docker-compose.nginx.yml` | Opt-in overlay: TLS-terminating nginx in front of fintracker/mongo-express. Inert unless `FT_NGINX_ENABLED=true` in `.env` -- see `docs/CICD.md` "Reverse proxy (nginx)". |
| `nginx/templates/default.conf.template` | nginx config template for the overlay above (rendered by nginx's own entrypoint at container start). |
| `env.example` | Template for `.env` (secrets and settings). |
| `README.md` | This guide. |

Application code lives on the `Development` branch. This branch is generated from it automatically. Don't edit it here: change `deploy/` or `env.example` on `Development` instead.

**The clone and `.env` on the server are now managed automatically** by `.github/workflows/publish-main.yml`
(job `sync-server`): every time this bundle changes, it renders `.env` from GitHub Secrets/Variables (see
`docs/CICD.md`) and clones/pulls this branch on the server, then runs `compose up -d` for the full stack —
detecting Docker or rootless Podman automatically. The steps below are for a manual first-time server
setup, a manual re-run, or troubleshooting; they are no longer required for normal operation.

## First-time setup (manual / reference)

`docker compose` is shown below; on a server running rootless Podman instead, substitute
`podman compose` (or the standalone `podman-compose`) throughout.

```sh
git clone --depth 1 --branch main --single-branch https://github.com/thrinadsanjay/FinTrack.git /opt/fintracker
cd /opt/fintracker
cp env.example .env
chmod 600 .env
# Edit .env: at least FT_SESSION_SECRET, FT_BASE_URL, FT_DEFAULT_ADMIN_PASSWORD,
# ME_CONFIG_BASICAUTH_PASSWORD, and FT_CERTS_DIR if you use TLS certificates.
#
# FT_CERTS_DIR (default /etc/fintracker/certs) must exist before the first `up`, even
# without TLS -- Docker auto-creates a missing bind-mount directory, rootless Podman
# does not (fails with "statfs ...: no such file or directory").
sudo mkdir -p "$(grep -m1 '^FT_CERTS_DIR=' .env | cut -d= -f2- || echo /etc/fintracker/certs)"
sudo chown "$(id -un):" "$(grep -m1 '^FT_CERTS_DIR=' .env | cut -d= -f2- || echo /etc/fintracker/certs)"
docker compose pull
docker compose up -d
docker compose ps
```

FinTracker listens on port `FT_PUBLIC_PORT` (default 8008). MongoDB (27017) and mongo-express (8081) are bound to `127.0.0.1` by default. Use an SSH tunnel to reach them, or set `FT_MONGO_BIND` / `FT_MONGO_EXPRESS_BIND` in `.env`.

> **Already have data on this server?** Run `docker volume ls` before the first start. The MongoDB volume is named `fin_tracker_mongodb_data` by default, which is the name the development stack creates. If your existing volume has a different name, set `FT_MONGO_VOLUME` in `.env`. Otherwise MongoDB starts empty (your old data is still in the old volume, untouched).

## Update to the newest release

```sh
cd /opt/fintracker
git pull                          # new compose file / env.example, if any
docker compose pull fintracker    # fetch the new `latest` image
docker compose up -d              # recreate only what changed
```

`docker compose up -d` alone does **not** download a newer `latest`. If the image tag already exists locally, Docker keeps using it, so always run `docker compose pull fintracker` first. Only the FinTracker service is pulled, which keeps MongoDB on the version it already runs.

After `git pull`, compare `env.example` with your `.env` (`diff <(grep -o '^[A-Z_]*=' env.example) <(grep -o '^[A-Z_]*=' .env)`) and add any new settings.

Check the running version:

```sh
curl -s http://127.0.0.1:${FT_PUBLIC_PORT:-8008}/health
```

## Pin or roll back a version

Every release is also published as an immutable tag (`automationbuilder/fintracker:1.0.7`). To run a specific one, set it in `.env`, then pull and restart:

```sh
echo 'FINTRACKER_VERSION=1.0.6' >> .env
docker compose pull fintracker && docker compose up -d
```

Remove the line to go back to `latest`. A rollback from GitHub Actions (**Rollback FinTracker**) also moves Docker Hub `latest` back by default, so the next `pull` does not bring the bad version back.

## Safe operations

* `docker compose restart fintracker`: restart the app only.
* `docker compose logs -f fintracker`: follow the logs.
* `docker compose down`: stop everything. **Never add `-v`**, which deletes the database volume.
* Before a MongoDB upgrade, take a backup (Admin → Backups, or `mongodump`) and pin `FT_MONGO_IMAGE_TAG`.
