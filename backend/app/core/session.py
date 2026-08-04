"""
Transporte de la sesión de wallet en cookies (tarea 1.13).

Antes: el JWT de SIWE viajaba solo en el body de `/wallet/verify` y el cliente
web lo guardaba en `localStorage`, donde cualquier XSS —propio o de una
dependencia— podía leerlo y usarlo hasta que expirara.

Ahora: `/wallet/verify` además fija la sesión en una cookie `HttpOnly`
(inalcanzable para JavaScript), `Secure` fuera de local y con `SameSite`
explícito. Como una cookie se envía sola en cada request, hace falta CSRF:
se usa doble envío firmado.

    csrf = HMAC-SHA256(SECRET_KEY, "dao-csrf-v1:" + <jwt de sesión>)

El valor se publica en una cookie legible por JS; el cliente lo repite en la
cabecera `X-CSRF-Token`. Un sitio atacante puede provocar que el navegador
mande la cookie de sesión, pero no puede leer la cookie CSRF (política de
mismo origen) ni calcular el HMAC sin `SECRET_KEY`. Al derivarse del propio
token, no hay estado que guardar ni que expirar por separado.

El header `Authorization: Bearer` sigue funcionando igual: la app móvil no
tiene cookies de navegador ni riesgo de CSRF, y no debe romperse.
"""

import hashlib
import hmac
from typing import Optional, Tuple

from fastapi import HTTPException, Request, Response

from .config import settings

CSRF_HEADER = "X-CSRF-Token"
_CSRF_DOMAIN_SEPARATOR = b"dao-csrf-v1:"

# Métodos sin efectos secundarios: no necesitan token CSRF.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def csrf_token_for(session_token: str) -> str:
    """Token CSRF determinístico y ligado a ESA sesión.

    Ligarlo al JWT (y no a un valor aleatorio suelto) evita que un token CSRF
    capturado sirva para otra sesión, y hace innecesario guardarlo en Mongo.
    """
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        _CSRF_DOMAIN_SEPARATOR + session_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def attach_session(response: Response, session_token: str) -> str:
    """Fija la cookie de sesión y la de CSRF. Devuelve el token CSRF.

    `max_age` coincide con la expiración del JWT: una cookie que sobreviva a
    su token solo consigue que el usuario parezca conectado y reciba 401.
    """
    common = {
        "max_age": settings.SESSION_TOKEN_EXPIRE_SECONDS,
        "path": "/",
        "secure": settings.session_cookie_secure,
        "samesite": settings.session_cookie_samesite,
    }
    domain = settings.SESSION_COOKIE_DOMAIN.strip() or None
    if domain:
        common["domain"] = domain

    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        session_token,
        httponly=True,
        **common,
    )
    csrf = csrf_token_for(session_token)
    # httponly=False es el punto: el cliente TIENE que poder leerla para
    # repetirla en la cabecera. No autentica nada por sí sola.
    response.set_cookie(
        settings.CSRF_COOKIE_NAME,
        csrf,
        httponly=False,
        **common,
    )
    return csrf


def clear_session(response: Response) -> None:
    """Borra ambas cookies con los MISMOS atributos con que se fijaron.

    Un `delete_cookie` con path/domain/samesite distintos deja la original
    intacta en el navegador y el cierre de sesión no cierra nada.
    """
    domain = settings.SESSION_COOKIE_DOMAIN.strip() or None
    for name in (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME):
        response.delete_cookie(
            name,
            path="/",
            domain=domain,
            secure=settings.session_cookie_secure,
            samesite=settings.session_cookie_samesite,
        )


def token_from_request(
    request: Request,
    authorization: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    """Devuelve (token, origen) donde origen ∈ {"header", "cookie", "none"}.

    El header gana sobre la cookie: un cliente que manda `Authorization`
    explícito está pidiendo esa sesión, y no la que el navegador arrastre.
    """
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token:
            return token, "header"
    cookie_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if cookie_token:
        return cookie_token, "cookie"
    return None, "none"


def verify_csrf(request: Request, session_token: str) -> None:
    """Exige el doble envío CSRF en métodos con efectos. 403 si no cuadra.

    Solo aplica a sesiones por cookie: un `Authorization` explícito no lo
    manda el navegador solo, así que no hay nada que falsificar desde otro
    sitio.
    """
    if request.method.upper() in SAFE_METHODS:
        return
    presented = request.headers.get(CSRF_HEADER, "")
    if not presented or not hmac.compare_digest(
        presented, csrf_token_for(session_token)
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Falta o no coincide el token CSRF (cabecera {CSRF_HEADER}). "
                "Repite el valor de la cookie de CSRF en esa cabecera."
            ),
        )
