"""
ERC-4337 Router — minteo patrocinado NO custodial (ADR-001, D-1).

El reparto de poderes, que es lo que define esta arquitectura:

  - La Safe es del **ciudadano**. Su owner es su wallet.
  - **Firma el usuario**, con MetaMask, sobre la estructura EIP-712 `SafeOp`.
  - El **backend nunca firma**. Prepara la operación, valida en profundidad
    qué se va a ejecutar, consigue el patrocinio y la retransmite.

Si el backend firmara, sería custodio: podría mintear membresías a nombre de
cualquiera sin su consentimiento. Por eso `SAFE_OWNER_PRIVATE_KEY` no solo no
se usa — tenerla configurada se reporta como error de configuración.

Qué valida `prepare-mint` antes de gastar el patrocinio, y por qué:

  1. La sesión SIWE pertenece a `owner_address`.
  2. El `callData` decodifica a UNA sola llamada, `operation=CALL`, valor cero,
     dirigida al contrato SBT configurado. Sin esto, el patrocinio de la DAO
     financiaría cualquier transacción que el cliente quisiera.
  3. La llamada interna es `mintMembership` con exactamente la wallet, prueba,
     nullifier y root del request. Un `callData` que dijera otra cosa que lo
     declarado convertiría la validación en teatro.
  4. La raíz está aprobada, el nullifier no se gastó y la wallet no tiene ya
     membresía — antes de pedir gas, no después.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from ..core.config import settings
from ..core.database import get_collection
from ..services import chain_service, paymaster_service
from .deps import current_address, ensure_acts_as_self

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/erc4337", tags=["ERC-4337"])

# Módulo Safe4337 canónico. El frontend lo fija y rechaza cualquier otro: un
# módulo distinto cambia el dominio EIP-712 y valida firmas con otras reglas.
SAFE_4337_MODULE = "0x75cf11467937ce3F2f357CE24ffc3DBF8fD5c226"
SAFE_VERSION = "1.4.1"
SAFE_SALT_NONCE = "0"

CHAIN_NAMES = {11155111: "Sepolia", 1: "Ethereum", 8453: "Base"}


def erc4337_operations_collection():
    return get_collection("erc4337_operations")


class ProofPayload(BaseModel):
    pA: List[str]
    pB: List[List[str]]
    pC: List[str]
    nullifier_hash: str
    identity_root: str


class PrepareMintRequest(BaseModel):
    owner_address: str
    safe_address: str
    chain_id: str
    entry_point: str
    proof: ProofPayload
    user_operation: dict


class SubmitMintRequest(BaseModel):
    operation_id: str
    user_operation: dict


@router.get("/config")
async def get_erc4337_config(authenticated: str = Depends(current_address)):
    """Parámetros que el cliente necesita para construir la Safe y la operación.

    Se devuelve `enabled: false` cuando falta configuración en vez de valores
    plausibles: el cliente debe poder distinguir "no disponible" de
    "disponible con otros parámetros", y falla cerrado ante lo primero.
    """
    status = paymaster_service.status()
    chain_id = settings.SIWE_CHAIN_ID

    return {
        "enabled": status["enabled"],
        "sponsorship_enabled": status["enabled"],
        "account_type": "safe",
        "safe_version": SAFE_VERSION,
        "safe_salt_nonce": SAFE_SALT_NONCE,
        "safe_4337_module_address": SAFE_4337_MODULE,
        "use_multi_send_for_setup": False,
        "bundler_provider": "pimlico",
        "paymaster_provider": "pimlico",
        "paymaster": settings.ERC4337_PAYMASTER_ADDRESS or None,
        "entry_point": paymaster_service.ENTRYPOINT_V07,
        "entry_point_version": "0.7",
        "chain_id": str(chain_id),
        "chain_name": CHAIN_NAMES.get(chain_id, f"chain-{chain_id}"),
        # El backend no es owner: se declara para que quede en el contrato de
        # API y no dependa de leer la documentación.
        "custodial": False,
        "missing": status["missing"],
    }


def _decode_inner_mint_call(call_data: str) -> dict:
    """Decodifica el callData y exige que sea exactamente un mintMembership.

    Es la validación que impide que el patrocinio de la DAO financie una
    transacción arbitraria: sin decodificar, `callData` es una caja negra que
    el cliente controla por completo.
    """
    from web3 import Web3

    w3 = Web3()
    contract = w3.eth.contract(abi=chain_service._MINT_ABI)

    try:
        function, args = contract.decode_function_input(call_data)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="El callData no decodifica como una llamada conocida al contrato.",
        ) from exc

    if function.fn_name != "mintMembership":
        raise HTTPException(
            status_code=422,
            detail=f"Solo se patrocina mintMembership, no {function.fn_name}.",
        )
    return args


@router.post("/prepare-mint")
async def prepare_mint(
    request: PrepareMintRequest,
    authenticated: str = Depends(current_address),
):
    """Valida, estima y consigue patrocinio. NO firma."""
    ensure_acts_as_self(
        request.owner_address, authenticated, "preparar un minteo patrocinado"
    )

    if not paymaster_service.is_enabled():
        raise HTTPException(
            status_code=503,
            detail=(
                "El patrocinio ERC-4337 no está disponible: "
                + ", ".join(paymaster_service.configuration_errors())
            ),
        )

    if request.chain_id != str(settings.SIWE_CHAIN_ID):
        raise HTTPException(status_code=422, detail="Red incorrecta.")
    if request.entry_point.lower() != paymaster_service.ENTRYPOINT_V07.lower():
        raise HTTPException(status_code=422, detail="EntryPoint no soportado.")

    user_op = dict(request.user_operation)
    sender = str(user_op.get("sender", "")).lower()
    if sender != request.safe_address.lower():
        raise HTTPException(
            status_code=422,
            detail="El sender de la operación no es la Safe declarada.",
        )

    # La llamada interna debe coincidir EXACTAMENTE con lo declarado. Si no se
    # comprobara, el cliente podría declarar una prueba y ejecutar otra cosa.
    inner = _decode_inner_mint_call(user_op.get("callData", ""))
    nullifier = request.proof.nullifier_hash.lower()

    if str(inner.get("to", "")).lower() != request.owner_address.lower():
        raise HTTPException(
            status_code=422,
            detail="El destinatario del SBT no es la wallet autenticada.",
        )
    if "0x" + inner.get("nullifierHash", b"").hex() != nullifier:
        raise HTTPException(
            status_code=422,
            detail="El nullifier del callData no coincide con el declarado.",
        )
    if str(inner.get("identityRoot")) != request.proof.identity_root:
        raise HTTPException(
            status_code=422,
            detail="La raíz de identidad del callData no coincide con la declarada.",
        )

    # Idempotencia por nullifier: un reintento no puede crear otra operación.
    existing = await erc4337_operations_collection().find_one(
        {"nullifier_hash": nullifier}
    )
    if existing and existing.get("status") == "confirmed":
        raise HTTPException(
            status_code=409, detail="Esta credencial ya fue minteada."
        )

    operation_id = (
        existing["operation_id"] if existing else f"op_{uuid.uuid4().hex}"
    )

    # Estimación y patrocinio. Pimlico no debe alterar sender, nonce, factory
    # ni callData: si lo hiciera, la firma del usuario dejaría de corresponder.
    import asyncio

    try:
        estimated = await asyncio.to_thread(
            paymaster_service.estimate_user_operation_gas, user_op
        )
        sponsored = await asyncio.to_thread(
            paymaster_service.sponsor_user_operation, {**user_op, **estimated}
        )
    except paymaster_service.UserOperationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    for immutable in ("sender", "nonce", "factory", "factoryData", "callData"):
        if immutable in user_op and sponsored.get(immutable) != user_op.get(immutable):
            raise HTTPException(
                status_code=502,
                detail=(
                    f"El patrocinador alteró '{immutable}'. Se descarta: la firma "
                    "del usuario dejaría de corresponder a lo que se ejecuta."
                ),
            )

    await erc4337_operations_collection().update_one(
        {"nullifier_hash": nullifier},
        {"$set": {
            "operation_id": operation_id,
            "nullifier_hash": nullifier,
            "owner_address": request.owner_address.lower(),
            "safe_address": request.safe_address.lower(),
            "identity_root": request.proof.identity_root,
            "prepared_user_operation": sponsored,
            "status": "prepared",
            "updated_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )

    return {"ok": True, "operation_id": operation_id, "user_operation": sponsored}


@router.post("/submit-mint")
async def submit_mint(
    request: SubmitMintRequest,
    authenticated: str = Depends(current_address),
):
    """Retransmite la operación FIRMADA POR EL USUARIO.

    Se acepta la firma como único campo modificado respecto a lo preparado.
    Cualquier otro cambio significaría que se firmó una cosa y se ejecuta otra.
    """
    record = await erc4337_operations_collection().find_one(
        {"operation_id": request.operation_id}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Operación desconocida.")

    ensure_acts_as_self(
        record["owner_address"], authenticated, "enviar este minteo"
    )

    if record.get("status") == "submitted" and record.get("user_operation_hash"):
        # Un reintento nunca crea otra UserOperation.
        return {"ok": True, "user_operation_hash": record["user_operation_hash"]}

    prepared = record["prepared_user_operation"]
    signed = dict(request.user_operation)

    for field, value in prepared.items():
        if field == "signature":
            continue
        if signed.get(field) != value:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"El campo '{field}' cambió respecto a lo preparado. Solo la "
                    "firma puede diferir."
                ),
            )
    if not signed.get("signature") or signed["signature"] == prepared.get("signature"):
        raise HTTPException(
            status_code=422, detail="Falta la firma del owner de la Safe."
        )

    import asyncio

    try:
        user_op_hash = await asyncio.to_thread(
            paymaster_service.send_user_operation, signed
        )
    except paymaster_service.UserOperationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await erc4337_operations_collection().update_one(
        {"operation_id": request.operation_id},
        {"$set": {
            "status": "submitted",
            "user_operation_hash": user_op_hash,
            "submitted_at": datetime.now(timezone.utc),
        }},
    )

    return {"ok": True, "user_operation_hash": user_op_hash}


@router.get("/operations/{user_operation_hash}")
async def get_operation(user_operation_hash: str):
    """Estado reconciliado de la operación.

    Devuelve `pending` mientras el bundler no confirme, nunca un token_id
    inventado: un SBT que no existe on-chain no debe aparecer como emitido.
    """
    record = await erc4337_operations_collection().find_one(
        {"user_operation_hash": user_operation_hash}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Operación desconocida.")

    if record.get("status") == "confirmed":
        return {
            "status": "confirmed",
            "user_operation_hash": user_operation_hash,
            "tx_hash": record.get("tx_hash"),
            "token_id": record.get("token_id"),
        }

    import asyncio

    try:
        receipt = await asyncio.to_thread(
            paymaster_service.get_user_operation_receipt, user_operation_hash
        )
    except paymaster_service.UserOperationError:
        receipt = None

    if not receipt:
        return {"status": "pending", "user_operation_hash": user_operation_hash}

    if not receipt.get("success"):
        await erc4337_operations_collection().update_one(
            {"user_operation_hash": user_operation_hash},
            {"$set": {"status": "failed"}},
        )
        return {"status": "failed", "user_operation_hash": user_operation_hash}

    tx_hash = (receipt.get("receipt") or {}).get("transactionHash")
    token_id = await asyncio.to_thread(
        chain_service.membership_token_of, record["owner_address"]
    )

    await erc4337_operations_collection().update_one(
        {"user_operation_hash": user_operation_hash},
        {"$set": {
            "status": "confirmed",
            "tx_hash": tx_hash,
            "token_id": token_id,
            "confirmed_at": datetime.now(timezone.utc),
        }},
    )

    return {
        "status": "confirmed",
        "user_operation_hash": user_operation_hash,
        "tx_hash": tx_hash,
        "token_id": token_id,
    }
