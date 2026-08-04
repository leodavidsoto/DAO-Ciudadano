"""
Firma de UserOperations para Safe (Safe4337Module).

Esto es lo más fácil de equivocar en silencio de toda la capa ERC-4337: una
construcción mal armada no falla acá, falla como `AA24 signature error` en el
EntryPoint después de que el bundler ya cobró la simulación.

Se fijan las piezas deterministas: el literal del tipo, el dominio, qué entra
en el hash y el empaquetado final. Lo que NO se puede probar sin una Safe
desplegada y un bundler es que el módulo acepte la firma — y eso queda dicho
en el módulo y en `paymaster_service.status()`.
"""

import pytest
from eth_account import Account
from eth_utils import keccak

from app.services import safe_4337
from app.services.safe_4337 import SafeOpValidity

OWNER = Account.from_key("0x" + "c3" * 32)
MODULE = "0x75cf11467937ce3F2f357CE24ffc3DBF8fD5c226"
ENTRYPOINT = "0x0000000071727De22E5E9d8BAf0edAc6f37da032"
CHAIN_ID = 11155111

BASE_OP = {
    "sender": "0x" + "11" * 20,
    "nonce": "0x0",
    "callData": "0xdeadbeef",
    "verificationGasLimit": "0x186a0",
    "callGasLimit": "0x186a0",
    "preVerificationGas": "0xc350",
    "maxPriorityFeePerGas": "0x3b9aca00",
    "maxFeePerGas": "0x77359400",
}


def test_safe_op_typehash_matches_the_literal():
    """El typehash debe salir del literal, no ser una constante opaca."""
    assert safe_4337.SAFE_OP_TYPEHASH == keccak(text=safe_4337.SAFE_OP_TYPE_STRING)
    # El orden de los campos es parte del contrato con el módulo.
    assert safe_4337.SAFE_OP_TYPE_STRING.startswith(
        "SafeOp(address safe,uint256 nonce,"
    )
    assert safe_4337.SAFE_OP_TYPE_STRING.endswith("address entryPoint)")


def test_domain_uses_the_module_not_the_safe():
    """verifyingContract es el MÓDULO. Usar la Safe da otro dominio."""
    with_module = safe_4337.domain_separator(CHAIN_ID, MODULE)
    with_safe = safe_4337.domain_separator(CHAIN_ID, BASE_OP["sender"])
    assert with_module != with_safe


def test_domain_is_chain_specific():
    """Sin chainId una firma valdría en otra red (replay entre cadenas)."""
    assert safe_4337.domain_separator(1, MODULE) != safe_4337.domain_separator(
        CHAIN_ID, MODULE
    )


def test_digest_changes_with_every_signed_field():
    """Cada campo debe entrar en el hash: si no, es maleable."""
    validity = SafeOpValidity()
    base = safe_4337.safe_op_digest(BASE_OP, ENTRYPOINT, CHAIN_ID, MODULE, validity)

    for field, value in [
        ("sender", "0x" + "22" * 20),
        ("nonce", "0x1"),
        ("callData", "0xc0ffee"),
        ("callGasLimit", "0x30d40"),
        ("maxFeePerGas", "0x1"),
    ]:
        mutated = {**BASE_OP, field: value}
        assert (
            safe_4337.safe_op_digest(mutated, ENTRYPOINT, CHAIN_ID, MODULE, validity)
            != base
        ), f"El campo {field} no entra en el digest"


def test_paymaster_fields_are_packed_in_entrypoint_order():
    """v0.7 desglosa el paymaster; el módulo lo firma concatenado."""
    packed = safe_4337._paymaster_and_data(
        {
            "paymaster": "0x" + "33" * 20,
            "paymasterVerificationGasLimit": "0x1",
            "paymasterPostOpGasLimit": "0x2",
            "paymasterData": "0xabcd",
        }
    )
    # 20 bytes de dirección + 16 + 16 de límites + los datos.
    assert len(packed) == 20 + 16 + 16 + 2
    assert packed[:20].hex() == "33" * 20


def test_no_paymaster_is_empty_bytes_not_zeroes():
    assert safe_4337._paymaster_and_data({}) == b""


def test_signature_packs_validity_before_the_ecdsa_bytes():
    """validAfter(6) ‖ validUntil(6) ‖ firma. El módulo los lee de ahí."""
    signature = safe_4337.pack_signature(b"\xaa" * 65, SafeOpValidity(1, 2))
    raw = bytes.fromhex(signature[2:])

    assert len(raw) == 6 + 6 + 65
    assert int.from_bytes(raw[:6], "big") == 1
    assert int.from_bytes(raw[6:12], "big") == 2
    assert raw[12:] == b"\xaa" * 65


def test_signing_recovers_the_owner_from_the_safeop_digest():
    """La firma debe recuperar al propietario sobre el digest EIP-712.

    Si se firmara el userOpHash del EntryPoint —el error intuitivo— el módulo
    recuperaría otra dirección y rechazaría la operación.
    """
    validity = SafeOpValidity()
    signed = safe_4337.sign_user_operation(
        BASE_OP,
        private_key=OWNER.key.hex(),
        entrypoint=ENTRYPOINT,
        chain_id=CHAIN_ID,
        module_address=MODULE,
        validity=validity,
    )

    raw = bytes.fromhex(signed["signature"][2:])
    owner_signature = raw[12:]
    digest = safe_4337.safe_op_digest(BASE_OP, ENTRYPOINT, CHAIN_ID, MODULE, validity)

    recovered = Account._recover_hash(digest, signature=owner_signature)
    assert recovered == OWNER.address


def test_signing_requires_a_key():
    with pytest.raises(safe_4337.SafeSigningError):
        safe_4337.sign_user_operation(
            BASE_OP,
            private_key="",
            entrypoint=ENTRYPOINT,
            chain_id=CHAIN_ID,
            module_address=MODULE,
        )


def test_missing_gas_field_fails_loudly():
    """Un campo ausente no puede firmarse como cero implícito."""
    incomplete = {k: v for k, v in BASE_OP.items() if k != "callGasLimit"}
    with pytest.raises(safe_4337.SafeSigningError):
        safe_4337.safe_op_digest(
            incomplete, ENTRYPOINT, CHAIN_ID, MODULE, SafeOpValidity()
        )
