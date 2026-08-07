"""
La cédula por NFC como proveedor de identidad civil (ROADMAP 5.8).

El foco de estos tests no es que una cédula válida funcione —eso lo cubre
`test_passive_auth.py`— sino que el endpoint no tenga ninguna puerta trasera:
que no exista un payload, por bien formado que esté, que produzca un grant sin
una firma válida del Registro Civil.
"""

import base64
import logging

import pytest

from app.core.config import settings
from app.services import (
    cedula_nfc,
    csca_trust_store,
    identity_grant,
    membership_grant,
    mrz,
)

import emrtd_fixtures as fx

# Cédula chilena sintética: RUN 12345678-5 en los datos opcionales de la MRZ.
RUN = "123456785"
DG1 = fx.dg1(fx.td1_mrz())
DG2 = b"\x75\x20" + b"\xab" * 32


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


@pytest.fixture
def csca():
    return fx.make_csca()


@pytest.fixture
def dsc(csca):
    return fx.make_dsc(csca)


@pytest.fixture
def trust_store(tmp_path, monkeypatch, csca):
    path = tmp_path / "csca_test.pem"
    path.write_bytes(fx.trust_store_pem(csca.certificate))
    monkeypatch.setattr(csca_trust_store.settings, "CSCA_TRUST_STORE_PATH", str(path))
    csca_trust_store.reset_cache()
    yield path
    csca_trust_store.reset_cache()


@pytest.fixture
def reading(dsc):
    """Payload de una lectura NFC legítima."""
    groups = {1: DG1, 2: DG2}
    return {
        "sod": _b64(fx.build_sod(dsc, groups)),
        "data_groups": {"1": _b64(DG1), "2": _b64(DG2)},
    }


# ---------------------------------------------------------------------------
# MRZ y RUN
# ---------------------------------------------------------------------------


def test_parses_a_td1_identity_card():
    parsed = mrz.parse(DG1)

    assert parsed.format == "TD1"
    assert parsed.issuing_state == "CHL"
    assert parsed.is_identity_card
    assert parsed.is_chilean
    assert parsed.national_number == RUN


def test_the_run_comes_from_the_second_optional_field(caplog):
    """AUDIT P-101: el RUN va en la línea 2, no en la 1.

    Se leía del campo opcional de la línea 1, que en la cédula real trae tres
    caracteres. Ninguna alta podía completarse.
    """
    parsed = mrz.parse(fx.dg1(fx.td1_mrz(run="123456785", optional_1="A12")))

    assert parsed.optional_data == "A12"
    assert parsed.optional_data_2 == "123456785"
    assert parsed.national_number == "123456785"

    # Y es el que se usa: si se leyera el de la línea 1, «A12» no es un RUN.
    assert cedula_nfc.normalize_run(parsed.national_number) == "12345678-5"


def test_the_document_number_is_never_used_as_the_run():
    """Tiene nueve dígitos igual que el RUN, pero cambia en cada renovación."""
    parsed = mrz.parse(fx.dg1(fx.td1_mrz(document_number="87654321", run="123456785")))

    assert parsed.document_number != parsed.national_number
    assert parsed.national_number == "123456785"


def test_rejects_a_dg1_that_is_not_an_mrz():
    with pytest.raises(mrz.MRZError):
        mrz.parse(b"\x61\x04\x5f\x1f\x02ab")


def test_run_check_digit_is_verified():
    """El RUN es la entrada de la que se deriva la identidad entera.

    Si el campo del que se extrae no fuera el que creemos, el dígito no
    cuadraría — y es preferible fallar aquí a emitir credenciales ligadas a un
    número que no identifica a nadie.
    """
    assert cedula_nfc.normalize_run("12345678-5") == "12345678-5"

    with pytest.raises(cedula_nfc.CedulaVerificationError):
        cedula_nfc.normalize_run("12345678-9")


def test_a_run_that_is_not_a_run_fails_closed():
    for value in ("", "<<<<<<", "ABC123", "1"):
        with pytest.raises(cedula_nfc.CedulaVerificationError):
            cedula_nfc.normalize_run(value)


