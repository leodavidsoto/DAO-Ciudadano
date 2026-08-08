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

Replay: por qué la Pasiva sola no bastaba
-----------------------------------------
La Autenticación Pasiva demuestra que los datos los firmó Chile. NO demuestra
que el chip esté presente ahora. Quien consiga los bytes de un SOD y sus DG
—leyendo la cédula ajena con el CAN, o interceptando un payload— puede
reenviarlos y obtener un grant para ESE titular.

Eso lo cierra la **Autenticación Activa** (`active_auth`): el chip firma un
desafío que emite el servidor y que solo vale una vez (`aa_challenge`). Una
captura completa —SOD, data groups, desafío y firma— no sirve dos veces: el
desafío ya está quemado, y para el siguiente haría falta la clave privada del
chip, que no se puede extraer.

Los dos niveles que emite este módulo dicen exactamente qué se comprobó:

  * ``CEDULA_NFC_PASSIVE`` — el documento es auténtico. No prueba presencia
    del chip, y por tanto sigue siendo replicable por quien capture los bytes.
  * ``CEDULA_NFC_ACTIVE``  — además, el chip respondió a un desafío nuestro.

En producción solo se admite el segundo (`settings.cedula_requires_active_auth`):
mientras el camino pasivo pueda producir un grant, el agujero sigue abierto
para quien lo use. Es una decisión de política y está donde se puede leer, no
escondida en un `if`.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from dataclasses import dataclass
from typing import Mapping, Optional

from ..core.config import settings
from ..core.identity import lookup_key
from . import active_auth as active_auth_module
from . import mrz as mrz_module
from . import passive_auth

logger = logging.getLogger(__name__)

PROVIDER_NAME = "cedula-nfc"

#: Autenticación Pasiva y nada más: el documento es auténtico, pero nadie
#: demostró que el chip estuviera presente. El nombre lo dice para que el
#: consumidor del grant pueda decidir con esa información delante.
ASSURANCE_LEVEL_PASSIVE = "CEDULA_NFC_PASSIVE"

#: Pasiva + Activa: además del documento auténtico, el chip firmó un desafío
#: del servidor que solo valía una vez.
ASSURANCE_LEVEL_ACTIVE = "CEDULA_NFC_ACTIVE"

#: EF.DG15 (clave pública de AA) y EF.DG14 (SecurityInfos, que declara el hash
#: cuando la clave es ECDSA). Van dentro de `data_groups` a propósito: así la
#: Autenticación Pasiva comprueba su hash contra el SOD como el de cualquier
#: otro archivo, y la clave de AA queda ligada a la firma del Registro Civil.
DG_ACTIVE_AUTH_PUBLIC_KEY = 15
DG_SECURITY_INFOS = 14

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
class ActiveAuthentication:
    """Respuesta del chip a un desafío ya resuelto por el servidor.

    El desafío llega en BYTES, no como el identificador que mandó el cliente:
    quien construye esto tiene que haberlo consumido antes contra
    `aa_challenge`. Si este dato pudiera venir del cliente, la Autenticación
    Activa no probaría nada — firmaría un desafío de su elección.
    """

    challenge: bytes
    signature: bytes


@dataclass(frozen=True)
class VerifiedCedula:
    #: Índice ciego derivado del RUN. Es lo único que sale de aquí y que
    #: identifica a la persona.
    subject_key: str
    document_number: str
    expires_on: str
    #: `CEDULA_NFC_PASSIVE` o `CEDULA_NFC_ACTIVE`, según lo que se comprobó.
    assurance_level: str
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


def describe_field_shape(value: str) -> str:
    """Describe un campo de la MRZ sin revelar su contenido (AUDIT P-101).

    Cada carácter se sustituye por su clase —`D` dígito, `A` letra, `<` relleno,
    `?` cualquier otra cosa— de modo que la salida distingue «nueve dígitos» de
    «vacío» o de «ocho dígitos y una letra», que es exactamente lo que hace
    falta para saber qué trae el campo, sin que el RUN llegue a ningún log.
    """
    mask = "".join(
        (
            "D"
            if char.isdigit()
            else "A" if char.isalpha() else "<" if char == "<" else "?"
        )
        for char in value or ""
    )
    return f"len={len(value or '')} {mask}"


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


