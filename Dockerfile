FROM python:3.12-slim

# Release version, injected by CI (release.yml). Empty for local/dev builds.
ARG APP_VERSION=""
ARG VCS_REF=""

LABEL org.opencontainers.image.title="FinTracker" \
      org.opencontainers.image.source="https://github.com/thrinadsanjay/FinTrack" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

RUN pip install --upgrade pip \
    && pip install -r requirements.txt  --trusted-host files.pythonhosted.org --trusted-host pypi.org

COPY app ./app

# The baked version is what the app reports (footer, /health, OpenAPI);
# it takes precedence over any FT_APP_VERSION left in the server's .env.
RUN if [ -n "${APP_VERSION}" ]; then printf '%s\n' "${APP_VERSION}" > /app/VERSION; fi

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD ["python", "-c", "import os, sys, urllib.request as u; sys.exit(0 if u.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=4).status == 200 else 1)"]

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --loop asyncio --http h11 --timeout-graceful-shutdown 10"]
