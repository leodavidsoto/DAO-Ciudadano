"""
Autenticación Pasiva del EF.SOD en el servidor (ICAO 9303-11, ROADMAP 5.8).

Por qué existe si el móvil ya la hace
-------------------------------------
`mobile/.../PassiveAuthenticator.kt` verifica el documento en el teléfono, y
eso es correcto: le dice a la persona, en el momento, si su cédula es
auténtica. Pero el resultado llegaba al backend como un booleano dentro de un
JSON — es decir, como una afirmación del cliente. Cualquiera con curl podía
enviar `identityVerified: true` y obtener lo mismo que quien apoyó una cédula
real en el teléfono. Una verificación que sólo ocurre en el cliente no es una
verificación: es una sugerencia.

Este módulo repite la comprobación completa sobre los bytes crudos del chip.
El veredicto del móvil pasa a ser lo que siempre debió ser: una comodidad de
interfaz. La decisión la toma el servidor.

Las cuatro comprobaciones, todas obligatorias
---------------------------------------------
1. La firma del SOD verifica con la clave pública del Document Signer.
2. El `messageDigest` firmado corresponde al eContent realmente presente
   (sin esto, la firma cubriría un contenido distinto del que se lee).
3. Los hashes de los data groups declarados en el SOD coinciden con los bytes
   recibidos, DG por DG.
4. El Document Signer encadena hasta una CSCA del Registro Civil que trajimos
   nosotros desde el PKD de la ICAO — nunca desde la propia tarjeta.

Ninguna es opcional y ninguna compensa a otra: tres de cuatro es NO
verificado. No hay bandera de configuración que las desactive. Un entorno de
pruebas sin cédulas reales no obtiene una verificación falsa, obtiene un
error — que es información verdadera.

Lo que este módulo NO hace
--------------------------
* **Autenticación Activa / Chip Authentication.** La PA prueba que los datos
  están firmados por Chile; no prueba que el chip no sea un clon. Clonar
  requiere acceso físico al documento y hoy la mitigación es el CAN + la
  presencia física. Queda declarado como riesgo abierto, no disimulado.
* **Revocación (CRL/OCSP).** El PKD publica CRLs en el archivo -001; no se
  consultan todavía. Un DSC revocado pero no expirado se aceptaría. Está en
  ROADMAP; fingir aquí una consulta que no se hace sería peor que omitirla.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Optional

from asn1crypto import cms, core
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from . import csca_trust_store

logger = logging.getLogger(__name__)

# id-icao-mrtd-security-ldsSecurityObject
LDS_SECURITY_OBJECT_OID = "2.23.136.1.1.1"
# EF.SOD envuelve el ContentInfo en un tag [APPLICATION 23].
EF_SOD_TAG = 0x77

# Data groups que una cédula chilena debe traer para que la verificación sirva
# de algo: DG1 es la MRZ (la identidad) y DG2 la foto (lo que se compara con
# la persona). Verificar sólo DG2 dejaría la identidad sin firmar comprobada.
REQUIRED_DATA_GROUPS = (1, 2)

# Ruta máxima DSC -> ... -> ancla. La PKI de la ICAO es de dos niveles con
# eslabones de rotación; más que esto es un ciclo o una cadena construida.
MAX_CHAIN_DEPTH = 6

_HASHES = {
    "sha1": hashes.SHA1,
    "sha224": hashes.SHA224,
    "sha256": hashes.SHA256,
    "sha384": hashes.SHA384,
    "sha512": hashes.SHA512,
}

# SHA-1 sigue apareciendo en documentos antiguos de varios países. Se admite
# para el digest de los data groups —romper la preimagen de un DG concreto no
# es un ataque práctico hoy— pero NO para la firma del SOD, donde una colisión
# sí permitiría fabricar un documento con firma válida.
FORBIDDEN_SIGNATURE_HASHES = {"sha1", "md5"}


class PassiveAuthError(RuntimeError):
    """La Autenticación Pasiva falló. `reasons` explica en qué paso y por qué."""

    def __init__(self, message: str, reasons: Optional[list[str]] = None):
        super().__init__(message)
        self.reasons = reasons or [message]


# ---------------------------------------------------------------------------
# LDSSecurityObject (ICAO 9303-10)
# ---------------------------------------------------------------------------


class _DataGroupHash(core.Sequence):
    _fields = [
        ("data_group_number", core.Integer),
        ("data_group_hash_value", core.OctetString),
    ]


class _DataGroupHashValues(core.SequenceOf):
    _child_spec = _DataGroupHash


class _LDSSecurityObject(core.Sequence):
    _fields = [
        ("version", core.Integer),
        ("hash_algorithm", cms.DigestAlgorithm),
        ("data_group_hash_values", _DataGroupHashValues),
        # `ldsVersionInfo` sólo existe en v1. Opcional para no rechazar los v0.
        ("lds_version_info", core.Any, {"optional": True}),
    ]


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PassiveAuthResult:
    """Qué se comprobó y contra qué. Todo booleano aquí es `True` o hubo error."""

    document_signer_subject: str
    document_signer_serial: str
    trust_anchor_subject: str
    trust_anchor_sha256: str
    #: DSC -> ... -> ancla, incluidos los eslabones de rotación.
    chain_subjects: tuple[str, ...]
    digest_algorithm: str
    signature_algorithm: str
    verified_data_groups: tuple[int, ...]
    #: Hashes de los DG tal como los declara el SOD. Se devuelven para que el
    #: llamador pueda ligar la credencial a un documento concreto sin volver a
    #: manejar los bytes del chip.
    data_group_hashes: Mapping[int, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "document_signer": self.document_signer_subject,
            "document_signer_serial": self.document_signer_serial,
            "trust_anchor": self.trust_anchor_subject,
            "trust_anchor_sha256": self.trust_anchor_sha256,
            "chain": list(self.chain_subjects),
            "digest_algorithm": self.digest_algorithm,
            "signature_algorithm": self.signature_algorithm,
            "verified_data_groups": list(self.verified_data_groups),
        }


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------


def _unwrap_ef_sod(raw: bytes) -> bytes:
    """Quita el envoltorio `[APPLICATION 23]` si el móvil mandó el EF completo.

    Se aceptan las dos formas —EF.SOD tal como sale del chip, o el ContentInfo
    ya desenvuelto— porque cuál de las dos llega depende de la librería del
    cliente, y rechazar la del chip obligaría al móvil a manipular ASN.1 antes
    de enviarlo: más código en el lado no confiable, sin ninguna ganancia.
    """
    if not raw:
        raise PassiveAuthError("El EF.SOD llegó vacío.")
    if raw[0] != EF_SOD_TAG:
        return raw

    offset = 1
    length_byte = raw[offset]
    offset += 1
    if length_byte & 0x80:
        count = length_byte & 0x7F
        if count == 0 or offset + count > len(raw):
            raise PassiveAuthError("El EF.SOD tiene una longitud DER inválida.")
        length = int.from_bytes(raw[offset : offset + count], "big")
        offset += count
    else:
        length = length_byte
    if offset + length > len(raw):
        raise PassiveAuthError(
            "El EF.SOD está truncado: la longitud excede el archivo."
        )
    return raw[offset : offset + length]


def _load_signed_data(sod_der: bytes) -> cms.SignedData:
    try:
        content_info = cms.ContentInfo.load(_unwrap_ef_sod(sod_der))
        if content_info["content_type"].native != "signed_data":
            raise PassiveAuthError(
                "El EF.SOD no es un CMS SignedData; no hay nada que verificar."
            )
        return content_info["content"]
    except PassiveAuthError:
        raise
    except Exception as exc:
        raise PassiveAuthError(
            f"El EF.SOD no se pudo interpretar como CMS: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Firma
# ---------------------------------------------------------------------------


def _hash_algorithm(name: str) -> hashes.HashAlgorithm:
    try:
        return _HASHES[name.lower()]()
    except KeyError:
        raise PassiveAuthError(f"Algoritmo de hash no soportado: {name}") from None


def _find_document_signer(
    signed_data: cms.SignedData, signer: cms.SignerInfo
) -> x509.Certificate:
    """El DSC que el SOD dice haber usado, buscado por el identificador del firmante.

    Se busca por `sid` en vez de tomar el primer certificado del SOD: un
    documento manipulado puede traer varios certificados y confiar en el orden
    permitiría que el verificado no fuera el que firmó.
    """
    certificates = signed_data["certificates"]
    if certificates is None:
        raise PassiveAuthError(
            "El EF.SOD no incluye el certificado del Document Signer."
        )

    sid = signer["sid"]
    for choice in certificates:
        if choice.name != "certificate":
            continue
        candidate = choice.chosen
        if sid.name == "issuer_and_serial_number":
            wanted = sid.chosen
            if (
                candidate.issuer == wanted["issuer"]
                and candidate.serial_number == wanted["serial_number"].native
            ):
                return x509.load_der_x509_certificate(candidate.dump())
        else:  # subject_key_identifier
            if candidate.key_identifier == sid.chosen.native:
                return x509.load_der_x509_certificate(candidate.dump())

    raise PassiveAuthError(
        "El EF.SOD no contiene el certificado con el que dice haberse firmado."
    )


def _verify_signature(
    certificate: x509.Certificate, signer: cms.SignerInfo, signed_payload: bytes
) -> str:
    """Comprueba la firma del SOD con la clave pública del DSC."""
    algorithm = signer["signature_algorithm"]
    try:
        signature_algo = algorithm.signature_algo
    except Exception as exc:
        raise PassiveAuthError(
            f"El algoritmo de firma del SOD no es reconocible: {exc}"
        ) from exc

    try:
        hash_name = algorithm.hash_algo
    except ValueError:
        # `signatureAlgorithm` puede ser el OID desnudo (rsaEncryption), sin
        # hash embebido. RFC 5652 dice que entonces el hash es el declarado en
        # `digestAlgorithm` del propio SignerInfo, y hay documentos reales
        # emitidos así. Rechazarlos sería confundir "no lo entiendo" con "es
        # falso".
        hash_name = signer["digest_algorithm"]["algorithm"].native

    if hash_name and hash_name.lower() in FORBIDDEN_SIGNATURE_HASHES:
        raise PassiveAuthError(
            f"La firma del SOD usa {hash_name.upper()}, que ya no ofrece "
            "resistencia a colisiones suficiente para autenticar un documento."
        )

    signature = signer["signature"].native
    public_key = certificate.public_key()
    digest = _hash_algorithm(hash_name)

    try:
        if signature_algo == "rsassa_pkcs1v15":
            if not isinstance(public_key, rsa.RSAPublicKey):
                raise PassiveAuthError("El DSC declara RSA pero su clave no lo es.")
            public_key.verify(signature, signed_payload, padding.PKCS1v15(), digest)
        elif signature_algo == "rsassa_pss":
            if not isinstance(public_key, rsa.RSAPublicKey):
                raise PassiveAuthError("El DSC declara RSA-PSS pero su clave no lo es.")
            public_key.verify(
                signature, signed_payload, _pss_padding(algorithm, digest), digest
            )
        elif signature_algo == "ecdsa":
            if not isinstance(public_key, ec.EllipticCurvePublicKey):
                raise PassiveAuthError("El DSC declara ECDSA pero su clave no lo es.")
            public_key.verify(signature, signed_payload, ec.ECDSA(digest))
        else:
            raise PassiveAuthError(
                f"Algoritmo de firma no soportado en el SOD: {signature_algo}"
            )
    except InvalidSignature:
        raise PassiveAuthError(
            "La firma del EF.SOD no verifica con la clave del Document Signer: "
            "el documento fue alterado o no lo firmó quien dice."
        ) from None

    return f"{signature_algo}-{hash_name}"


def _pss_padding(
    algorithm: cms.SignedDigestAlgorithm, digest: hashes.HashAlgorithm
) -> padding.PSS:
    """Parámetros PSS declarados en el certificado, no asumidos.

    RSASSA-PSS lleva el hash de MGF1 y la longitud de sal FUERA del OID. Usar
    valores por defecto rechazaría firmas legítimas que usen otros — y, peor,
    aceptar cualquier longitud de sal debilitaría la verificación.
    """
    parameters = algorithm["parameters"]
    try:
        mgf_alg = parameters["mask_gen_algorithm"]["parameters"]["algorithm"]
        mgf_hash = _hash_algorithm(mgf_alg.native)
        salt_length = parameters["salt_length"].native
    except Exception:
        # Valores por defecto de RFC 4055 cuando el certificado los omite.
        mgf_hash = digest
        salt_length = 20
    return padding.PSS(mgf=padding.MGF1(mgf_hash), salt_length=salt_length)


def _signed_payload(
    signer: cms.SignerInfo, econtent: bytes, econtent_type: str
) -> bytes:
    """Bytes que la firma cubre realmente, y comprobación de que cubren el eContent.

    Si hay `signedAttrs`, la firma NO cubre el eContent directamente: cubre los
    atributos, y el vínculo con el contenido es el atributo `messageDigest`.
    Verificar la firma sin comprobar ese atributo dejaría pasar un SOD con
    firma válida sobre unos atributos y un eContent completamente distinto —
    exactamente el fallo que hizo famosos a varios verificadores de eMRTD.
    """
    signed_attrs = signer["signed_attrs"]
    if signed_attrs is None or len(signed_attrs) == 0:
        # Sin atributos firmados la firma cubre el eContent tal cual.
        return econtent

    declared_digest: Optional[bytes] = None
    declared_type: Optional[str] = None
    for attribute in signed_attrs:
        name = attribute["type"].native
        values = attribute["values"]
        if name == "message_digest":
            declared_digest = values[0].native
        elif name == "content_type":
            declared_type = values[0].dotted

    if declared_digest is None:
        raise PassiveAuthError(
            "El SOD firma unos atributos que no incluyen messageDigest: la firma "
            "no quedaría ligada al contenido del documento."
        )

    digest_name = signer["digest_algorithm"]["algorithm"].native
    actual_digest = hashlib.new(digest_name.replace("-", ""), econtent).digest()
    if actual_digest != declared_digest:
        raise PassiveAuthError(
            "El messageDigest firmado no corresponde al contenido del SOD: el "
            "contenido fue sustituido después de firmarse."
        )

    if declared_type is not None and declared_type != econtent_type:
        raise PassiveAuthError(
            "El contentType firmado no coincide con el del contenido: la firma "
            "podría estar reutilizada de otro tipo de documento."
        )

    # La firma se calcula sobre el DER con tag SET OF (0x31), no sobre el
    # [0] IMPLICIT con el que viaja. `untag()` hace exactamente ese cambio; sin
    # él, ninguna firma legítima verificaría.
    return signed_attrs.untag().dump()


# ---------------------------------------------------------------------------
# Data groups
# ---------------------------------------------------------------------------


def _verify_data_groups(
    econtent: bytes, data_groups: Mapping[int, bytes]
) -> tuple[str, tuple[int, ...], dict[int, str]]:
    try:
        lds = _LDSSecurityObject.load(econtent)
        digest_name = lds["hash_algorithm"]["algorithm"].native
        declared = {
            int(entry["data_group_number"].native): entry[
                "data_group_hash_value"
            ].native
            for entry in lds["data_group_hash_values"]
        }
    except Exception as exc:
        raise PassiveAuthError(
            f"El contenido firmado del SOD no es un LDSSecurityObject válido: {exc}"
        ) from exc

    missing = [dg for dg in REQUIRED_DATA_GROUPS if dg not in data_groups]
    if missing:
        raise PassiveAuthError(
            "Faltan data groups obligatorios en la lectura: "
            + ", ".join(f"DG{dg}" for dg in missing)
        )

    reasons: list[str] = []
    verified: list[int] = []
    for number in sorted(data_groups):
        expected = declared.get(number)
        if expected is None:
            reasons.append(f"El SOD no declara ningún hash para DG{number}.")
            continue
        try:
            actual = hashlib.new(
                digest_name.replace("-", ""), data_groups[number]
            ).digest()
        except ValueError:
            raise PassiveAuthError(
                f"El SOD declara un algoritmo de hash desconocido: {digest_name}"
            ) from None
        if actual != expected:
            reasons.append(
                f"El contenido de DG{number} no coincide con su hash firmado en el SOD."
            )
            continue
        verified.append(number)

    if reasons:
        raise PassiveAuthError("Los data groups no coinciden con el SOD.", reasons)

    # Que los DG enviados cuadren no basta si los obligatorios no se
    # comprobaron: sin esto, mandar sólo un DG irrelevante pasaría el paso.
    not_verified = [dg for dg in REQUIRED_DATA_GROUPS if dg not in verified]
    if not_verified:
        raise PassiveAuthError(
            "No se pudo verificar el hash de: "
            + ", ".join(f"DG{dg}" for dg in not_verified)
        )

    return digest_name, tuple(verified), {n: declared[n].hex() for n in verified}


# ---------------------------------------------------------------------------
# Cadena de confianza
# ---------------------------------------------------------------------------


def _assert_valid_now(certificate: x509.Certificate, label: str, now: datetime) -> None:
    if now < certificate.not_valid_before_utc:
        raise PassiveAuthError(
            f"{label} todavía no es válido "
            f"(desde {certificate.not_valid_before_utc:%Y-%m-%d})."
        )
    if now > certificate.not_valid_after_utc:
        raise PassiveAuthError(
            f"{label} expiró el {certificate.not_valid_after_utc:%Y-%m-%d}."
        )


def _build_chain(
    document_signer: x509.Certificate, store: csca_trust_store.TrustStore, now: datetime
) -> tuple[x509.Certificate, tuple[str, ...]]:
    """Encadena el DSC hasta una CSCA de confianza. Devuelve (ancla, ruta).

    Búsqueda en profundidad porque puede haber varias rutas: con eslabones de
    rotación, un DSC nuevo encadena tanto con la raíz nueva como con la vieja
    a través del link certificate. Basta con que UNA ruta completa valide.
    """
    _assert_valid_now(document_signer, "El certificado del Document Signer", now)

    reasons: list[str] = []

    def walk(
        certificate: x509.Certificate, path: list[x509.Certificate], depth: int
    ) -> Optional[tuple[x509.Certificate, list[x509.Certificate]]]:
        if depth > MAX_CHAIN_DEPTH:
            return None
        for issuer in store.issuers_of(certificate):
            # Un certificado repetido en la ruta es un ciclo entre eslabones.
            if any(
                issuer.fingerprint(hashes.SHA256()) == c.fingerprint(hashes.SHA256())
                for c in path
            ):
                continue
            try:
                certificate.verify_directly_issued_by(issuer)
            except Exception:
                continue
            subject = issuer.subject.rfc4514_string()
            try:
                _assert_valid_now(issuer, f"La CSCA «{subject}»", now)
            except PassiveAuthError as exc:
                reasons.append(str(exc))
                continue
            if issuer in store.anchors:
                return issuer, path + [issuer]
            found = walk(issuer, path + [issuer], depth + 1)
            if found is not None:
                return found
        return None

    found = walk(document_signer, [document_signer], 0)
    if found is None:
        reasons.insert(
            0,
            "El certificado del documento no encadena con ninguna CSCA del "
            "Registro Civil instalada en el servidor.",
        )
        raise PassiveAuthError(reasons[0], reasons)

    anchor, path = found
    return anchor, tuple(c.subject.rfc4514_string() for c in path)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def verify(
    sod_der: bytes,
    data_groups: Mapping[int, bytes],
    now: Optional[datetime] = None,
) -> PassiveAuthResult:
    """Autenticación Pasiva completa. Lanza `PassiveAuthError` o devuelve el resultado.

    No existe un valor de retorno que signifique "verificado a medias": o las
    cuatro comprobaciones pasan, o hay excepción.
    """
    now = now or datetime.now(timezone.utc)
    store = csca_trust_store.load()  # TrustStoreError si no hay anclas: fail-closed.

    signed_data = _load_signed_data(sod_der)

    signers = signed_data["signer_infos"]
    if len(signers) != 1:
        # ICAO 9303 especifica exactamente un firmante. Con varios habría que
        # decidir cuál manda, y esa decisión la tomaría el atacante.
        raise PassiveAuthError(
            f"El EF.SOD declara {len(signers)} firmantes; ICAO 9303 exige exactamente uno."
        )
    signer = signers[0]

    encap = signed_data["encap_content_info"]
    econtent_type = encap["content_type"].dotted
    if econtent_type != LDS_SECURITY_OBJECT_OID:
        raise PassiveAuthError(
            f"El contenido firmado no es un LDS Security Object (OID {econtent_type})."
        )
    econtent = encap["content"].native
    if not econtent:
        raise PassiveAuthError("El EF.SOD no trae contenido firmado.")

    document_signer = _find_document_signer(signed_data, signer)

    # Orden deliberado: primero se establece QUÉ bytes cubre la firma (y que
    # cubren este eContent), y sólo después se verifica la firma sobre ellos.
    payload = _signed_payload(signer, econtent, econtent_type)
    signature_algorithm = _verify_signature(document_signer, signer, payload)

    digest_algorithm, verified, hashes_by_dg = _verify_data_groups(
        econtent, data_groups
    )

    anchor, chain = _build_chain(document_signer, store, now)

    return PassiveAuthResult(
        document_signer_subject=document_signer.subject.rfc4514_string(),
        document_signer_serial=f"{document_signer.serial_number:x}",
        trust_anchor_subject=anchor.subject.rfc4514_string(),
        trust_anchor_sha256=anchor.fingerprint(hashes.SHA256()).hex(),
        chain_subjects=chain,
        digest_algorithm=digest_algorithm,
        signature_algorithm=signature_algorithm,
        verified_data_groups=verified,
        data_group_hashes=hashes_by_dg,
    )
