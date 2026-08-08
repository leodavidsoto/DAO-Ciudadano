"""
Relevo del minteo real on-chain (ROADMAP tarea 1.5, D-1).

El único camino de minteo real es el ZK: `mint_with_proof` llama a
`DAOCiudadanaSBT.mintMembership(to, pA, pB, pC, nullifierHash, identityRoot)`
(`contracts/DAOCiudadanaSBT.sol`). La prueba Groth16 ES la autorización, así
que la wallet del relayer no necesita ningún rol para enviarla: solo saldo
para gas. Aprobar raíces de identidad sí exige `ROOT_MANAGER_ROLE`, y es un
poder distinto.

Una configuración incompleta o inválida falla explícitamente y nunca degrada a
demo ni fabrica un `tx_hash`.
"""

import logging
import threading
import time
from typing import Any, Callable, Optional, Tuple
from urllib.parse import urlparse

from ..core.config import settings

logger = logging.getLogger(__name__)

SEPOLIA_CHAIN_ID = 11155111
_runtime_cache = None
_RUNTIME_CACHE_SECONDS = 30
_nonce_lock = threading.Lock()

# ABI mínima: solo lo que este servicio necesita, no el ABI completo del
# contrato. Evita depender del archivo de artifacts de Hardhat en runtime.
_MINT_ABI = [
    # NOTA: la firma antigua de mintMembership (to, identityHash,
    # assuranceLevel, uri) se eliminó al migrar al modelo ZK. Ya no existe en
    # el contrato desplegado; dejarla haría que web3 tuviera que desambiguar
    # dos funciones con el mismo nombre y podría seleccionar la equivocada.
    {
        "inputs": [{"name": "member", "type": "address"}],
        "name": "getMembershipToken",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "member", "type": "address"}],
        "name": "hasMembership",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "member", "type": "address"},
            {"indexed": True, "name": "tokenId", "type": "uint256"},
            {"indexed": True, "name": "nullifierHash", "type": "bytes32"},
            {"indexed": False, "name": "identityRoot", "type": "uint256"},
            {"indexed": False, "name": "timestamp", "type": "uint256"},
        ],
        "name": "MembershipMinted",
        "type": "event",
    },
    # `mintMembership` es `whenNotPaused`: con el contrato pausado todo minteo
    # revierte, y eso hay que poder decirlo antes de gastar gas.
    {
        "inputs": [],
        "name": "paused",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    # Fuente de verdad para reconciliar: si el nullifier ya se quemó, la
    # credencial se emitió, pase lo que pase con nuestro registro en Mongo.
    {
        "inputs": [{"name": "nullifierHash", "type": "bytes32"}],
        "name": "isNullifierUsed",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    # === Modelo ZK (ADR-001, D-2) — contrato de Codex en 5d36007 ===
    {
        "inputs": [],
        "name": "membershipScope",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "identityRoot", "type": "uint256"}],
        "name": "approveIdentityRoot",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "identityRoot", "type": "uint256"}],
        "name": "isIdentityRootApproved",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "ROOT_MANAGER_ROLE",
        "outputs": [{"name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "pA", "type": "uint256[2]"},
            {"name": "pB", "type": "uint256[2][2]"},
            {"name": "pC", "type": "uint256[2]"},
            {"name": "nullifierHash", "type": "bytes32"},
            {"name": "identityRoot", "type": "uint256"},
        ],
        "name": "mintMembership",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "role", "type": "bytes32"},
            {"name": "account", "type": "address"},
        ],
        "name": "hasRole",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class ChainMintError(RuntimeError):
    """El envío de la transacción de minteo falló (RPC, gas, revert, etc.)."""


class ChainReadError(RuntimeError):
    """Una lectura `view` no pudo completarse (RPC caído, ABI, red).

    Distinta de "la respuesta fue False": el llamador no debe confundir "no
    se pudo consultar" con "no tiene membresía".
    """


