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


# === Puntos de orden bajo (hallazgo de Codex) ===

# Punto de orden 2 en Baby Jubjub: (0, -1). Está EN la curva y no es (0,1),
# así que la comprobación de ecuación por sí sola lo aceptaba.
ORDER2_X = 0
ORDER2_Y = maci_service.BN254_FIELD - 1


def test_low_order_points_are_on_the_curve_but_not_valid_keys():
    """Estar en la curva NO basta: el cofactor 8 deja puntos de orden bajo.

    Cifrar hacia uno degenera el espacio de claves —el resultado toma muy
    pocos valores— y filtra la clave privada del coordinador.
    """
    assert maci_service.is_on_babyjub_curve(ORDER2_X, ORDER2_Y) is True
    assert maci_service.is_in_prime_subgroup(ORDER2_X, ORDER2_Y) is False

    with pytest.raises(maci_service.MaciKeyError) as exc:
        maci_service.validate_public_key(ORDER2_X, ORDER2_Y)
    assert "orden bajo" in str(exc.value)


def test_generator_is_in_the_prime_subgroup():
    """Contraprueba: el generador publicado sí debe pasar."""
    assert maci_service.is_in_prime_subgroup(BASE_X, BASE_Y) is True
    assert maci_service.is_in_prime_subgroup(DOUBLE_X, DOUBLE_Y) is True


