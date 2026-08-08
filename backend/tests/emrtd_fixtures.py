"""
Fábrica de eMRTD sintéticos para probar la Autenticación Pasiva.

No hay cédulas chilenas reales en CI, y no debería haberlas: los bytes de un
documento auténtico son datos personales de alguien. Lo que sí se puede
construir es la MISMA estructura criptográfica —CSCA auto-firmada, DSC emitido
por ella, EF.SOD con LDSSecurityObject y signedAttrs— y comprobar contra ella
tanto que un documento legítimo pasa como que cada manipulación concreta
falla.

Esto no sustituye una prueba con una cédula real: los certificados del
Registro Civil y su perfil exacto sólo se validan contra `csca_chile.pem`. Lo
que cubre es la lógica de verificación, que es donde vive el riesgo de
escribir un verificador que diga "sí" por el motivo equivocado.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional

from asn1crypto import algos, cms, core
from asn1crypto import x509 as a1x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.x509.oid import NameOID

from app.services.passive_auth import LDS_SECURITY_OBJECT_OID

# Claves pequeñas: son juguetes de test y generar RSA-3072 en cada caso hace
# la suite lenta sin probar nada distinto.
KEY_SIZE = 2048


@dataclass
class Issued:
    certificate: x509.Certificate
    key: rsa.RSAPrivateKey


def _name(common_name: str, country: str = "CL") -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, country),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Ministerio de Justicia"),
            x509.NameAttribute(
                NameOID.ORGANIZATIONAL_UNIT_NAME,
                "Servicio de Registro Civil e Identificacion",
            ),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )


def make_csca(
    common_name: str = "CSCA",
    country: str = "CL",
    not_before: Optional[datetime] = None,
    not_after: Optional[datetime] = None,
) -> Issued:
    """CSCA raíz auto-firmada."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE)
    now = datetime.now(timezone.utc)
    subject = _name(common_name, country)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before or now - timedelta(days=365))
        .not_valid_after(not_after or now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    return Issued(certificate, key)


def make_link_certificate(previous: Issued, successor: Issued) -> x509.Certificate:
    """Eslabón de rotación: la CSCA anterior firma la clave de la siguiente.

    Reproduce el caso real del Registro Civil: mismo DN que su emisor, así que
    `subject == issuer` aunque NO sea auto-firmado.
    """
    now = datetime.now(timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(successor.certificate.subject)
        .issuer_name(previous.certificate.subject)
        .public_key(successor.key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=30))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(previous.key, hashes.SHA256())
    )


