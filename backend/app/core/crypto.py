"""
Cifrado de PII en reposo, con rotación de llaves (ROADMAP 1.3 / 1.4).

Antes: rut/email/nombre/apellido se guardaban en texto plano en MongoDB.
Cualquiera con acceso de lectura (backup, snapshot, empleado del hosting)
veía datos personales de ciudadanos chilenos sin ninguna barrera.

Después: Fernet (AES-128-CBC + HMAC-SHA256) sobre cada campo sensible, con
`PII_ENCRYPTION_KEY` como llave simétrica única. Eso protegía el volcado,
pero dejaba un problema abierto: **una llave que no se puede rotar es una
llave para siempre**. Si se filtraba, la única salida era descifrar y volver
a cifrar todo a mano, con la aplicación parada.

Ahora: `PII_ENCRYPTION_KEYS` admite varias llaves separadas por comas, de la
más nueva a la más vieja.

    PII_ENCRYPTION_KEYS=<nueva>,<anterior>

* Se **cifra** siempre con la primera.
* Se **descifra** con cualquiera de ellas (MultiFernet).

Así, publicar la llave nueva no invalida ni un solo registro existente, y
`scripts/pii_maintenance.py rotate` los reescribe con la nueva sin parar el
servicio. Cuando `status` reporta 0 registros con llave antigua, la vieja se
retira de la variable y deja de existir operativamente.

Sobre KMS
─────────
Esto NO es un KMS. Las llaves siguen viviendo en variables de entorno del
proceso: quien pueda leer el entorno del servidor puede leerlas. Lo que sí
queda resuelto es la mecánica de rotación, que era el bloqueo real para
adoptar un KMS después. `_load_keys()` es el único punto que materializa las
llaves; una implementación contra AWS KMS o GCP KMS entra ahí sin tocar el
resto del código. Mientras eso no exista, la custodia de llaves NO está
resuelta y no debe declararse como tal.

Falla cerrado: sin ninguna llave válida y DEBUG=False, encrypt()/decrypt()
lanzan EncryptionKeyMissing.
"""

import base64
import hashlib
from typing import List

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .config import settings


class EncryptionKeyMissing(RuntimeError):
    """No hay ninguna llave de PII configurada y DEBUG=False (fail closed)."""


# Llave de DESARROLLO, determinística a propósito (P-47).
#
# Antes se generaba con `Fernet.generate_key()` al importar el módulo, o sea
# una distinta POR PROCESO. Con `--reload` o varios workers, lo que cifraba un
# proceso no lo podía descifrar otro: el nombre del ciudadano volvía como
# `None` sin ningún error que explicara por qué.
#
# Derivarla de una constante fija hace que todos los procesos locales
# compartan la misma. El valor es obviamente de desarrollo y está en el
# repositorio a la vista: NO es un secreto, y por eso solo se usa cuando no
# hay ninguna llave configurada Y `DEBUG` está activo. `key_status()` no la
# cuenta, así que readiness sigue bloqueando producción por falta de llave.
_DEV_ONLY_SEED = b"dao-ciudadana::dev-only::insecure-pii-key::do-not-use-in-production"
_DEV_ONLY_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(_DEV_ONLY_SEED).digest()
).decode("ascii")


def _configured_keys() -> List[str]:
    """Llaves declaradas, de la más nueva a la más vieja, sin validar.

    `PII_ENCRYPTION_KEY` (singular) se mantiene por compatibilidad: los
    despliegues existentes no tienen que renombrar nada para seguir
    funcionando. Si aparece en las dos variables, no se duplica.
    """
    raw: List[str] = []
    for candidate in settings.PII_ENCRYPTION_KEYS.split(","):
        candidate = candidate.strip()
        if candidate:
            raw.append(candidate)

    legacy = settings.PII_ENCRYPTION_KEY.strip()
    if legacy and legacy not in raw:
        # Al final: si alguien declara ambas, la nueva manda para cifrar y la
        # antigua solo sirve para descifrar lo que aún no se rotó.
        raw.append(legacy)
    return raw


def _load_keys() -> List[Fernet]:
    """Único punto que materializa las llaves. Aquí entraría un KMS."""
    keys: List[Fernet] = []
    for value in _configured_keys():
        try:
            keys.append(Fernet(value.encode("utf-8")))
        except (TypeError, ValueError):
            # Una llave malformada no puede tumbar a las demás, pero tampoco
            # se ignora en silencio: `key_status()` la reporta y readiness la
            # ve.
            continue

    if keys:
        return keys

    if settings.DEBUG:
        return [Fernet(_DEV_ONLY_KEY.encode("utf-8"))]

    raise EncryptionKeyMissing(
        "No hay ninguna PII_ENCRYPTION_KEY(S) válida configurada. Sin ella no "
        "se puede cifrar ni descifrar PII de forma segura."
    )


def _multi() -> MultiFernet:
    return MultiFernet(_load_keys())


def generate_key() -> str:
    """Genera una llave Fernet nueva (para configurar PII_ENCRYPTION_KEYS)."""
    return Fernet.generate_key().decode("utf-8")


def encrypt(plaintext: str) -> str:
    """Cifra SIEMPRE con la llave primaria (la primera de la lista)."""
    if plaintext is None:
        return None
    return _multi().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    """Descifra con cualquiera de las llaves configuradas."""
    if ciphertext is None:
        return None
    try:
        return _multi().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "No se pudo descifrar el valor (llave incorrecta o dato corrupto)"
        ) from exc


def is_current(ciphertext: str) -> bool:
    """¿Está cifrado con la llave primaria?

    Es lo que permite saber cuánto queda por rotar: MultiFernet no dice con
    cuál de las llaves consiguió descifrar.
    """
    if ciphertext is None:
        return True
    primary = _load_keys()[0]
    try:
        primary.decrypt(ciphertext.encode("utf-8"))
        return True
    except InvalidToken:
        return False


def rotate(ciphertext: str) -> str:
    """Re-cifra un valor con la llave primaria sin exponer el texto plano.

    `MultiFernet.rotate` descifra con la llave que corresponda y vuelve a
    cifrar con la primaria en una sola operación.
    """
    if ciphertext is None:
        return None
    try:
        return _multi().rotate(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "No se pudo rotar el valor: ninguna llave configurada lo descifra"
        ) from exc


def fingerprint(key: str) -> str:
    """Identificador corto y no reversible de una llave.

    Permite que un operador confirme QUÉ llaves cargó el proceso (y que
    coinciden con las del gestor de secretos) sin que el valor aparezca en
    los logs, en `/health/ready` ni en una captura de pantalla.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def key_status() -> dict:
    """Estado de las llaves, para readiness y para el script de mantenimiento."""
    configured = _configured_keys()
    valid: List[str] = []
    invalid = 0
    for value in configured:
        try:
            Fernet(value.encode("utf-8"))
            valid.append(value)
        except (TypeError, ValueError):
            invalid += 1

    return {
        "configured": len(configured),
        "usable": len(valid),
        "invalid": invalid,
        "primary": fingerprint(valid[0]) if valid else None,
        # Las secundarias existen solo para descifrar lo que aún no se rotó.
        "secondary": [fingerprint(v) for v in valid[1:]],
        "rotation_in_progress": len(valid) > 1,
    }
