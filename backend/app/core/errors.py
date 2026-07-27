"""
Client-safe error handling.

Audit finding N-8: routers and services returned `str(e)` to the client.
Driver and provider exceptions can carry connection strings, query fragments
and infrastructure paths. Log the detail with a correlation id; give the
client the id and nothing else.
"""
import logging
import uuid

logger = logging.getLogger(__name__)

GENERIC_MESSAGE = "Ocurrió un error procesando la solicitud"


def report(exc: Exception, context: str, message: str = GENERIC_MESSAGE) -> str:
    """Log `exc` with a correlation id and return a client-safe message.

    The id lets support match a user report to a log line without exposing
    anything about the failure itself.
    """
    error_id = uuid.uuid4().hex[:12]
    logger.error(f"[{error_id}] {context}: {exc}", exc_info=True)
    return f"{message} (ref: {error_id})"
