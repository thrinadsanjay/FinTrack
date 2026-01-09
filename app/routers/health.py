"""
Health check endpoint.

Used by:
- Load balancers
- Kubernetes liveness probes
- Monitoring systems

Must remain:
- Fast
- Stateless
- Side-effect free
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check():
    return {"status": "ok"}
