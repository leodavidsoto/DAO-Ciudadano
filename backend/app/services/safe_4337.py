"""
Firma de UserOperations para cuentas Safe vía Safe4337Module (ADR-001, D-1).

Por qué un módulo aparte: una Safe NO firma el `userOpHash` del EntryPoint.
El Safe4337Module define su propia estructura EIP-712 (`SafeOp`) y valida la
firma contra ella. Firmar el hash del EntryPoint —el error intuitivo— produce
`AA24 signature error` después de que el bundler ya cobró la simulación.

Estructura que se firma (Safe4337Module v0.3.0, EntryPoint v0.7):

    SafeOp(
        address safe, uint256 nonce, bytes initCode, bytes callData,
        uint128 verificationGasLimit, uint128 callGasLimit,
        uint256 preVerificationGas,
        uint128 maxPriorityFeePerGas, uint128 maxFeePerGas,
        bytes paymasterAndData, uint48 validAfter, uint48 validUntil,
        address entryPoint
    )

Dominio EIP-712: `EIP712Domain(uint256 chainId, address verifyingContract)`,
donde `verifyingContract` es la dirección del **módulo**, no la de la Safe.

Formato final de la firma que espera el módulo:

    validAfter (6 bytes) ‖ validUntil (6 bytes) ‖ firmas de los propietarios

Los 12 bytes de validez van FUERA de la firma ECDSA pero DENTRO del campo
`signature` de la UserOperation, porque el módulo los lee de ahí antes de
verificar.

ESTADO DE VERIFICACIÓN: la construcción sigue la especificación del módulo y
está cubierta por tests deterministas (typehash, dominio, empaquetado, orden
de firmantes). NO se ha ejecutado contra un bundler ni una Safe desplegada:
este entorno no tiene credenciales ni cuenta. Hasta que eso ocurra, el
transporte permanece apagado por configuración.
"""
import logging
from dataclasses import dataclass

from eth_abi import encode as abi_encode
from eth_utils import keccak

logger = logging.getLogger(__name__)

# keccak256 del literal del tipo SafeOp. Se calcula, no se pega como constante
# opaca: así el literal queda auditable junto al hash.
SAFE_OP_TYPE_STRING = (
    "SafeOp(address safe,uint256 nonce,bytes initCode,bytes callData,"
    "uint128 verificationGasLimit,uint128 callGasLimit,uint256 preVerificationGas,"
    "uint128 maxPriorityFeePerGas,uint128 maxFeePerGas,bytes paymasterAndData,"
    "uint48 validAfter,uint48 validUntil,address entryPoint)"
)
SAFE_OP_TYPEHASH = keccak(text=SAFE_OP_TYPE_STRING)

DOMAIN_TYPE_STRING = "EIP712Domain(uint256 chainId,address verifyingContract)"
DOMAIN_TYPEHASH = keccak(text=DOMAIN_TYPE_STRING)


class SafeSigningError(RuntimeError):
    """La UserOperation no se pudo firmar de forma verificable."""


@dataclass(frozen=True)
class SafeOpValidity:
    """Ventana de validez. 0/0 significa "sin límite", que es lo habitual."""

    valid_after: int = 0
    valid_until: int = 0


def _to_bytes(value) -> bytes:
    """Normaliza hex o bytes a bytes. Un campo ausente es b''."""
    if value is None or value == "":
        return b""
    if isinstance(value, bytes):
        return value
    text = str(value)
    if not text.startswith("0x"):
        raise SafeSigningError(f"Se esperaba hexadecimal con prefijo 0x: {text[:20]}")
    return bytes.fromhex(text[2:])


def _to_int(value, label: str) -> int:
    if value is None:
        raise SafeSigningError(f"Falta {label} en la UserOperation.")
    if isinstance(value, int):
        return value
    text = str(value)
    return int(text, 16) if text.startswith("0x") else int(text)


