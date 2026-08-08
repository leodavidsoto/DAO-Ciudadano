"""
Autenticación Activa del eMRTD (ICAO 9303-11 §6.1).

Estos tests existen porque una implementación anterior de este módulo (commit
`bdb78cf`, nunca fusionado) verificaba las firmas RSA con PKCS#1 v1.5 y traía
96 líneas de tests EN VERDE. Sus tests pasaban porque estaban escritos contra
la misma suposición equivocada que el código: ninguna cédula real habría
validado jamás. Es el mismo patrón que P-97 y P-101 — el fixture reproducía el
error en vez de detectarlo.

La defensa contra eso es un vector conocido que no salga de aquí. Se usa el de
la suite de BouncyCastle (`core/src/test/java/org/bouncycastle/crypto/test/
ISO9796Test.java`, `doTest13`), cuyo comentario dice literalmente «USING INPUT
FROM INTERNAL AUTHENTICATE»: es una respuesta de Autenticación Activa de un
eMRTD, con desafío de 8 bytes, SHA-1 y tráiler implícito. BouncyCastle es
además la implementación que JMRTD usa contra chips reales en Android, así que
el vector no es una curiosidad de laboratorio: es lo que valida el lector que
llevamos en el teléfono.

El vector ancla las DOS direcciones:

  1. el verificador acepta una firma que no calculó él;
  2. el firmante de `emrtd_fixtures` reproduce esa misma firma byte a byte.

Sin (2), el resto de la suite estaría comprobando que dos módulos nuestros se
entienden entre ellos.
"""

import hashlib

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from app.services import active_auth

import emrtd_fixtures as fx

# === Vector conocido: BouncyCastle ISO9796Test.doTest13 =====================

KAT_MODULUS = int(
    "CDCBDABBF93BE8E8294E32B055256BBD0397735189BF75816341BB0D488D05D6"
    "27991221DF7D59835C76A4BB4808ADEEB779E7794504E956ADC2A661B46904CD"
    "C71337DD29DDDD454124EF79CFDD7BC2C21952573CEFBA485CC38C6BD2428809"
    "B5A31A898A6B5648CAA4ED678D9743B589134B7187478996300EDBA16271A861",
    16,
)
KAT_PUBLIC_EXPONENT = 0x010001
KAT_PRIVATE_EXPONENT = int(
    "4BA6432AD42C74AA5AFCB6DF60FD57846CBC909489994ABD9C59FE439CC6D23D"
    "6DE2F3EA65B8335E796FD7904CA37C248367997257AFBD82B26F1A30525C447A"
    "236C65E6ADE43ECAAF7283584B2570FA07B340D9C9380D88EAACFFAEEFE7F472"
    "DBC9735C3FF3A3211E8A6BBFD94456B6A33C17A2C4EC18CE6335150548ED126D",
    16,
)
#: Desafío del vector: 8 bytes a cero.
KAT_CHALLENGE = bytes(8)
KAT_SIGNATURE = bytes.fromhex(
    "482E20D1EDDED34359C38F5E7C01203F9D6B2641CDCA5C404D49ADAEDE034C74"
    "81D781D043722587761C90468DE69C6585A1E8B9C322F90E1B580EEDAB3F6007"
    "D0C366CF92B4DB8B41C8314929DCE2BE889C0129123484D2FD3D12763D2EBFD1"
    "2AC8E51D7061AFCA1A53DEDEC7B9A617472A78C952CCC72467AE008E5F132994"
)
#: Relleno aleatorio que generó el chip del vector (la parte recuperable, M1).
KAT_RECOVERED_M1 = bytes.fromhex(
    "539BB29260E7BC226C8798B01AF2CAAADC3675E26065E1E3856615894D5BAEF7"
    "D97634278D6DD609CF9091B68B248CC2F817CCC2E98AD7EFA3B730EE97AFC20A"
    "D5C00E24F8A49B89CDB05613B5CE2094CC21C9AFB84A23C771BE5CA500E8FB5D"
    "75F40D93CAB6EE019569"
)


def kat_public_key() -> rsa.RSAPublicKey:
    return rsa.RSAPublicNumbers(KAT_PUBLIC_EXPONENT, KAT_MODULUS).public_key()


def test_the_verifier_accepts_a_signature_it_did_not_produce():
    """El ancla: una firma real de INTERNAL AUTHENTICATE, verificada aquí."""
    assert (
        active_auth.verify_iso9796_2_ds1(kat_public_key(), KAT_CHALLENGE, KAT_SIGNATURE)
        == "sha1"
    )


