"""
Membership endpoints: mint (off-chain demo unless chain_service is
configured), duplicate rejection, address validation, lookups, and wallet
session auth (C-1: minting "as" another address is rejected).
"""
from eth_account import Account
from eth_account.messages import encode_defunct

# Direcciones reales derivadas de llaves privadas fijas de prueba (NO usar en
# producción). Necesarias porque POST /api/membership/mint ahora exige una
# sesión de wallet (SIWE, ver services/siwe_service.py) — firmar el desafío
# requiere una llave privada real, no basta un string "0x..." arbitrario.
VALID_ACCOUNT = Account.from_key("0x" + "11" * 32)
OTHER_ACCOUNT = Account.from_key("0x" + "22" * 32)
VALID_ADDRESS = VALID_ACCOUNT.address.lower()
OTHER_ADDRESS = OTHER_ACCOUNT.address.lower()


async def _sign_in(client, account):
    """Ejecuta el flujo SIWE real (challenge + firma + verify) y devuelve
    los headers de Authorization para autenticar como esa cuenta."""
    challenge = await client.post("/api/wallet/challenge", json={"address": account.address})
    challenge.raise_for_status()
    body = challenge.json()
    signed = Account.sign_message(encode_defunct(text=body["message"]), private_key=account.key)
    verify = await client.post("/api/wallet/verify", json={
        "address": account.address,
        "nonce": body["nonce"],
        "signature": signed.signature.hex(),
    })
    verify.raise_for_status()
    return {"Authorization": f"Bearer {verify.json()['token']}"}


async def _mint(client, account=VALID_ACCOUNT, address=None, doc_hash="0xdeadbeef", level="AL2"):
    """Mintea autenticado como `account`. Por defecto usa la propia
    dirección de `account`; pásale `address` distinto para probar el
    rechazo de "mintear como otra persona" (C-1)."""
    headers = await _sign_in(client, account)
    return await client.post("/api/membership/mint", json={
        "wallet_address": address if address is not None else account.address,
        "assurance_level": level,
        "doc_hash": doc_hash,
    }, headers=headers)


async def test_mint_requires_wallet_session(client):
    """Sin Authorization: Bearer, mint se rechaza con 401 (no con un ok:false)."""
    response = await client.post("/api/membership/mint", json={
        "wallet_address": VALID_ADDRESS,
        "assurance_level": "AL2",
        "doc_hash": "0xdeadbeef",
    })
    assert response.status_code == 401


async def test_mint_rejects_acting_as_another_address(client):
    """Autenticado como VALID_ACCOUNT pero reclamando OTHER_ADDRESS en el
    body: 403, nunca se llega a intentar el minteo (cierra C-1)."""
    response = await _mint(client, account=VALID_ACCOUNT, address=OTHER_ADDRESS)
    assert response.status_code == 403


async def test_mint_creates_member(client):
    response = await _mint(client)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["token_id"] == 1
    # chain_service no está configurado en tests: nunca se fabrica un tx_hash
    assert data["tx_hash"] is None


async def test_mint_rejects_duplicate_wallet_case_insensitive(client):
    first = await _mint(client, account=VALID_ACCOUNT)
    assert first.json()["ok"] is True

    # Mismo wallet, distinto casing en el body -- pero debe seguir
    # autenticando como la MISMA cuenta (las direcciones no distinguen
    # mayúsculas), así que ensure_acts_as_self lo sigue aceptando.
    duplicate = await _mint(client, account=VALID_ACCOUNT, address=VALID_ACCOUNT.address.upper().replace("0X", "0x"))
    data = duplicate.json()
    assert data["ok"] is False
    assert "Ya existe" in data["error"]


async def test_mint_requires_doc_hash(client):
    response = await _mint(client, doc_hash="")
    data = response.json()
    assert data["ok"] is False


async def test_token_ids_are_sequential(client):
    first = await _mint(client, account=VALID_ACCOUNT)
    second = await _mint(client, account=OTHER_ACCOUNT)
    assert first.json()["token_id"] == 1
    assert second.json()["token_id"] == 2


async def test_verify_membership(client):
    await _mint(client, account=VALID_ACCOUNT)

    found = await client.get("/api/membership/verify/1")
    data = found.json()
    assert data["valid"] is True
    assert data["wallet_address"] == VALID_ADDRESS
    assert data["status"] == "active"

    missing = await client.get("/api/membership/verify/999")
    assert missing.json()["valid"] is False


async def test_get_member_by_wallet(client):
    await _mint(client, account=VALID_ACCOUNT)

    found = await client.get(f"/api/membership/member/{VALID_ADDRESS}")
    data = found.json()
    assert data["found"] is True
    assert data["member"]["token_id"] == 1

    missing = await client.get(f"/api/membership/member/{OTHER_ADDRESS}")
    assert missing.json()["found"] is False
