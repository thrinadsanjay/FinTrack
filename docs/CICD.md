# FinTracker CI/CD

GitHub Actions builds, versions and publishes the FinTracker image to Docker Hub, then deploys it to the
server over SSH. Code lives on `Development`; the `main` branch holds only the deployment bundle
(`README.md`, `docker-compose.yml`, `env.example`), which the server clones. The pipeline never edits
files on the server.

```
feature/* push ──► CI (lint · tests · Docker build) ──► auto PR  feature/* → Development
                                                          │  review + approval (never auto-merged)
                                                          ▼
                                       merge into Development
                                                          │
Release FinTracker:  merged-PR guard ─► CI gate ─► next version (git tag +1 patch)
                     ─► build & push  automationbuilder/fintracker:X.Y.Z  +  :latest (same image)
                     ─► tag commit vX.Y.Z ─► SSH deploy ─► verify /health reports X.Y.Z
                     (only when app/, Dockerfile, .dockerignore or requirements.txt changed)

Publish bundle:      deploy/README.md, deploy/docker-compose.yml, env.example changed on Development
                     ─► main = exactly those 3 files (no image is built)
```

### What triggers what

| Change merged into `Development` | Image build + deploy | `main` updated |
|---|---|---|
| `app/**`, `Dockerfile`, `.dockerignore`, `requirements.txt` | yes | no |
| `deploy/README.md`, `deploy/docker-compose.yml`, `env.example` | no | yes |
| `README.md`, `docs/**`, `tests/**`, `.github/**`, anything else | no | no |

Tests still run on every pull request (CI has no path filter), so a PR is never stuck waiting for a
required check. To rebuild without a code change (e.g. base-image security patches), run
**Actions → Release FinTracker → Run workflow** on `Development`.

## Workflows

| File | Trigger | What it does |
|---|---|---|
| `.github/workflows/ci.yml` | push to any branch except `Development`/`main`; PRs into `Development`; called by release | Secret-scan, `ruff`, `pytest`, dependency audit (informational), Docker build (not pushed). On `feature/`, `fix/`, `bugfix/`, `hotfix/`, `chore/` branches, when all pass, calls `pull-request.yml`. Uses **no secrets** (safe for fork PRs). |
| `.github/workflows/pull-request.yml` | called by CI | Opens a PR `branch → Development` (or refreshes the existing one) with commits, changed files, CI and Docker build status. Never approves or merges. |
| `.github/workflows/release.yml` | push to `Development` touching image content (see above); manual | Guard → CI gate → version → build & push → git tag → deploy → summary. Serialized (`concurrency: release-development`), never cancelled. |
| `.github/workflows/publish-main.yml` | push to `Development` touching the deployment bundle; manual | Replaces `main`'s tree with `deploy/README.md` → `README.md`, `deploy/docker-compose.yml` → `docker-compose.yml`, `env.example`. Builds nothing. |
| `.github/workflows/rollback.yml` | manual (**Actions → Rollback FinTracker**) | Redeploys an existing version; optionally moves Docker Hub `latest` to it. Shares the release queue. |
| `.github/actions/ssh-deploy/` | used by release & rollback | Strict host-key SSH; streams `scripts/deploy/remote_deploy.sh` to the server. |

Third-party actions are pinned to commit SHAs (tag noted in a comment).

## Versioning

* **Source of truth: git tags `vMAJOR.MINOR.PATCH`.** This reuses the tags the previous pipeline created
  (`v0.18.0 … v0.22.0`); no second version file is introduced.
* Each release takes the highest tag and increments PATCH (`v0.22.0` → `0.22.1`). With no tags the first
  release is `1.0.0`.
* The tag is created **after** the image is pushed, so a failed build doesn't consume a version.
  Tags pushed with `GITHUB_TOKEN` don't trigger workflows and nothing is committed back to `Development`,
  so there is **no CI loop** and branch protection needs **no bypass**.
