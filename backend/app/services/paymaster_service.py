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

Cuenta elegida: Safe
────────────────────
La firma la implementa `safe_4337`, contra la estructura EIP-712 `SafeOp` que
valida el Safe4337Module. Solo se admite `safe`: SimpleAccount y Kernel firman
de otra forma, y aceptar un valor desconocido produciría firmas que el módulo
rechaza sin explicar por qué.

ARQUITECTURA NO CUSTODIAL: el backend NUNCA firma. La Safe pertenece al
ciudadano y su owner firma con MetaMask. El servidor prepara la UserOperation,
valida en profundidad lo que se va a ejecutar y la retransmite al bundler.
Si el backend firmara, sería custodio: podría mintear a nombre de cualquiera.

NO VERIFICADO CONTRA UN BUNDLER REAL: este entorno no tiene credenciales de
Pimlico ni una Safe desplegada. La construcción sigue la especificación de
EntryPoint v0.7 y Safe4337Module v0.3.0, y está cubierta por tests
deterministas (typehash, dominio, empaquetado), pero no se ha ejecutado ni un
solo envío. Por eso el transporte sigue apagado por configuración: el relayer
EOA, que sí está probado, continúa siendo el camino activo.
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
            "falta: debe ser 'safe' (única implementación soportada)"
        )
    elif settings.ERC4337_ACCOUNT_IMPLEMENTATION.strip().lower() != "safe":
        errors["ERC4337_ACCOUNT_IMPLEMENTATION"] = (
            "solo está implementada 'safe' (Safe4337Module)"
        )

    if settings.ERC4337_ACCOUNT_IMPLEMENTATION.strip().lower() == "safe":
        if not settings.SAFE_4337_MODULE_ADDRESS.strip():
            errors["SAFE_4337_MODULE_ADDRESS"] = "falta"
        # SAFE_OWNER_PRIVATE_KEY ya NO se exige ni se usa: el owner es el
        # ciudadano. Si alguien la configura, es una señal de alarma.
        if settings.SAFE_OWNER_PRIVATE_KEY.strip():
            errors["SAFE_OWNER_PRIVATE_KEY"] = (
                "no debe configurarse: el backend no es owner ni custodio"
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
        "account_implementation": settings.ERC4337_ACCOUNT_IMPLEMENTATION or None,
        # La firma Safe está implementada, pero nunca se ejecutó contra un
        # bundler real. Se declaran por separado a propósito: "implementado"
        # y "verificado" no son lo mismo, y confundirlos es como se despliega
        # algo que falla con AA24 en producción.
        # El backend no firma: es arquitectura, no una carencia.
        "custodial": False,
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
    """NO IMPLEMENTADA — y no debe estarlo.

    El backend NO es owner ni custodio de la Safe del ciudadano. Quien firma
    la UserOperation es el usuario con MetaMask, sobre la estructura EIP-712
    `SafeOp` que construye el frontend. El servidor solo prepara la operación,
    la valida y la retransmite.

    Se conserva `safe_4337.safe_op_digest` porque sigue siendo útil del lado
    del servidor para VALIDAR que la firma recibida corresponde al owner
    declarado — verificar no es firmar.

    Firmar aquí con una llave del servidor haría al backend custodio de las
    membresías: podría mintear en nombre de cualquiera sin su consentimiento.
    """
    raise PaymasterUnavailable(
        "El backend no firma UserOperations: la Safe pertenece al ciudadano y "
        "firma con su wallet. Usa /api/erc4337/prepare-mint y submit-mint."
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
        "nonce": hex(entrypoint_nonce(cfg.account_address)),
        "callData": call_data,
    }

    # 1. Estimar gas, 2. pedir patrocinio, 3. firmar, 4. enviar. El orden
    #    importa: el Paymaster firma sobre los límites de gas ya fijados.
    user_op = {**user_op, **estimate_user_operation_gas(user_op)}
    user_op = sponsor_user_operation(user_op)
    user_op = sign_user_operation(user_op)

    user_op_hash = send_user_operation(user_op)
    receipt = wait_for_receipt(user_op_hash)

    if not receipt.get("success"):
        raise UserOperationError("La UserOperation se revirtió on-chain.")

    # El tokenId lo resuelve el llamador leyendo el contrato: el recibo de una
    # UserOperation no expone el valor de retorno de la llamada interna.
    return user_op_hash, None


def entrypoint_nonce(account_address: str, key: int = 0) -> int:
    """Nonce bidimensional del EntryPoint.

    Cada worker puede usar una `key` distinta y enviar en paralelo sin
    coordinación: es lo que resuelve el lock de nonce local al proceso que
    documenta la trampa 11 de HANDOFF.
    """
    from web3 import Web3

    cfg = config()
    w3 = Web3(Web3.HTTPProvider(settings.SEPOLIA_RPC_URL, request_kwargs={"timeout": 10}))
    entrypoint = w3.eth.contract(
        address=Web3.to_checksum_address(cfg.entrypoint),
        abi=[{
            "inputs": [
                {"name": "sender", "type": "address"},
                {"name": "key", "type": "uint192"},
            ],
            "name": "getNonce",
            "outputs": [{"name": "nonce", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        }],
    )
    return int(entrypoint.functions.getNonce(
        Web3.to_checksum_address(account_address), key
    ).call())


def estimate_user_operation_gas(user_op: dict) -> dict:
    """Pide al bundler los límites de gas de la operación."""
    cfg = config()
    result = _rpc("eth_estimateUserOperationGas", [user_op, cfg.entrypoint])
    if not isinstance(result, dict):
        raise UserOperationError("El bundler no devolvió una estimación de gas.")
    return result


def get_user_operation_receipt(user_op_hash: str):
    """Recibo de la UserOperation, o None si el bundler aún no la incluyó."""
    cfg = config()
    return _rpc("eth_getUserOperationReceipt", [user_op_hash])
