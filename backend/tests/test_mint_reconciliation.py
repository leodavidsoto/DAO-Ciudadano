"""
Reconciliación cadena↔Mongo del minteo ZK (ROADMAP fases 1 y 3).

Lo que se fija aquí es una sola regla, mirada desde todos los ángulos en los
que se puede romper: **el estado real lo decide la cadena, nunca un
temporizador de este proceso ni el silencio de un RPC.**

El fallo original: si el worker moría durante la espera del recibo (hasta
120 s), la operación quedaba `pending` para siempre y el ciudadano recibía un
409 permanente; y si la espera expiraba, se marcaba `failed` y el reintento
enviaba una SEGUNDA transacción que revertía por nullifier repetido, quemando
gas de la DAO sin emitir nada.
"""

from datetime import datetime, timedelta, timezone

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from app.core.database import members_collection
from app.services import chain_service, mint_operations

CITIZEN = Account.from_key("0x" + "f7" * 32)
NULLIFIER = "0x" + "bc" * 32
TX = "0x" + "11" * 32


async def _session(client, account):
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


def _body():
    return {
        "wallet_address": CITIZEN.address,
        "pA": ["1", "2"],
        "pB": [["1", "2"], ["3", "4"]],
        "pC": ["5", "6"],
        "nullifier_hash": NULLIFIER,
        "identity_root": "123",
    }


