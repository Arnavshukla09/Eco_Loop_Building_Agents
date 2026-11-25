"""Shared authentication and browser origin checks."""
from contextvars import ContextVar
from secrets import compare_digest
from urllib.parse import urlsplit

from config.settings import settings

mcp_authenticated: ContextVar[bool] = ContextVar("mcp_authenticated", default=False)


def valid_api_key(candidate: str | None) -> bool:
    """Compare UTF-8 tokens without leaking matching prefixes through timing."""
    return bool(settings.API_KEY and candidate is not None and compare_digest(
        candidate.encode("utf-8"), settings.API_KEY.encode("utf-8")
    ))


def browser_origin_allowed(origin: str | None, scope: dict) -> bool:
    """Native clients have no Origin; browser control requires a trusted origin.

    CORS response headers alone do not stop simple cross-origin POST requests.
    A wildcard permits public reads, but never grants browser control access.
    """
    if origin is None:
        return True
    if origin == "null":
        return False
    if origin in settings.CORS_ORIGINS and origin != "*":
        return True
    headers = dict(scope.get("headers", []))
    host = headers.get(b"host", b"").decode("latin-1")
    scheme = {"ws": "http", "wss": "https"}.get(scope.get("scheme"), scope.get("scheme", "http"))
    # A hostname supplied by the request must not establish trust: an attacker
    # can rebind their own domain to loopback and manufacture same-origin calls.
    try:
        local_hostname = urlsplit(origin).hostname in ("localhost", "127.0.0.1", "::1")
    except ValueError:
        return False
    return bool(local_hostname and host and origin == f"{scheme}://{host}")