def configuration_errors() -> dict[str, str]:
    """Validate on-chain inputs without making a network request."""
    from web3 import Web3
    from eth_account import Account

    errors: dict[str, str] = {}

    rpc_url = settings.SEPOLIA_RPC_URL.strip()
    parsed_rpc = urlparse(rpc_url)
    if not rpc_url:
        errors["SEPOLIA_RPC_URL"] = "falta"
    elif parsed_rpc.scheme not in {"http", "https"} or not parsed_rpc.netloc:
        errors["SEPOLIA_RPC_URL"] = "debe ser una URL HTTP(S) válida"
    elif settings.is_production and parsed_rpc.scheme != "https":
        errors["SEPOLIA_RPC_URL"] = "debe usar HTTPS en producción"

    contract_address = settings.SBT_CONTRACT_ADDRESS.strip()
    if not contract_address:
        errors["SBT_CONTRACT_ADDRESS"] = "falta"
    elif not Web3.is_address(contract_address):
        errors["SBT_CONTRACT_ADDRESS"] = "debe ser una dirección Ethereum válida"

    private_key = settings.MINTER_PRIVATE_KEY.strip()
    if not private_key:
        errors["MINTER_PRIVATE_KEY"] = "falta"
    else:
        try:
            Account.from_key(private_key)
        except (TypeError, ValueError):
            errors["MINTER_PRIVATE_KEY"] = "debe ser una llave privada Ethereum válida"

    return errors


def is_configured() -> bool:
    """Configuración completa: lecturas Y envío de transacciones."""
    return not configuration_errors()


def can_read_chain() -> bool:
    """Solo lo necesario para LEER: RPC y dirección del contrato.

    Separado de `is_configured` porque las lecturas no necesitan llave
    privada. Exigirla hacía que la emisión de credenciales fallara con "no se
    pudo leer membershipScope()" cuando el único problema era que el relayer
    no estaba configurado — dos cosas sin relación.
    """
    errors = configuration_errors()
    return not {k for k in errors if k != "MINTER_PRIVATE_KEY"}


def _read_only_contract():
    """Contrato para llamadas `view`, sin necesidad de cuenta."""
    from web3 import Web3

    w3 = Web3(
        Web3.HTTPProvider(settings.SEPOLIA_RPC_URL, request_kwargs={"timeout": 10})
    )
    return w3.eth.contract(
        address=Web3.to_checksum_address(settings.SBT_CONTRACT_ADDRESS),
        abi=_MINT_ABI,
    )


def _client():
    """Construye (w3, contract, account) bajo demanda.

    Import local de web3/eth_account: así los módulos que no mintean
    on-chain (la mayoría de los tests) no pagan el costo de importarlos.
    """
    from web3 import Web3
    from eth_account import Account

    w3 = Web3(
        Web3.HTTPProvider(
            settings.SEPOLIA_RPC_URL,
            request_kwargs={"timeout": 5},
        )
    )
    account = Account.from_key(settings.MINTER_PRIVATE_KEY)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(settings.SBT_CONTRACT_ADDRESS),
        abi=_MINT_ABI,
    )
    return w3, contract, account


def _probe_membership_contract(w3, contract, account, result: dict) -> list[str]:
    """Comprueba lo que el contrato REALMENTE exige para relevar un minteo.

    Se llama con el contrato ya localizado (red correcta y bytecode presente) y
    rellena los campos informativos de `result`. Devuelve la lista de errores
    que impiden relevar un minteo; una lista vacía significa que se puede.
    """
    errors: list[str] = []

    # ABI compatible. `membershipScope()` es lo que distingue el contrato ZK
    # actual del histórico (Ownable/`string`), y nombrar esa diferencia es más
    # útil que un "no se pudo validar" que obliga a adivinar.
    try:
        scope = int(contract.functions.membershipScope().call())
    except Exception:
        return [
            "la dirección configurada no expone membershipScope(): no es el "
            "contrato DAOCiudadanaSBT actual"
        ]
    if scope <= 0:
        return ["membershipScope() devolvió 0: el contrato no está inicializado"]
    result["membership_scope"] = str(scope)

    # `mintMembership` es `whenNotPaused`. Es un estado operativo, no un error
    # de configuración, y por eso se reporta además en su propio campo.
    try:
        paused = bool(contract.functions.paused().call())
        result["paused"] = paused
        if paused:
            errors.append("el contrato de membresía está pausado")
    except Exception:
        errors.append("no se pudo leer paused() del contrato")

    # Saldo del relayer: lo ÚNICO que necesita para enviar el minteo. La
    # prueba Groth16 es la autorización, así que el contrato no le pide rol
    # alguno a quien la releva.
    try:
        if w3.eth.get_balance(account.address) <= 0:
            errors.append("la wallet del relayer no tiene saldo para gas")
    except Exception:
        errors.append("no se pudo consultar el saldo del relayer")

    # ROOT_MANAGER_ROLE es informativo y NO bloquea el relevo: hace falta para
    # aprobar raíces (emitir credenciales), que es otro poder. Un despliegue
    # donde el Safe admin aprueba las raíces a mano es legítimo, y exigirlo
    # aquí dejaría ese despliegue sin poder mintear nunca. `None` = no se pudo
    # averiguar, que no es lo mismo que "no lo tiene".
    try:
        role = contract.functions.ROOT_MANAGER_ROLE().call()
        result["can_approve_roots"] = bool(
            contract.functions.hasRole(role, account.address).call()
        )
    except Exception:
        result["can_approve_roots"] = None

    return errors