def test_the_fixture_signer_reproduces_the_known_signature_byte_for_byte():
    """Y el ancla en la otra dirección: el firmante del fixture no es propio.

    Si esto falla, todos los demás tests que firman con `emrtd_fixtures` están
    comprobando un esquema inventado, no ISO/IEC 9796-2.
    """
    block = fx.iso9796_2_ds1_block(
        128, KAT_CHALLENGE, digest="sha1", m1=KAT_RECOVERED_M1
    )
    signature = pow(
        int.from_bytes(block, "big"), KAT_PRIVATE_EXPONENT, KAT_MODULUS
    ).to_bytes(128, "big")
    assert signature == KAT_SIGNATURE


def test_another_challenge_does_not_verify_against_the_same_signature():
    """Lo que hace de esto un anti-replay: la firma vale para UN desafío."""
    with pytest.raises(active_auth.ActiveAuthError):
        active_auth.verify_iso9796_2_ds1(
            kat_public_key(), b"\x00" * 7 + b"\x01", KAT_SIGNATURE
        )


def test_a_pkcs1v15_signature_is_rejected():
    """La rama RSA del commit sin fusionar, comprobada como lo que era.

    Si el verificador aceptara PKCS#1 v1.5 estaría admitiendo firmas que
    ningún chip produce, y —peor— no estaría comprobando el esquema que sí
    producen: una cédula real nunca habría pasado.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    challenge = b"\x11" * 8
    signature = key.sign(challenge, padding.PKCS1v15(), hashes.SHA256())
    with pytest.raises(active_auth.ActiveAuthError):
        active_auth.verify_iso9796_2_ds1(key.public_key(), challenge, signature)


# === Estructura del esquema ================================================


@pytest.fixture(scope="module")
def aa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def test_a_freshly_signed_challenge_verifies(aa_key):
    challenge = b"\xa1\xb2\xc3\xd4\xe5\xf6\x07\x18"
    signature = fx.iso9796_2_ds1_signature(aa_key, challenge)
    assert (
        active_auth.verify_iso9796_2_ds1(aa_key.public_key(), challenge, signature)
        == "sha1"
    )


def test_both_roots_of_the_signature_are_opened(aa_key):
    """ISO/IEC 9796-2 §8.3 admite `s` y `n − s`; B.7 obliga a abrir las dos.

    Comprobar solo una rechazaría, de media, la mitad de los documentos
    legítimos — y el fallo parecería un chip defectuoso.
    """
    challenge = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    signature = fx.iso9796_2_ds1_signature(
        aa_key, challenge, least_absolute_residue=True
    )
    assert (
        active_auth.verify_iso9796_2_ds1(aa_key.public_key(), challenge, signature)
        == "sha1"
    )


def test_a_signature_from_another_chip_is_rejected(aa_key):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    challenge = b"\x99" * 8
    signature = fx.iso9796_2_ds1_signature(other, challenge)
    with pytest.raises(active_auth.ActiveAuthError):
        active_auth.verify_iso9796_2_ds1(aa_key.public_key(), challenge, signature)


def test_a_flipped_bit_in_the_signature_is_rejected(aa_key):
    challenge = b"\x42" * 8
    signature = bytearray(fx.iso9796_2_ds1_signature(aa_key, challenge))
    signature[64] ^= 0x01
    with pytest.raises(active_auth.ActiveAuthError):
        active_auth.verify_iso9796_2_ds1(
            aa_key.public_key(), challenge, bytes(signature)
        )


def test_a_signature_of_the_wrong_length_is_rejected(aa_key):
    challenge = b"\x42" * 8
    signature = fx.iso9796_2_ds1_signature(aa_key, challenge)
    with pytest.raises(active_auth.ActiveAuthError):
        active_auth.verify_iso9796_2_ds1(aa_key.public_key(), challenge, signature[:-1])


def test_sha256_in_an_explicit_trailer_verifies(aa_key):
    """Tráiler de dos bytes: `0x34CC` es SHA-256 según ISO/IEC 10118-3.

    Se construye a mano porque el fixture solo emite tráiler implícito, y el
    punto es que el verificador lea el identificador en vez de dar SHA-1 por
    supuesto.
    """
    challenge = b"\x5a" * 8
    numbers = aa_key.private_numbers()
    modulus = numbers.public_numbers.n
    block_length = (modulus.bit_length() + 7) // 8
    m1 = bytes(block_length - 32 - 3)
    block = (
        bytes([0x6A])
        + m1
        + hashlib.sha256(m1 + challenge).digest()
        + bytes([0x34, 0xCC])
    )
    signature = pow(int.from_bytes(block, "big"), numbers.d, modulus).to_bytes(
        block_length, "big"
    )
    assert (
        active_auth.verify_iso9796_2_ds1(aa_key.public_key(), challenge, signature)
        == "sha256"
    )


# === EF.DG15 ===============================================================


def test_dg15_is_parsed_through_its_6f_wrapper(aa_key):
    """Un DG15 real viene envuelto en `6F`. Cargarlo entero como SPKI falla."""
    parsed = active_auth.parse_dg15(fx.dg15(aa_key.public_key()))
    assert isinstance(parsed, rsa.RSAPublicKey)
    assert parsed.public_numbers() == aa_key.public_key().public_numbers()


def test_a_dg15_that_is_not_a_public_key_fails_closed():
    with pytest.raises(active_auth.ActiveAuthError):
        active_auth.parse_dg15(b"\x6f\x04\xde\xad\xbe\xef")


def test_a_truncated_dg15_fails_closed():
    with pytest.raises(active_auth.ActiveAuthError):
        active_auth.parse_dg15(b"\x6f\x40\x01\x02")


# === ECDSA (BSI TR-03111, formato plano) ===================================

ECDSA_PLAIN_SHA256 = "0.4.0.127.0.7.1.1.4.1.3"


@pytest.fixture(scope="module")
def ec_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def test_ecdsa_active_authentication_uses_the_hash_declared_in_dg14(ec_key):
    challenge = b"\x0f" * 8
    result = active_auth.verify(
        dg15=fx.dg15(ec_key.public_key()),
        challenge=challenge,
        signature=fx.ecdsa_plain_signature(ec_key, challenge),
        dg14=fx.dg14(ECDSA_PLAIN_SHA256),
    )
    assert result.scheme == "ecdsa-plain"
    assert result.digest_algorithm == "sha256"


def test_ecdsa_without_dg14_is_refused_instead_of_guessing(ec_key):
    """ICAO no fija un hash por defecto para ECDSA. Adivinarlo sería inventar."""
    challenge = b"\x0f" * 8
    with pytest.raises(active_auth.ActiveAuthError, match="DG14"):
        active_auth.verify(
            dg15=fx.dg15(ec_key.public_key()),
            challenge=challenge,
            signature=fx.ecdsa_plain_signature(ec_key, challenge),
        )


def test_a_der_encoded_ecdsa_signature_is_rejected(ec_key):
    """Los chips devuelven `r ‖ s`, no DER. Aceptar DER admitiría longitudes
    que la curva no produce y dejaría el formato sin comprobar."""
    challenge = b"\x0f" * 8
    der = ec_key.sign(challenge, ec.ECDSA(hashes.SHA256()))
    with pytest.raises(active_auth.ActiveAuthError):
        active_auth.verify(
            dg15=fx.dg15(ec_key.public_key()),
            challenge=challenge,
            signature=der,
            dg14=fx.dg14(ECDSA_PLAIN_SHA256),
        )


def test_an_ecdsa_signature_over_another_challenge_is_rejected(ec_key):
    with pytest.raises(active_auth.ActiveAuthError):
        active_auth.verify(
            dg15=fx.dg15(ec_key.public_key()),
            challenge=b"\x0f" * 8,
            signature=fx.ecdsa_plain_signature(ec_key, b"\x10" * 8),
            dg14=fx.dg14(ECDSA_PLAIN_SHA256),
        )


# === API ===================================================================


def test_the_challenge_must_be_eight_bytes(aa_key):
    """Un desafío de otro tamaño es un fallo NUESTRO, no del documento."""
    with pytest.raises(active_auth.ActiveAuthError, match="8"):
        active_auth.verify(
            dg15=fx.dg15(aa_key.public_key()),
            challenge=b"\x01" * 16,
            signature=b"\x00" * 256,
        )


def test_the_result_binds_to_the_dg15_it_verified(aa_key):
    challenge = b"\x77" * 8
    dg15 = fx.dg15(aa_key.public_key())
    result = active_auth.verify(
        dg15=dg15,
        challenge=challenge,
        signature=fx.iso9796_2_ds1_signature(aa_key, challenge),
    )
    assert result.scheme == "rsa-iso9796-2-ds1"
    assert result.key_bits == 2048
    assert result.dg15_sha256 == hashlib.sha256(dg15).hexdigest()
    # El resultado no lleva nada del titular: solo material público del chip.
    assert set(result.as_dict()) == {
        "scheme",
        "digest_algorithm",
        "key_bits",
        "dg15_sha256",
    }
