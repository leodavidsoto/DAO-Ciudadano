"""
Árbol Merkle de identidades (ADR-001, D-2).

El emisor inserta como máximo un commitment por ciudadano. El commitment lo
calcula el cliente —`Poseidon(identitySecret, recipient, scope)`— y el backend
NUNCA ve `identitySecret`: solo recibe el resultado. Esa es la propiedad que
hace que el servidor no pueda suplantar a nadie ni vincular una prueba con la
persona que la generó.

Diseño: árbol incremental estilo Tornado/Semaphore. En vez de guardar el árbol
completo (2^25 nodos), se mantienen `filled_subtrees[level]` y las raíces de
subárbol vacío `zeros[level]`. Insertar cuesta 25 hashes y O(1) memoria.

Sobre la validez de la ruta: la ruta que se entrega es válida contra la raíz
del momento de la inserción. Insertar después cambia la raíz, pero el contrato
mantiene aprobadas las raíces anteriores (`_approvedIdentityRoots` no se limpia
solo), así que una credencial emitida hoy sigue sirviendo mañana. Si alguien
revoca una raíz con `revokeIdentityRoot`, las credenciales emitidas contra ella
dejan de poder mintear — es una decisión de gobernanza, no un accidente.
"""
import logging
from dataclasses import dataclass
from typing import List, Optional

from pymongo.errors import DuplicateKeyError

from ..core.database import get_collection
from ..core.poseidon import FIELD, poseidon2

logger = logging.getLogger(__name__)

TREE_DEPTH = 25
# 25 niveles admiten 33.554.432 commitments: más que el padrón electoral chileno.
MAX_LEAVES = 1 << TREE_DEPTH

_STATE_ID = "identity_tree_v1"


def identity_tree_collection():
    return get_collection("identity_tree")


def identity_commitments_collection():
    return get_collection("identity_commitments")


class IdentityTreeError(RuntimeError):
    """La inserción no se pudo completar de forma consistente."""


def zero_hashes(depth: int = TREE_DEPTH) -> List[int]:
    """Raíces de subárbol vacío. zeros[0] = 0 (hoja vacía)."""
    zeros = [0]
    for _ in range(depth):
        zeros.append(poseidon2(zeros[-1], zeros[-1]))
    return zeros


# Se calculan una vez por proceso: son constantes del protocolo.
ZEROS = zero_hashes()

# Raíz de un árbol completamente vacío.
EMPTY_ROOT = ZEROS[TREE_DEPTH]


@dataclass(frozen=True)
class MerkleWitness:
    """Lo que el ciudadano necesita para construir su prueba."""

    index: int
    root: int
    path_elements: List[int]
    path_indices: List[int]

    def as_response(self) -> dict:
        # Enteros decimales canónicos: el circuito trabaja sobre el campo, no
        # sobre hex, y el cliente los normaliza como cadenas para no perder
        # precisión en JavaScript (Number no llega a 2^53).
        return {
            "identity_root": str(self.root),
            "path_elements": [str(value) for value in self.path_elements],
            "path_indices": [str(bit) for bit in self.path_indices],
        }


def _validate_commitment(commitment: int) -> int:
    if not isinstance(commitment, int) or isinstance(commitment, bool):
        raise IdentityTreeError("El commitment debe ser un entero.")
    if commitment <= 0 or commitment >= FIELD:
        # El cero es la hoja vacía: aceptarlo rompería la distinción entre
        # una posición ocupada y una libre.
        raise IdentityTreeError("El commitment está fuera del campo escalar BN254.")
    return commitment


async def _load_state() -> dict:
    state = await identity_tree_collection().find_one({"_id": _STATE_ID})
    if state:
        return state
    return {
        "_id": _STATE_ID,
        "next_index": 0,
        "filled_subtrees": [str(value) for value in ZEROS[:TREE_DEPTH]],
        "root": str(EMPTY_ROOT),
    }


def _compute_witness(
    commitment: int,
    index: int,
    filled_subtrees: List[int],
) -> tuple[MerkleWitness, List[int]]:
    """Calcula ruta y raíz nueva, y devuelve los filled_subtrees actualizados.

    `path_indices[level]` es 0 si el nodo actual es hijo izquierdo y 1 si es
    derecho — la misma convención que verify_identity.circom, donde
    `left = hashes[i] + idx*(pathElements[i] - hashes[i])`.
    """
    path_elements: List[int] = []
    path_indices: List[int] = []
    updated = list(filled_subtrees)

    current = commitment
    position = index
    for level in range(TREE_DEPTH):
        if position % 2 == 0:
            # Hijo izquierdo: el hermano derecho todavía está vacío y este
            # nodo pasa a ser el subárbol lleno de su nivel.
            path_elements.append(ZEROS[level])
            path_indices.append(0)
            updated[level] = current
            current = poseidon2(current, ZEROS[level])
        else:
            # Hijo derecho: el hermano izquierdo es el subárbol ya lleno.
            path_elements.append(updated[level])
            path_indices.append(1)
            current = poseidon2(updated[level], current)
        position //= 2

    witness = MerkleWitness(
        index=index,
        root=current,
        path_elements=path_elements,
        path_indices=path_indices,
    )
    return witness, updated


