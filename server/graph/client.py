import logging

import httpx
import pyTigerGraph as tg

from server.settings import settings

logger = logging.getLogger(__name__)


def _mint_cloud_token(host: str, secret: str) -> str:
    """Exchanges a secret for a JWT via the raw TG 4.x token endpoint.

    Bypasses pyTigerGraph's `getToken()`, which always attaches a Basic-auth
    header built from whatever username/password the connection was
    constructed with (default "tigergraph"/"tigergraph" -- pyTigerGraph
    `common/base.py::_refresh_auth_headers`'s fallback order is JWT > apiToken
    > Basic, and neither JWT nor apiToken exist yet on this first call). Local
    Docker's REST++ ignores that header when a valid secret is in the body, so
    `getToken()` works fine there (verified in Phase 0). TigerGraph Cloud's
    gateway validates the Authorization header first and 401s before even
    reading the body, regardless of the secret's validity -- confirmed by a
    raw request with no Authorization header succeeding where the identical
    body via `getToken()` failed.
    """
    resp = httpx.post(f"{host}/gsql/v1/tokens", json={"secret": secret}, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(f"Token request failed: {body.get('message')}")
    return str(body["token"])


def get_tg_connection(graphname: str | None = None) -> tg.TigerGraphConnection:
    """
    Returns an authenticated pyTigerGraph connection using the configured settings.
    If no graphname is provided, defaults to the one in settings.
    """
    gn = graphname or settings.tg_graph

    # Initialize connection
    conn = tg.TigerGraphConnection(
        host=settings.tg_host,
        graphname=gn,
        username=settings.tg_username,
        password=settings.tg_password,
        restppPort=settings.tg_restpp_port,
        gsPort=settings.tg_gs_port,
    )

    # Handle Authentication
    if settings.tg_secret:
        # Use provided secret (Common for TigerGraph Cloud / Savanna) -- see
        # _mint_cloud_token for why this doesn't just call conn.getToken().
        jwt = _mint_cloud_token(settings.tg_host, settings.tg_secret)
        conn.jwtToken = jwt
        conn.apiToken = jwt
        conn._refresh_auth_headers()
        # pyTigerGraph unconditionally disables TLS verification for any
        # https:// host (common/base.py: useCert=True for https -> verify=
        # False, regardless of whether a real CA-signed cert is in use).
        # Savanna serves a standard publicly-trusted cert, so there's no
        # reason to skip verification here; re-enable it.
        conn.verify = True
    else:
        # Generate a new secret and token (Common for local Docker setups)
        try:
            secret = conn.createSecret()
            conn.getToken(secret)
        except Exception as e:
            logger.warning(f"Could not create secret/token, proceeding with basic auth: {e}")

    return conn