def runtime_status() -> dict:
    """Probe the selected chain, contract and relayer without sending a tx.

    Comprueba lo que el contrato exige de verdad: red correcta, bytecode
    presente, ABI compatible, contrato no pausado y saldo para gas.

    Antes se probaba `MINTER_ROLE()`, una función que `DAOCiudadanaSBT.sol` no
    declara: la llamada revertía, se capturaba como "no se pudo validar" y
    TODO minteo real moría en la precondición sin haber enviado nada. El suite
    seguía verde porque el contrato falso del test sí exponía ese rol — es
    exactamente el fallo que la regla "verifica contra la fuente, no contra la
    documentación" existe para atrapar.

    Results are cached briefly because `/health/ready` may be polled often;
    an unauthenticated health check must not amplify traffic to the RPC.
    Error messages are deliberately generic so an RPC URL containing an API
    key is never reflected to callers.
    """
    global _runtime_cache

    cache_key = (
        settings.SEPOLIA_RPC_URL,
        settings.SBT_CONTRACT_ADDRESS,
        settings.MINTER_PRIVATE_KEY,
    )
    now = time.monotonic()
    if _runtime_cache:
        cached_key, cached_at, cached_value = _runtime_cache
        if cached_key == cache_key and now - cached_at < _RUNTIME_CACHE_SECONDS:
            return dict(cached_value)

    errors = configuration_errors()
    result: dict[str, Any] = {
        "checked": True,
        "ready": False,
        "chain_id": None,
        "minter_address": None,
        "membership_scope": None,
        "paused": None,
        "can_approve_roots": None,
        "errors": list(errors.values()),
    }
    if errors:
        _runtime_cache = (cache_key, now, result)
        return dict(result)

    try:
        w3, contract, account = _client()
        result["minter_address"] = account.address

        if not w3.is_connected():
            result["errors"] = ["RPC de Sepolia no disponible"]
        else:
            chain_id = int(w3.eth.chain_id)
            result["chain_id"] = chain_id
            if chain_id != SEPOLIA_CHAIN_ID:
                result["errors"] = [
                    f"chainId inesperado: {chain_id}; se requiere {SEPOLIA_CHAIN_ID}"
                ]
            elif not w3.eth.get_code(contract.address):
                result["errors"] = ["la dirección configurada no contiene bytecode"]
            else:
                result["errors"] = _probe_membership_contract(
                    w3, contract, account, result
                )
                result["ready"] = not result["errors"]
    except Exception:
        logger.error("On-chain readiness probe failed", exc_info=True)
        result["errors"] = ["no se pudo validar RPC, red, contrato y ABI"]

    _runtime_cache = (cache_key, now, result)
    return dict(result)


def tx_hash_hex(raw) -> str:
    """Hash de transacción como `0x…`, venga de web3 o de Mongo.

    `HexBytes.hex()` dejó de incluir el prefijo en hexbytes 1.x, así que
    guardarlo tal cual producía hashes que ningún explorador acepta. Aquí se
    normaliza una sola vez para que ni el registro ni la respuesta al
    ciudadano dependan de la versión de una dependencia transitiva.
    """
    value = raw.hex() if hasattr(raw, "hex") else str(raw)
    return value if value.startswith("0x") else f"0x{value}"