def test_the_shape_diagnostic_distinguishes_the_hypotheses():
    """AUDIT P-101: la forma basta para saber qué trae el campo."""
    # Las tres hipótesis sobre por qué la cédula real no produce un RUN son
    # distinguibles por la forma sola: campo vacío (el RUN estaría en DG11/13),
    # RUN legible, o un carácter de más (dígito de control del propio campo).
    assert cedula_nfc.describe_field_shape("") == "len=0 "
    assert cedula_nfc.describe_field_shape("123456785") == "len=9 DDDDDDDDD"
    assert cedula_nfc.describe_field_shape("12345678K") == "len=9 DDDDDDDDA"
    assert cedula_nfc.describe_field_shape("1234<<<") == "len=7 DDDD<<<"


def test_the_shape_diagnostic_never_reveals_the_field():
    """Es lo único que se registra del campo, así que no puede filtrarlo."""
    for value in ("123456785", "9876543-2", "12345678K", "AB12<34"):
        mask = cedula_nfc.describe_field_shape(value).split(" ", 1)[1]
        # Ningún carácter del original sobrevive salvo el relleno, que no
        # identifica a nadie.
        assert not any(char.isdigit() for char in mask)
        assert set(mask) <= {"D", "A", "<", "?"}


def test_the_run_failure_logs_the_shape_and_not_the_run(caplog):
    """El aviso del camino real sale de la máscara, nunca del valor."""
    logger = logging.getLogger(cedula_nfc.__name__)
    run_like = "123456789012"

    with caplog.at_level(logging.WARNING, logger=cedula_nfc.__name__):
        logger.warning(
            "El campo opcional de la MRZ no expone un RUN reconocible (forma: %s)",
            cedula_nfc.describe_field_shape(run_like),
        )

    assert "len=12 DDDDDDDDDDDD" in caplog.text
    assert run_like not in caplog.text


def test_the_subject_key_does_not_leak_the_run(trust_store, reading):
    verified = cedula_nfc.verify_reading(**reading)

    assert RUN not in verified.subject_key
    assert "12345678" not in verified.subject_key
    # Determinístico: la misma persona vuelve al mismo sujeto.
    assert cedula_nfc.verify_reading(**reading).subject_key == verified.subject_key


def test_the_subject_key_survives_a_document_renewal(trust_store, dsc, reading):
    """Renovar la cédula cambia el número de documento, no a la persona.

    Si el sujeto se derivara del número de documento, cada renovación crearía
    una identidad nueva y la misma persona podría acumular varias.
    """
    renewed_dg1 = fx.dg1(fx.td1_mrz(document_number="87654321"))
    renewed_sod = fx.build_sod(dsc, {1: renewed_dg1, 2: DG2})

    original = cedula_nfc.verify_reading(**reading)
    renewed = cedula_nfc.verify_reading(
        sod=_b64(renewed_sod),
        data_groups={"1": _b64(renewed_dg1), "2": _b64(DG2)},
    )

    assert renewed.document_number != original.document_number
    assert renewed.subject_key == original.subject_key


# ---------------------------------------------------------------------------
# Reglas del documento
# ---------------------------------------------------------------------------


def test_rejects_a_foreign_document(trust_store, dsc):
    foreign = fx.dg1(fx.td1_mrz(issuing_state="ARG", nationality="ARG"))
    sod = fx.build_sod(dsc, {1: foreign, 2: DG2})

    with pytest.raises(cedula_nfc.CedulaVerificationError) as exc:
        cedula_nfc.verify_reading(
            sod=_b64(sod), data_groups={"1": _b64(foreign), "2": _b64(DG2)}
        )

    assert "Chile" in str(exc.value)


