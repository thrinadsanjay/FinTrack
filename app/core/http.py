import httpx
from app.core.security import get_http_verify


def get_http_client() -> httpx.Client:
    return httpx.Client(verify=get_http_verify(), timeout=10)


def get_async_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(verify=get_http_verify(), timeout=10)