# === Modelo ZK (ADR-001, D-2) ===================================================
# El emisor lee el scope del contrato y aprueba raíces; el relayer envía el
# mint con la prueba. La llave del minter necesita ROOT_MANAGER_ROLE para
# aprobar raíces, que es un permiso distinto del de mintear.


def membership_scope() -> Optional[int]:
    """Lee membershipScope() del contrato. None si no se puede consultar.

    Se consulta la cadena y no la configuración: el scope se deriva de
    version + chainId + address(this) dentro del propio contrato, así que
    calcularlo aquí sería duplicar una fuente de verdad que ya existe.
    """
    if not can_read_chain():
        return None
    try:
        contract = _read_only_contract()
        return int(contract.functions.membershipScope().call())
    except Exception:
        logger.error("No se pudo leer membershipScope()", exc_info=True)
        return None


def identity_root_is_approved(identity_root: int) -> Optional[bool]:
    """True/False según el contrato; None si la consulta falla."""
    if not can_read_chain():
        return None
    try:
        contract = _read_only_contract()
        return bool(contract.functions.isIdentityRootApproved(identity_root).call())
    except Exception:
        logger.error("No se pudo consultar isIdentityRootApproved()", exc_info=True)
        return None


def approve_identity_root(identity_root: int) -> Optional[str]:
    """Aprueba una raíz on-chain. Devuelve el tx_hash, o None si ya estaba.

    Idempotente: si la raíz ya está aprobada no se envía transacción. Sin esto,
    cada credencial emitida contra la misma raíz gastaría gas para nada.
    """
    if not is_configured():
        raise ChainMintError(
            "La aprobación de raíces requiere SEPOLIA_RPC_URL, "
            "SBT_CONTRACT_ADDRESS y MINTER_PRIVATE_KEY."
        )

    already = identity_root_is_approved(identity_root)
    if already is True:
        return None
    if already is None:
        raise ChainMintError("No se pudo comprobar si la raíz ya estaba aprobada.")

    # `approveIdentityRoot` es `onlyRole(ROOT_MANAGER_ROLE)`, y el script de
    # despliegue concede ese rol SOLO al admin. Sin esta comprobación el fallo
    # aparecía como un revert opaco durante la estimación de gas, y el operador
    # no tenía forma de saber que lo que faltaba era una concesión de rol.
    operational = runtime_status()
    if operational.get("can_approve_roots") is False:
        raise ChainMintError(
            "La wallet configurada no tiene ROOT_MANAGER_ROLE en el contrato: "
            "no puede aprobar raíces de identidad. Concédeselo desde el admin "
            "o aprueba la raíz con la wallet que sí lo tiene."
        )

    try:
        w3, contract, account = _client()
        with _nonce_lock:
            nonce = w3.eth.get_transaction_count(account.address, "pending")
            tx = contract.functions.approveIdentityRoot(
                identity_root
            ).build_transaction(
                {
                    "from": account.address,
                    "nonce": nonce,
                    "chainId": SEPOLIA_CHAIN_ID,
                }
            )
            signed = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status != 1:
            raise ChainMintError("La aprobación de la raíz se revirtió on-chain.")
        return tx_hash_hex(tx_hash)
    except ChainMintError:
        raise
    except Exception as e:
        logger.error("Error aprobando la raíz de identidad (%s)", type(e).__name__)
        raise ChainMintError("Fallo interno al aprobar la raíz de identidad") from e


