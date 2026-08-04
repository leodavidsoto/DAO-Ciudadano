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

    # ERC4337_ACCOUNT_ADDRESS ya NO se exige: en el modelo no custodial el
    # `sender` es la Safe del ciudadano y llega en cada petición. Pedir una
    # cuenta global era un resto del diseño custodial eliminado.

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
    return str(settings.ERC4337_ENABLED).strip().lower() == "true" and is_configured()


def config() -> BundlerConfig:
    errors = configuration_errors()
    if errors:
        raise PaymasterUnavailable(
            "Transporte ERC-4337 incompleto: " + ", ".join(sorted(errors))
        )
    return BundlerConfig(
        rpc_url=settings.BUNDLER_RPC_URL.strip(),
        entrypoint=SUPPORTED_ENTRYPOINTS[settings.ERC4337_ENTRYPOINT_VERSION.strip()],
        account_implementation=settings.ERC4337_ACCOUNT_IMPLEMENTATION.strip(),
    )


_runtime_cache = None
_RUNTIME_CACHE_SECONDS = 60


def runtime_status() -> dict:
    """Sonda real contra el bundler. No es una afirmación estática.

    Comprueba tres cosas que, si no coinciden, producen fallos opacos más
    tarde: que la credencial pasa, que la red es la que opera este backend, y
    que el bundler soporta el EntryPoint que construimos. Se cachea porque
    /health/ready puede consultarse a menudo y una sonda sin autenticar no
    debe amplificar tráfico hacia el proveedor.
    """
    global _runtime_cache

    import time as _time

    now = _time.monotonic()
    if _runtime_cache and now - _runtime_cache[0] < _RUNTIME_CACHE_SECONDS:
        return dict(_runtime_cache[1])

    result = {
        "checked": True,
        "reachable": False,
        "chain_id": None,
        "entrypoint_supported": False,
        "errors": [],
    }
    if not is_configured():
        result["errors"] = sorted(configuration_errors())
        _runtime_cache = (now, result)
        return dict(result)

    try:
        chain_id = int(_rpc("eth_chainId", []), 16)
        result["chain_id"] = chain_id
        result["reachable"] = True
        if chain_id != settings.SIWE_CHAIN_ID:
            result["errors"].append(
                f"el bundler opera en chainId {chain_id}; este backend usa "
                f"{settings.SIWE_CHAIN_ID}"
            )

        entrypoints = [e.lower() for e in _rpc("eth_supportedEntryPoints", [])]
        cfg = config()
        result["entrypoint_supported"] = cfg.entrypoint.lower() in entrypoints
        if not result["entrypoint_supported"]:
            result["errors"].append("el bundler no soporta el EntryPoint configurado")
    except UserOperationError as exc:
        result["errors"].append(str(exc))
    except Exception:
        logger.error("Sonda del bundler fallida", exc_info=True)
        result["errors"].append("no se pudo contactar al bundler")

    _runtime_cache = (now, result)
    return dict(result)


def status(probe: bool = False) -> dict:
    """Estado para /health/ready. Honesto sobre lo que falta."""
    errors = configuration_errors()
    return {
        "enabled": is_enabled(),
        "configured": not errors,
        "missing": sorted(errors),
        "entrypoint_version": settings.ERC4337_ENTRYPOINT_VERSION,
        "account_implementation": settings.ERC4337_ACCOUNT_IMPLEMENTATION or None,
        # El backend no firma: es arquitectura, no una carencia. Firma el
        # ciudadano con MetaMask sobre la estructura SafeOp.
        "custodial": False,
        "signing_implemented": False,
        # Resultado MEDIDO de la sonda, no una constante. Antes era un `False`
        # fijo que había que acordarse de cambiar a mano — justo el tipo de
        # afirmación que se queda desactualizada y acaba mintiendo.
        "bundler": runtime_status() if probe else None,
    }


# === Transporte JSON-RPC ===

# Pimlico está detrás de Cloudflare, que rechaza el user-agent por defecto de
# `requests` con un 403 "error code: 1010" — un error de Cloudflare, no de la
# API, así que ni siquiera llega a evaluarse la credencial. Verificado contra
# el endpoint real: con el UA por defecto son 403; con este, responde.
_USER_AGENT = "dao-ciudadana-backend/1.0"


def _rpc(method: str, params: list) -> dict:
    """Llamada JSON-RPC al bundler. Síncrona: el llamador usa to_thread."""
    import requests  # noqa: F401  (dependencia de producción ya presente vía web3)

    cfg = config()
    try:
        response = requests.post(
            cfg.rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            timeout=20,
        )
        if response.status_code == 403:
            # Se distingue del rechazo de la API: confundirlos manda a revisar
            # la credencial cuando el problema es el filtro de borde.
            raise UserOperationError(
                "El bundler devolvió 403 antes de procesar la petición "
                "(filtro de borde). Revisa el User-Agent y la red de salida, "
                "no la credencial."
            )
        payload = response.json()
    except UserOperationError:
        raise
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


# El antiguo `mint_via_user_operation` se eliminó con el resto del camino
# custodial: enviaba desde una cuenta del backend usando su propia firma. El
# flujo vigente es /api/erc4337/prepare-mint + submit-mint, donde la Safe es
# del ciudadano y firma él.


def entrypoint_nonce(account_address: str, key: int = 0) -> int:
    """Nonce bidimensional del EntryPoint.

    Cada worker puede usar una `key` distinta y enviar en paralelo sin
    coordinación: es lo que resuelve el lock de nonce local al proceso que
    documenta la trampa 11 de HANDOFF.
    """
    from web3 import Web3

    cfg = config()
    w3 = Web3(
        Web3.HTTPProvider(settings.SEPOLIA_RPC_URL, request_kwargs={"timeout": 10})
    )
    entrypoint = w3.eth.contract(
        address=Web3.to_checksum_address(cfg.entrypoint),
        abi=[
            {
                "inputs": [
                    {"name": "sender", "type": "address"},
                    {"name": "key", "type": "uint192"},
                ],
                "name": "getNonce",
                "outputs": [{"name": "nonce", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function",
            }
        ],
    )
    return int(
        entrypoint.functions.getNonce(
            Web3.to_checksum_address(account_address), key
        ).call()
    )


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
