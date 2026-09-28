import pyTigerGraph as tg
import logging
from server.settings import settings

logger = logging.getLogger(__name__)

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
        password=settings.tg_password
    )
    
    # Handle Authentication
    if settings.tg_secret:
        # Use provided secret (Common for TigerGraph Cloud / Savanna)
        conn.getToken(settings.tg_secret)
    else:
        # Generate a new secret and token (Common for local Docker setups)
        try:
            secret = conn.createSecret()
            conn.getToken(secret)
        except Exception as e:
            logger.warning(f"Could not create secret/token, proceeding with basic auth: {e}")
            
    return conn