def domain_separator(chain_id: int, module_address: str) -> bytes:
    """Separador de dominio del Safe4337Module.

    `verifyingContract` es el MÓDULO, no la Safe. Usar la Safe produce un
    dominio distinto y una firma que el módulo rechaza.
    """
    return keccak(
        abi_encode(
            ["bytes32", "uint256", "address"],
            [DOMAIN_TYPEHASH, chain_id, module_address],
        )
    )


def safe_op_struct_hash(user_op: dict, entrypoint: str, validity: SafeOpValidity) -> bytes:
    """Hash de la estructura SafeOp.

    `initCode`, `callData` y `paymasterAndData` entran como keccak de sus
    bytes, según la codificación EIP-712 de tipos dinámicos.
    """
    paymaster_and_data = _paymaster_and_data(user_op)

    return keccak(
        abi_encode(
            [
                "bytes32", "address", "uint256", "bytes32", "bytes32",
                "uint128", "uint128", "uint256",
                "uint128", "uint128", "bytes32",
                "uint48", "uint48", "address",
            ],
            [
                SAFE_OP_TYPEHASH,
                user_op["sender"],
                _to_int(user_op.get("nonce"), "nonce"),
                keccak(_init_code(user_op)),
                keccak(_to_bytes(user_op.get("callData"))),
                _to_int(user_op.get("verificationGasLimit"), "verificationGasLimit"),
                _to_int(user_op.get("callGasLimit"), "callGasLimit"),
                _to_int(user_op.get("preVerificationGas"), "preVerificationGas"),
                _to_int(user_op.get("maxPriorityFeePerGas"), "maxPriorityFeePerGas"),
                _to_int(user_op.get("maxFeePerGas"), "maxFeePerGas"),
                keccak(paymaster_and_data),
                validity.valid_after,
                validity.valid_until,
                entrypoint,
            ],
        )
    )


def _init_code(user_op: dict) -> bytes:
    """initCode = factory ‖ factoryData en v0.7, o el campo directo en v0.6."""
    factory = user_op.get("factory")
    if factory:
        return _to_bytes(factory) + _to_bytes(user_op.get("factoryData"))
    return _to_bytes(user_op.get("initCode"))


def _paymaster_and_data(user_op: dict) -> bytes:
    """En v0.7 el paymaster viene desglosado; el módulo lo firma concatenado.

    Orden fijado por el EntryPoint v0.7:
      paymaster (20) ‖ verificationGasLimit (16) ‖ postOpGasLimit (16) ‖ data
    """
    if user_op.get("paymasterAndData"):
        return _to_bytes(user_op["paymasterAndData"])

    paymaster = user_op.get("paymaster")
    if not paymaster:
        return b""

    return (
        _to_bytes(paymaster)
        + _to_int(user_op.get("paymasterVerificationGasLimit", 0), "paymasterVerificationGasLimit").to_bytes(16, "big")
        + _to_int(user_op.get("paymasterPostOpGasLimit", 0), "paymasterPostOpGasLimit").to_bytes(16, "big")
        + _to_bytes(user_op.get("paymasterData"))
    )


def safe_op_digest(
    user_op: dict,
    entrypoint: str,
    chain_id: int,
    module_address: str,
    validity: SafeOpValidity,
) -> bytes:
    """Digest EIP-712 completo: 0x1901 ‖ dominio ‖ structHash."""
    return keccak(
        b"\x19\x01"
        + domain_separator(chain_id, module_address)
        + safe_op_struct_hash(user_op, entrypoint, validity)
    )


def pack_signature(owner_signatures: bytes, validity: SafeOpValidity) -> str:
    """validAfter (6) ‖ validUntil (6) ‖ firmas.

    El módulo lee los 12 bytes de validez del propio campo `signature`, así
    que van dentro pero fuera de lo firmado por ECDSA.
    """
    return "0x" + (
        validity.valid_after.to_bytes(6, "big")
        + validity.valid_until.to_bytes(6, "big")
        + owner_signatures
    ).hex()


