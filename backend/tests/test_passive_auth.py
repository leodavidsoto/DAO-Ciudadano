"""
Autenticación Pasiva del EF.SOD en el servidor (ROADMAP 5.8).

Cada test que espera un fallo nombra el ataque concreto que evita. Un
verificador que sólo se prueba con documentos válidos no está probado: lo que
importa no es que diga "sí" a una cédula auténtica, sino que diga "no" a todo
lo demás.
"""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from app.services import csca_trust_store, passive_auth

import emrtd_fixtures as fx

DG1 = b"\x61\x1d\x5f\x1f\x1aI<CHL12345678<<<<<<<<<<<<<<"
DG2 = b"\x75\x10" + b"\xff" * 16
DATA_GROUPS = {1: DG1, 2: DG2}


@pytest.fixture
def csca():
    return fx.make_csca()


@pytest.fixture
def dsc(csca):
    return fx.make_dsc(csca)


@pytest.fixture
def trust_store(tmp_path, monkeypatch, csca):
    """Instala un trust store con esta CSCA y sólo esta."""

    def _install(*certificates):
        path = tmp_path / "csca_test.pem"
        path.write_bytes(fx.trust_store_pem(*certificates))
        monkeypatch.setattr(
            csca_trust_store.settings, "CSCA_TRUST_STORE_PATH", str(path)
        )
        csca_trust_store.reset_cache()
        return path

    _install(csca.certificate)
    yield _install
    csca_trust_store.reset_cache()


# ---------------------------------------------------------------------------
# El camino feliz
# ---------------------------------------------------------------------------


def test_verifies_a_well_formed_document(trust_store, csca, dsc):
    sod = fx.build_sod(dsc, DATA_GROUPS)

    result = passive_auth.verify(sod, DATA_GROUPS)

    assert result.verified_data_groups == (1, 2)
    assert result.trust_anchor_subject == csca.certificate.subject.rfc4514_string()
    assert result.signature_algorithm == "rsassa_pkcs1v15-sha256"
    # La ruta empieza en el DSC y termina en el ancla.
    assert len(result.chain_subjects) == 2


def test_accepts_the_content_info_without_the_ef_sod_wrapper(trust_store, dsc):
    """Según la librería del cliente, el SOD llega con o sin [APPLICATION 23]."""
    sod = fx.build_sod(dsc, DATA_GROUPS, wrap_ef_sod=False)

    assert passive_auth.verify(sod, DATA_GROUPS).verified_data_groups == (1, 2)


def test_extra_data_groups_are_verified_too(trust_store, dsc):
    groups = {**DATA_GROUPS, 11: b"\x6b\x04datos"}
    sod = fx.build_sod(dsc, groups)

    assert passive_auth.verify(sod, groups).verified_data_groups == (1, 2, 11)


# ---------------------------------------------------------------------------
# Manipulación del contenido
# ---------------------------------------------------------------------------


def test_rejects_a_modified_data_group(trust_store, dsc):
    """El ataque básico: cambiar la MRZ dejando la firma original."""
    sod = fx.build_sod(dsc, DATA_GROUPS)
    tampered = {**DATA_GROUPS, 1: DG1.replace(b"12345678", b"87654321")}

    with pytest.raises(passive_auth.PassiveAuthError) as exc:
        passive_auth.verify(sod, tampered)

    assert "DG1" in str(exc.value.reasons)


def test_rejects_a_substituted_econtent(trust_store, dsc):
    """SOD con firma válida sobre unos atributos y OTRO contenido.

    Es el fallo clásico de los verificadores que comprueban la firma pero no
    el `messageDigest`: la firma verifica, y aun así el documento que se lee
    no es el que se firmó.
    """
    other = fx.lds_security_object({1: b"otro dg1", 2: DG2})
    sod = fx.build_sod(dsc, DATA_GROUPS, econtent_override=other)

    with pytest.raises(passive_auth.PassiveAuthError) as exc:
        passive_auth.verify(sod, DATA_GROUPS)

    assert "messageDigest" in str(exc.value)


def test_rejects_signed_attributes_without_message_digest(trust_store, dsc):
    """Sin messageDigest la firma no queda ligada a ningún contenido."""
    sod = fx.build_sod(dsc, DATA_GROUPS, omit_message_digest=True)

    with pytest.raises(passive_auth.PassiveAuthError) as exc:
        passive_auth.verify(sod, DATA_GROUPS)

    assert "messageDigest" in str(exc.value)


