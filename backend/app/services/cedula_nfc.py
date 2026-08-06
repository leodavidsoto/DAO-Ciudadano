"""
La cédula chilena como proveedor de identidad civil (ROADMAP 5.8).

Este módulo es lo que convierte una lectura NFC en un grant civil. Antes, el
móvil verificaba el documento y mandaba `identityVerified: true`; el backend
se lo creía. Ahora el backend recibe los BYTES del chip, repite la
Autenticación Pasiva completa (`passive_auth`) y sólo entonces emite un grant.
La diferencia práctica: antes bastaba un `curl`.

Qué tiene que cumplir un documento para producir un grant — todo, no la
mayoría:

  1. Autenticación Pasiva válida contra una CSCA del Registro Civil
     (firma del SOD, messageDigest, hashes de DG1/DG2, cadena de confianza).
  2. Emitido por Chile y con nacionalidad chilena en la MRZ.
  3. Cédula de identidad, no pasaporte ni otro documento de viaje.
  4. No caducado.
  5. Con un número nacional (RUN) legible en la MRZ, que es lo que identifica
     establemente a la persona entre renovaciones del documento.

El `subject_key` se deriva del RUN con el pepper del servidor, igual que el
resto del sistema: es un índice ciego. El RUN en claro no se guarda, no se
registra y no sale de esta función.

Riesgo declarado, no mitigado: replay
-------------------------------------
La Autenticación Pasiva demuestra que los datos los firmó Chile. NO demuestra
que el chip esté presente ahora. Quien consiga los bytes de un SOD y sus DG
—leyendo la cédula ajena con el CAN, o interceptando un payload— puede
reenviarlos y obtener un grant para ESE titular. Lo que cierra ese hueco es la
Autenticación Activa o Chip Authentication, donde el chip firma un desafío
nuestro; no está implementada (ni en el móvil ni aquí).

Lo que sí acota el daño hoy: el `subject_key` es el del titular del documento,
no el de quien envía. Un replay no crea una identidad nueva ni permite
duplicar la de nadie —el árbol de identidades es idempotente por sujeto—, así
que el ataque se reduce a suplantar a una persona concreta cuyo documento ya
se leyó físicamente. Sigue siendo grave y sigue abierto: está en el ROADMAP,
no disimulado detrás de un booleano.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from dataclasses import dataclass
from typing import Mapping, Optional

from ..core.identity import lookup_key
from . import mrz as mrz_module
from . import passive_auth

logger = logging.getLogger(__name__)

PROVIDER_NAME = "cedula-nfc"

# Dominio propio para el índice ciego: el mismo RUN nunca debe producir la
# misma clave aquí y en `lookup_key(rut)` del registro por formulario.
SUBJECT_DOMAIN = "cl-cedula-nfc-run"

# Tamaño máximo por archivo. Un DG2 con foto ronda los 20 KB; el margen es
# amplio, pero un límite explícito evita que alguien use este endpoint para
# hacer trabajo criptográfico arbitrario con megabytes de basura.
MAX_FILE_BYTES = 128 * 1024
MAX_DATA_GROUPS = 16

#: RUN completo: cuerpo de 6 a 8 dígitos más su verificador. El verificador se
#: exige siempre —un RUN sin él no es un RUN— porque es lo único que permite
#: comprobar que el campo del que se extrajo era el correcto.
_RUN_PATTERN = re.compile(r"^(?P<body>[0-9]{6,8})-?(?P<check>[0-9K])$")


class CedulaVerificationError(RuntimeError):
    """El documento no supera la verificación. `reasons` explica por qué."""

    def __init__(self, message: str, reasons: Optional[list[str]] = None):
        super().__init__(message)
        self.reasons = reasons or [message]


@dataclass(frozen=True)
class VerifiedCedula:
    #: Índice ciego derivado del RUN. Es lo único que sale de aquí y que
    #: identifica a la persona.
    subject_key: str
    document_number: str
    expires_on: str
    #: Detalle criptográfico para auditoría. Sin datos del titular.
    verification: dict


def _decode(value: str, label: str) -> bytes:
    if not isinstance(value, str) or not value.strip():
        raise CedulaVerificationError(f"Falta {label} en la lectura enviada.")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise CedulaVerificationError(f"{label} no viene en base64 válido.") from None
    if not raw:
        raise CedulaVerificationError(f"{label} llegó vacío.")
    if len(raw) > MAX_FILE_BYTES:
        raise CedulaVerificationError(
            f"{label} supera el tamaño máximo admitido ({MAX_FILE_BYTES} bytes)."
        )
    return raw


def _decode_data_groups(data_groups: Mapping[str, str]) -> dict[int, bytes]:
    if not isinstance(data_groups, Mapping) or not data_groups:
        raise CedulaVerificationError("La lectura no incluye ningún data group.")
    if len(data_groups) > MAX_DATA_GROUPS:
        raise CedulaVerificationError("La lectura incluye demasiados data groups.")

    decoded: dict[int, bytes] = {}
    for key, value in data_groups.items():
        label = str(key).strip().upper().removeprefix("DG")
        try:
            number = int(label)
        except ValueError:
            raise CedulaVerificationError(
                f"«{key}» no identifica a ningún data group."
            ) from None
        if not 1 <= number <= 16:
            raise CedulaVerificationError(f"DG{number} no existe en un eMRTD.")
        decoded[number] = _decode(value, f"DG{number}")
    return decoded


def normalize_run(value: str) -> str:
    """Normaliza el RUN y comprueba su dígito verificador.

    Se valida el módulo 11 porque el RUN es la entrada de la que se deriva la
    identidad entera de la persona en este sistema. Si el campo de la MRZ del
    que se extrae no fuera el que creemos, casi con seguridad no cuadraría el
    dígito — y es mucho mejor fallar aquí que emitir credenciales ligadas a un
    número que no identifica a nadie.
    """
    # El guion NO se quita antes de comparar: sin él, "123456785" es ambiguo
    # —cuerpo de 9 dígitos, o de 8 más verificador— y quedarse con la lectura
    # equivocada derivaría dos identidades distintas para la misma persona
    # según cómo viniera escrito el mismo número.
    cleaned = re.sub(r"[.\s]", "", (value or "")).upper()
    match = _RUN_PATTERN.match(cleaned)
    if not match:
        raise CedulaVerificationError(
            "La MRZ del documento no expone un RUN reconocible. No se deriva "
            "una identidad de un campo que no se sabe interpretar."
        )

    body = match.group("body")
    check = match.group("check")
    if _run_check_digit(body) != check:
        raise CedulaVerificationError(
            "El RUN leído del documento no supera su dígito verificador."
        )
    # Canónico y sin ceros a la izquierda: el mismo RUN escrito de dos formas
    # tiene que producir el mismo `subject_key`.
    return f"{body.lstrip('0')}-{check}"


def _run_check_digit(body: str) -> str:
    total = 0
    factor = 2
    for digit in reversed(body):
        total += int(digit) * factor
        factor = 2 if factor == 7 else factor + 1
    remainder = 11 - (total % 11)
    if remainder == 11:
        return "0"
    if remainder == 10:
        return "K"
    return str(remainder)


def verify_reading(sod: str, data_groups: Mapping[str, str]) -> VerifiedCedula:
    """Verifica una lectura NFC completa y devuelve el sujeto ciego.

    Lanza `CedulaVerificationError` en cuanto algo falla. No hay ningún camino
    que devuelva un `VerifiedCedula` sin haber pasado las cinco condiciones.
    """
    sod_der = _decode(sod, "el EF.SOD")
    groups = _decode_data_groups(data_groups)

    # 1. Autenticación Pasiva. Es lo primero: sin ella, los datos del DG1 no
    #    son más que bytes que alguien envió.
    try:
        result = passive_auth.verify(sod_der, groups)
    except passive_auth.PassiveAuthError as exc:
        raise CedulaVerificationError(str(exc), exc.reasons) from exc

    # 2-5. Ahora el DG1 ya está respaldado por la firma del Registro Civil.
    try:
        mrz = mrz_module.parse(groups[1])
    except mrz_module.MRZError as exc:
        raise CedulaVerificationError(
            f"El documento está firmado por Chile pero su MRZ no se puede leer: {exc}"
        ) from exc

    reasons: list[str] = []
    if not mrz.is_chilean:
        reasons.append(
            f"El documento lo emitió «{mrz.issuing_state or '?'}», no Chile."
        )
    if not mrz.is_identity_card:
        reasons.append(
            "Sólo se admite la cédula de identidad chilena; este documento es "
            f"de tipo «{mrz.document_code or '?'}»."
        )
    if mrz.is_expired():
        reasons.append("El documento está caducado.")
    if reasons:
        raise CedulaVerificationError(reasons[0], reasons)

    # El RUN, no el número de documento: el número cambia en cada renovación y
    # usarlo daría a la misma persona una identidad nueva con cada cédula.
    run = normalize_run(mrz.optional_data)

    # Nunca se registra el RUN ni el número de documento.
    logger.info(
        "Cédula verificada por Autenticación Pasiva (ancla: %s)",
        result.trust_anchor_subject,
    )

    return VerifiedCedula(
        subject_key=lookup_key(run, SUBJECT_DOMAIN),
        document_number=mrz.document_number,
        expires_on=mrz.date_of_expiry,
        verification=result.as_dict(),
    )
