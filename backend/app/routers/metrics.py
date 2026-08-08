"""
Endpoint de métricas Prometheus, autenticado.

`Instrumentator().expose(app)` publica `/metrics` sin ninguna autenticación.
Las métricas no llevan PII, pero sí describen el sistema con precisión:
inventario de rutas, volumen de tráfico por endpoint, latencias y recuento de
errores. Es reconocimiento gratuito para quien lo pida, y además revela qué
endpoints existen aunque no estén documentados.

Aquí se sirve la misma información detrás de `METRICS_TOKEN`:

    curl -H "Authorization: Bearer $METRICS_TOKEN" https://api.../metrics

Fail closed en producción: si las métricas están habilitadas y no hay token,
el endpoint responde 503 en vez de publicarse abierto. Fuera de producción se
permite sin token para no estorbar el desarrollo local, pero se avisa en los
logs.
"""

import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Response
from typing import Optional

from ..core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Observability"])


def _authorize(authorization: Optional[str]) -> None:
    token = settings.METRICS_TOKEN.strip()

    if not token:
        if settings.is_production:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Las métricas están habilitadas pero METRICS_TOKEN no está "
                    "configurado. No se publican sin autenticación."
                ),
            )
        logger.warning(
            "/metrics servido SIN token: solo aceptable fuera de producción."
        )
        return

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Se requiere Authorization: Bearer <METRICS_TOKEN>.",
        )

    presented = authorization.split(" ", 1)[1].strip()
    # compare_digest: comparar con == filtra por tiempo cuántos caracteres
    # iniciales acertó quien lo intenta.
    if not hmac.compare_digest(presented, token):
        raise HTTPException(status_code=401, detail="Token de métricas inválido.")


@router.get("/metrics", include_in_schema=False)
async def metrics(authorization: Optional[str] = Header(default=None)):
    """Métricas en formato Prometheus. Requiere METRICS_TOKEN."""
    _authorize(authorization)

    from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )
