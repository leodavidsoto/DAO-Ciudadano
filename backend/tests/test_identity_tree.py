"""
Árbol Merkle de identidades.

Lo que de verdad importa aquí no es que el código corra, sino que la ruta que
el backend entrega reproduzca la misma raíz que calcula el circuito. Por eso
el primer test replica la aritmética de verify_identity.circom en lugar de
comparar contra la implementación misma.
"""
import json
from pathlib import Path

import pytest

from app.core.poseidon import poseidon, poseidon2
from app.services import identity_tree
from app.services.identity_tree import (
    EMPTY_ROOT,
    TREE_DEPTH,
    IdentityTreeError,
    insert_commitment,
    leaf_count,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "circuits"
    / "test"
    / "fixtures"
    / "membership-proof.json"
)
FIXTURE_IDENTITY_SECRET = 18374686479671623683


def fold_path(leaf: int, path_elements, path_indices) -> int:
    """Reproduce el bucle del circuito:

        left  = hashes[i] + idx*(pathElements[i] - hashes[i])
        right = pathElements[i] + idx*(hashes[i] - pathElements[i])

    es decir: idx==0 -> el nodo actual va a la izquierda; idx==1 -> a la derecha.
    """
    current = leaf
    for sibling, index in zip(path_elements, path_indices):
        if index == 0:
            current = poseidon2(current, sibling)
        else:
            current = poseidon2(sibling, current)
    return current


async def test_witness_reproduces_the_circuit_root(client):
    """Una hoja insertada debe reconstruir su raíz con la aritmética del circuito."""
    commitment = poseidon([12345, 67890])

    witness = await insert_commitment(commitment, subject_key="sujeto-a")

    assert len(witness.path_elements) == TREE_DEPTH
    assert len(witness.path_indices) == TREE_DEPTH
    assert set(witness.path_indices) <= {0, 1}
    assert fold_path(commitment, witness.path_elements, witness.path_indices) == witness.root


async def test_matches_the_published_circuit_fixture(client):
    """La primera hoja debe dar exactamente la raíz de la fixture de Codex.

    La fixture inserta su commitment en el índice 0 de un árbol vacío. Si el
    backend produce otra raíz para el mismo commitment, el circuito y el
    backend han divergido.
    """
    if not FIXTURE.exists():
        pytest.skip("Falta la fixture del circuito")
    vector = json.loads(FIXTURE.read_text())

    leaf = poseidon([
        FIXTURE_IDENTITY_SECRET,
        int(vector["recipient"], 16),
        int(vector["membershipScope"]),
    ])

    witness = await insert_commitment(leaf, subject_key="sujeto-fixture")

    assert witness.index == 0
    assert witness.root == int(vector["identityRoot"])
    assert all(index == 0 for index in witness.path_indices)


async def test_several_leaves_stay_consistent(client):
    """Cada hoja debe validar contra la raíz que se le entregó."""
    witnesses = []
    for n in range(5):
        commitment = poseidon([1000 + n, 2000 + n])
        witness = await insert_commitment(commitment, subject_key=f"sujeto-{n}")
        witnesses.append((commitment, witness))

    assert await leaf_count() == 5

    for position, (commitment, witness) in enumerate(witnesses):
        assert witness.index == position
        assert fold_path(
            commitment, witness.path_elements, witness.path_indices
        ) == witness.root

    # Insertar cambia la raíz: no es un error, es lo que obliga al contrato a
    # mantener aprobadas las raíces históricas.
    assert witnesses[0][1].root != witnesses[-1][1].root


async def test_insertion_is_idempotent_per_subject(client):
    """Un reintento no puede darle dos credenciales a la misma persona."""
    commitment = poseidon([42, 43])

    first = await insert_commitment(commitment, subject_key="sujeto-repetido")
    second = await insert_commitment(commitment, subject_key="sujeto-repetido")

    assert await leaf_count() == 1
    assert first.index == second.index
    assert first.root == second.root
    assert first.path_elements == second.path_elements


async def test_same_subject_cannot_swap_commitment(client):
    """Reutilizar el sujeto con otro commitment sería una segunda identidad."""
    await insert_commitment(poseidon([7, 8]), subject_key="sujeto-unico")

    with pytest.raises(IdentityTreeError):
        await insert_commitment(poseidon([9, 10]), subject_key="sujeto-unico")


async def test_rejects_commitments_outside_the_field(client):
    from app.core.poseidon import FIELD

    for invalid in (0, -1, FIELD, FIELD + 1):
        with pytest.raises(IdentityTreeError):
            await insert_commitment(invalid, subject_key=f"invalido-{invalid}")


async def test_empty_root_is_the_zero_subtree(client):
    """Un árbol sin hojas tiene la raíz del subárbol vacío, no cero."""
    assert await identity_tree.current_root() == EMPTY_ROOT
    assert EMPTY_ROOT != 0