async def test_endpoint_rejects_low_order_keys(client):
    headers = await _mint_member(client, VOTER)

    response = await client.post(
        "/api/maci/keys",
        json={
            "wallet_address": VOTER.address,
            "public_key": _key(ORDER2_X, ORDER2_Y),
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert "orden bajo" in response.json()["detail"]


# === Transporte anónimo ===

ANON_BODY = {
    "protocol_version": "maci-v2.5.0",
    "proposal_id": "prop-1",
    "poll_id": "1",
    "message": {"data": [str(i + 1) for i in range(10)]},
    "encryption_public_key": {"x": str(BASE_X), "y": str(BASE_Y)},
    "coordinator_key_hash": "0x" + "00" * 32,
    "idempotency_key": "idem-0123456789",
}


async def test_anonymous_transport_takes_no_bearer(client):
    """El transporte no lleva sesión: llevarla reconstruiría el enlace.

    Falla por la llave del coordinador (no configurada), NO por falta de
    autenticación — que es lo que se quiere comprobar.
    """
    response = await client.post("/api/maci/polls/1/messages", json=ANON_BODY)
    assert response.status_code != 401


async def _open_poll(proposal_id="prop-1"):
    """Propuesta vigente + poll registrado para ella.

    Sin esto, la petición muere antes en la validación del poll y el test no
    comprobaría lo que dice comprobar.
    """
    from datetime import datetime, timedelta, timezone

    from app.core.database import proposals_collection
    from app.services import maci_service

    await proposals_collection().insert_one({
        "id": proposal_id,
        "title": "Propuesta con urna",
        "status": "active",
        "ends_at": datetime.now(timezone.utc) + timedelta(days=7),
    })
    return await maci_service.poll_id_for_proposal(proposal_id)


async def test_anonymous_transport_refuses_without_an_anchored_key(client):
    """Sin llave anclada on-chain no se acepta nada.

    Aceptar cifrado hacia una llave no verificada produciría votos que el
    coordinador no puede descifrar: se perderían en silencio.
    """
    poll_id = await _open_poll()

    response = await client.post(
        f"/api/maci/polls/{poll_id}/messages",
        json={**ANON_BODY, "poll_id": poll_id},
    )

    assert response.status_code == 503


async def test_anonymous_transport_rejects_an_unknown_protocol(client):
    response = await client.post(
        "/api/maci/polls/1/messages",
        json={**ANON_BODY, "protocol_version": "maci-v1"},
    )
    assert response.status_code == 422


async def test_anonymous_message_stores_nothing_identifying(client):
    """La garantía central: ningún campo enlaza el ciphertext con una persona."""
    result = await maci_service.publish_anonymous_message(
        poll_id="anon-1",
        ephemeral_x=str(BASE_X),
        ephemeral_y=str(BASE_Y),
        ciphertext=[str(i + 1) for i in range(10)],
        idempotency_key="idem-abcdefgh",
    )
    assert result["duplicate"] is False

    stored = await maci_service.maci_messages_collection().find_one(
        {"poll_id": "anon-1"}
    )
    for forbidden in ("wallet_address", "choice", "vote", "signature", "state_index"):
        assert forbidden not in stored, f"el transporte anónimo guardó {forbidden}"


async def test_anonymous_message_is_idempotent_by_client_key(client):
    """Deduplicar por wallet es imposible aquí: no se conoce."""
    args = dict(
        poll_id="anon-2",
        ephemeral_x=str(BASE_X),
        ephemeral_y=str(BASE_Y),
        ciphertext=[str(i + 1) for i in range(10)],
        idempotency_key="idem-repetida",
    )
    first = await maci_service.publish_anonymous_message(**args)
    second = await maci_service.publish_anonymous_message(**args)

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert first["index"] == second["index"]


async def test_state_index_starts_at_one_and_is_stable(client):
    """MACI reserva el índice 0; reasignarlo rompería el nonce del votante."""
    first = await maci_service.assign_state_index("poll-x", VOTER.address)
    again = await maci_service.assign_state_index("poll-x", VOTER.address)
    other = await maci_service.assign_state_index("poll-x", OUTSIDER.address)

    assert first == 1
    assert again == 1
    assert other == 2


async def test_poll_endpoint_does_not_announce_an_unanchored_key(client):
    """Sin coordinador configurado no se inventa una llave."""
    headers = await _mint_member(client, VOTER)
    response = await client.get("/api/maci/proposals/prop-1/poll", headers=headers)
    assert response.status_code == 503


# === Generación de la llave del coordinador ===

def test_generated_keypair_is_valid_by_construction():
    """Lo generado debe pasar la MISMA validación que las llaves de votantes.

    Si no, se podría publicar on-chain una llave de orden bajo y el sistema
    quedaría comprometido desde el primer voto.
    """
    private_key, (x, y) = maci_service.generate_coordinator_keypair()

    assert 0 < private_key < maci_service.BABYJUB_SUBORDER
    assert maci_service.is_on_babyjub_curve(x, y) is True
    assert maci_service.is_in_prime_subgroup(x, y) is True
    # No lanza: es la misma función que filtra a los votantes.
    maci_service.validate_public_key(x, y)


def test_public_key_derivation_is_deterministic():
    assert maci_service.derive_public_key(12345) == maci_service.derive_public_key(12345)
    assert maci_service.derive_public_key(1) != maci_service.derive_public_key(2)


def test_the_generator_is_the_public_key_of_private_key_one():
    """Contraprueba de la derivación: 1·Base8 debe ser Base8."""
    assert maci_service.derive_public_key(1) == maci_service.BASE8


def test_private_keys_outside_the_subgroup_range_are_rejected():
    """Fuera de [1, subOrder) el punto no pertenece al subgrupo primo."""
    for invalid in (0, -1, maci_service.BABYJUB_SUBORDER,
                    maci_service.BABYJUB_SUBORDER + 1):
        with pytest.raises(maci_service.MaciKeyError):
            maci_service.derive_public_key(invalid)


def test_two_generated_keypairs_differ():
    """Una generación determinista haría predecible la llave del coordinador."""
    first, _ = maci_service.generate_coordinator_keypair()
    second, _ = maci_service.generate_coordinator_keypair()
    assert first != second


# === Frontera anónima endurecida (TAREA 5) ===

async def test_extra_fields_are_rejected_not_ignored(client):
    """Antes se descartaban en silencio: el frontend podía estar filtrando
    identidad en cada voto sin que nadie se enterara."""
    poll_id = await _open_poll()

    response = await client.post(
        f"/api/maci/polls/{poll_id}/messages",
        json={**ANON_BODY, "poll_id": poll_id, "wallet_address": "0x" + "11" * 20},
    )

    assert response.status_code == 422
    assert "wallet_address" in str(response.json()).lower()


async def test_an_extra_field_inside_the_message_is_also_rejected(client):
    poll_id = await _open_poll()

    response = await client.post(
        f"/api/maci/polls/{poll_id}/messages",
        json={
            **ANON_BODY,
            "poll_id": poll_id,
            "message": {"data": [str(i + 1) for i in range(10)], "choice": "for"},
        },
    )

    assert response.status_code == 422


async def test_a_poll_from_another_proposal_is_rejected(client):
    """`proposal_id` llegaba y no se miraba."""
    poll_id = await _open_poll("prop-1")
    await _open_poll("prop-2")

    response = await client.post(
        f"/api/maci/polls/{poll_id}/messages",
        json={**ANON_BODY, "poll_id": poll_id, "proposal_id": "prop-2"},
    )

    assert response.status_code == 422
    assert "no corresponde" in response.json()["detail"]


async def test_a_closed_proposal_does_not_accept_messages(client):
    """Encolar un voto que nadie contará es peor que rechazarlo."""
    from datetime import datetime, timedelta, timezone

    from app.core.database import proposals_collection
    from app.services import maci_service

    await proposals_collection().insert_one({
        "id": "prop-cerrada",
        "status": "expired",
        "ends_at": datetime.now(timezone.utc) - timedelta(days=1),
    })
    poll_id = await maci_service.poll_id_for_proposal("prop-cerrada")

    response = await client.post(
        f"/api/maci/polls/{poll_id}/messages",
        json={**ANON_BODY, "poll_id": poll_id, "proposal_id": "prop-cerrada"},
    )

    assert response.status_code == 409
    assert "plazo" in response.json()["detail"]


def test_the_accumulator_matches_the_contract():
    """keccak256(abi.encode(...)), igual que MACICoordinator.

    Vector contrastado con `ethers.AbiCoder`: si alguien cambia el formato,
    el recibo deja de ser recomputable contra la cadena y este test lo dice.
    """
    from app.services import maci_service

    chain = maci_service.next_message_chain(
        maci_service.ZERO_MESSAGE_CHAIN,
        12345678901234567890,
        98765432109876543210,
        list(range(1, 11)),
    )

    assert chain == (
        "0x7ec175c5b4535fde4ddf8c338d742c74b28282f41caebbd6652020d2911a43f6"
    )


def test_the_accumulator_chains_previous_values():
    """Cambiar el acumulador anterior cambia el resultado: es una cadena."""
    from app.services import maci_service

    first = maci_service.next_message_chain(
        maci_service.ZERO_MESSAGE_CHAIN, 1, 2, [3] * 10
    )
    second = maci_service.next_message_chain(first, 1, 2, [3] * 10)

    assert first != second
    assert second == maci_service.next_message_chain(first, 1, 2, [3] * 10)


async def test_status_declares_the_four_protocol_gaps(client):
    """Las cuatro garantías que la auditoría cruzada encontró ausentes."""
    body = (await client.get("/api/maci/status")).json()

    assert body["poll_bound_messages"] is False
    assert body["stateful_nonces"] is False
    assert body["unique_tally_leaves"] is False
    assert body["process_tally_linked"] is False
    assert body["private_voting"] is False


def test_the_anonymous_transport_has_its_own_rate_limit():
    from app.core.security_middleware import RateLimitMiddleware

    assert RateLimitMiddleware._is_sensitive_path("/api/maci/polls/7/messages")
    assert not RateLimitMiddleware._is_sensitive_path("/api/maci/status")