* Re-running a release for the same commit reuses its version and image; the pipeline refuses to
  overwrite an existing version tag on Docker Hub.
* The version is baked into the image (`APP_VERSION` build arg → `/app/VERSION` + OCI label). The app
  shows it in the footer/sidebar, OpenAPI and `GET /health` (`{"Error":200,"status":"ok","version":"X.Y.Z"}`).
  A baked version takes precedence over any `FT_APP_VERSION` in the server's `.env`.
* **Starting at 1.0.x instead of continuing 0.22.x:** once, before the first release, run
  `git tag -a v1.0.0 -m "FinTracker 1.0.0" origin/Development && git push origin v1.0.0` — the next
  release becomes `1.0.1`. (A minor/major bump later works the same way: push `v1.1.0`, next is `1.1.1`.)

## GitHub configuration

**Settings → Secrets and variables → Actions**

### Secrets

| Name | Value |
|---|---|
| `DOCKERHUB_USERNAME` | Docker Hub user with push rights to `automationbuilder/fintracker` |
| `DOCKERHUB_TOKEN` | Docker Hub **access token** (Account settings → Personal access tokens), scope *Read & Write*, not the password |
| `SERVER_HOST` | Server hostname or IP (masked in logs) |
| `SERVER_USER` | Deployment user, e.g. `deploy` (not root) |
| `SSH_PRIVATE_KEY` | Private key (ed25519) whose public key is in the deploy user's `authorized_keys` |
| `SSH_KNOWN_HOSTS` | **Additional, required.** The server's host key line(s) for strict host-key verification (see below). Without it the pipeline would have to disable host-key checking, which it refuses to do. |

### Variables

| Name | Value | Notes |
|---|---|---|
| `DOCKER_IMAGE` | `automationbuilder/fintracker` | default if unset |
| `DEPLOY_PATH` | `/opt/fintracker` | **required**: the server's clone of `main` (holds `docker-compose.yml` and `.env`) |
| `SERVER_PORT` | `22` | default if unset |
| `COMPOSE_SERVICE` | `fintracker` | optional; compose service name of the app |
| `COMPOSE_FILE` | *(empty)* | optional; e.g. `docker-compose.prod.yml` if not the default name |

No credentials go into variables.

### Repository settings

* **Settings → Actions → General → Workflow permissions:** "Read repository contents" is fine (jobs
  request what they need), and tick **"Allow GitHub Actions to create and approve pull requests"**
  (needed for the automatic PR; it never approves).
* **Settings → Environments → `Development`** is created on first deploy. Optionally add *required
  reviewers* there for a manual gate before each deploy, and/or move the server secrets into it.

* **Settings → General → Default branch: `Development`.** Manually-run workflows (Rollback, Release,
  Publish) only appear under *Actions → Run workflow* when their file is on the default branch, and `main`
  no longer carries workflows.

### Secret for a protected `main` (optional)

`publish-main.yml` pushes with the built-in `GITHUB_TOKEN`. If you protect `main` so Actions can't push,
create a fine-grained personal access token limited to this repository with **Contents: Read and write**
and store it as the secret `MAIN_BRANCH_TOKEN`; the workflow uses it automatically.

### One-time conversion of `main`

`main` still holds the old code and `.github/workflows/ci-cd.yml`. The built-in token is not allowed to
delete workflow files, so do the first conversion yourself (after `deploy/` has been merged to Development):

```bash
git fetch origin
git switch main && git pull --ff-only
git rm -r -q .
git checkout origin/Development -- deploy/README.md deploy/docker-compose.yml env.example
git mv deploy/README.md README.md && git mv deploy/docker-compose.yml docker-compose.yml
git commit -m "main: deployment bundle only"
git push origin main
```

From then on `publish-main.yml` keeps it in sync. `main`'s history still contains the old code; the server
avoids it by cloning with `--depth 1 --single-branch`. If you also want the history gone, recreate `main`
as an orphan branch with the same three files and `git push --force origin main` (irreversible for the old
`main` commits).

