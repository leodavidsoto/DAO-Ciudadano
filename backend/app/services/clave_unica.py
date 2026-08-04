"""
ClaveÚnica: OpenID Connect real (ROADMAP 4.1).

Sustituye al simulador que devolvía `demo:clave-unica:<uuid>` y un
`assurance_level` inventado. Ese endpoint no autenticaba a nadie: aceptaba
cualquier RUT con formato válido.

Flujo implementado: `authorization_code` + **PKCE S256**, validación completa
del `id_token` emitido por el Estado y extracción del RUN. Al terminar se emite
un **grant civil de un solo uso** (`identity_grant`), que es lo único que
autoriza a insertar un commitment en el árbol de identidades (ADR-001, D-2).
Así ClaveÚnica se enchufa al camino que ya existe en vez de abrir uno paralelo.

Lo que NO se guarda
───────────────────
El RUN no se persiste en ninguna parte. Del sujeto solo queda `subject_key`,
un índice ciego HMAC con el pepper del servidor (`identity.lookup_key`), que
no permite recuperar el RUN ni comprobar si una persona concreta se registró
sin conocer ya su RUN. El `id_token` tampoco se almacena.

Decisiones de seguridad que conviene no revertir
────────────────────────────────────────────────
* **El algoritmo de firma se fija por configuración**, nunca se lee de la
  cabecera del token. Aceptar el `alg` que trae el propio token es la
  confusión de algoritmos: con un JWKS RS256 publicado, un atacante firma con
  HMAC usando la clave pública —que es pública— y el token pasa.
* **`state`, `nonce` y el verificador PKCE viven en el servidor**, atados
  entre sí, de un solo uso y con TTL corto. El `state` se consume
  atómicamente: dos callbacks con el mismo código no producen dos grants.
* **Sin configuración no hay flujo.** Ni endpoints por defecto ni "modo
  demo": si falta cualquier valor, se responde 503 en TODOS los entornos.
  Un simulador de identidad civil es justo lo que esta tarea elimina.
"""

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

from ..core.config import settings
from ..core.database import get_collection
from ..core.identity import lookup_key

logger = logging.getLogger(__name__)

PROVIDER_NAME = "clave-unica"
# Versión del contrato que el frontend exige literalmente antes de habilitar
# el botón. Si cambia la semántica de alguna garantía, cambia esta cadena.
PROTOCOL_VERSION = "clave-unica-oidc-pkce-v1"
# Nivel de aseguramiento que declara una autenticación con ClaveÚnica. No es
# una constante decorativa: distingue esta credencial de las de los demos.
ASSURANCE_LEVEL = "CLAVE_UNICA"

# Margen para desfase de reloj al validar exp/iat. Corto: el resto de la
# seguridad del flujo depende de que la ventana temporal signifique algo.
CLOCK_SKEW_SECONDS = 60


class ClaveUnicaError(RuntimeError):
    """Fallo atribuible al flujo o a la respuesta del proveedor."""


class ClaveUnicaProviderError(ClaveUnicaError):
    """El proveedor no respondió, tardó demasiado o devolvió algo ilegible.

    Se distingue de `ClaveUnicaError` a propósito: un timeout del Estado no es
    "tu inicio de sesión no es válido". Decirle eso al ciudadano lo mandaría a
    repetir un flujo que no falló por su culpa; el router responde 502.
    """


class ClaveUnicaUnavailable(RuntimeError):
    """Falta configuración: el flujo no puede ni intentarse."""


def login_sessions_collection():
    return get_collection("oidc_login_sessions")


