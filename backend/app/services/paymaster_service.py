"""
Transporte ERC-4337: Bundler + Paymaster (ADR-001, D-1).

Qué resuelve y qué no
─────────────────────
Hoy el minteo ZK lo envía una EOA del backend que paga el gas
(`chain_service.mint_with_proof`). Funciona y el ciudadano no necesita ETH,
pero NO es ERC-4337: no hay UserOperation, ni Bundler, ni Paymaster. Este
módulo es el transporte que falta.

Por qué el diseño encaja sin tocar frontend ni contrato: `mintMembership` es
permissionless y recibe `to` como parámetro explícito ligado dentro de la
prueba (no usa `msg.sender`). Por eso cualquier cuenta puede retransmitir la
prueba sin poder desviar el SBT, y la cuenta inteligente que envía la
UserOperation no tiene que ser la del ciudadano.

Lo que además arregla: el `_nonce_lock` de `chain_service` es local al proceso
(trampa 11 de HANDOFF), así que escalar a varias instancias hoy provocaría
colisiones de nonce. El EntryPoint usa nonces bidimensionales (`key`, `seq`),
de modo que cada worker puede tomar una `key` distinta y enviar en paralelo
sin coordinación.

DECISIÓN PENDIENTE — bloquea la activación
──────────────────────────────────────────
Firmar una UserOperation exige saber **qué implementación de cuenta
inteligente** la envía: SimpleAccount, Safe y Kernel construyen y validan la
firma de forma distinta, y usan `initCode`/factory distintos. Esa decisión no
está tomada y no la debe tomar sola una implementación: define qué contrato
custodia la capacidad de retransmitir y cómo se recupera si se compromete.

Por eso `sign_user_operation` no está implementada y este servicio falla
cerrado. Devolver una firma inventada produciría UserOperations que el
EntryPoint rechaza con `AA24 signature error` — un fallo opaco y caro de
diagnosticar. Es el mismo criterio que `OnChainMembershipVerifier`.

NO VERIFICADO CONTRA UN BUNDLER REAL: no hay credenciales ni cuenta desplegada
en este entorno. El transporte está escrito contra la especificación
(EntryPoint v0.7), pero no se ejecutó ningún envío.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from ..core.config import settings

logger = logging.getLogger(__name__)

# EntryPoint canónico v0.7 (misma dirección en todas las redes).
ENTRYPOINT_V07 = "0x0000000071727De22E5E9d8BAf0edAc6f37da032"
ENTRYPOINT_V06 = "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789"

SUPPORTED_ENTRYPOINTS = {"0.7": ENTRYPOINT_V07, "0.6": ENTRYPOINT_V06}


class PaymasterUnavailable(RuntimeError):
    """El transporte ERC-4337 no está configurado o no puede operar."""


class UserOperationError(RuntimeError):
    """El bundler rechazó la UserOperation."""


@dataclass(frozen=True)
class BundlerConfig:
    rpc_url: str
    entrypoint: str
    account_address: str
    account_implementation: str


def configuration_errors() -> dict[str, str]:
    """Qué falta para poder enviar UserOperations. Sin red."""
    errors: dict[str, str] = {}

    if not settings.BUNDLER_RPC_URL.strip():
        errors["BUNDLER_RPC_URL"] = "falta"
    elif not settings.BUNDLER_RPC_URL.strip().startswith("https://"):
        errors["BUNDLER_RPC_URL"] = "debe ser HTTPS"

    version = settings.ERC4337_ENTRYPOINT_VERSION.strip()
    if version not in SUPPORTED_ENTRYPOINTS:
        errors["ERC4337_ENTRYPOINT_VERSION"] = (
            f"debe ser una de {sorted(SUPPORTED_ENTRYPOINTS)}"
        )

    if not settings.ERC4337_ACCOUNT_ADDRESS.strip():
        errors["ERC4337_ACCOUNT_ADDRESS"] = "falta"

    # Sin esto no se puede firmar: cada implementación firma distinto.
    if not settings.ERC4337_ACCOUNT_IMPLEMENTATION.strip():
        errors["ERC4337_ACCOUNT_IMPLEMENTATION"] = (
            "falta: define cómo se firma la UserOperation (decisión pendiente)"
        )

    return errors


def is_configured() -> bool:
    return not configuration_errors()


def is_enabled() -> bool:
    """¿Se debe usar ERC-4337 en vez del envío directo desde la EOA?"""
    return (
        str(settings.ERC4337_ENABLED).strip().lower() == "true"
        and is_configured()
    )


def config() -> BundlerConfig:
    errors = configuration_errors()
    if errors:
        raise PaymasterUnavailable(
            "Transporte ERC-4337 incompleto: " + ", ".join(sorted(errors))
        )
    return BundlerConfig(
        rpc_url=settings.BUNDLER_RPC_URL.strip(),
        entrypoint=SUPPORTED_ENTRYPOINTS[settings.ERC4337_ENTRYPOINT_VERSION.strip()],
        account_address=settings.ERC4337_ACCOUNT_ADDRESS.strip(),
        account_implementation=settings.ERC4337_ACCOUNT_IMPLEMENTATION.strip(),
    )


def status() -> dict:
    """Estado para /health/ready. Honesto sobre lo que falta."""
    errors = configuration_errors()
    return {
        "enabled": is_enabled(),
        "configured": not errors,
        "missing": sorted(errors),
        "entrypoint_version": settings.ERC4337_ENTRYPOINT_VERSION,
        # Se declara explícito: hoy el gas lo paga la EOA del relayer.
        "signing_implemented": False,
        "verified_against_bundler": False,
    }


# === Transporte JSON-RPC ===

def _rpc(method: str, params: list) -> dict:
    """Llamada JSON-RPC al bundler. Síncrona: el llamador usa to_thread."""
    import requests  # noqa: F401  (dependencia de producción ya presente vía web3)

    cfg = config()
    try:
        response = requests.post(
            cfg.rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=20,
        )
        payload = response.json()
    except Exception as exc:
        raise UserOperationError("El bundler no respondió.") from exc

    if "error" in payload:
        # El mensaje del bundler puede contener la URL con su API key.
        logger.error("Bundler rechazó %s: %s", method, payload["error"])
        raise UserOperationError(f"El bundler rechazó la operación ({method}).")
    return payload.get("result")


def build_mint_calldata(
    to: str,
    proof_a: list,
    proof_b: list,
    proof_c: list,
    nullifier_hash: str,
    identity_root: int,
) -> str:
    """Codifica la llamada a mintMembership(...) para el campo callData.

    Se construye con el ABI real del contrato, no a mano: equivocar el
    selector o el empaquetado produce una transacción que revierte sin
    explicación después de haber pagado el gas.
    """
    from web3 import Web3

    from . import chain_service

    w3 = Web3()
    contract = w3.eth.contract(abi=chain_service._MINT_ABI)
    nullifier_bytes = bytes.fromhex(nullifier_hash.removeprefix("0x"))
    if len(nullifier_bytes) != 32:
        raise UserOperationError("nullifierHash debe ser bytes32.")

    return contract.encode_abi(
        "mintMembership",
        args=[
            Web3.to_checksum_address(to),
            [int(v) for v in proof_a],
            [[int(v) for v in row] for row in proof_b],
            [int(v) for v in proof_c],
            nullifier_bytes,
            int(identity_root),
        ],
    )


def sponsor_user_operation(user_op: dict) -> dict:
    """Pide al Paymaster que patrocine la operación.

    Devuelve la operación con los campos de paymaster rellenos. El nombre del
    método varía entre proveedores (`pm_sponsorUserOperation` en Pimlico y
    Alchemy, `pm_*` propietario en otros), así que es configurable.
    """
    cfg = config()
    method = settings.PAYMASTER_SPONSOR_METHOD.strip() or "pm_sponsorUserOperation"
    result = _rpc(method, [user_op, cfg.entrypoint])
    if not isinstance(result, dict):
        raise UserOperationError("El Paymaster devolvió una respuesta inesperada.")
    return {**user_op, **result}


def sign_user_operation(user_op: dict) -> dict:
    """Firma la UserOperation con la llave de la cuenta inteligente.

    NO IMPLEMENTADA a propósito. Requiere decidir la implementación de cuenta
    (SimpleAccount / Safe / Kernel): cada una construye el hash y valida la
    firma de forma distinta, y elegir mal produce `AA24 signature error` en el
    EntryPoint —un fallo caro y opaco— en vez de un error claro aquí.

    Devolver una firma cualquiera para "dejarlo andando" sería exactamente la
    capacidad fingida que este repositorio está eliminando.
    """
    raise NotImplementedError(
        "Falta decidir la implementación de cuenta inteligente ERC-4337 "
        "(SimpleAccount / Safe / Kernel) antes de poder firmar UserOperations. "
        "Ver docs/ROADMAP.md D-1 y el ADR correspondiente."
    )


def send_user_operation(user_op: dict) -> str:
    """Envía la UserOperation firmada. Devuelve su hash."""
    cfg = config()
    result = _rpc("eth_sendUserOperation", [user_op, cfg.entrypoint])
    if not isinstance(result, str):
        raise UserOperationError("El bundler no devolvió un hash de operación.")
    return result


def wait_for_receipt(user_op_hash: str, attempts: int = 30, delay: float = 2.0) -> dict:
    """Espera el recibo de la UserOperation."""
    import time

    for _ in range(attempts):
        receipt = _rpc("eth_getUserOperationReceipt", [user_op_hash])
        if receipt:
            return receipt
        time.sleep(delay)
    raise UserOperationError(
        "La UserOperation no confirmó a tiempo; requiere reconciliación."
    )


def mint_via_user_operation(
    wallet_address: str,
    proof_a: list,
    proof_b: list,
    proof_c: list,
    nullifier_hash: str,
    identity_root: int,
) -> tuple[str, Optional[int]]:
    """Camino completo ERC-4337 del minteo ZK.

    Falla cerrado mientras la firma no esté resuelta: es preferible seguir
    usando el relayer EOA —que funciona y está probado— a enviar operaciones
    que el EntryPoint rechaza.
    """
    if not is_enabled():
        raise PaymasterUnavailable(
            "El transporte ERC-4337 no está habilitado o configurado."
        )

    cfg = config()
    call_data = build_mint_calldata(
        wallet_address, proof_a, proof_b, proof_c, nullifier_hash, identity_root
    )
    user_op = {
        "sender": cfg.account_address,
        "callData": call_data,
        # El nonce lo aporta el EntryPoint (bidimensional): resolverlo forma
        # parte del trabajo que queda junto con la firma.
        "nonce": None,
    }

    sponsored = sponsor_user_operation(user_op)
    signed = sign_user_operation(sponsored)  # NotImplementedError, a propósito
    user_op_hash = send_user_operation(signed)
    receipt = wait_for_receipt(user_op_hash)

    if not receipt.get("success"):
        raise UserOperationError("La UserOperation se revirtió on-chain.")
    return user_op_hash, None