def test_rejects_a_wrong_message_digest(trust_store, dsc):
    sod = fx.build_sod(dsc, DATA_GROUPS, wrong_message_digest=True)

    with pytest.raises(passive_auth.PassiveAuthError):
        passive_auth.verify(sod, DATA_GROUPS)


def test_rejects_a_missing_required_data_group(trust_store, dsc):
    """Mandar sólo DG2 dejaría la identidad (DG1) sin comprobar."""
    sod = fx.build_sod(dsc, DATA_GROUPS)

    with pytest.raises(passive_auth.PassiveAuthError) as exc:
        passive_auth.verify(sod, {2: DG2})

    assert "DG1" in str(exc.value)


def test_rejects_an_empty_read(trust_store, dsc):
    sod = fx.build_sod(dsc, DATA_GROUPS)

    with pytest.raises(passive_auth.PassiveAuthError):
        passive_auth.verify(sod, {})


# ---------------------------------------------------------------------------
# Cadena de confianza
# ---------------------------------------------------------------------------


def test_rejects_a_document_signed_by_an_unknown_csca(trust_store, dsc):
    """El ataque que hace inútil toda la PA si no se comprueba: un documento
    falsificado trae su propia raíz y valida contra sí mismo."""
    forged_csca = fx.make_csca(common_name="CSCA Falsificada")
    forged_dsc = fx.make_dsc(forged_csca)
    sod = fx.build_sod(
        forged_dsc, DATA_GROUPS, extra_certificates=(forged_csca.certificate,)
    )

    with pytest.raises(passive_auth.PassiveAuthError) as exc:
        passive_auth.verify(sod, DATA_GROUPS)

    assert "no encadena" in str(exc.value)


def test_a_csca_shipped_inside_the_document_is_not_an_anchor(trust_store, dsc):
    """Incluir la raíz en el propio SOD no la convierte en confiable."""
    forged_csca = fx.make_csca()
    forged_dsc = fx.make_dsc(forged_csca)
    sod = fx.build_sod(
        forged_dsc,
        DATA_GROUPS,
        # Mismo DN que la CSCA legítima, para que ni el nombre ayude.
        extra_certificates=(forged_csca.certificate,),
    )

    with pytest.raises(passive_auth.PassiveAuthError):
        passive_auth.verify(sod, DATA_GROUPS)


def test_chains_through_a_link_certificate(trust_store, csca):
    """Rotación de clave: el ancla instalada es la generación ANTERIOR.

    Es el caso real del Registro Civil desde 2024, y el que rompe cualquier
    implementación que sólo mire anclas directas.
    """
    successor = fx.make_csca()
    link = fx.make_link_certificate(csca, successor)
    new_dsc = fx.make_dsc(successor)
    trust_store(csca.certificate, link)

    result = passive_auth.verify(fx.build_sod(new_dsc, DATA_GROUPS), DATA_GROUPS)

    assert result.trust_anchor_subject == csca.certificate.subject.rfc4514_string()
    assert len(result.chain_subjects) == 3  # DSC -> link -> ancla


def test_a_link_certificate_alone_is_not_an_anchor(trust_store, csca):
    """Un eslabón sin su raíz no cierra la cadena.

    Como su `subject` coincide con su `issuer`, un clasificador que mire DNs
    lo tomaría por raíz. Aquí se comprueba que no ocurre.
    """
    successor = fx.make_csca()
    link = fx.make_link_certificate(csca, successor)
    new_dsc = fx.make_dsc(successor)
    trust_store(link)  # sólo el eslabón, sin la raíz

    with pytest.raises(csca_trust_store.TrustStoreError):
        passive_auth.verify(fx.build_sod(new_dsc, DATA_GROUPS), DATA_GROUPS)


def test_rejects_an_expired_document_signer(trust_store, csca):
    past = datetime.now(timezone.utc) - timedelta(days=400)
    expired = fx.make_dsc(
        csca, not_before=past, not_after=past + timedelta(days=30)
    )

    with pytest.raises(passive_auth.PassiveAuthError) as exc:
        passive_auth.verify(fx.build_sod(expired, DATA_GROUPS), DATA_GROUPS)

    assert "expiró" in str(exc.value)


