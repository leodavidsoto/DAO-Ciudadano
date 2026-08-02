"""
Compatibilidad de app/core/poseidon.py con circomlib.

Esta es la prueba que sostiene toda la capa ZK del backend. Si Poseidon
difiere de circomlib aunque sea en una constante, el backend publica una raíz
Merkle que el circuito no reproduce y **todas** las pruebas fallan al
verificarse on-chain, sin ningún mensaje que apunte a la causa.

Los vectores no están inventados: salen de
`circuits/test/fixtures/membership-proof.json`, que Codex generó con
circomlibjs y cuya prueba verifica contra el verificador desplegado.
"""
import json
from pathlib import Path

import pytest

from app.core.poseidon import FIELD, PoseidonError, poseidon, poseidon2

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "circuits"
    / "test"
    / "fixtures"
    / "membership-proof.json"
)

# Secreto del generador de la fixture (circuits/scripts/generate-test-fixture.js).
# Es material de prueba público y determinista; nunca debe usarse en producción.
FIXTURE_IDENTITY_SECRET = 18374686479671623683

TREE_DEPTH = 25


@pytest.fixture(scope="module")
def vector():
    if not FIXTURE.exists():
        pytest.skip(f"Falta la fixture del circuito: {FIXTURE}")
    return json.loads(FIXTURE.read_text())


def test_nullifier_matches_circomlib(vector):
    """nullifierHash = Poseidon(identitySecret, scope) — 2 entradas."""
    computed = poseidon([FIXTURE_IDENTITY_SECRET, int(vector["membershipScope"])])
    assert computed == int(vector["nullifierHash"], 16)


def test_identity_root_matches_circomlib(vector):
    """Reproduce la raíz completa: hoja de 3 entradas + 25 niveles de 2."""
    scope = int(vector["membershipScope"])
    recipient = int(vector["recipient"], 16)

    leaf = poseidon([FIXTURE_IDENTITY_SECRET, recipient, scope])

    # Subárboles vacíos: zero_hashes[i] es la raíz de un subárbol vacío de nivel i.
    zero_hashes = [0]
    for _ in range(TREE_DEPTH):
        zero_hashes.append(poseidon2(zero_hashes[-1], zero_hashes[-1]))

    root = leaf
    for level in range(TREE_DEPTH):
        root = poseidon2(root, zero_hashes[level])

    assert root == int(vector["identityRoot"])


def test_public_signal_order_is_the_protocol_boundary(vector):
    """El orden [identityRoot, nullifierHash, recipient, scope] es contrato.

    El contrato construye las señales en ese orden exacto. Si cambia, el
    verificador rechaza pruebas válidas.
    """
    assert vector["signalOrder"] == [
        "identityRoot",
        "nullifierHash",
        "recipient",
        "scope",
    ]
    assert vector["publicSignals"] == [
        vector["identityRoot"],
        str(int(vector["nullifierHash"], 16)),
        str(int(vector["recipient"], 16)),
        vector["membershipScope"],
    ]


def test_poseidon_is_deterministic():
    assert poseidon([1, 2]) == poseidon([1, 2])
    assert poseidon([1, 2]) != poseidon([2, 1])


def test_rejects_values_outside_the_scalar_field():
    with pytest.raises(PoseidonError):
        poseidon([FIELD, 1])
    with pytest.raises(PoseidonError):
        poseidon([-1, 1])
    with pytest.raises(PoseidonError):
        poseidon([True, 1])  # bool no es un elemento de campo


def test_rejects_unsupported_arity():
    with pytest.raises(PoseidonError):
        poseidon([1])
    with pytest.raises(PoseidonError):
        poseidon([1, 2, 3, 4])