def configuration_errors() -> dict[str, str]:
    """Qué falta para poder hablar con ClaveÚnica. Sin tocar la red."""
    errors: dict[str, str] = {}
    required = {
        "CLAVE_UNICA_CLIENT_ID": settings.CLAVE_UNICA_CLIENT_ID,
        "CLAVE_UNICA_CLIENT_SECRET": settings.CLAVE_UNICA_CLIENT_SECRET,
        "CLAVE_UNICA_REDIRECT_URI": settings.CLAVE_UNICA_REDIRECT_URI,
        "CLAVE_UNICA_ISSUER": settings.CLAVE_UNICA_ISSUER,
        "CLAVE_UNICA_AUTHORIZATION_ENDPOINT": settings.CLAVE_UNICA_AUTHORIZATION_ENDPOINT,
        "CLAVE_UNICA_TOKEN_ENDPOINT": settings.CLAVE_UNICA_TOKEN_ENDPOINT,
    }
    for key, value in required.items():
        if not str(value).strip():
            errors[key] = "falta"

    alg = settings.CLAVE_UNICA_ID_TOKEN_ALG.strip().upper()
    if alg not in {"RS256", "HS256"}:
        errors["CLAVE_UNICA_ID_TOKEN_ALG"] = "debe ser RS256 o HS256"
    elif alg == "RS256" and not settings.CLAVE_UNICA_JWKS_URI.strip():
        # Con RS256 hace falta de dónde sacar la clave pública. Sin JWKS no se
        # puede verificar nada, y "no verificar" no es una opción.
        errors["CLAVE_UNICA_JWKS_URI"] = "obligatorio con RS256"

    redirect = settings.CLAVE_UNICA_REDIRECT_URI.strip()
    if redirect and settings.is_production and not redirect.startswith("https://"):
        errors["CLAVE_UNICA_REDIRECT_URI"] = "debe ser HTTPS en producción"

    # Los endpoints del Estado son HTTPS. Aceptar http aquí expondría el
    # código de autorización y el client_secret en claro, en cualquier entorno.
    for key in (
        "CLAVE_UNICA_ISSUER",
        "CLAVE_UNICA_AUTHORIZATION_ENDPOINT",
        "CLAVE_UNICA_TOKEN_ENDPOINT",
        "CLAVE_UNICA_USERINFO_ENDPOINT",
        "CLAVE_UNICA_JWKS_URI",
    ):
        value = str(getattr(settings, key, "")).strip()
        if value and not value.startswith("https://"):
            errors[key] = "debe ser HTTPS"

    return errors


def is_configured() -> bool:
    return not configuration_errors()


def _require_configuration() -> None:
    errors = configuration_errors()
    if errors:
        raise ClaveUnicaUnavailable(
            "ClaveÚnica no está configurada: "
            + ", ".join(f"{k} ({v})" for k, v in errors.items())
        )


def new_browser_binding() -> tuple[str, str]:
    """Devuelve (valor para la cookie, hash que se persiste).

    El problema que resuelve
    ────────────────────────
    El backend guarda el `code_verifier`, así que ES el cliente confidencial
    frente a ClaveÚnica. PKCE protege el canje contra un atacante que
    intercepte el código *camino del proveedor*, pero no protege ESTA
    frontera: quien consiga `code + state` puede llamar a `/callback` desde
    cualquier cliente HTTP y recibir el grant. El backend haría de oráculo
    PKCE. Comparar el `state` en sessionStorage no lo impide, porque esa
    comprobación vive en el navegador honesto, no aquí.

    El binding ata el canje al MISMO agente de usuario que inició el flujo:
    sin la cookie no hay grant, y la cookie es `HttpOnly`, así que ni un XSS
    puede leerla para reenviarla.

    Se persiste solo el hash: quien lea la base de datos no puede fabricar la
    cookie de nadie.
    """
    value = secrets.token_urlsafe(32)
    return value, hash_browser_binding(value)


