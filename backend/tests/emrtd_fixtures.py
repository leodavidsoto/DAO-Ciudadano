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
from cryptography.hazmat.primitives.asymmetric import padding, rsa
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


def lds_security_object(data_groups: Mapping[int, bytes], digest: str = "sha256") -> bytes:
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
                value=a1x509.Certificate.load(extra.public_bytes(serialization.Encoding.DER)),
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
) -> str:
    """MRZ TD1 (90 caracteres) con los dígitos verificadores CALCULADOS.

    Escribirlos a mano en el test es una fuente silenciosa de falsos fallos:
    un dígito mal puesto hace fallar al parser por el motivo equivocado y
    parece un bug del código bajo prueba.
    """
    number = document_number.ljust(9, "<")
    line1 = (
        document_code.ljust(2, "<")
        + issuing_state.ljust(3, "<")
        + number
        + _mrz_check_digit(number)
        + run.ljust(15, "<")
    )
    composite_birth = date_of_birth + _mrz_check_digit(date_of_birth)
    composite_expiry = date_of_expiry + _mrz_check_digit(date_of_expiry)
    line2 = (
        composite_birth
        + "M"
        + composite_expiry
        + nationality.ljust(3, "<")
        + "<" * 11
    )
    line2 += _mrz_check_digit(
        number + _mrz_check_digit(number) + run.ljust(15, "<")
        + composite_birth + composite_expiry
    )
    line3 = f"{surname}<<{given_names}".ljust(30, "<")[:30]

    assert len(line1) == 30 and len(line2) == 30, (len(line1), len(line2))
    return line1 + line2 + line3


def dg1(mrz_text: str) -> bytes:
    """Envuelve una MRZ en el TLV del DG1 (`61` -> `5F1F`)."""
    body = mrz_text.encode("ascii")
    inner = b"\x5f\x1f" + bytes([len(body)]) + body
    return b"\x61" + bytes([len(inner)]) + inner


def trust_store_pem(*certificates: x509.Certificate) -> bytes:
    return b"\n".join(
        certificate.public_bytes(serialization.Encoding.PEM)
        for certificate in certificates
    )