def split_packed_signature(signature) -> tuple[SafeOpValidity, bytes]:
    """Separa `validAfter ‖ validUntil ‖ firma` tal como lo empaqueta el módulo.

    Los 12 primeros bytes son la ventana de validez que el módulo lee del
    propio campo `signature`; el resto es la firma ECDSA del propietario.
    """
    raw = _to_bytes(signature)
    if len(raw) < 12 + 65:
        raise ValueError(
            "La firma SafeOp debe ser validAfter(6) + validUntil(6) + 65 bytes"
        )
    validity = SafeOpValidity(
        valid_after=int.from_bytes(raw[:6], "big"),
        valid_until=int.from_bytes(raw[6:12], "big"),
    )
    return validity, raw[12:]


def recover_owner(
    user_op: dict,
    entrypoint: str,
    chain_id: int,
    module_address: str,
) -> str:
    """Dirección que firmó esta SafeOp. Lanza ValueError si no se puede recuperar.

    Verificar no es firmar: el backend nunca es propietario de la Safe, pero
    sí puede comprobar que la operación que va a retransmitir la autorizó
    quien dice. Sin esto se pagaba el viaje al bundler para recibir un rechazo
    opaco, y se retransmitía una operación cuya autorización nadie miró.

    Se admiten las dos convenciones que producen las wallets reales:
    `v` 27/28 para una firma EIP-712 directa y `v` 31/32 para la variante de
    Safe en que el digest se firmó envuelto en el prefijo de `personal_sign`.
    """
    from eth_keys.datatypes import Signature

    validity, owner_signature = split_packed_signature(user_op.get("signature"))
    if len(owner_signature) != 65:
        raise ValueError(
            "Solo se admite una Safe de un propietario (firma de 65 bytes)"
        )

    digest = safe_op_digest(
        {k: v for k, v in user_op.items() if k != "signature"},
        entrypoint,
        chain_id,
        module_address,
        validity,
    )

    v = owner_signature[64]
    if v in (31, 32):
        # Convención de Safe: el propietario firmó el digest envuelto en el
        # prefijo de personal_sign. Hay que reproducir ese envoltorio o la
        # dirección recuperada sería otra cualquiera.
        digest = keccak(b"\x19Ethereum Signed Message:\n32" + digest)
        v -= 4
    if v in (27, 28):
        v -= 27
    if v not in (0, 1):
        raise ValueError(f"Parámetro de recuperación inválido en la firma: {v}")

    signature = Signature(owner_signature[:64] + bytes([v]))
    return signature.recover_public_key_from_msg_hash(digest).to_checksum_address()


def sign_user_operation(
    user_op: dict,
    private_key: str,
    entrypoint: str,
    chain_id: int,
    module_address: str,
    validity: SafeOpValidity = SafeOpValidity(),
) -> dict:
    """Firma la UserOperation para una Safe de un solo propietario.

    Limitación explícita: una Safe con umbral > 1 necesita las firmas de
    varios propietarios concatenadas y ORDENADAS por dirección ascendente.
    Este servicio firma con una sola llave, así que solo sirve para una Safe
    de umbral 1. Con umbral mayor, el módulo rechaza la operación — falla
    ruidoso, no silencioso.
    """
    from eth_account import Account

    if not private_key:
        raise SafeSigningError("Falta la llave del propietario de la Safe.")

    digest = safe_op_digest(user_op, entrypoint, chain_id, module_address, validity)

    # Se firma el digest EIP-712 ya construido, sin volver a prefijarlo:
    # `sign_message` con encode_defunct añadiría el prefijo personal_sign y el
    # módulo recuperaría otro firmante.
    signed = Account._sign_hash(digest, private_key=private_key)
    owner_signature = (
        signed.r.to_bytes(32, "big")
        + signed.s.to_bytes(32, "big")
        + bytes([signed.v])
    )

    return {**user_op, "signature": pack_signature(owner_signature, validity)}