def test_rejects_an_expired_trust_anchor(trust_store):
    past = datetime.now(timezone.utc) - timedelta(days=800)
    old_csca = fx.make_csca(not_before=past, not_after=past + timedelta(days=100))
    old_dsc = fx.make_dsc(old_csca, not_before=past, not_after=past + timedelta(days=90))
    trust_store(old_csca.certificate)

    with pytest.raises(passive_auth.PassiveAuthError):
        passive_auth.verify(fx.build_sod(old_dsc, DATA_GROUPS), DATA_GROUPS)


def test_rejects_a_sod_whose_signer_certificate_is_absent(trust_store, csca, dsc):
    """El SOD debe traer el certificado con el que dice haberse firmado.

    Aquí viaja OTRO certificado legítimo de la misma CSCA. Un verificador que
    tome "el primer certificado del SOD" en vez de buscar por `sid` intentaría
    validar con el equivocado — y si el atacante controla ese otro par de
    claves, la firma verificaría.
    """
    decoy = fx.make_dsc(csca, common_name="Otro Document Signer")
    sod = fx.build_sod(
        dsc,
        DATA_GROUPS,
        omit_signer_certificate=True,
        extra_certificates=(decoy.certificate,),
    )

    with pytest.raises(passive_auth.PassiveAuthError) as exc:
        passive_auth.verify(sod, DATA_GROUPS)

    assert "no contiene el certificado" in str(exc.value)


# ---------------------------------------------------------------------------
# Entrada malformada
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"no soy asn.1",
        b"\x77\x03\x01\x02\x03",  # envoltorio EF.SOD con basura dentro
        b"\x30\x03\x02\x01\x00",  # DER válido que no es un ContentInfo
    ],
)
def test_rejects_malformed_input(trust_store, payload):
    """Basura entra, error sale — nunca una excepción sin controlar."""
    with pytest.raises(passive_auth.PassiveAuthError):
        passive_auth.verify(payload, DATA_GROUPS)


def test_fails_closed_without_a_trust_store(tmp_path, monkeypatch, dsc):
    """Sin anclas no se verifica nada: no hay modo degradado."""
    monkeypatch.setattr(
        csca_trust_store.settings,
        "CSCA_TRUST_STORE_PATH",
        str(tmp_path / "no-existe.pem"),
    )
    csca_trust_store.reset_cache()

    with pytest.raises(csca_trust_store.TrustStoreError):
        passive_auth.verify(fx.build_sod(dsc, DATA_GROUPS), DATA_GROUPS)

    csca_trust_store.reset_cache()


# ---------------------------------------------------------------------------
# El trust store real del Registro Civil
# ---------------------------------------------------------------------------


def test_the_shipped_chilean_trust_store_loads_with_anchors():
    """El .pem que se despliega tiene que cargar y tener anclas de verdad.

    Si alguien regenera el archivo con un filtro equivocado y deja dentro sólo
    link certificates, la app arrancaría y rechazaría TODAS las cédulas. Esto
    lo detecta en CI en vez de en producción.
    """
    csca_trust_store.reset_cache()
    store = csca_trust_store.load()

    assert store.anchors, "El trust store desplegado no tiene ninguna ancla"
    for anchor in store.anchors:
        # Definición criptográfica, no comparación de DN.
        anchor.verify_directly_issued_by(anchor)
        subject = anchor.subject.rfc4514_string()
        assert "C=CL" in subject
        assert "Registro Civil" in subject


def test_the_shipped_link_certificates_chain_to_an_anchor():
    """Todo eslabón del archivo tiene que llevar a alguna raíz. Uno huérfano
    sería un certificado en el que confiamos sin saber por qué está ahí."""
    csca_trust_store.reset_cache()
    store = csca_trust_store.load()

    for link in store.links:
        assert any(
            _issued_by(link, candidate) for candidate in store.certificates
        ), f"Link certificate huérfano en el trust store: {link.subject.rfc4514_string()}"


def _issued_by(certificate, issuer) -> bool:
    if certificate == issuer:
        return False
    try:
        certificate.verify_directly_issued_by(issuer)
    except Exception:
        return False
    return True
