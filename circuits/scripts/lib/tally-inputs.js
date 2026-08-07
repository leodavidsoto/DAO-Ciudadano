"use strict";
/**
 * Construcción de entradas para `maci_tally.circom`.
 *
 * Vive aparte porque lo necesitan dos consumidores con ciclos de vida
 * distintos: el generador del fixture de tests (`generate-tally-fixture.js`) y
 * la tarea de Hardhat `maci:tally`. Duplicar el árbol de Merkle y el orden de
 * los inputs en ambos es exactamente el tipo de divergencia que produce una
 * prueba que verifica off-chain y falla on-chain sin explicación.
 *
 * El árbol replica la convención de `verify_identity.circom`:
 * pathIndices[i] == 0 significa que el nodo actual es hijo izquierdo.
 */

const assert = require("node:assert/strict");
const { buildPoseidon } = require("circomlibjs");

// Fijados en `component main` de maci_tally.circom. Cambiarlos aquí sin
// recompilar el circuito produce testigos que no satisfacen las restricciones.
const STATE_TREE_DEPTH = 10;
const BATCH_SIZE = 5;
const VOTE_OPTIONS = 3;
const MAX_VOICE_CREDITS = 1;

const FIELD =
    21888242871839275222246405745257275088548364400416034343698204186575808495617n;

/**
 * @param {object} options
 * @param {bigint[][]} options.votes  BATCH_SIZE x VOTE_OPTIONS
 * @param {bigint[]} [options.currentResults]  totales previos (por defecto 0)
 * @param {bigint} [options.currentSalt]
 * @param {bigint} [options.newSalt]
 * @returns entradas del circuito más los valores derivados que hacen falta
 *          para armar la llamada on-chain.
 */
async function buildTallyInput({
    votes,
    currentResults = Array(VOTE_OPTIONS).fill(0n),
    currentSalt = 111n,
    newSalt = 222n,
} = {}) {
    assert.equal(
        votes.length, BATCH_SIZE,
        `El lote debe tener exactamente ${BATCH_SIZE} votantes`
    );
    for (const vote of votes) {
        assert.equal(
            vote.length, VOTE_OPTIONS,
            `Cada voto debe cubrir ${VOTE_OPTIONS} opciones`
        );
        const spent = vote.reduce((a, b) => a + b, 0n);
        // Se comprueba acá además de en el circuito: un lote inválido produce
        // un fallo críptico de generación de testigo, y saber cuál votante lo
        // rompió ahorra depurar restricciones a ciegas.
        assert.ok(
            spent <= BigInt(MAX_VOICE_CREDITS),
            `Un votante gasta ${spent} créditos y solo tiene ${MAX_VOICE_CREDITS}`
        );
    }

    const poseidon = await buildPoseidon();
    const H = (inputs) => BigInt(poseidon.F.toString(poseidon(inputs)));

    const zeros = [0n];
    for (let level = 0; level < STATE_TREE_DEPTH; level += 1) {
        zeros.push(H([zeros[level], zeros[level]]));
    }

    const pubKeyX = votes.map((_, i) => 100n + BigInt(i));
    const pubKeyY = votes.map((_, i) => 200n + BigInt(i));
    const voiceCredits = Array(BATCH_SIZE).fill(BigInt(MAX_VOICE_CREDITS));

    const leaves = votes.map((v, i) =>
        H([pubKeyX[i], pubKeyY[i], voiceCredits[i], H(v)])
    );

    let level = [...leaves];
    const levels = [level];
    for (let depth = 0; depth < STATE_TREE_DEPTH; depth += 1) {
        const next = [];
        for (let i = 0; i < Math.ceil(level.length / 2); i += 1) {
            next.push(
                H([level[2 * i] ?? zeros[depth], level[2 * i + 1] ?? zeros[depth]])
            );
        }
        level = next;
        levels.push(level);
    }
    const stateRoot = level[0];

    const pathElements = [];
    const pathIndices = [];
    for (let i = 0; i < BATCH_SIZE; i += 1) {
        const elements = [];
        const indices = [];
        let position = i;
        for (let depth = 0; depth < STATE_TREE_DEPTH; depth += 1) {
            const sibling = position % 2 === 0 ? position + 1 : position - 1;
            elements.push((levels[depth][sibling] ?? zeros[depth]).toString());
            indices.push(position % 2);
            position = Math.floor(position / 2);
        }
        pathElements.push(elements);
        pathIndices.push(indices);
    }

    const newResults = Array.from({ length: VOTE_OPTIONS }, (_, j) =>
        votes.reduce((acc, vote) => acc + vote[j], currentResults[j])
    );

    const commit = (salt, results) => H([salt, ...results]);
    const currentResultsCommitment = commit(currentSalt, currentResults);
    const newResultsCommitment = commit(newSalt, newResults);

    const input = {
        pubKeyX: pubKeyX.map(String),
        pubKeyY: pubKeyY.map(String),
        voiceCredits: voiceCredits.map(String),
        votes: votes.map((v) => v.map(String)),
        pathElements,
        pathIndices,
        currentResults: currentResults.map(String),
        currentSalt: currentSalt.toString(),
        newResults: newResults.map(String),
        newSalt: newSalt.toString(),
        stateRoot: stateRoot.toString(),
        currentResultsCommitment: currentResultsCommitment.toString(),
        newResultsCommitment: newResultsCommitment.toString(),
    };

    return {
        input,
        stateRoot,
        currentResults,
        newResults,
        currentSalt,
        newSalt,
        currentResultsCommitment,
        newResultsCommitment,
        // El orden es frontera de protocolo con el verificador desplegado.
        expectedSignals: [
            stateRoot.toString(),
            currentResultsCommitment.toString(),
            newResultsCommitment.toString(),
        ],
    };
}

/** Lote del piloto: 3 a favor, 1 en contra, 1 abstención. */
function defaultVotes() {
    return [
        [1n, 0n, 0n],
        [1n, 0n, 0n],
        [1n, 0n, 0n],
        [0n, 1n, 0n],
        [0n, 0n, 1n],
    ];
}

module.exports = {
    buildTallyInput,
    defaultVotes,
    STATE_TREE_DEPTH,
    BATCH_SIZE,
    VOTE_OPTIONS,
    MAX_VOICE_CREDITS,
    FIELD,
};