### Branch protection for `Development`

Settings → Branches (or Rules → Rulesets) → target `Development`:

* Require a pull request before merging — **1 approval**; dismiss stale approvals on new commits.
* Require status checks to pass: **`Lint & tests`** and **`Docker build`** (appear after the first CI run).
* Require branches to be up to date before merging (recommended: the release deploys the merged result).
* Block force pushes and deletions; do not allow bypass for admins if you want the rules to apply to you too.
* Direct pushes are also caught by the release **guard**: a commit on `Development` that didn't come from a
  merged PR fails the release and deploys nothing.

Also recommended: protect tags `v*` (Rules → Rulesets → Tag) so only Actions/admins can create them.

## Server preparation (one time)

As root / sudo on the server:

```bash
# 1. Dedicated deploy user that can run Docker (docker group = root-equivalent; keep the key safe)
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy
# login shell must be bash (the pipeline runs `bash -s`)
sudo chsh -s /bin/bash deploy

# 2. Deployment directory owned by deploy
sudo mkdir -p /opt/fintracker
sudo chown deploy:deploy /opt/fintracker
# clone the deployment bundle (see deploy/README.md, published as main's README)
sudo -u deploy git clone --depth 1 --branch main --single-branch https://github.com/thrinadsanjay/FinTrack.git /opt/fintracker
sudo -u deploy cp /opt/fintracker/env.example /opt/fintracker/.env   # or copy your existing .env

# 3. SSH key for GitHub Actions (on your workstation)
ssh-keygen -t ed25519 -C "github-actions-fintracker" -f fintracker_deploy -N ""
# public key -> server
sudo -u deploy mkdir -p ~deploy/.ssh && sudo -u deploy chmod 700 ~deploy/.ssh
cat fintracker_deploy.pub | sudo -u deploy tee -a ~deploy/.ssh/authorized_keys
sudo -u deploy chmod 600 ~deploy/.ssh/authorized_keys
# private key contents -> GitHub secret SSH_PRIVATE_KEY, then delete the local copy

# 4. Host key for SSH_KNOWN_HOSTS — capture it, then verify the fingerprint on the server itself
ssh-keyscan -p 22 -t ed25519 <server-host>            # paste output into SSH_KNOWN_HOSTS
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub       # (on the server) fingerprints must match

# 5. Sanity check as deploy
sudo -u deploy -i bash -c 'docker compose version && cd /opt/fintracker && docker compose config --services'
```

The image is public on Docker Hub only if the repository is public. For a **private** repository, log the
deploy user in once with a *read-only* token: `sudo -u deploy docker login -u <user>` (the pipeline never
sends Docker credentials to the server).

## Server compose file

The server runs `deploy/docker-compose.yml` (published to `main` as `docker-compose.yml`): MongoDB,
mongo-express and `fintracker` with `image: automationbuilder/fintracker:${FINTRACKER_VERSION:-latest}` and
no `build:`. Change it on `Development` under `deploy/`; the server picks it up with `git pull`.

* Remove any `FT_APP_VERSION=` line from the server `.env` (harmless — the baked version wins — but misleading).
* MongoDB and mongo-express bind to `127.0.0.1` by default (`FT_MONGO_BIND`, `FT_MONGO_EXPRESS_BIND`).
* Volume names are fixed (`fin_tracker_mongodb_data`, …) and match the development stack. On a server that
  already has data, check `docker volume ls` first and set `FT_MONGO_VOLUME` if yours differs.
* A release that also needs compose or `.env` changes: the image deploys automatically, but the server only
  gets the new compose file on `git pull`. Pull (and update `.env`) before or right after merging.

### `latest` and pulling

`docker compose up -d` never re-downloads a tag that already exists locally, so a newer `latest` on Docker
Hub is ignored until you pull. The automatic deploy handles this (it pulls the exact version and re-points
the local `latest`). For manual updates always run:

```bash
git pull && docker compose pull fintracker && docker compose up -d
```

The compose file deliberately has no `pull_policy: always`: after a failed deploy the script restores the
previous image by re-pointing the local `latest`, and an always-pull would fetch the broken one again.

What a deploy runs on the server (`scripts/deploy/remote_deploy.sh`):

1. `docker pull automationbuilder/fintracker:X.Y.Z` (exact version, not a moving tag)
2. `docker tag …:X.Y.Z …:latest` (local pointer used by compose)
3. `docker compose up -d --no-deps fintracker` — **only** the app container is recreated; MongoDB and
   other services are neither pulled nor restarted (so a `mongo:latest` image can't upgrade by accident)
4. Verify for up to 180 s: container `running`, running image = new image, Docker health not `unhealthy`,
   and `/health` (queried inside the container) reports `X.Y.Z`
5. On failure: print `docker compose ps` + last 100 log lines, **restore the previous image** so the site
   stays up, and exit non-zero → the GitHub job fails.

## Database safety

* No `docker compose down`, `-v`, volume, or database commands exist anywhere in the pipeline.
* FinTracker (MongoDB) has **no migration framework**. Schema-less collections plus idempotent index setup
  at app start-up (`app/db/init_db.py`, `create_index`) are all that runs. That code also drops two
  *legacy index definitions* when present (`users.email_1` non-sparse, `accounts.name_1`) and recreates
  them correctly — index changes only, no data is removed.
* Take a backup before risky releases (Admin → Backups, or the scheduled backup).

## Rollback

* **Automatic:** a deploy that fails verification restores the previous image on the server and the job fails.
* **Manual:** Actions → **Rollback FinTracker** → Run workflow → `version` = e.g. `1.0.4`,
  `move_latest` = true (so `latest` = what's running and a manual `docker compose pull` won't undo it).
  Versions available: Docker Hub tags or `git tag --list 'v*'`. Version tags are never deleted or overwritten.
* **By hand on the server** (e.g. GitHub unavailable):
  ```bash
  cd /opt/fintracker
  docker pull automationbuilder/fintracker:1.0.4
  docker tag automationbuilder/fintracker:1.0.4 automationbuilder/fintracker:latest
  docker compose up -d --no-deps fintracker
  ```

## Safe test procedure

1. **CI only:** create `feature/ci-smoke`, change a comment, push. Expect `CI` green and a PR to
   `Development` whose body lists the commit and ✅ statuses. Push again → the same PR is updated.
2. **Failure path:** on that branch break a test, push → CI red, **no** PR update. Revert.
3. **Guard:** (if you can) push a commit directly to `Development` → `Release FinTracker` fails at
   *Merged-PR guard*, nothing is built or deployed.
4. **First release:** decide the starting version (see Versioning), merge the smoke PR after approval.
   Watch: CI gate → version → image on Docker Hub (`X.Y.Z` and `latest`, same digest) → tag `vX.Y.Z`
   → deploy → summary. Check `https://<your-host>/health` shows the version and the footer shows `vX.Y.Z`.
5. **Rollback:** run *Rollback FinTracker* with the previous version; confirm `/health`. Roll forward the same way.
6. Optional: add required reviewers to the `Development` environment before step 4 for a manual go/no-go.

## Assumptions

* The server is `linux/amd64` (images are built for that platform; add `linux/arm64` in `release.yml` if needed).
* The server has Docker Engine + Compose v2, and the deploy user's login shell is bash.
* The compose service is `fintracker`; the container has Python (it does — the app image) for the in-container health query.
* `Development` is the only deployment target (environment name "Development"). `main` only carries the
  deployment bundle and is written by `publish-main.yml`.
* The dev stack in `docker/compose.yml` (local builds, `--reload`) is unrelated to deployment.
