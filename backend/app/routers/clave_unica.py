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
from typing import Optional

from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel, Field

from ..core.config import settings
from ..services import clave_unica, identity_grant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/clave-unica", tags=["ClaveÚnica"])

# FastAPI no admite un alias dinámico en `Cookie(...)`, así que el nombre se
# resuelve al importar. Cambiarlo exige reiniciar, que es lo esperable para el
# nombre de una cookie.
BINDING_COOKIE_ALIAS = settings.CLAVE_UNICA_BINDING_COOKIE_NAME


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


class StatusResponse(BaseModel):
    """Contrato que la web exige literalmente antes de habilitar el botón."""

    available: bool
    protocol_version: str
    pkce_method: str
    browser_bound: bool
    credential_exchange_browser_bound: bool
    callback_idempotent: bool
    grant_single_use: bool
    redirect_transport: str
    grant_ttl_seconds: int


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


def _set_binding_cookie(response: Response, value: str) -> None:
    """Fija el binding de navegador.

    `HttpOnly`: ni un XSS puede leerla para reenviarla desde otro cliente.
    `SameSite`/`Secure` se derivan del entorno igual que la cookie de sesión —
    en producción eso es `None; Secure`, que es lo que hace falta cuando el
    frontend y la API están en sitios distintos; en local, `Lax`, porque los
    navegadores DESCARTAN `SameSite=None` sin `Secure` sobre http.

    `path=/api`: lo más estrecho que sirve, porque el canje del grant en
    `/api/identity/identity-credential` vuelve a exigir esta misma cookie.
    """
    response.set_cookie(
        settings.CLAVE_UNICA_BINDING_COOKIE_NAME,
        value,
        max_age=settings.CLAVE_UNICA_LOGIN_TTL_SECONDS,
        path="/api",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
    )


@router.get("/status", response_model=StatusResponse)
async def status():
    """Telemetría del contrato. Sin secretos y sin tocar la red."""
    return StatusResponse(**clave_unica.status())


@router.post("/authorize", response_model=AuthorizeResponse)
async def authorize(response: Response):
    """Crea el intento de login, fija el binding y devuelve la URL.

    El verificador PKCE y el nonce se quedan en el servidor; el navegador
    recibe `state` (que por sí solo no completa nada) y una cookie HttpOnly
    que no puede leer pero que tendrá que presentar al volver.
    """
    try:
        started = await clave_unica.start_login()
    except clave_unica.ClaveUnicaUnavailable as exc:
        raise _unavailable(exc) from exc

    _set_binding_cookie(response, started.pop("browser_binding"))
    return AuthorizeResponse(**started)


@router.post("/callback", response_model=CallbackResponse)
async def callback(
    request: CallbackRequest,
    binding: Optional[str] = Cookie(default=None, alias=BINDING_COOKIE_ALIAS),
):
    """Valida el retorno del Estado y emite un grant civil de un solo uso.

    Sin sesión de wallet: aquí todavía no hay wallet. Lo que ata este canje al
    navegador que se identificó es la cookie de binding, y se comprueba ANTES
    de hablar con el proveedor: quien capture `code + state` no puede usar
    este endpoint como oráculo PKCE desde otro cliente.
    """
    try:
        result = await clave_unica.complete_login(
            request.code, request.state, binding
        )
    except clave_unica.LoginAlreadyCompleted as done:
        # Idempotencia: la respuesta anterior se perdió y el navegador
        # reintenta. Se devuelve EL MISMO grant, no otro.
        return CallbackResponse(
            ok=True,
            identity_grant=done.grant,
            identity_grant_expires_in=settings.IDENTITY_GRANT_TTL_SECONDS,
            assurance_level=clave_unica.ASSURANCE_LEVEL,
            name=done.name,
        )
    except clave_unica.LoginInProgress as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except clave_unica.ClaveUnicaUnavailable as exc:
        raise _unavailable(exc) from exc
    except clave_unica.ClaveUnicaProviderError as exc:
        # 502: falló el tercero, no el ciudadano. Mandarlo a repetir con un
        # 401 sería culparlo de algo que no hizo.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except clave_unica.ClaveUnicaError as exc:
        # 401: el fallo es del intento de autenticación, no del servidor.
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    try:
        grant = await identity_grant.issue(
            subject_key=result["subject_key"],
            provider=clave_unica.PROVIDER_NAME,
            browser_binding=result["browser_binding"],
        )
    except identity_grant.IdentityGrantError as exc:
        # Ocurre si IDENTITY_PROVIDER no declara un proveedor en producción:
        # la autenticación fue real, pero el despliegue no está habilitado
        # para emitir credenciales. Se dice tal cual en vez de devolver un
        # grant que no respalda nada.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Se recuerda cifrado para poder repetir esta misma respuesta si se pierde.
    await clave_unica.remember_issued_grant(
        result["state"], grant, result["name"]
    )

    return CallbackResponse(
        ok=True,
        identity_grant=grant,
        identity_grant_expires_in=settings.IDENTITY_GRANT_TTL_SECONDS,
        assurance_level=result["assurance_level"],
        name=result["name"],
    )
