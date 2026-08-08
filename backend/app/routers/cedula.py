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

El desafío de Autenticación Activa se pide en `POST /auth/cedula/aa-challenge`
y se devuelve por su identificador, nunca por su valor. Esa asimetría es el
anti-replay entero: el cliente no puede presentar un desafío que ya tenga
firmado de otra sesión, porque el que cuenta lo recuerda el servidor.
"""

import base64
import binascii
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.config import settings
from ..services import (
    aa_challenge,
    cedula_nfc,
    csca_trust_store,
    identity_grant,
    membership_grant,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/cedula", tags=["Cédula NFC"])


class ActiveAuthenticationPayload(BaseModel):
    """Respuesta del chip a INTERNAL AUTHENTICATE.

    No incluye el desafío: el servidor lo tiene guardado bajo `challenge_id`.
    Aceptarlo del cliente convertiría la Autenticación Activa en una firma
    sobre datos que el propio firmante elige, que no prueba nada.
    """

    challenge_id: str = Field(
        description="Identificador devuelto por POST /auth/cedula/aa-challenge."
    )
    signature: str = Field(
        description="Firma del chip en base64, en crudo tal como respondió."
    )


class CedulaReadingRequest(BaseModel):
    """Lectura cruda del chip. Base64 de los archivos TAL COMO se leyeron.

    Volver a serializar un data group ya parseado produce bytes distintos y el
    hash del SOD no cuadraría: el cliente debe mandar el archivo íntegro con
    su tag, no el contenido interpretado.
    """

    sod: str = Field(description="EF.SOD en base64, con o sin el envoltorio 77.")
    data_groups: dict[str, str] = Field(
        description=(
            "Archivos DG en base64, indexados por número ('1', '2' o 'DG1'). "
            "Para Autenticación Activa han de incluir DG15, y DG14 si el chip "
            "firma con ECDSA: así el SOD respalda también la clave del chip."
        )
    )
    active_authentication: Optional[ActiveAuthenticationPayload] = Field(
        default=None,
        description=(
            "Autenticación Activa. Obligatoria cuando el despliegue la exige "
            "(CEDULA_REQUIRE_ACTIVE_AUTH; por defecto, en producción)."
        ),
    )


class ActiveAuthChallengeResponse(BaseModel):
    challenge_id: str
    #: Los 8 bytes que hay que mandarle al chip en INTERNAL AUTHENTICATE.
    challenge: str
    expires_in: int


class CedulaVerificationResponse(BaseModel):
    ok: bool
    identity_grant: str
    identity_grant_expires_in: int
    #: Grant de membresía (JWT, ROADMAP 1.10): certifica sujeto y nivel, y es
    #: lo que POST /api/membership/mint exige y quema.
    membership_grant: str
    membership_grant_expires_in: int
    assurance_level: str
    #: Detalle criptográfico de lo comprobado. Sin datos del titular.
    verification: dict


@router.post("/aa-challenge", response_model=ActiveAuthChallengeResponse)
async def issue_active_auth_challenge():
    """Emite un desafío de Autenticación Activa: 8 bytes, un solo uso, TTL corto.

    Público y sin sesión, como la propia verificación: en este punto del flujo
    todavía no hay wallet ni identidad. Lo que protege el endpoint es que el
    desafío no sirva dos veces, no quién lo pida — un desafío sin usar no
    autoriza nada.
    """
    issued = await aa_challenge.issue()
    return ActiveAuthChallengeResponse(
        challenge_id=issued.challenge_id,
        challenge=base64.b64encode(issued.challenge).decode("ascii"),
        expires_in=aa_challenge.ttl_seconds(),
    )


def _decode_signature(value: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=400,
            detail="La firma de Autenticación Activa no viene en base64 válido.",
        ) from None
    if not raw:
        raise HTTPException(
            status_code=400,
            detail="La firma de Autenticación Activa llegó vacía.",
        )
    if len(raw) > cedula_nfc.MAX_FILE_BYTES:
        raise HTTPException(
            status_code=400,
            detail="La firma de Autenticación Activa supera el tamaño admitido.",
        )
    return raw


@router.post("/verify", response_model=CedulaVerificationResponse)
async def verify_cedula(request: CedulaReadingRequest):
    """Verifica la lectura NFC y emite un grant civil de un solo uso.

    Sin sesión de wallet: igual que el callback de ClaveÚnica, aquí todavía no
    hay wallet. El grant se canjea después en `/api/auth/identity-credential`,
    que sí exige SIWE y liga la credencial a la dirección autenticada.
    """
    active = None
    if request.active_authentication is not None:
        signature = _decode_signature(request.active_authentication.signature)
        # El desafío se quema ANTES de verificar nada. Es deliberado: un
        # desafío es gratis —se pide otro y se vuelve a apoyar la cédula—, y
        # dejarlo vivo mientras se decide daría a dos peticiones simultáneas
        # con la misma captura dos oportunidades de pasar.
        try:
            challenge = await aa_challenge.consume(
                request.active_authentication.challenge_id
            )
        except aa_challenge.ActiveAuthChallengeError as exc:
            logger.warning("Desafío de Autenticación Activa rechazado: %s", exc)
            raise HTTPException(
                status_code=401,
                detail={
                    "message": "El desafío de Autenticación Activa no es utilizable.",
                    "reasons": [str(exc)],
                },
            ) from exc
        active = cedula_nfc.ActiveAuthentication(
            challenge=challenge, signature=signature
        )

    try:
        verified = cedula_nfc.verify_reading(
            request.sod, request.data_groups, active=active
        )
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
        membership = membership_grant.issue(
            subject_key=verified.subject_key,
            assurance_level=verified.assurance_level,
            provider=cedula_nfc.PROVIDER_NAME,
        )
    except (
        identity_grant.IdentityGrantError,
        membership_grant.MembershipGrantError,
    ) as exc:
        # El documento es auténtico, pero el despliegue no está habilitado para
        # emitir grants (IDENTITY_PROVIDER). Se dice tal cual.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return CedulaVerificationResponse(
        ok=True,
        identity_grant=grant,
        identity_grant_expires_in=settings.IDENTITY_GRANT_TTL_SECONDS,
        membership_grant=membership,
        membership_grant_expires_in=settings.MEMBERSHIP_GRANT_TTL_SECONDS,
        assurance_level=verified.assurance_level,
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
