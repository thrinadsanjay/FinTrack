"""
Health check endpoint.

Used by:
- Load balancers
- Container HEALTHCHECK / deployment verification (reports the running version)
- Monitoring systems

Must remain:
- Fast
- Stateless
- Side-effect free
"""

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/health")
def health_check():
    return {"Error": 200, "status": "ok", "version": settings.FT_APP_VERSION}
