"""
Poseidon hash sobre BN254, compatible bit a bit con circomlib.

Por qué existe este módulo en vez de una dependencia:

Las opciones de PyPI (`poseidon-hash`) arrastran numba, llvmlite, galois y
numpy — 261 MB medidos — y compilan en JIT durante minutos en el primer uso.
El backend corre en el plan free de Render (512 MB, arranque en frío de 30-60 s
ya documentado en HANDOFF), así que eso no es viable. Esta implementación es
stdlib puro: aritmética modular con enteros de Python.

Por qué la compatibilidad exacta es crítica:

El backend construye el árbol Merkle cuya raíz se aprueba on-chain y cuya ruta
recibe el ciudadano. Si este Poseidon difiere del de circomlib aunque sea en
una constante, el circuito calcula otra raíz y **todas** las pruebas fallan al
verificarse — sin ningún error que apunte a la causa. Por eso
`tests/test_poseidon.py` lo contrasta contra el vector público que Codex
generó con circomlibjs (`circuits/test/fixtures/membership-proof.json`).

Algoritmo (espejo de circomlibjs/src/poseidon_reference.js):

    state = [0, *inputs]
    para cada ronda r:
        state[i] += C[r * t + i]
        s-box: x^5 en todas las posiciones (ronda completa) o solo en
               state[0] (ronda parcial)
        state = M · state
    devuelve state[0]

Las rondas completas son las 4 primeras y las 4 últimas; las del medio son
parciales. Es la construcción HADES estándar.
"""
from .poseidon_constants import CONSTANTS, FIELD, N_ROUNDS_F, N_ROUNDS_P


class PoseidonError(ValueError):
    """Entrada fuera del campo escalar o aridad no soportada."""


def _check_field_element(value: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PoseidonError(f"{label} debe ser un entero.")
    if value < 0 or value >= FIELD:
        raise PoseidonError(f"{label} está fuera del campo escalar BN254.")
    return value


def poseidon(inputs: list[int]) -> int:
    """Poseidon(inputs) -> elemento del campo, igual que circomlib.

    Soporta 2 y 3 entradas, que es lo que usa el protocolo:
      - 2 entradas: nodos internos del árbol Merkle y el nullifier
      - 3 entradas: la hoja Poseidon(identitySecret, recipient, scope)
        (el backend no la calcula —no conoce el secreto— pero se soporta
        para poder verificar el vector completo en los tests)
    """
    n = len(inputs)
    if n not in CONSTANTS:
        raise PoseidonError(
            f"Poseidon con {n} entradas no está soportado (disponibles: {sorted(CONSTANTS)})."
        )

    constants, mds = CONSTANTS[n]
    for index, value in enumerate(inputs):
        _check_field_element(value, f"La entrada {index}")

    t = n + 1
    rounds_p = N_ROUNDS_P[n]
    half_f = N_ROUNDS_F // 2

    # El primer elemento del estado es la capacidad, siempre 0.
    state = [0] + list(inputs)

    for round_index in range(N_ROUNDS_F + rounds_p):
        # ARK: suma de constantes de ronda
        base = round_index * t
        state = [(state[i] + constants[base + i]) % FIELD for i in range(t)]

        # S-box x^5. Rondas completas al principio y al final; parciales en
        # medio (solo state[0]), que es lo que abarata el circuito.
        if round_index < half_f or round_index >= half_f + rounds_p:
            state = [pow(x, 5, FIELD) for x in state]
        else:
            state[0] = pow(state[0], 5, FIELD)

        # MIX: producto por la matriz MDS
        state = [
            sum(mds[i][j] * state[j] for j in range(t)) % FIELD
            for i in range(t)
        ]

    return state[0]


def poseidon2(left: int, right: int) -> int:
    """Atajo para nodos internos del árbol Merkle."""
    return poseidon([left, right])