def _as_utc(value) -> Optional[datetime]:
    """Normaliza una fecha leída de Mongo a UTC con zona.

    El driver devuelve datetimes SIN tzinfo (Mongo guarda milisegundos UTC),
    así que compararlas con `datetime.now(timezone.utc)` revienta con
    "can't compare offset-naive and offset-aware". No es un detalle de los
    tests: pasaría igual en producción.
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def hash_browser_binding(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def binding_matches(presented: Optional[str], stored_hash: Optional[str]) -> bool:
    """Comparación en tiempo constante. Sin cookie o sin hash, no coincide."""
    if not presented or not stored_hash:
        return False
    return secrets.compare_digest(hash_browser_binding(presented), stored_hash)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def code_challenge_for(verifier: str) -> str:
    """S256, el único método que se ofrece.

    `plain` deja el verificador a la vista de cualquiera que intercepte la
    redirección, que es justo lo que PKCE viene a evitar.
    """
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


async def start_login() -> dict:
    """Crea el intento de login y devuelve la URL de autorización.

    El verificador PKCE, el nonce y el hash del binding se quedan en el
    servidor: el navegador solo recibe `state` (en la URL) y el binding (en
    una cookie HttpOnly que no puede leer).
    """
    _require_configuration()

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    # 43-128 caracteres según RFC 7636; 32 bytes urlsafe dan 43.
    verifier = secrets.token_urlsafe(32)
    binding_value, binding_hash = new_browser_binding()
    now = datetime.now(timezone.utc)

    await login_sessions_collection().insert_one(
        {
            "state": state,
            "nonce": nonce,
            "code_verifier": verifier,
            "browser_binding": binding_hash,
            "created_at": now,
            "expires_at": now
            + timedelta(seconds=settings.CLAVE_UNICA_LOGIN_TTL_SECONDS),
            "consumed": False,
        }
    )

    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.CLAVE_UNICA_CLIENT_ID.strip(),
            "redirect_uri": settings.CLAVE_UNICA_REDIRECT_URI.strip(),
            "scope": settings.CLAVE_UNICA_SCOPES.strip() or "openid run",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge_for(verifier),
            "code_challenge_method": "S256",
        }
    )
    separator = "&" if "?" in settings.CLAVE_UNICA_AUTHORIZATION_ENDPOINT else "?"
    url = settings.CLAVE_UNICA_AUTHORIZATION_ENDPOINT.strip() + separator + query

    return {
        "authorization_url": url,
        "state": state,
        "expires_in": settings.CLAVE_UNICA_LOGIN_TTL_SECONDS,
        # Lo fija el router en una cookie HttpOnly; nunca va en el cuerpo que
        # el navegador pueda leer desde JavaScript.
        "browser_binding": binding_value,
    }


async def _load_login_session(state: str, binding: Optional[str]) -> dict:
    """Recupera el intento y EXIGE el binding, antes de tocar la red.

    El orden importa: comprobar la cookie antes de llamar al proveedor evita
    que un tercero con `code + state` use este endpoint como oráculo PKCE, y
    además no gasta el código de autorización de nadie.
    """
    if not state:
        raise ClaveUnicaError("Falta el parámetro state.")

    record = await login_sessions_collection().find_one({"state": state})
    expires_at = _as_utc(record.get("expires_at")) if record else None
    if not record or not expires_at or expires_at <= datetime.now(timezone.utc):
        raise ClaveUnicaError(
            "El intento de inicio de sesión no existe o expiró. Vuelve a empezar."
        )

    if not binding_matches(binding, record.get("browser_binding")):
        # Mismo mensaje tanto si falta la cookie como si no coincide: no hay
        # nada que ganar diciéndole a quien roba un código cuál de las dos
        # cosas le falta.
        raise ClaveUnicaError(
            "Este intento de inicio de sesión pertenece a otro navegador. "
            "Vuelve a empezar desde el mismo dispositivo."
        )
    return record


async def _claim_login_session(state: str, binding_hash: str) -> Optional[dict]:
    """Marca el intento como consumido. `None` si otro lo ganó primero."""
    return await login_sessions_collection().find_one_and_update(
        {
            "state": state,
            "browser_binding": binding_hash,
            "consumed": False,
            "expires_at": {"$gt": datetime.now(timezone.utc)},
        },
        {"$set": {"consumed": True, "consumed_at": datetime.now(timezone.utc)}},
    )


def _exchange_code(code: str, verifier: str) -> dict:
    """Canjea el código por tokens. Bloqueante: llamar en un hilo."""
    import requests

    try:
        response = requests.post(
            settings.CLAVE_UNICA_TOKEN_ENDPOINT.strip(),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.CLAVE_UNICA_REDIRECT_URI.strip(),
                "client_id": settings.CLAVE_UNICA_CLIENT_ID.strip(),
                "client_secret": settings.CLAVE_UNICA_CLIENT_SECRET.strip(),
                "code_verifier": verifier,
            },
            timeout=10,
            headers={"Accept": "application/json"},
        )
    except Exception as exc:
        logger.error("No se pudo contactar a ClaveÚnica (%s)", type(exc).__name__)
        raise ClaveUnicaProviderError(
            "El proveedor de identidad no respondió. Intenta de nuevo en unos minutos."
        ) from exc

    if response.status_code != 200:
        # Nunca se refleja el cuerpo del proveedor: puede traer el código, el
        # secreto o datos del titular, y acabaría en logs y en pantalla.
        logger.error(
            "ClaveÚnica rechazó el canje del código (HTTP %s)", response.status_code
        )
        raise ClaveUnicaError("El proveedor rechazó el intercambio del código.")

    try:
        payload = response.json()
    except ValueError as exc:
        raise ClaveUnicaProviderError(
            "El proveedor devolvió una respuesta que no es JSON."
        ) from exc
    if not isinstance(payload, dict) or not payload.get("id_token"):
        raise ClaveUnicaProviderError("El proveedor no devolvió un id_token.")
    return payload


def _signing_key(token: str):
    """Clave con la que verificar la firma, según el algoritmo CONFIGURADO."""
    import jwt

    alg = settings.CLAVE_UNICA_ID_TOKEN_ALG.strip().upper()
    if alg == "HS256":
        return settings.CLAVE_UNICA_CLIENT_SECRET.strip()

    client = jwt.PyJWKClient(settings.CLAVE_UNICA_JWKS_URI.strip())
    return client.get_signing_key_from_jwt(token).key


def validate_id_token(token: str, nonce: str) -> dict:
    """Valida firma, emisor, audiencia, vigencia y nonce. Bloqueante.

    `options` desactiva nada: se exigen exp, iat y aud explícitamente. Y el
    algoritmo se pasa como lista de UNO, el configurado, para que la cabecera
    del token no pueda elegir por nosotros.
    """
    import jwt

    alg = settings.CLAVE_UNICA_ID_TOKEN_ALG.strip().upper()
    try:
        claims = jwt.decode(
            token,
            _signing_key(token),
            algorithms=[alg],
            audience=settings.CLAVE_UNICA_CLIENT_ID.strip(),
            issuer=settings.CLAVE_UNICA_ISSUER.strip(),
            leeway=CLOCK_SKEW_SECONDS,
            options={
                "require": ["exp", "iat", "iss", "aud"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except jwt.PyJWTError as exc:
        logger.warning("id_token de ClaveÚnica rechazado (%s)", type(exc).__name__)
        raise ClaveUnicaError(
            f"El id_token no es válido: {type(exc).__name__}"
        ) from exc

    # El nonce ata este token al intento de login que lo pidió. Sin esto, un
    # id_token capturado de otra sesión se podría reinyectar aquí.
    if claims.get("nonce") != nonce:
        raise ClaveUnicaError("El nonce del id_token no corresponde a este login.")

    # `azp` solo aparece con varias audiencias, pero si viene tiene que ser
    # nuestro cliente: identifica a quién se emitió realmente el token.
    azp = claims.get("azp")
    if azp and azp != settings.CLAVE_UNICA_CLIENT_ID.strip():
        raise ClaveUnicaError("El id_token fue emitido para otro cliente.")

    if not claims.get("sub"):
        raise ClaveUnicaError("El id_token no identifica a ningún sujeto.")

    return claims


def _fetch_userinfo(access_token: str) -> dict:
    """UserInfo cuando el id_token no trae el RUN. Bloqueante."""
    import requests

    endpoint = settings.CLAVE_UNICA_USERINFO_ENDPOINT.strip()
    if not endpoint:
        return {}
    response = requests.get(
        endpoint,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        timeout=10,
    )
    if response.status_code != 200:
        logger.error("UserInfo de ClaveÚnica falló (HTTP %s)", response.status_code)
        return {}
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _run_check_digit(number: int) -> str:
    """Dígito verificador del RUN (módulo 11)."""
    total = 0
    multiplier = 2
    for digit in reversed(str(number)):
        total += int(digit) * multiplier
        multiplier = multiplier + 1 if multiplier < 7 else 2
    remainder = 11 - (total % 11)
    if remainder == 11:
        return "0"
    if remainder == 10:
        return "K"
    return str(remainder)


def extract_run(claims: dict) -> str:
    """RUN normalizado (`12345678-9`) desde los claims. Lanza si no está.

    Se admite la forma documentada de ClaveÚnica —`RolUnico` con `numero` y
    `DV`— y una forma plana por si el despliegue recibe el RUN como cadena.
    Si no aparece en ninguna, se falla: **no se inventa un identificador**, y
    sin RUN no hay identidad civil que acreditar.

    El dígito verificador se recalcula. Un RUN cuyo DV no cuadra no es un RUN,
    venga de donde venga: aceptarlo dejaría entrar identificadores inválidos
    con la firma del Estado por delante.
    """
    rol = claims.get("RolUnico") or claims.get("rol_unico")
    number: Optional[str] = None
    dv: Optional[str] = None

    if isinstance(rol, dict):
        number = str(rol.get("numero", "")).strip()
        dv = str(rol.get("DV") or rol.get("dv") or "").strip().upper()
    else:
        flat = claims.get("run") or claims.get("rut") or claims.get("RUN")
        if flat:
            cleaned = str(flat).replace(".", "").replace("-", "").strip().upper()
            if len(cleaned) >= 2:
                number, dv = cleaned[:-1], cleaned[-1]

    if not number or not dv or not number.isdigit():
        raise ClaveUnicaError(
            "La respuesta de ClaveÚnica no incluye un RUN utilizable."
        )

    expected = _run_check_digit(int(number))
    if dv != expected:
        raise ClaveUnicaError("El RUN recibido tiene un dígito verificador inválido.")

    return f"{int(number)}-{dv}"


def subject_key_for(run: str) -> str:
    """Índice ciego del RUN. Es lo ÚNICO que sale de aquí sobre la persona.

    Mismo pepper y misma separación de dominio que el resto de índices
    ciegos, así que rota con `pii_maintenance.py reindex-lookups`.
    """
    return lookup_key(run, domain="clave-unica-run")


class LoginAlreadyCompleted(RuntimeError):
    """El intento ya terminó: hay un grant emitido para este mismo flujo."""

    def __init__(self, grant: str, name: str):
        super().__init__("El intento de inicio de sesión ya se completó.")
        self.grant = grant
        self.name = name


class LoginInProgress(RuntimeError):
    """Otro callback del mismo flujo está en curso ahora mismo."""


async def remember_issued_grant(state: str, grant: str, name: str) -> None:
    """Guarda el grant CIFRADO para poder repetir la respuesta.

    Requisito de idempotencia: si la respuesta HTTP se pierde, el navegador
    reintenta y debe recibir EL MISMO grant, no otro —eso duplicaría
    identidades— ni un 401 —eso dejaría a la persona sin credencial y sin
    forma de obtenerla—.

    Se cifra en reposo por la misma razón que los grants solo se persisten
    como digest: quien lea la base no debe poder canjear el de nadie. Aquí
    hace falta el valor, no un digest, así que se cifra con la llave de PII.
    """
    from ..core.crypto import encrypt

    await login_sessions_collection().update_one(
        {"state": state},
        {
            "$set": {
                "issued_grant": encrypt(grant),
                "issued_name": name,
                "completed_at": datetime.now(timezone.utc),
            }
        },
    )


async def _replay_issued_grant(session: dict) -> None:
    """Repite el grant del intento si sigue vigente. Lanza si corresponde."""
    from ..core.crypto import decrypt
    from . import identity_grant

    stored = session.get("issued_grant")
    if not stored:
        # Consumido pero sin grant guardado: hay otro callback a mitad de
        # camino. Decirlo es más honesto que devolver "no existe".
        raise LoginInProgress(
            "Este inicio de sesión ya se está completando. Espera un momento."
        )

    try:
        grant = decrypt(stored)
    except ValueError as exc:
        raise ClaveUnicaError(
            "No se pudo recuperar el grant de este intento; vuelve a empezar."
        ) from exc

    record = await identity_grant.identity_grants_collection().find_one(
        {"digest": identity_grant.digest(grant)}
    )
    grant_expires_at = _as_utc(record.get("expires_at")) if record else None
    if (
        not record
        or record.get("consumed")
        or (grant_expires_at and grant_expires_at <= datetime.now(timezone.utc))
    ):
        # El grant ya se canjeó o caducó. Devolverlo otra vez sería entregar
        # algo que no sirve; emitir uno nuevo sin volver a autenticar sería
        # peor.
        raise ClaveUnicaError(
            "La credencial de este inicio de sesión ya se emitió o caducó. "
            "Vuelve a identificarte con ClaveÚnica."
        )

    raise LoginAlreadyCompleted(grant, session.get("issued_name", ""))


async def complete_login(code: str, state: str, binding: Optional[str]) -> dict:
    """Cierra el flujo: binding, canje, validación, RUN y grant.

    Devuelve `{subject_key, assurance_level, name}`; el grant lo emite el
    router, que es quien conoce el servicio de grants.
    """
    import asyncio

    _require_configuration()
    if not code:
        raise ClaveUnicaError("Falta el código de autorización.")

    # PRIMERO el binding: sin la cookie correcta no se habla con el proveedor
    # ni se gasta el código de autorización.
    session = await _load_login_session(state, binding)

    if session.get("consumed"):
        await _replay_issued_grant(session)

    claimed = await _claim_login_session(state, session["browser_binding"])
    if claimed is None:
        # Alguien lo consumió entre la lectura y la reclamación: se vuelve a
        # mirar por si ya dejó un grant que repetir.
        refreshed = await login_sessions_collection().find_one({"state": state})
        await _replay_issued_grant(refreshed or {})
    session = claimed

    try:
        tokens = await asyncio.to_thread(_exchange_code, code, session["code_verifier"])
    except ClaveUnicaError:
        raise
    except Exception as exc:
        # Red, DNS, TLS, timeouts: nada de esto es culpa de quien inicia
        # sesión, y ninguno debe salir como un 500 opaco.
        logger.error("Fallo hablando con ClaveÚnica (%s)", type(exc).__name__)
        raise ClaveUnicaProviderError(
            "El proveedor de identidad no respondió. Intenta de nuevo en unos minutos."
        ) from exc

    id_token = tokens.get("id_token")
    if not id_token:
        raise ClaveUnicaProviderError("El proveedor no devolvió un id_token.")

    claims = await asyncio.to_thread(validate_id_token, id_token, session["nonce"])

    try:
        run = extract_run(claims)
    except ClaveUnicaError:
        access_token = tokens.get("access_token")
        if not access_token:
            raise
        # El RUN puede venir solo en UserInfo según el scope concedido.
        userinfo = await asyncio.to_thread(_fetch_userinfo, access_token)
        if userinfo.get("sub") and userinfo["sub"] != claims["sub"]:
            # Mezclar dos sujetos distintos acreditaría a la persona
            # equivocada. Es un fallo grave del proveedor o un ataque.
            raise ClaveUnicaError(
                "El sujeto de UserInfo no coincide con el del id_token."
            )
        run = extract_run(userinfo)

    # A partir de aquí el RUN ya no viaja: solo su índice ciego.
    logger.info("ClaveÚnica autenticó a un ciudadano (RUN no registrado)")
    return {
        "subject_key": subject_key_for(run),
        "assurance_level": ASSURANCE_LEVEL,
        "name": claims.get("name") or "",
        # El router ata el grant a este mismo navegador y recuerda el
        # resultado para poder repetirlo si la respuesta se pierde.
        "browser_binding": session["browser_binding"],
        "state": state,
    }


def status() -> dict:
    """Contrato que el frontend exige literalmente antes de redirigir.

    Cada campo describe una garantía que este backend cumple de verdad; si
    alguna dejara de cumplirse habría que bajar la bandera, no maquillarla.
    """
    return {
        "available": is_configured(),
        "protocol_version": PROTOCOL_VERSION,
        "pkce_method": "S256",
        # El canje exige la cookie HttpOnly fijada en /authorize.
        "browser_bound": True,
        # …y /identity-credential exige la misma cookie más el binding del
        # grant, además de SIWE y CSRF.
        "credential_exchange_browser_bound": True,
        # Repetir un callback del mismo flujo devuelve el mismo grant vigente.
        "callback_idempotent": True,
        "grant_single_use": True,
        # El Estado redirige al frontend, que hace POST de code+state: nunca
        # viaja un grant por la URL.
        "redirect_transport": "frontend-post",
        "grant_ttl_seconds": settings.IDENTITY_GRANT_TTL_SECONDS,
    }
