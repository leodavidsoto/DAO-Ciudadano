"""
Router de verificación de cédula por NFC (ROADMAP 5.8).

Vive fuera de `auth.py` por la misma razón que `identity.py`: aquel router
lleva `require_non_production_identity_demo` a nivel de router para apagar los
simuladores en producción. Este endpoint es el camino real y tiene que
funcionar precisamente ahí. Colgarlo del mismo router lo habría dejado
devolviendo 503 justo donde debe servir.

Aquí no hay simulación posible. El endpoint no acepta un veredicto: acepta los
bytes del chip y los verifica. Si la Autenticación Pasiva falla, responde 401
y no emite nada — no existe combinación de campos que produzca un grant sin
una firma válida del Registro Civil.
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.config import settings
from ..services import cedula_nfc, csca_trust_store, identity_grant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/cedula", tags=["Cédula NFC"])


class CedulaReadingRequest(BaseModel):
    """Lectura cruda del chip. Base64 de los archivos TAL COMO se leyeron.

    Volver a serializar un data group ya parseado produce bytes distintos y el
    hash del SOD no cuadraría: el cliente debe mandar el archivo íntegro con
    su tag, no el contenido interpretado.
    """

    sod: str = Field(description="EF.SOD en base64, con o sin el envoltorio 77.")
    data_groups: dict[str, str] = Field(
        description="Archivos DG en base64, indexados por número ('1', '2' o 'DG1')."
    )


class CedulaVerificationResponse(BaseModel):
    ok: bool
    identity_grant: str
    identity_grant_expires_in: int
    #: Detalle criptográfico de lo comprobado. Sin datos del titular.
    verification: dict


@router.post("/verify", response_model=CedulaVerificationResponse)
async def verify_cedula(request: CedulaReadingRequest):
    """Verifica la lectura NFC y emite un grant civil de un solo uso.

    Sin sesión de wallet: igual que el callback de ClaveÚnica, aquí todavía no
    hay wallet. El grant se canjea después en `/api/auth/identity-credential`,
    que sí exige SIWE y liga la credencial a la dirección autenticada.
    """
    try:
        verified = cedula_nfc.verify_reading(request.sod, request.data_groups)
    except csca_trust_store.TrustStoreError as exc:
        # No hay anclas del Registro Civil instaladas. Es un fallo de
        # despliegue, no del ciudadano, y se dice como tal: un 401 aquí
        # mandaría a la gente a repetir una lectura que nunca podría pasar.
        logger.error("Trust store de CSCA no disponible: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "La verificación de cédulas no está disponible: al servidor le "
                "faltan los certificados del Registro Civil."
            ),
        ) from exc
    except cedula_nfc.CedulaVerificationError as exc:
        # 401: la lectura no acredita identidad. El motivo se devuelve para que
        # la app pueda decir qué pasó (chip alterado, documento caducado, CSCA
        # desconocida) en vez de un "no se pudo verificar" que no ayuda a nadie.
        logger.warning("Autenticación Pasiva rechazada: %s", exc.reasons)
        raise HTTPException(
            status_code=401,
            detail={
                "message": "La cédula no superó la verificación criptográfica.",
                "reasons": exc.reasons,
            },
        ) from exc

    try:
        grant = await identity_grant.issue(
            subject_key=verified.subject_key,
            provider=cedula_nfc.PROVIDER_NAME,
        )
    except identity_grant.IdentityGrantError as exc:
        # El documento es auténtico, pero el despliegue no está habilitado para
        # emitir grants (IDENTITY_PROVIDER). Se dice tal cual.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return CedulaVerificationResponse(
        ok=True,
        identity_grant=grant,
        identity_grant_expires_in=settings.IDENTITY_GRANT_TTL_SECONDS,
        verification=verified.verification,
    )


@router.get("/trust-store")
async def describe_trust_store():
    """Contra qué anclas se validan las cédulas.

    Público a propósito: cualquiera debe poder comprobar que este servidor
    confía en las CSCA del Registro Civil y no en otras. Sólo expone subjects,
    huellas y caducidades — información que ya es pública en el PKD de la ICAO.
    """
    return csca_trust_store.status()