def make_dsc(
    csca: Issued,
    common_name: str = "Document Signer",
    not_before: Optional[datetime] = None,
    not_after: Optional[datetime] = None,
) -> Issued:
    """Document Signer emitido por la CSCA."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE)
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(_name(common_name))
        .issuer_name(csca.certificate.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before or now - timedelta(days=30))
        .not_valid_after(not_after or now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(csca.key, hashes.SHA256())
    )
    return Issued(certificate, key)


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
        ("hash_algorithm", algos.DigestAlgorithm),
        ("data_group_hash_values", _DataGroupHashValues),
    ]


def lds_security_object(
    data_groups: Mapping[int, bytes], digest: str = "sha256"
) -> bytes:
    """LDSSecurityObject con el hash de cada DG.

    Se define aquí con sus propias clases ASN.1 en vez de reutilizar las del
    servicio: si el test construyera el objeto con el mismo código que lo
    interpreta, un error en esa definición se cancelaría consigo mismo y la
    prueba pasaría igual.
    """
    entries = [
        {
            "data_group_number": number,
            "data_group_hash_value": hashlib.new(digest, content).digest(),
        }
        for number, content in sorted(data_groups.items())
    ]
    return _LDSSecurityObject(
        {
            "version": 0,
            "hash_algorithm": {"algorithm": digest},
            "data_group_hash_values": entries,
        }
    ).dump()


def build_sod(
    dsc: Issued,
    data_groups: Mapping[int, bytes],
    digest: str = "sha256",
    *,
    econtent_override: Optional[bytes] = None,
    omit_message_digest: bool = False,
    wrong_message_digest: bool = False,
    extra_certificates: tuple[x509.Certificate, ...] = (),
    omit_signer_certificate: bool = False,
    wrap_ef_sod: bool = True,
) -> bytes:
    """EF.SOD firmado. Los flags fabrican documentos manipulados a propósito."""
    econtent = lds_security_object(data_groups, digest)
    signed_econtent = econtent_override if econtent_override is not None else econtent

    digest_value = hashlib.new(digest, econtent).digest()
    if wrong_message_digest:
        digest_value = hashlib.new(digest, econtent + b"x").digest()

    attributes = [
        {"type": "content_type", "values": [LDS_SECURITY_OBJECT_OID]},
    ]
    if not omit_message_digest:
        attributes.append({"type": "message_digest", "values": [digest_value]})

    # `CMSAttributes` es un SET OF: `.dump()` ya produce el tag 0x31 sobre el
    # que se calcula la firma. Dentro del SignerInfo viaja con [0] IMPLICIT, y
    # es el verificador quien tiene que deshacer ese cambio.
    signed_attrs = cms.CMSAttributes(attributes)
    signature = dsc.key.sign(signed_attrs.dump(), padding.PKCS1v15(), hashes.SHA256())

    certificates = []
    if not omit_signer_certificate:
        certificates.append(
            cms.CertificateChoices(
                name="certificate",
                value=a1x509.Certificate.load(
                    dsc.certificate.public_bytes(serialization.Encoding.DER)
                ),
            )
        )
    for extra in extra_certificates:
        certificates.append(
            cms.CertificateChoices(
                name="certificate",
                value=a1x509.Certificate.load(
                    extra.public_bytes(serialization.Encoding.DER)
                ),
            )
        )

    signer_info = cms.SignerInfo(
        {
            "version": "v1",
            "sid": cms.SignerIdentifier(
                name="issuer_and_serial_number",
                value=cms.IssuerAndSerialNumber(
                    {
                        "issuer": a1x509.Certificate.load(
                            dsc.certificate.public_bytes(serialization.Encoding.DER)
                        ).issuer,
                        "serial_number": dsc.certificate.serial_number,
                    }
                ),
            ),
            "digest_algorithm": {"algorithm": digest},
            "signed_attrs": signed_attrs,
            "signature_algorithm": {"algorithm": "sha256_rsa"},
            "signature": signature,
        }
    )

    signed_data = cms.SignedData(
        {
            "version": "v3",
            "digest_algorithms": [{"algorithm": digest}],
            "encap_content_info": {
                "content_type": LDS_SECURITY_OBJECT_OID,
                "content": signed_econtent,
            },
            "certificates": certificates,
            "signer_infos": [signer_info],
        }
    )
    content_info = cms.ContentInfo(
        {"content_type": "signed_data", "content": signed_data}
    ).dump()

    return _wrap_ef_sod(content_info) if wrap_ef_sod else content_info


def _wrap_ef_sod(content_info: bytes) -> bytes:
    """Envuelve en `[APPLICATION 23]`, como sale del chip."""
    length = len(content_info)
    if length < 0x80:
        header = bytes([0x77, length])
    else:
        encoded = length.to_bytes((length.bit_length() + 7) // 8, "big")
        header = bytes([0x77, 0x80 | len(encoded)]) + encoded
    return header + content_info


def _mrz_check_digit(value: str) -> str:
    weights = (7, 3, 1)
    total = 0
    for index, character in enumerate(value):
        if character.isdigit():
            weight = int(character)
        elif character == "<":
            weight = 0
        else:
            weight = ord(character) - 55
        total += weight * weights[index % 3]
    return str(total % 10)


def td1_mrz(
    document_number: str = "12345678",
    run: str = "123456785",
    issuing_state: str = "CHL",
    nationality: str = "CHL",
    date_of_birth: str = "900101",
    date_of_expiry: str = "350101",
    document_code: str = "I<",
    surname: str = "PEREZ",
    given_names: str = "JUAN",
    optional_1: str = "",
) -> str:
    """MRZ TD1 (90 caracteres) con los dígitos verificadores CALCULADOS.

    Escribirlos a mano en el test es una fuente silenciosa de falsos fallos:
    un dígito mal puesto hace fallar al parser por el motivo equivocado y
    parece un bug del código bajo prueba.
    """
    number = document_number.ljust(9, "<")
    # El campo opcional de la línea 1 NO lleva el RUN. En la cédula chilena
    # real trae tres caracteres (una letra y dos dígitos); el RUN va en el
    # segundo campo opcional, en la línea 2 (AUDIT P-101).
    optional_1_field = optional_1.ljust(15, "<")
    line1 = (
        document_code.ljust(2, "<")
        + issuing_state.ljust(3, "<")
        + number
        + _mrz_check_digit(number)
        + optional_1_field
    )
    composite_birth = date_of_birth + _mrz_check_digit(date_of_birth)
    composite_expiry = date_of_expiry + _mrz_check_digit(date_of_expiry)
    # Segundo campo opcional (posiciones 19-29 de la línea 2): aquí es donde
    # la cédula chilena lleva el RUN.
    run_field = run.ljust(11, "<")
    line2 = (
        composite_birth
        + "M"
        + composite_expiry
        + nationality.ljust(3, "<")
        + run_field
    )
    line2 += _mrz_check_digit(
        number
        + _mrz_check_digit(number)
        + optional_1_field
        + composite_birth
        + composite_expiry
        + run_field
    )
    line3 = f"{surname}<<{given_names}".ljust(30, "<")[:30]

    assert len(line1) == 30 and len(line2) == 30, (len(line1), len(line2))
    return line1 + line2 + line3


def dg1(mrz_text: str) -> bytes:
    """Envuelve una MRZ en el TLV del DG1 (`61` -> `5F1F`)."""
    body = mrz_text.encode("ascii")
    inner = b"\x5f\x1f" + bytes([len(body)]) + body
    return b"\x61" + bytes([len(inner)]) + inner


# ===========================================================================
# Autenticación Activa (ICAO 9303-11 §6.1)
# ===========================================================================


def _der_tlv(tag: int, content: bytes) -> bytes:
    """Envuelve `content` en un TLV con longitud DER."""
    length = len(content)
    if length < 0x80:
        header = bytes([tag, length])
    else:
        encoded = length.to_bytes((length.bit_length() + 7) // 8, "big")
        header = bytes([tag, 0x80 | len(encoded)]) + encoded
    return header + content


def dg15(public_key) -> bytes:
    """EF.DG15: la SubjectPublicKeyInfo del chip dentro de un TLV `6F`.

    El envoltorio no es decorativo. Un verificador que cargue el archivo entero
    como SPKI —sin quitarlo— falla contra cualquier documento real, y como el
    fallo es "no pude leer la clave" se confunde con un documento inválido.
    """
    spki = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return _der_tlv(0x6F, spki)


class _SecurityInfo(core.Sequence):
    _fields = [
        ("protocol", core.ObjectIdentifier),
        ("required_data", core.Any),
        ("optional_data", core.Any, {"optional": True}),
    ]


class _SecurityInfos(core.SetOf):
    _child_spec = _SecurityInfo


def dg14(signature_algorithm_oid: str, version: int = 1) -> bytes:
    """EF.DG14 con un `ActiveAuthenticationInfo` que declara el hash de firma.

    Es obligatorio cuando el chip firma con ECDSA: ICAO no fija un hash por
    defecto, así que sin este archivo no hay con qué verificar.
    """
    info = _SecurityInfo(
        {
            "protocol": "2.23.136.1.1.5",
            "required_data": core.Integer(version),
            "optional_data": core.ObjectIdentifier(signature_algorithm_oid),
        }
    )
    return _der_tlv(0x6E, _SecurityInfos([info]).dump())


def iso9796_2_ds1_block(
    block_length: int,
    challenge: bytes,
    *,
    digest: str = "sha1",
    m1: Optional[bytes] = None,
) -> bytes:
    """Representante `F` de ISO/IEC 9796-2 Scheme 1, con tráiler implícito.

        cabecera 0x6A | M1 (relleno del chip) | H(M1 ‖ desafío) | 0xBC

    `0x6A` es recuperación PARCIAL sin relleno: el desafío no viaja dentro del
    representante —es lo que el verificador tiene que aportar— y M1 se
    dimensiona para llenar el bloque exacto.

    Se construye a partir del esquema, no del verificador. `test_active_auth.py`
    lo ancla a un vector conocido: con el M1 de ese vector, esta función más la
    operación privada de RSA reproducen su firma BYTE A BYTE. Sin ese ancla, un
    fixture y un verificador que compartieran el mismo malentendido se darían
    la razón mutuamente y la suite no probaría nada — que es exactamente lo que
    pasó con P-97 y P-101.
    """
    digest_size = hashlib.new(digest).digest_size
    # Un byte de cabecera y uno de tráiler implícito.
    recovered_length = block_length - digest_size - 2
    if recovered_length < 0:
        raise ValueError("El bloque es demasiado pequeño para este hash.")

    if m1 is None:
        # El chip genera este relleno; su contenido da igual, lo que importa es
        # que el hash lo cubra junto al desafío.
        m1 = bytes((index * 7 + 11) % 256 for index in range(recovered_length))
    if len(m1) != recovered_length:
        raise ValueError(
            f"M1 debe medir {recovered_length} bytes para este bloque y hash, "
            f"no {len(m1)}."
        )

    return (
        bytes([0x6A])
        + m1
        + hashlib.new(digest, m1 + challenge).digest()
        + bytes([0xBC])
    )


def iso9796_2_ds1_signature(
    private_key: rsa.RSAPrivateKey,
    challenge: bytes,
    *,
    digest: str = "sha1",
    m1: Optional[bytes] = None,
    least_absolute_residue: bool = False,
) -> bytes:
    """Firma de Autenticación Activa RSA, según ISO/IEC 9796-2 Scheme 1.

    `least_absolute_residue` produce `n − s` en vez de `s`: las dos son firmas
    válidas del mismo representante (ISO/IEC 9796-2 §8.3) y un verificador
    tiene que abrir las dos (B.7).
    """
    numbers = private_key.private_numbers()
    modulus = numbers.public_numbers.n
    block_length = (modulus.bit_length() + 7) // 8

    block = iso9796_2_ds1_block(
        block_length, challenge, digest=digest, m1=m1
    )
    signature = pow(int.from_bytes(block, "big"), numbers.d, modulus)
    if least_absolute_residue:
        signature = modulus - signature
    return signature.to_bytes(block_length, "big")


def ecdsa_plain_signature(
    private_key: ec.EllipticCurvePrivateKey, challenge: bytes, digest: str = "sha256"
) -> bytes:
    """Firma AA con ECDSA en el formato plano `r ‖ s` de BSI TR-03111.

    No es DER: los chips devuelven las dos coordenadas concatenadas y rellenas
    a la longitud de la curva.
    """
    algorithm = {"sha1": hashes.SHA1, "sha256": hashes.SHA256}[digest]()
    r, s = decode_dss_signature(private_key.sign(challenge, ec.ECDSA(algorithm)))
    component = (private_key.curve.key_size + 7) // 8
    return r.to_bytes(component, "big") + s.to_bytes(component, "big")


def trust_store_pem(*certificates: x509.Certificate) -> bytes:
    return b"\n".join(
        certificate.public_bytes(serialization.Encoding.PEM)
        for certificate in certificates
    )
