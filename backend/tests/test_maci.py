"""
Registro de llaves públicas MACI (ADR-001, D-3).

Lo que se protege aquí:

1. Que solo entren puntos que están **de verdad** en Baby Jubjub. Una llave
   fuera de la curva no sirve para cifrar hacia el coordinador: la papeleta
   quedaría ilegible y el voto se perdería en silencio.
2. Que cambiar de llave funcione y quede historial: en MACI ese cambio es el
   mecanismo con el que un votante anula en secreto una papeleta emitida bajo
   coacción. Impedirlo rompería la garantía central del protocolo.
3. Que el endpoint de estado no dé a entender que ya se puede votar en privado.
"""
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from app.services import maci_service

VOTER = Account.from_key("0x" + "a1" * 32)
OUTSIDER = Account.from_key("0x" + "b2" * 32)

# Generador del subgrupo de orden primo de Baby Jubjub (EIP-2494 / circomlib).
BASE_X = 5299619240641551281634865583518297030282874472190772894086521144482721001553
BASE_Y = 16950150798460657717958625567821834550301663161624707787222815936182638968203

# Otro punto real de la curva: 2·Base8, para probar el cambio de llave.
DOUBLE_X = 6890855772600357754907169075114257697580319025794532037257385534741338397365
DOUBLE_Y = 4338620300185947561074059802482547481416142213883829469920100239455078257889


async def _headers_for(client, account):
    challenge = await client.post(
        "/api/wallet/challenge", json={"address": account.address}
    )
    data = challenge.json()
    signature = account.sign_message(
        encode_defunct(text=data["message"])
    ).signature.hex()
    verify = await client.post(
        "/api/wallet/verify",
        json={
            "address": account.address,
            "nonce": data["nonce"],
            "signature": signature,
        },
    )
    return {"Authorization": f"Bearer {verify.json()['token']}"}


async def _mint_member(client, account):
    headers = await _headers_for(client, account)
    response = await client.post(
        "/api/membership/mint",
        json={
            "wallet_address": account.address,
            "assurance_level": "AL2",
            "doc_hash": f"0xdoc{account.address[-8:]}",
        },
        headers=headers,
    )
    assert response.json()["ok"] is True
    return headers


def _key(x=BASE_X, y=BASE_Y):
    return {"x": str(x), "y": str(y)}


# === Validación de curva ===

def test_generator_is_recognised_as_on_curve():
    """Contraste contra el generador publicado: si esto falla, la ecuación está mal."""
    assert maci_service.is_on_babyjub_curve(BASE_X, BASE_Y) is True
    assert maci_service.is_on_babyjub_curve(DOUBLE_X, DOUBLE_Y) is True


def test_points_outside_the_curve_are_rejected():
    assert maci_service.is_on_babyjub_curve(12345, 67890) is False
    with pytest.raises(maci_service.MaciKeyError):
        maci_service.validate_public_key(12345, 67890)


def test_identity_point_is_not_a_usable_key():
    """(0,1) está en la curva pero corresponde a la clave privada cero."""
    assert maci_service.is_on_babyjub_curve(0, 1) is True
    with pytest.raises(maci_service.MaciKeyError):
        maci_service.validate_public_key(0, 1)


def test_coordinates_outside_the_field_are_rejected():
    with pytest.raises(maci_service.MaciKeyError):
        maci_service.validate_public_key(maci_service.BN254_FIELD, BASE_Y)
    with pytest.raises(maci_service.MaciKeyError):
        maci_service.validate_public_key(-1, BASE_Y)
    with pytest.raises(maci_service.MaciKeyError):
        maci_service.validate_public_key("no-es-un-entero", BASE_Y)


# === Endpoint ===

async def test_member_can_register_a_key(client):
    headers = await _mint_member(client, VOTER)

    response = await client.post(
        "/api/maci/keys",
        json={"wallet_address": VOTER.address, "public_key": _key()},
        headers=headers,
    )

    assert response.status_code == 200
    key = response.json()["key"]
    assert key["public_key"] == {"x": str(BASE_X), "y": str(BASE_Y)}
    assert key["version"] == 1
    assert key["wallet_address"] == VOTER.address.lower()


async def test_registration_requires_a_wallet_session(client):
    response = await client.post(
        "/api/maci/keys",
        json={"wallet_address": VOTER.address, "public_key": _key()},
    )
    assert response.status_code == 401


async def test_cannot_register_a_key_for_another_wallet(client):
    headers = await _mint_member(client, VOTER)

    response = await client.post(
        "/api/maci/keys",
        json={"wallet_address": OUTSIDER.address, "public_key": _key()},
        headers=headers,
    )

    assert response.status_code == 403


async def test_non_members_cannot_register(client):
    headers = await _headers_for(client, OUTSIDER)

    response = await client.post(
        "/api/maci/keys",
        json={"wallet_address": OUTSIDER.address, "public_key": _key()},
        headers=headers,
    )

    assert response.status_code == 403


async def test_off_curve_key_is_rejected_by_the_endpoint(client):
    headers = await _mint_member(client, VOTER)

    response = await client.post(
        "/api/maci/keys",
        json={"wallet_address": VOTER.address, "public_key": _key(12345, 67890)},
        headers=headers,
    )

    assert response.status_code == 422
    assert "Baby Jubjub" in response.json()["detail"]


# === Cambio de llave: el anti-coerción de MACI ===