def _verify_active_authentication(
    groups: Mapping[int, bytes],
    result: passive_auth.PassiveAuthResult,
    active: ActiveAuthentication,
) -> dict:
    """Comprueba que el chip firmó NUESTRO desafío con la clave que firmó Chile.

    Las dos mitades tienen que darse. La firma sola no prueba nada: un atacante
    que fabricara un DG15 con su propia clave pública firmaría el desafío
    perfectamente. Lo que convierte esa firma en identidad es que el hash del
    DG15 esté declarado en el EF.SOD — y eso lo comprueba la Autenticación
    Pasiva, que ya corrió sobre TODOS los data groups recibidos.

    Por eso aquí se exige que 15 aparezca entre `verified_data_groups` y no
    basta con que venga en la lectura: sin esa comprobación, la Autenticación
    Activa sería un teatro caro.
    """
    dg15 = groups.get(DG_ACTIVE_AUTH_PUBLIC_KEY)
    if dg15 is None:
        raise CedulaVerificationError(
            "La lectura trae una firma de Autenticación Activa pero no el "
            "EF.DG15 con el que comprobarla."
        )
    if DG_ACTIVE_AUTH_PUBLIC_KEY not in result.verified_data_groups:
        # No debería poder ocurrir —`passive_auth.verify` lanza antes de
        # llegar aquí si un DG recibido no cuadra con el SOD—, pero la
        # afirmación es el punto entero de la Autenticación Activa y no se
        # deja depender de que otro módulo siga comportándose igual mañana.
        raise CedulaVerificationError(
            "El EF.DG15 no quedó respaldado por la firma del EF.SOD: la clave "
            "pública del chip no la puso el Registro Civil."
        )

    dg14 = groups.get(DG_SECURITY_INFOS)
    if dg14 is not None and DG_SECURITY_INFOS not in result.verified_data_groups:
        raise CedulaVerificationError(
            "El EF.DG14 no quedó respaldado por la firma del EF.SOD."
        )

    try:
        outcome = active_auth_module.verify(
            dg15=dg15,
            challenge=active.challenge,
            signature=active.signature,
            dg14=dg14,
        )
    except active_auth_module.ActiveAuthError as exc:
        raise CedulaVerificationError(str(exc)) from exc

    return outcome.as_dict()


def verify_reading(
    sod: str,
    data_groups: Mapping[str, str],
    active: Optional[ActiveAuthentication] = None,
) -> VerifiedCedula:
    """Verifica una lectura NFC completa y devuelve el sujeto ciego.

    Lanza `CedulaVerificationError` en cuanto algo falla. No hay ningún camino
    que devuelva un `VerifiedCedula` sin haber pasado las cinco condiciones —
    ni, cuando la política lo exige, sin Autenticación Activa.
    """
    sod_der = _decode(sod, "el EF.SOD")
    groups = _decode_data_groups(data_groups)

    if active is None and settings.cedula_requires_active_auth:
        # Antes de gastar trabajo criptográfico: en este despliegue una lectura
        # sin Autenticación Activa no puede producir un grant, venga como venga.
        raise CedulaVerificationError(
            "Este servidor exige Autenticación Activa: el chip tiene que firmar "
            "un desafío del servidor. Una lectura sin ella no acredita que la "
            "cédula esté presente, solo que alguien tuvo sus datos alguna vez."
        )

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
    # `national_number` sabe en qué campo lo pone cada formato de MRZ.
    #
    # El dígito verificador es lo que confirma que el campo es el correcto: si
    # estuviéramos leyendo otra cosa de nueve dígitos —el número de documento,
    # por ejemplo— sólo cuadraría una vez de cada once.
    try:
        run = normalize_run(mrz.national_number)
    except CedulaVerificationError:
        # Diagnóstico temporal (AUDIT P-101). Contra una cédula chilena real
        # este campo no contiene lo que `mrz.py` supone, y sin saber QUÉ trae
        # no se puede decidir entre leer DG11/DG13, ajustar el corte de la
        # línea 1, o descartar un dígito de control sobrante.
        #
        # Se registra la FORMA, nunca el valor: longitud y máscara de clases.
        # Un RUN sigue siendo un identificador civil y no entra en un log ni
        # para depurar. Borrar esto en cuanto se sepa la respuesta.
        logger.warning(
            "El campo opcional de la MRZ no expone un RUN reconocible "
            "(formato: %s | opcional-1: %s | opcional-2: %s | documento: %s)",
            mrz.format,
            describe_field_shape(mrz.optional_data),
            describe_field_shape(mrz.optional_data_2),
            describe_field_shape(mrz.document_number),
        )
        raise

    verification = result.as_dict()
    assurance_level = ASSURANCE_LEVEL_PASSIVE
    if active is not None:
        verification["active_authentication"] = _verify_active_authentication(
            groups, result, active
        )
        assurance_level = ASSURANCE_LEVEL_ACTIVE

    # Nunca se registra el RUN ni el número de documento.
    logger.info(
        "Cédula verificada (%s, ancla: %s)",
        assurance_level,
        result.trust_anchor_subject,
    )

    return VerifiedCedula(
        subject_key=lookup_key(run, SUBJECT_DOMAIN),
        document_number=mrz.document_number,
        expires_on=mrz.date_of_expiry,
        assurance_level=assurance_level,
        verification=verification,
    )
