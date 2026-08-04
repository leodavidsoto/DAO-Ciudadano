"""
ClaveÚnica: rutas del flujo OIDC real (ROADMAP 4.1).

Router APARTE del de `/auth` a propósito. Aquel tiene una dependencia que
responde 503 en producción para TODOS sus endpoints, porque son simulaciones
—NFC sin PACE, un LLM que no verifica presencia en vivo, RUT+email que solo
prueba conocer los datos enviados—. Ese bloqueo debe seguir intacto: nada de
lo que hay ahí se ha vuelto real por implementar ClaveÚnica.

Este flujo sí autentica identidad civil, así que funciona en producción
**cuando está configurado**, y responde 503 en cualquier entorno cuando no lo
está. No hay modo demo: un simulador de identidad civil es exactamente lo que
esta tarea elimina.

Contrato para el cliente:

    POST /api/auth/clave-unica/authorize   -> { authorization_url, state }
    (el navegador va a esa URL; el Estado redirige al redirect_uri con code+state)
    POST /api/auth/clave-unica/callback    -> { identity_grant, ... }

El grant resultante es de un solo uso y con TTL corto: se canjea en
`POST /api/identity/identity-credential` para obtener la credencial ZK.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.config import settings
from ..services import clave_unica, identity_grant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/clave-unica", tags=["ClaveÚnica"])


class AuthorizeResponse(BaseModel):
    authorization_url: str
    state: str
    expires_in: int


class CallbackRequest(BaseModel):
    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=1, max_length=512)


class CallbackResponse(BaseModel):
    ok: bool
    identity_grant: str
    identity_grant_expires_in: int
    assurance_level: str
    # Nombre para saludar en la interfaz. NO se persiste en ninguna parte.
    name: str = ""


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


@router.post("/authorize", response_model=AuthorizeResponse)
async def authorize():
    """Crea el intento de login y devuelve la URL de ClaveÚnica.

    El verificador PKCE y el nonce se quedan en el servidor; el cliente solo
    recibe `state`, que por sí solo no permite completar el intercambio.
    """
    try:
        return AuthorizeResponse(**await clave_unica.start_login())
    except clave_unica.ClaveUnicaUnavailable as exc:
        raise _unavailable(exc) from exc


@router.post("/callback", response_model=CallbackResponse)
async def callback(request: CallbackRequest):
    """Valida el retorno del Estado y emite un grant civil de un solo uso.

    Sin sesión de wallet: aquí todavía no hay wallet. Lo que ata este grant a
    una persona concreta es el `subject_key`, y lo que impide reusarlo es que
    se canjea una sola vez al emitir la credencial.
    """
    try:
        result = await clave_unica.complete_login(request.code, request.state)
    except clave_unica.ClaveUnicaUnavailable as exc:
        raise _unavailable(exc) from exc
    except clave_unica.ClaveUnicaError as exc:
        # 401: el fallo es del intento de autenticación, no del servidor.
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    try:
        grant = await identity_grant.issue(
            subject_key=result["subject_key"],
            provider=clave_unica.PROVIDER_NAME,
        )
    except identity_grant.IdentityGrantError as exc:
        # Ocurre si IDENTITY_PROVIDER no declara un proveedor en producción:
        # la autenticación fue real, pero el despliegue no está habilitado
        # para emitir credenciales. Se dice tal cual en vez de devolver un
        # grant que no respalda nada.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return CallbackResponse(
        ok=True,
        identity_grant=grant,
        identity_grant_expires_in=settings.IDENTITY_GRANT_TTL_SECONDS,
        assurance_level=result["assurance_level"],
        name=result["name"],
    )