def mint_with_proof(
    wallet_address: str,
    proof_a: list,
    proof_b: list,
    proof_c: list,
    nullifier_hash: str,
    identity_root: int,
    on_submitted: Optional[Callable[[str], None]] = None,
) -> Tuple[str, int]:
    """Envía el mint con la prueba ZK. Devuelve (tx_hash, token_id).

    El `token_id` nunca es `None`: si no se puede resolver, se lanza
    `ChainMintError` para que lo recoja la reconciliación. Devolver la
    transacción sin su token dejaría al llamador inventándose el valor.

    El relayer paga el gas: el ciudadano no necesita ETH (D-1, ERC-4337). No
    puede alterar el destinatario, porque `recipient` está ligado dentro de la
    hoja del árbol y la prueba dejaría de verificar.

    `on_submitted` recibe el hash EN CUANTO la transacción se difunde, antes de
    esperar el recibo. Esa espera dura hasta 120 s y una caída dentro de esa
    ventana dejaba una transacción real sin ningún rastro en la base de datos:
    el reintento no tenía con qué reconciliar y volvía a gastar gas contra un
    revert seguro por nullifier repetido.
    """
    from web3 import Web3

    if not is_configured():
        raise ChainMintError("El minteo on-chain no está configurado.")

    operational = runtime_status()
    if not operational.get("ready"):
        raise ChainMintError(
            "La precondición operativa on-chain falló: "
            + "; ".join(operational.get("errors") or ["motivo no determinado"])
        )

    try:
        to = Web3.to_checksum_address(wallet_address)
        nullifier_bytes = bytes.fromhex(nullifier_hash.removeprefix("0x"))
        if len(nullifier_bytes) != 32:
            raise ChainMintError("nullifierHash debe ser bytes32.")

        w3, contract, account = _client()
        with _nonce_lock:
            nonce = w3.eth.get_transaction_count(account.address, "pending")
            tx = contract.functions.mintMembership(
                to,
                [int(v) for v in proof_a],
                [[int(v) for v in row] for row in proof_b],
                [int(v) for v in proof_c],
                nullifier_bytes,
                int(identity_root),
            ).build_transaction(
                {
                    "from": account.address,
                    "nonce": nonce,
                    "chainId": SEPOLIA_CHAIN_ID,
                }
            )
            signed = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

        submitted = tx_hash_hex(tx_hash)
        if on_submitted is not None:
            # Un fallo al registrar el envío no puede anular una transacción ya
            # difundida: se deja constancia en el log y se sigue esperando el
            # recibo. La red no acepta un rollback.
            try:
                on_submitted(submitted)
            except Exception:
                logger.error(
                    "No se pudo registrar el envío del minteo antes de esperar "
                    "el recibo; la transacción ya está en la red",
                    exc_info=True,
                )

        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        if receipt.status != 1:
            raise ChainMintError(f"El minteo se revirtió on-chain (tx {submitted}).")

        token_id = None
        try:
            events = contract.events.MembershipMinted().process_receipt(receipt)
            if events:
                token_id = int(events[0]["args"]["tokenId"])
        except Exception as e:
            logger.warning(
                "No se pudo leer el tokenId del recibo (%s)", type(e).__name__
            )

        if token_id is None:
            try:
                resolved = int(contract.functions.getMembershipToken(to).call())
            except Exception as exc:
                raise ChainMintError(
                    "La transacción se confirmó pero no se pudo resolver su tokenId; "
                    "requiere reconciliación."
                ) from exc
            if resolved <= 0:
                raise ChainMintError(
                    "La transacción se confirmó sin un tokenId válido; requiere reconciliación."
                )
            token_id = resolved

        return submitted, token_id

    except ChainMintError:
        raise
    except Exception as e:
        logger.error("Error minteando con prueba ZK (%s)", type(e).__name__)
        raise ChainMintError(
            "Fallo interno al enviar o confirmar la transacción"
        ) from e


# === Lecturas de reconciliación =================================================
# La cadena es la única fuente de verdad cuando el registro en Mongo quedó a
# medias. Todas estas devuelven `None`/"unknown" ante un RPC caído: convertir
# "no se pudo consultar" en "no pasó nada" es lo que autoriza un segundo envío
# de gas contra un revert seguro.


def transaction_outcome(tx_hash: str) -> Tuple[str, Optional[int]]:
    """Qué pasó con una transacción de minteo, según la cadena.

    Devuelve `("confirmed", token_id | None)`, `("reverted", None)` o
    `("unknown", None)`.

    `unknown` cubre dos casos que no se distinguen desde fuera —sigue en el
    mempool, o se cayó de él— y por eso nunca se traduce a un veredicto: quien
    llama debe decidir consultando el nullifier, no suponiendo.
    """
    if not can_read_chain() or not tx_hash:
        return ("unknown", None)

    from eth_typing import HexStr
    from web3 import Web3

    try:
        w3 = Web3(
            Web3.HTTPProvider(settings.SEPOLIA_RPC_URL, request_kwargs={"timeout": 10})
        )
        receipt = w3.eth.get_transaction_receipt(HexStr(tx_hash))
    except Exception:
        # Incluye TransactionNotFound: ausencia de recibo no es un veredicto.
        return ("unknown", None)

    if receipt is None:
        return ("unknown", None)
    if int(receipt["status"]) != 1:
        return ("reverted", None)

    token_id = None
    try:
        contract = _read_only_contract()
        events = contract.events.MembershipMinted().process_receipt(receipt)
        if events:
            token_id = int(events[0]["args"]["tokenId"])
    except Exception:
        logger.warning("No se pudo leer el tokenId de un recibo reconciliado")

    return ("confirmed", token_id)