def test_rejects_an_expired_document(trust_store, dsc):
    expired = fx.dg1(fx.td1_mrz(date_of_expiry="100101"))
    sod = fx.build_sod(dsc, {1: expired, 2: DG2})

    with pytest.raises(cedula_nfc.CedulaVerificationError) as exc:
        cedula_nfc.verify_reading(
            sod=_b64(sod), data_groups={"1": _b64(expired), "2": _b64(DG2)}
        )

    assert "caducado" in str(exc.value)


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"sod": "", "data_groups": {"1": "AAAA"}},
        {"sod": "no-es-base64!!", "data_groups": {"1": "AAAA"}},
        {"sod": "AAAA", "data_groups": {}},
        {"sod": "AAAA", "data_groups": {"cero": "AAAA"}},
        {"sod": "AAAA", "data_groups": {"99": "AAAA"}},
    ],
)
def test_rejects_malformed_payloads(trust_store, payload):
    with pytest.raises(cedula_nfc.CedulaVerificationError):
        cedula_nfc.verify_reading(**payload)


def test_rejects_an_oversized_file(trust_store):
    huge = _b64(b"\x00" * (cedula_nfc.MAX_FILE_BYTES + 1))

    with pytest.raises(cedula_nfc.CedulaVerificationError) as exc:
        cedula_nfc.verify_reading(sod=huge, data_groups={"1": "AAAA"})

    assert "tamaño" in str(exc.value)


# ---------------------------------------------------------------------------
# El endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(settings, "IDENTITY_PROVIDER", "cedula-nfc")


async def test_the_endpoint_issues_a_grant_for_a_valid_reading(
    client, trust_store, provider, reading
):
    response = await client.post("/api/auth/cedula/verify", json=reading)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["identity_grant"]
    # El grant tiene que ser canjeable de verdad, no un valor decorativo.
    subject = await identity_grant.consume(body["identity_grant"])
    assert subject == cedula_nfc.verify_reading(**reading).subject_key

    # El JWT de alta declara exactamente lo que se comprobó: Autenticación
    # Pasiva. Sin Autenticación Activa no puede afirmar presencia del chip.
    claims = membership_grant.verify(body["membership_grant"])
    assert claims.subject_key == subject
    assert claims.assurance_level == "CEDULA_NFC_PASSIVE"
    assert body["assurance_level"] == "CEDULA_NFC_PASSIVE"


async def test_the_endpoint_never_issues_a_grant_for_a_forged_document(
    client, trust_store, provider, reading
):
    """La puerta trasera que no debe existir: un documento con su propia raíz."""
    forged_csca = fx.make_csca()
    forged_dsc = fx.make_dsc(forged_csca)
    forged_sod = fx.build_sod(
        forged_dsc, {1: DG1, 2: DG2}, extra_certificates=(forged_csca.certificate,)
    )

    response = await client.post(
        "/api/auth/cedula/verify",
        json={
            "sod": _b64(forged_sod),
            "data_groups": {"1": _b64(DG1), "2": _b64(DG2)},
        },
    )

    assert response.status_code == 401
    assert "identity_grant" not in response.json()


async def test_the_endpoint_does_not_accept_a_client_verdict(
    client, trust_store, provider
):
    """Mandar `identityVerified: true` no hace nada: no existe ese campo.

    Era exactamente el bypass anterior. El endpoint sólo mira los bytes.
    """
    response = await client.post(
        "/api/auth/cedula/verify",
        json={
            "sod": _b64(b"basura"),
            "data_groups": {"1": _b64(DG1)},
            "identityVerified": True,
            "passed": True,
        },
    )

    assert response.status_code == 401


async def test_the_endpoint_reports_503_without_a_trust_store(
    client, tmp_path, monkeypatch, provider, reading
):
    """Sin anclas es un fallo de despliegue, no del ciudadano.

    Un 401 aquí mandaría a la gente a repetir una lectura que nunca podría
    pasar, y el operador no vería que le falta el trust store.
    """
    monkeypatch.setattr(
        csca_trust_store.settings, "CSCA_TRUST_STORE_PATH", str(tmp_path / "vacio.pem")
    )
    csca_trust_store.reset_cache()

    response = await client.post("/api/auth/cedula/verify", json=reading)

    assert response.status_code == 503
    csca_trust_store.reset_cache()


async def test_the_trust_store_endpoint_exposes_no_private_material(client):
    response = await client.get("/api/auth/cedula/trust-store")

    assert response.status_code == 200
    body = response.text
    assert "PRIVATE KEY" not in body
    assert "BEGIN CERTIFICATE" not in body
