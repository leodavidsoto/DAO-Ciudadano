"""
Autenticación Activa del eMRTD (ICAO 9303-11 §6.1, ROADMAP 5.8).

Qué prueba, y por qué la Pasiva no basta
----------------------------------------
La Autenticación Pasiva demuestra que el Registro Civil firmó esos datos. No
demuestra que el chip esté presente: quien consiga los bytes de un SOD y sus
data groups —leyendo la cédula ajena con el CAN, o interceptando un payload—
puede reenviarlos y obtener un grant a nombre de otro.

La Autenticación Activa cierra eso. El chip guarda una clave privada que no
puede extraerse y firma con ella un desafío que elige el SERVIDOR. Una captura
de tráfico no sirve: el desafío siguiente será otro, y sin la clave del chip no
hay forma de firmarlo.

Las dos mitades tienen que estar las dos
----------------------------------------
Este módulo verifica la firma contra la clave pública de EF.DG15. Por sí sola
esa comprobación no vale nada: un atacante pondría su propia clave en un DG15
inventado y firmaría con la suya. Lo que la hace válida es que el hash de DG15
esté declarado en el EF.SOD y coincida — es decir, que la clave la haya puesto
Chile. Esa segunda mitad NO vive aquí: la hace `passive_auth._verify_data_groups`
sobre todos los data groups recibidos, y `cedula_nfc` exige que DG15 aparezca
entre los verificados antes de llamar a este módulo.

Por qué no vale PKCS#1 v1.5
---------------------------
La AA de un eMRTD con clave RSA usa **ISO/IEC 9796-2 Digital Signature Scheme
1**, con recuperación de mensaje: el chip no firma un hash envuelto en el
padding de PKCS#1, sino un representante `F` que contiene una parte aleatoria
del propio chip (M1), el hash de `M1 || desafío`, y un tráiler. Verificarlo con
PKCS1v15 no rechaza documentos falsos: rechaza TODOS los documentos, incluidos
los auténticos. Una implementación así puede tener sus tests en verde y no
haber validado jamás una cédula.

Lo que este módulo NO hace
--------------------------
* **Chip Authentication (EAC).** Es la otra vía de ICAO contra el clonado, y
  además cifra el canal. No está implementada; la AA no la sustituye.
* **Detección de clonado.** La AA prueba que la clave privada del chip está
  presente. Si alguien extrajera esa clave de un chip real (ataque físico,
  invasivo), podría fabricar un clon que pasara la AA.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from asn1crypto import core
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes as crypto_hashes
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

#: EF.DG15 envuelve la SubjectPublicKeyInfo en un TLV `[APPLICATION 15]`.
DG15_TAG = 0x6F
#: EF.DG14 envuelve los SecurityInfos en un TLV `[APPLICATION 14]`.
DG14_TAG = 0x6E

#: id-icao-mrtd-security-aaProtocolObject (ICAO 9303-11, ActiveAuthenticationInfo).
ACTIVE_AUTHENTICATION_INFO_OID = "2.23.136.1.1.5"

#: El desafío de la Autenticación Activa son 8 bytes: es el tamaño que el chip
#: espera en el campo de datos de INTERNAL AUTHENTICATE (ICAO 9303-11 §6.1).
CHALLENGE_BYTES = 8

#: Identificadores de función de hash del tráiler de ISO/IEC 9796-2 (los
#: asigna ISO/IEC 10118-3). Solo se listan los que este módulo sabe calcular:
#: un tráiler que declare RIPEMD o Whirlpool se rechaza diciendo por qué, en
#: vez de verificarse contra otro hash.
_TRAILER_HASHES = {
    0x33: "sha1",
    0x34: "sha256",
    0x35: "sha512",
    0x36: "sha384",
    0x38: "sha224",
}

#: Tráiler implícito. ICAO 9303-11 §6.1.1: cuando el tráiler es un solo byte
#: `0xBC`, la función de hash es SHA-1.
_IMPLICIT_TRAILER = 0xBC
_IMPLICIT_TRAILER_HASH = "sha1"

#: OIDs de firma ECDSA en formato plano (r||s) de BSI TR-03111, que son los que
#: ICAO 9303-11 admite en `ActiveAuthenticationInfo.signatureAlgorithm`.
_ECDSA_PLAIN_HASHES = {
    "0.4.0.127.0.7.1.1.4.1.1": "sha1",
    "0.4.0.127.0.7.1.1.4.1.2": "sha224",
    "0.4.0.127.0.7.1.1.4.1.3": "sha256",
    "0.4.0.127.0.7.1.1.4.1.4": "sha384",
    "0.4.0.127.0.7.1.1.4.1.5": "sha512",
}

#: Anotado como factoría y no como `type[HashAlgorithm]` porque el join de las
#: clases concretas es la base abstracta, y mypy rechaza instanciarla.
_CRYPTO_HASHES: Dict[str, Callable[[], crypto_hashes.HashAlgorithm]] = {
    "sha1": crypto_hashes.SHA1,
    "sha224": crypto_hashes.SHA224,
    "sha256": crypto_hashes.SHA256,
    "sha384": crypto_hashes.SHA384,
    "sha512": crypto_hashes.SHA512,
}


class ActiveAuthError(RuntimeError):
    """La Autenticación Activa no se pudo comprobar, o no verifica."""


class ActiveAuthUnsupported(ActiveAuthError):
    """El documento no admite Autenticación Activa (no trae DG15).

    Se distingue de un fallo de verificación porque la respuesta correcta es
    distinta: un documento sin DG15 no es un documento falso. Quien decide qué
    hacer con esto es la política de `cedula_nfc`, no este módulo.
    """


@dataclass(frozen=True)
class ActiveAuthResult:
    """Qué se comprobó. Sin datos del titular: una clave pública y un algoritmo."""

    #: "rsa-iso9796-2-ds1" o "ecdsa-plain".
    scheme: str
    #: Hash con el que se verificó, tal como lo declaró el documento.
    digest_algorithm: str
    #: Tamaño de la clave del chip, en bits.
    key_bits: int
    #: SHA-256 del EF.DG15 recibido. Liga este resultado a un documento
    #: concreto sin volver a manejar sus bytes.
    dg15_sha256: str

    def as_dict(self) -> dict:
        return {
            "scheme": self.scheme,
            "digest_algorithm": self.digest_algorithm,
            "key_bits": self.key_bits,
            "dg15_sha256": self.dg15_sha256,
        }


# ---------------------------------------------------------------------------
# TLV de los data groups
# ---------------------------------------------------------------------------


def _unwrap(raw: bytes, tag: int, label: str) -> bytes:
    """Quita el TLV exterior de un data group.

    Igual que en `passive_auth._unwrap_ef_sod`, se acepta tanto el archivo tal
    como sale del chip como el contenido ya desenvuelto: cuál de los dos llega
    depende de la librería del cliente, y obligar al móvil a manipular ASN.1
    antes de enviarlo pone más código en el lado no confiable sin ganar nada.
    """
    if not raw:
        raise ActiveAuthError(f"{label} llegó vacío.")
    if raw[0] != tag:
        return raw

    offset = 1
    if offset >= len(raw):
        raise ActiveAuthError(f"{label} está truncado: no trae longitud.")
    length_byte = raw[offset]
    offset += 1
    if length_byte & 0x80:
        count = length_byte & 0x7F
        if count == 0 or offset + count > len(raw):
            raise ActiveAuthError(f"{label} tiene una longitud DER inválida.")
        length = int.from_bytes(raw[offset : offset + count], "big")
        offset += count
    else:
        length = length_byte
    if offset + length > len(raw):
        raise ActiveAuthError(f"{label} está truncado: la longitud excede el archivo.")
    return raw[offset : offset + length]


def parse_dg15(dg15: bytes):
    """Clave pública de Autenticación Activa que declara EF.DG15.

    DG15 es un TLV `6F` que envuelve una SubjectPublicKeyInfo en DER. El
    envoltorio existe: cargar el archivo entero como SPKI —sin quitarlo—
    falla contra cualquier documento real.
    """
    spki = _unwrap(dg15, DG15_TAG, "El EF.DG15")
    try:
        public_key = serialization.load_der_public_key(spki)
    except Exception as exc:
        raise ActiveAuthError(
            f"El EF.DG15 no contiene una clave pública interpretable: {exc}"
        ) from exc
    if not isinstance(public_key, (rsa.RSAPublicKey, ec.EllipticCurvePublicKey)):
        raise ActiveAuthError(
            "La clave de EF.DG15 no es RSA ni ECDSA; ICAO 9303 no define "
            "Autenticación Activa con otro tipo de clave."
        )
    return public_key


# ---------------------------------------------------------------------------
# EF.DG14 — SecurityInfos
# ---------------------------------------------------------------------------


class _SecurityInfo(core.Sequence):
    _fields = [
        ("protocol", core.ObjectIdentifier),
        ("required_data", core.Any),
        ("optional_data", core.Any, {"optional": True}),
    ]


class _SecurityInfos(core.SetOf):
    _child_spec = _SecurityInfo


def active_authentication_digest(dg14: bytes) -> Optional[str]:
    """Hash que `ActiveAuthenticationInfo` declara en EF.DG14, si lo declara.

    Para ECDSA es obligatorio: ICAO no fija un hash por defecto y adivinar uno
    sería inventar el parámetro del que depende la verificación. Para RSA no se
    usa —ahí manda el tráiler de ISO/IEC 9796-2— y este valor solo sirve para
    dejar constancia.
    """
    infos = _SecurityInfos.load(_unwrap(dg14, DG14_TAG, "El EF.DG14"))
    for info in infos:
        if info["protocol"].dotted != ACTIVE_AUTHENTICATION_INFO_OID:
            continue
        optional = info["optional_data"]
        if optional is None:
            return None
        try:
            oid = core.ObjectIdentifier.load(optional.dump()).dotted
        except Exception:
            return None
        return _ECDSA_PLAIN_HASHES.get(oid)
    return None


# ---------------------------------------------------------------------------
# ISO/IEC 9796-2 Digital Signature Scheme 1
# ---------------------------------------------------------------------------


def _open_representative(
    value: int, modulus_bytes: int, challenge: bytes
) -> Optional[str]:
    """Interpreta un representante de ISO/IEC 9796-2 DS1 y comprueba el hash.

    Devuelve el nombre del hash si el representante es válido Y su hash cubre
    el desafío; `None` si no lo es. Nunca lanza: el llamador prueba las dos
    raíces admitidas por la función de apertura (ISO/IEC 9796-2 B.7).

    Estructura de `F`, de fuera hacia dentro:

        cabecera (4 bits) | relleno 0xBB… | M1 | H(M1 ‖ M2) | tráiler

    donde M2 es la parte NO recuperable del mensaje —para la AA de un eMRTD, el
    desafío del servidor— y M1 es relleno aleatorio que genera el chip.
    """
    if value < 0:
        return None
    try:
        block = value.to_bytes(modulus_bytes, "big")
    except OverflowError:
        return None

    # Cabecera: los dos bits altos han de ser `01`. El bit 0x20 distingue
    # recuperación parcial (0x6…) de total (0x4…).
    if block[0] & 0xC0 != 0x40:
        return None
    # Tráiler: el último nibble es siempre 0xC.
    if block[-1] & 0x0F != 0x0C:
        return None

    if block[-1] == _IMPLICIT_TRAILER:
        trailer_length = 1
        digest_name: Optional[str] = _IMPLICIT_TRAILER_HASH
    else:
        if len(block) < 2:
            return None
        trailer_length = 2
        digest_name = _TRAILER_HASHES.get(block[-2])
    if digest_name is None:
        return None

    digest_size = hashlib.new(digest_name).digest_size
    hash_offset = len(block) - trailer_length - digest_size
    if hash_offset <= 0:
        return None

    # El relleno son bytes 0xBB y termina en uno cuyo nibble bajo es 0xA
    # (la cabecera misma cuando no hay relleno: 0x4A / 0x6A).
    start = 0
    while start < len(block) and block[start] & 0x0F != 0x0A:
        start += 1
    start += 1
    if start > hash_offset:
        return None

    recovered = block[start:hash_offset]
    declared = block[hash_offset : hash_offset + digest_size]

    if block[0] & 0x20:
        # Recuperación parcial: M = M1 ‖ desafío. Es el caso de la AA.
        message = recovered + challenge
    else:
        # Recuperación total: el mensaje entero viaja dentro del representante,
        # así que el desafío tiene que estar ahí — y al final. Sin esta
        # comprobación, una firma sobre cualquier otro mensaje pasaría.
        if not challenge or not recovered.endswith(challenge):
            return None
        message = recovered

    if not hmac.compare_digest(hashlib.new(digest_name, message).digest(), declared):
        return None
    return digest_name


def verify_iso9796_2_ds1(
    public_key: rsa.RSAPublicKey, challenge: bytes, signature: bytes
) -> str:
    """Verifica una firma de Autenticación Activa con clave RSA.

    Devuelve el nombre del hash usado, o lanza `ActiveAuthError`.
    """
    numbers = public_key.public_numbers()
    modulus_bytes = (numbers.n.bit_length() + 7) // 8
    if len(signature) != modulus_bytes:
        raise ActiveAuthError(
            f"La firma de Autenticación Activa mide {len(signature)} bytes y la "
            f"clave del chip {modulus_bytes}: no es una firma de esa clave."
        )
    representative = int.from_bytes(signature, "big")
    if representative >= numbers.n:
        raise ActiveAuthError(
            "La firma de Autenticación Activa no es menor que el módulo del chip."
        )

    opened = pow(representative, numbers.e, numbers.n)
    # ISO/IEC 9796-2 §8.3 produce la firma como el menor de F* y n − F*, así que
    # la apertura tiene que probar las dos raíces (B.7). Comprobar solo una
    # rechazaría firmas legítimas de la mitad de los documentos.
    for candidate in (opened, numbers.n - opened):
        digest_name = _open_representative(candidate, modulus_bytes, challenge)
        if digest_name is not None:
            return digest_name

    raise ActiveAuthError(
        "La firma de Autenticación Activa no verifica con la clave de EF.DG15: "
        "el chip que respondió no es el dueño de esa clave, o la respuesta se "
        "grabó de otra sesión."
    )


# ---------------------------------------------------------------------------
# ECDSA en formato plano (BSI TR-03111)
# ---------------------------------------------------------------------------


def verify_ecdsa_plain(
    public_key: ec.EllipticCurvePublicKey,
    challenge: bytes,
    signature: bytes,
    digest_name: str,
) -> str:
    """Verifica una AA con clave ECDSA. La firma viaja como `r ‖ s`, no en DER."""
    algorithm = _CRYPTO_HASHES.get(digest_name)
    if algorithm is None:
        raise ActiveAuthError(
            f"EF.DG14 declara un hash no soportado para la Autenticación "
            f"Activa: {digest_name}."
        )

    component = (public_key.curve.key_size + 7) // 8
    if len(signature) != 2 * component:
        raise ActiveAuthError(
            f"La firma ECDSA de Autenticación Activa mide {len(signature)} bytes; "
            f"la curva del chip exige {2 * component} (r‖s en formato plano)."
        )
    r = int.from_bytes(signature[:component], "big")
    s = int.from_bytes(signature[component:], "big")
    if r == 0 or s == 0:
        raise ActiveAuthError("La firma ECDSA de Autenticación Activa es degenerada.")

    try:
        public_key.verify(encode_dss_signature(r, s), challenge, ec.ECDSA(algorithm()))
    except InvalidSignature:
        raise ActiveAuthError(
            "La firma de Autenticación Activa no verifica con la clave de "
            "EF.DG15: el chip que respondió no es el dueño de esa clave, o la "
            "respuesta se grabó de otra sesión."
        ) from None
    return digest_name


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def verify(
    dg15: bytes,
    challenge: bytes,
    signature: bytes,
    dg14: Optional[bytes] = None,
) -> ActiveAuthResult:
    """Autenticación Activa completa. Lanza `ActiveAuthError` o devuelve el resultado.

    `dg15` tiene que ser el archivo cuyo hash ya verificó la Autenticación
    Pasiva contra el EF.SOD. Llamar aquí con un DG15 que no pasó ese paso hace
    que toda la comprobación no signifique nada — la clave la habría elegido
    quien envía.
    """
    if len(challenge) != CHALLENGE_BYTES:
        # No es un error del ciudadano: es un error nuestro. Un desafío de otro
        # tamaño significa que el servidor emitió algo que el chip no firmó.
        raise ActiveAuthError(
            f"El desafío de Autenticación Activa debe medir {CHALLENGE_BYTES} "
            f"bytes; llegó uno de {len(challenge)}."
        )
    if not signature:
        raise ActiveAuthError("No llegó ninguna firma de Autenticación Activa.")

    public_key = parse_dg15(dg15)

    declared_digest: Optional[str] = None
    if dg14:
        try:
            declared_digest = active_authentication_digest(dg14)
        except ActiveAuthError:
            raise
        except Exception as exc:
            raise ActiveAuthError(
                f"El EF.DG14 no se pudo interpretar como SecurityInfos: {exc}"
            ) from exc

    if isinstance(public_key, rsa.RSAPublicKey):
        digest_name = verify_iso9796_2_ds1(public_key, challenge, signature)
        scheme = "rsa-iso9796-2-ds1"
        key_bits = public_key.key_size
    else:
        if declared_digest is None:
            # ICAO no define un hash por defecto para la AA con ECDSA: va en
            # `ActiveAuthenticationInfo`. Elegir uno aquí sería inventar el
            # parámetro del que depende la verificación.
            raise ActiveAuthError(
                "El chip usa ECDSA para la Autenticación Activa pero no llegó "
                "un EF.DG14 que declare con qué hash firma. No se adivina."
            )
        digest_name = verify_ecdsa_plain(
            public_key, challenge, signature, declared_digest
        )
        scheme = "ecdsa-plain"
        key_bits = public_key.curve.key_size

    return ActiveAuthResult(
        scheme=scheme,
        digest_algorithm=digest_name,
        key_bits=key_bits,
        dg15_sha256=hashlib.sha256(dg15).hexdigest(),
    )