async def insert_commitment(commitment: int, subject_key: str) -> MerkleWitness:
    """Inserta un commitment y devuelve su ruta Merkle.

    Idempotente por `subject_key`: reintentar tras un timeout devuelve la misma
    hoja y la misma ruta en vez de insertar otra. Sin esto, un reintento del
    cliente le daría a la misma persona dos credenciales, que es exactamente el
    doble registro que el nullifier debe impedir.
    """
    commitment = _validate_commitment(commitment)
    if not subject_key:
        raise IdentityTreeError("Falta el identificador de sujeto para la idempotencia.")

    existing = await identity_commitments_collection().find_one(
        {"subject_key": subject_key}
    )
    if existing:
        if int(existing["commitment"]) != commitment:
            # Reutilizar el grant con otro commitment sería emitir una segunda
            # identidad para la misma persona.
            raise IdentityTreeError(
                "Este sujeto ya tiene una credencial emitida con otro commitment."
            )
        return MerkleWitness(
            index=int(existing["leaf_index"]),
            root=int(existing["identity_root"]),
            path_elements=[int(v) for v in existing["path_elements"]],
            path_indices=[int(v) for v in existing["path_indices"]],
        )

    state = await _load_state()
    index = int(state["next_index"])
    if index >= MAX_LEAVES:
        raise IdentityTreeError("El árbol de identidades está lleno.")

    filled_subtrees = [int(v) for v in state["filled_subtrees"]]
    witness, updated_subtrees = _compute_witness(commitment, index, filled_subtrees)

    # El índice único sobre subject_key es lo que realmente impide dos hojas
    # para la misma persona bajo concurrencia; la lectura de arriba solo da un
    # error más claro.
    try:
        await identity_commitments_collection().insert_one({
            "subject_key": subject_key,
            "commitment": str(commitment),
            "leaf_index": index,
            "identity_root": str(witness.root),
            "path_elements": [str(v) for v in witness.path_elements],
            "path_indices": [str(v) for v in witness.path_indices],
        })
    except DuplicateKeyError:
        stored = await identity_commitments_collection().find_one(
            {"subject_key": subject_key}
        )
        if not stored:
            raise IdentityTreeError("Conflicto al insertar el commitment.")
        return MerkleWitness(
            index=int(stored["leaf_index"]),
            root=int(stored["identity_root"]),
            path_elements=[int(v) for v in stored["path_elements"]],
            path_indices=[int(v) for v in stored["path_indices"]],
        )

    # Avanzar el estado solo si la hoja quedó registrada. El filtro por
    # next_index hace la actualización condicional: si otro proceso insertó
    # mientras tanto, esta escritura no pisa la suya.
    result = await identity_tree_collection().update_one(
        {"_id": _STATE_ID, "next_index": index},
        {
            "$set": {
                "next_index": index + 1,
                "filled_subtrees": [str(v) for v in updated_subtrees],
                "root": str(witness.root),
            }
        },
        upsert=True,
    )
    if result.matched_count == 0 and result.upserted_id is None:
        # Otro proceso ganó la carrera: la hoja ya está escrita pero su ruta
        # se calculó contra un estado obsoleto. Falla explícito en vez de
        # entregar una ruta que no reproduce ninguna raíz.
        await identity_commitments_collection().delete_one(
            {"subject_key": subject_key, "leaf_index": index}
        )
        raise IdentityTreeError(
            "Otra inserción concurrente modificó el árbol; reintenta la solicitud."
        )

    logger.info("Identity commitment inserted at leaf %s", index)
    return witness


async def current_root() -> int:
    state = await _load_state()
    return int(state["root"])


async def leaf_count() -> int:
    state = await _load_state()
    return int(state["next_index"])


async def find_by_subject(subject_key: str) -> Optional[MerkleWitness]:
    record = await identity_commitments_collection().find_one(
        {"subject_key": subject_key}
    )
    if not record:
        return None
    return MerkleWitness(
        index=int(record["leaf_index"]),
        root=int(record["identity_root"]),
        path_elements=[int(v) for v in record["path_elements"]],
        path_indices=[int(v) for v in record["path_indices"]],
    )