def nullifier_is_used(nullifier_hash: str) -> Optional[bool]:
    """`isNullifierUsed(bytes32)` del contrato. `None` si no se pudo consultar.

    `None` no es `False`: es lo que impide que un RPC caído se lea como "no
    pasó nada on-chain" y habilite un reintento que quemaría gas.
    """
    if not can_read_chain():
        return None
    try:
        raw = bytes.fromhex(nullifier_hash.removeprefix("0x"))
    except (AttributeError, ValueError):
        return None
    if len(raw) != 32:
        return None
    try:
        contract = _read_only_contract()
        return bool(contract.functions.isNullifierUsed(raw).call())
    except Exception as exc:
        logger.error("No se pudo consultar isNullifierUsed() (%s)", type(exc).__name__)
        return None


def has_membership(wallet_address: str) -> bool:
    """`hasMembership(address)` del SBT (ROADMAP 3.1). Bloqueante: llámala en un hilo.

    Lanza `ChainReadError` si la cadena no se pudo consultar. Devolver False
    ante un RPC caído convertiría una incidencia de infraestructura en la
    afirmación "esta persona no es miembro", que es justo la clase de mentira
    que este proyecto está quitando del código.
    """
    from web3 import Web3

    if not can_read_chain():
        raise ChainReadError(
            "La verificación de membresía on-chain requiere SEPOLIA_RPC_URL y "
            "SBT_CONTRACT_ADDRESS válidas."
        )
    try:
        checksummed = Web3.to_checksum_address(wallet_address)
    except (TypeError, ValueError) as exc:
        raise ChainReadError("Dirección Ethereum inválida.") from exc
    try:
        contract = _read_only_contract()
        return bool(contract.functions.hasMembership(checksummed).call())
    except Exception as exc:
        # Sin exc_info y sin el texto del error: la URL del RPC puede llevar
        # una API key y acaba en los logs del proveedor.
        logger.error("No se pudo leer hasMembership() (%s)", type(exc).__name__)
        raise ChainReadError("No se pudo consultar la membresía on-chain.") from exc


def membership_token_of(wallet_address: str) -> Optional[int]:
    """tokenId del SBT de una wallet, o None si no tiene o falla la consulta.

    Se lee de la cadena y no del recibo: el recibo de una UserOperation no
    expone el valor de retorno de la llamada interna.
    """
    from web3 import Web3

    if not can_read_chain():
        return None
    try:
        contract = _read_only_contract()
        token_id = int(
            contract.functions.getMembershipToken(
                Web3.to_checksum_address(wallet_address)
            ).call()
        )
        return token_id or None
    except Exception:
        logger.error("No se pudo leer getMembershipToken()", exc_info=True)
        return None


# === MACICoordinator ==========================================================

_MACI_ABI = [
    {
        "inputs": [],
        "name": "coordinatorPubKeyX",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "coordinatorPubKeyY",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def maci_coordinator_key():
    """Llave pública del coordinador leída del contrato MACI. None si falla.

    Nunca se devuelve la de la configuración como respaldo: el valor de este
    endpoint es precisamente que esté anclado on-chain, y un fallback silencioso
    lo convertiría en una afirmación del servidor.
    """
    from web3 import Web3

    address = settings.MACI_COORDINATOR_ADDRESS.strip()
    rpc = settings.SEPOLIA_RPC_URL.strip()
    if not address or not rpc:
        return None
    try:
        w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 5}))
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(address), abi=_MACI_ABI
        )
        x = int(contract.functions.coordinatorPubKeyX().call())
        y = int(contract.functions.coordinatorPubKeyY().call())
        if x == 0 and y == 0:
            return None
        return (x, y)
    except Exception:
        logger.error("No se pudo leer la llave del coordinador MACI", exc_info=True)
        return None