async def test_changing_the_key_bumps_the_version_and_keeps_history(client):
    """Cambiar de llave es cómo se anula en secreto un voto coaccionado."""
    headers = await _mint_member(client, VOTER)

    first = await client.post(
        "/api/maci/keys",
        json={"wallet_address": VOTER.address, "public_key": _key()},
        headers=headers,
    )
    second = await client.post(
        "/api/maci/keys",
        json={
            "wallet_address": VOTER.address,
            "public_key": _key(DOUBLE_X, DOUBLE_Y),
        },
        headers=headers,
    )

    assert first.json()["key"]["version"] == 1
    assert second.json()["key"]["version"] == 2

    current = await maci_service.get_public_key(VOTER.address)
    assert (current.x, current.y) == (DOUBLE_X, DOUBLE_Y)

    # El coordinador necesita el orden de los cambios para procesar mensajes.
    history = await maci_service.maci_key_history_collection().find(
        {"wallet_address": VOTER.address.lower()}
    ).to_list(length=10)
    assert sorted(int(h["version"]) for h in history) == [1, 2]


async def test_resending_the_same_key_is_not_a_key_change(client):
    """Un reintento por timeout no debe parecer un cambio de llave."""
    headers = await _mint_member(client, VOTER)

    first = await client.post(
        "/api/maci/keys",
        json={"wallet_address": VOTER.address, "public_key": _key()},
        headers=headers,
    )
    second = await client.post(
        "/api/maci/keys",
        json={"wallet_address": VOTER.address, "public_key": _key()},
        headers=headers,
    )

    assert first.json()["key"]["version"] == second.json()["key"]["version"] == 1


# === Honestidad del estado ===

async def test_lookup_reports_unregistered_wallets_honestly(client):
    body = (await client.get(f"/api/maci/keys/{OUTSIDER.address}")).json()
    assert body["registered"] is False


async def test_status_does_not_claim_private_voting_works(client):
    """Existir /maci/keys no puede implicar que ya se vota en privado."""
    body = (await client.get("/api/maci/status")).json()

    assert body["key_registry"] is True
    assert body["private_voting"] is False
    assert body["coordinator_configured"] is False
    assert body["tally_proof"] is False


# === Votos cifrados ===

CIPHERTEXT = [str(i + 1) for i in range(10)]


async def _registered_voter(client):
    headers = await _mint_member(client, VOTER)
    await client.post(
        "/api/maci/keys",
        json={"wallet_address": VOTER.address, "public_key": _key()},
        headers=headers,
    )
    return headers


def _vote(**overrides):
    body = {
        "poll_id": "consulta-1",
        "wallet_address": VOTER.address,
        "ephemeral_public_key": _key(),
        "ciphertext": CIPHERTEXT,
    }
    body.update(overrides)
    return body


async def test_encrypted_vote_is_queued_with_its_order(client):
    """El índice y el acumulador fijan el ORDEN, que decide el resultado."""
    headers = await _registered_voter(client)

    first = await client.post("/api/maci/vote", json=_vote(), headers=headers)
    second = await client.post("/api/maci/vote", json=_vote(), headers=headers)

    assert first.status_code == 200
    assert first.json()["index"] == 0
    assert second.json()["index"] == 1
    # Encadenar hace que reordenar mensajes cambie el acumulador.
    assert first.json()["message_chain"] != second.json()["message_chain"]


async def test_vote_requires_a_registered_maci_key(client):
    """Sin llave registrada el coordinador no puede procesar la papeleta."""
    headers = await _mint_member(client, VOTER)

    response = await client.post("/api/maci/vote", json=_vote(), headers=headers)

    assert response.status_code == 409
    assert "llave MACI" in response.json()["detail"]


async def test_vote_cannot_be_cast_for_another_wallet(client):
    headers = await _registered_voter(client)

    response = await client.post(
        "/api/maci/vote",
        json=_vote(wallet_address=OUTSIDER.address),
        headers=headers,
    )

    assert response.status_code == 403


async def test_ciphertext_shape_is_enforced(client):
    """El circuito espera exactamente 10 elementos de campo."""
    headers = await _registered_voter(client)

    short = await client.post(
        "/api/maci/vote", json=_vote(ciphertext=["1", "2"]), headers=headers
    )
    out_of_field = await client.post(
        "/api/maci/vote",
        json=_vote(ciphertext=[str(maci_service.BN254_FIELD)] + CIPHERTEXT[1:]),
        headers=headers,
    )

    assert short.status_code == 422
    assert out_of_field.status_code == 422


async def test_a_vote_and_a_key_change_are_indistinguishable(client):
    """El servidor no puede separar un voto de su anulación.

    Si pudiera, un coaccionador podría exigir la prueba de cuál fue cuál — y
    esa imposibilidad es la garantía central de MACI.
    """
    headers = await _registered_voter(client)

    await client.post("/api/maci/vote", json=_vote(), headers=headers)
    await client.post("/api/maci/vote", json=_vote(), headers=headers)

    stored = await maci_service.maci_messages_collection().find(
        {"poll_id": "consulta-1"}
    ).to_list(length=10)

    assert len(stored) == 2
    # Ningún campo declara el tipo de mensaje: solo texto cifrado y su orden.
    for message in stored:
        assert "vote" not in message
        assert "choice" not in message
        assert "message_type" not in message


# === Recuento ===

async def test_tally_never_publishes_an_unverifiable_result(client):
    """Un conteo sin prueba no es un resultado: es un número no verificable."""
    headers = await _registered_voter(client)
    await client.post("/api/maci/vote", json=_vote(), headers=headers)

    body = (await client.get("/api/maci/polls/consulta-1/tally")).json()

    assert body["message_count"] == 1
    assert body["tallied"] is False
    assert body["results"] is None
    assert body["tally_proof_verified"] is False


async def test_tally_of_an_unknown_poll_is_empty_not_invented(client):
    body = (await client.get("/api/maci/polls/no-existe/tally")).json()
    assert body["message_count"] == 0
    assert body["results"] is None