async def _insert(status, **extra):
    document = {
        "nullifier_hash": NULLIFIER,
        "wallet_address": CITIZEN.address.lower(),
        "status": status,
        "attempts": 1,
        "created_at": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    document.update(extra)
    await mint_operations.mint_operations_collection().insert_one(document)


async def _operation():
    return await mint_operations.mint_operations_collection().find_one(
        {"nullifier_hash": NULLIFIER}
    )


def _never_sends(monkeypatch):
    """Falla el test si el relayer intenta enviar una segunda transacción."""

    def guard(*args, **kwargs):
        raise AssertionError("no se puede reenviar el minteo en este escenario")

    monkeypatch.setattr(chain_service, "mint_with_proof", guard)


# === Una transacción difundida se resuelve por su recibo =====================


async def test_a_crashed_worker_recovers_the_sbt_from_the_receipt(client, monkeypatch):
    """El caso central: la tx confirmó, el proceso murió esperando el recibo.

    El reintento del ciudadano tiene que devolverle SU credencial, no un 409
    eterno ni una segunda transacción.
    """
    headers = await _session(client, CITIZEN)
    await _insert(mint_operations.SUBMITTED, tx_hash=TX)
    monkeypatch.setattr(
        chain_service, "transaction_outcome", lambda tx_hash: ("confirmed", 7)
    )
    _never_sends(monkeypatch)

    response = await client.post(
        "/api/membership/mint-zk", json=_body(), headers=headers
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "token_id": 7,
        "tx_hash": TX,
        "error": None,
        # La vía ZK no declara nivel a propósito: el servidor no sabe —ni debe
        # saber— quién minteó, así que no puede certificar nada sobre esa
        # persona. La garantía la impone el contrato al verificar la prueba.
        "assurance_level": None,
    }
    assert (await _operation())["status"] == mint_operations.CONFIRMED


async def test_recovering_the_sbt_also_makes_it_visible_to_governance(
    client, monkeypatch
):
    """Confirmar sin reflejarlo en `members` deja al miembro fuera del gate."""
    headers = await _session(client, CITIZEN)
    await _insert(mint_operations.SUBMITTED, tx_hash=TX)
    monkeypatch.setattr(
        chain_service, "transaction_outcome", lambda tx_hash: ("confirmed", 7)
    )
    _never_sends(monkeypatch)

    await client.post("/api/membership/mint-zk", json=_body(), headers=headers)

    member = await members_collection().find_one(
        {"wallet_address": CITIZEN.address.lower()}
    )
    assert member["token_id"] == 7
    assert member["status"] == "active"
    assert member["identity_verified"] is True


async def test_a_receipt_without_a_token_id_resolves_it_from_the_contract(
    client, monkeypatch
):
    """El recibo de una UserOperation no expone el retorno de la llamada."""
    headers = await _session(client, CITIZEN)
    await _insert(mint_operations.SUBMITTED, tx_hash=TX)
    monkeypatch.setattr(
        chain_service, "transaction_outcome", lambda tx_hash: ("confirmed", None)
    )
    monkeypatch.setattr(chain_service, "membership_token_of", lambda wallet: 12)
    _never_sends(monkeypatch)

    response = await client.post(
        "/api/membership/mint-zk", json=_body(), headers=headers
    )

    assert response.json()["token_id"] == 12


async def test_a_confirmed_tx_without_a_resolvable_token_is_never_invented(
    client, monkeypatch
):
    """Antes que fabricar un tokenId, se deja la operación en vuelo."""
    headers = await _session(client, CITIZEN)
    await _insert(mint_operations.SUBMITTED, tx_hash=TX)
    monkeypatch.setattr(
        chain_service, "transaction_outcome", lambda tx_hash: ("confirmed", None)
    )
    monkeypatch.setattr(chain_service, "membership_token_of", lambda wallet: None)
    _never_sends(monkeypatch)

    response = await client.post(
        "/api/membership/mint-zk", json=_body(), headers=headers
    )

    assert response.status_code == 409
    assert (await _operation())["status"] == mint_operations.SUBMITTED


# === Un revert no cierra el caso: lo cierra el nullifier =====================


async def test_a_revert_with_a_free_nullifier_can_be_retried(client, monkeypatch):
    headers = await _session(client, CITIZEN)
    await _insert(mint_operations.SUBMITTED, tx_hash=TX)
    monkeypatch.setattr(
        chain_service, "transaction_outcome", lambda tx_hash: ("reverted", None)
    )
    monkeypatch.setattr(chain_service, "nullifier_is_used", lambda nullifier: False)

    response = await client.post(
        "/api/membership/mint-zk", json=_body(), headers=headers
    )

    # Reintenta de verdad: falla al enviar porque no hay cadena configurada,
    # pero NO se queda en el 409 que bloqueaba la credencial.
    assert response.status_code == 502
    operation = await _operation()
    assert operation["attempts"] == 2
    # El hash de la transacción revertida no se arrastra al nuevo intento.
    assert operation.get("tx_hash") is None


async def test_a_revert_caused_by_an_already_used_nullifier_recovers_the_sbt(
    client, monkeypatch
):
    """El revert pudo ser "nullifier ya usado": entonces la credencial existe.

    Declararlo `failed` mandaría al ciudadano a gastar gas contra un revert
    garantizado.
    """
    headers = await _session(client, CITIZEN)
    await _insert(mint_operations.SUBMITTED, tx_hash=TX)
    monkeypatch.setattr(
        chain_service, "transaction_outcome", lambda tx_hash: ("reverted", None)
    )
    monkeypatch.setattr(chain_service, "nullifier_is_used", lambda nullifier: True)
    monkeypatch.setattr(chain_service, "membership_token_of", lambda wallet: 3)
    _never_sends(monkeypatch)

    response = await client.post(
        "/api/membership/mint-zk", json=_body(), headers=headers
    )

    assert response.status_code == 200
    assert response.json()["token_id"] == 3


# === Un RPC caído nunca autoriza un segundo envío ============================


async def test_an_rpc_outage_keeps_the_operation_in_flight(client, monkeypatch):
    """`None` de la cadena no es `False`.

    Si "no se pudo consultar" se leyera como "no pasó nada", un corte de red
    bastaría para reenviar la transacción y quemar el gas por segunda vez.
    """
    headers = await _session(client, CITIZEN)
    await _insert(mint_operations.PENDING)
    monkeypatch.setattr(chain_service, "nullifier_is_used", lambda nullifier: None)
    _never_sends(monkeypatch)

    response = await client.post(
        "/api/membership/mint-zk", json=_body(), headers=headers
    )

    assert response.status_code == 409
    assert (await _operation())["status"] == mint_operations.PENDING


async def test_a_stale_pending_that_never_reached_the_chain_is_retryable(
    client, monkeypatch
):
    """`pending` sin tx difundida y sin nullifier quemado: no pasó nada."""
    headers = await _session(client, CITIZEN)
    await _insert(mint_operations.PENDING)
    monkeypatch.setattr(chain_service, "nullifier_is_used", lambda nullifier: False)

    response = await client.post(
        "/api/membership/mint-zk", json=_body(), headers=headers
    )

    assert response.status_code == 502
    assert (await _operation())["attempts"] == 2


async def test_a_fresh_pending_answers_409_without_touching_the_chain(
    client, monkeypatch
):
    """El 409 de "hay un minteo en curso" sigue siendo local e inmediato.

    Sin la ventana de antigüedad, cada reintento del cliente golpearía el RPC.
    """
    headers = await _session(client, CITIZEN)
    await _insert(mint_operations.PENDING, created_at=datetime.now(timezone.utc))

    def unexpected(*args, **kwargs):
        raise AssertionError("una operación reciente no debe consultar la cadena")

    monkeypatch.setattr(chain_service, "nullifier_is_used", unexpected)
    monkeypatch.setattr(chain_service, "transaction_outcome", unexpected)
    _never_sends(monkeypatch)

    response = await client.post(
        "/api/membership/mint-zk", json=_body(), headers=headers
    )

    assert response.status_code == 409


# === Contradicciones: se marcan, no se adivinan ==============================


async def test_a_burned_nullifier_without_an_sbt_is_flagged_for_review(
    client, monkeypatch
):
    """El nullifier está consumido pero la wallet no tiene SBT.

    No debería poder pasar —el `recipient` va ligado dentro de la hoja— y
    justamente por eso no se resuelve con una suposición.
    """
    headers = await _session(client, CITIZEN)
    await _insert(mint_operations.PENDING)
    monkeypatch.setattr(chain_service, "nullifier_is_used", lambda nullifier: True)
    monkeypatch.setattr(chain_service, "membership_token_of", lambda wallet: None)
    _never_sends(monkeypatch)

    response = await client.post(
        "/api/membership/mint-zk", json=_body(), headers=headers
    )

    assert response.status_code == 409
    assert "revisión manual" in response.json()["detail"]
    assert (await _operation())["status"] == mint_operations.NEEDS_REVIEW


async def test_an_operation_under_review_is_never_resent(client, monkeypatch):
    headers = await _session(client, CITIZEN)
    await _insert(mint_operations.NEEDS_REVIEW, review_reason="incoherencia")

    def unexpected(*args, **kwargs):
        raise AssertionError("una operación en revisión no consulta ni envía nada")

    monkeypatch.setattr(chain_service, "nullifier_is_used", unexpected)
    _never_sends(monkeypatch)

    response = await client.post(
        "/api/membership/mint-zk", json=_body(), headers=headers
    )

    assert response.status_code == 409


# === El hash se persiste ANTES de esperar el recibo ==========================


async def test_the_tx_hash_is_persisted_before_the_receipt_wait(client, monkeypatch):
    """El corazón del arreglo.

    La espera del recibo dura hasta 120 s. Si el hash solo se guardara al
    terminarla, una caída dentro de esa ventana dejaba una transacción real
    sin rastro y nada con que reconciliar.
    """
    headers = await _session(client, CITIZEN)

    def submit_then_die(*, on_submitted, **kwargs):
        on_submitted(TX)
        raise chain_service.ChainMintError("timeout esperando el recibo")

    monkeypatch.setattr(chain_service, "mint_with_proof", submit_then_die)

    response = await client.post(
        "/api/membership/mint-zk", json=_body(), headers=headers
    )

    operation = await _operation()
    assert operation["tx_hash"] == TX
    # `submitted`, no `failed`: marcarla fallida es lo que provocaba el segundo
    # envío y el gasto de gas contra un revert seguro.
    assert operation["status"] == mint_operations.SUBMITTED
    assert response.status_code == 409
    assert TX in response.json()["detail"]


async def test_after_a_lost_receipt_the_retry_resolves_instead_of_resending(
    client, monkeypatch
):
    """Continuación del anterior: el reintento cierra la operación con la cadena."""
    headers = await _session(client, CITIZEN)

    def submit_then_die(*, on_submitted, **kwargs):
        on_submitted(TX)
        raise chain_service.ChainMintError("timeout esperando el recibo")

    monkeypatch.setattr(chain_service, "mint_with_proof", submit_then_die)
    await client.post("/api/membership/mint-zk", json=_body(), headers=headers)

    monkeypatch.setattr(
        chain_service, "transaction_outcome", lambda tx_hash: ("confirmed", 9)
    )
    _never_sends(monkeypatch)

    response = await client.post(
        "/api/membership/mint-zk", json=_body(), headers=headers
    )

    assert response.status_code == 200
    assert response.json()["token_id"] == 9


# === Barrido de operaciones olvidadas ========================================


async def test_the_sweep_closes_forgotten_operations(client, monkeypatch):
    """Nadie reintenta: el barrido tiene que cerrarlas igual."""
    await _insert(mint_operations.SUBMITTED, tx_hash=TX)
    monkeypatch.setattr(
        chain_service, "transaction_outcome", lambda tx_hash: ("confirmed", 5)
    )

    summary = await mint_operations.sweep()

    assert summary["scanned"] == 1
    assert summary[mint_operations.CONFIRMED] == 1
    assert (await _operation())["token_id"] == 5


async def test_the_sweep_leaves_unresolvable_operations_alone(client, monkeypatch):
    await _insert(mint_operations.PENDING)
    monkeypatch.setattr(chain_service, "nullifier_is_used", lambda nullifier: None)

    summary = await mint_operations.sweep()

    assert summary[mint_operations.IN_FLIGHT] == 1
    assert (await _operation())["status"] == mint_operations.PENDING


# === Ventana de antigüedad ===================================================


@pytest.mark.parametrize("field", ["created_at", "retried_at", "submitted_at"])
def test_staleness_is_measured_from_the_last_known_activity(field):
    """Un reintento reciente sobre una operación vieja NO es viejo."""
    now = datetime.now(timezone.utc)
    operation = {
        "created_at": now - timedelta(hours=2),
        field: now,
    }
    assert mint_operations.is_stale(operation, now=now) is False


def test_an_operation_without_dates_is_treated_as_stale():
    """Un registro sin fecha no puede afirmarse reciente.

    Dejarlo bloqueado para siempre es peor que consultar la cadena una vez.
    """
    assert mint_operations.is_stale({}) is True
