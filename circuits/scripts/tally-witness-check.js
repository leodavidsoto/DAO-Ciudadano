"use strict";
/**
 * Comprueba que maci_tally.circom es satisfacible con entradas honestas y que
 * RECHAZA las deshonestas.
 *
 * Sin esto, "compila" solo significa que la sintaxis es válida — no que las
 * restricciones digan lo que creemos. Un circuito que compila pero no
 * restringe deja pasar recuentos falsos con una prueba perfectamente válida,
 * que es el peor resultado posible en una elección.
 *
 * Cada caso corre en su propio proceso (`node tally-witness-check.js <caso>`):
 * snarkjs deja un FileHandle sin cerrar en la ruta de error y Node 25 lo
 * convierte en excepción durante la recolección de basura, lo que enmascararía
 * los casos siguientes.
 */
const assert = require("node:assert/strict");
const os = require("node:os");
const path = require("node:path");
const { buildPoseidon } = require("circomlibjs");
const snarkjs = require("snarkjs");

const DEPTH = 10;
const BATCH = 5;

const wasm = path.join(
    __dirname, "..", "build", "tally", "maci_tally_js", "maci_tally.wasm"
);

let counter = 0;
const calc = (input) =>
    snarkjs.wtns.calculate(
        input,
        wasm,
        path.join(os.tmpdir(), `tally-wtns-${process.pid}-${counter++}.wtns`)
    );

async function buildHonestInput() {
    const poseidon = await buildPoseidon();
    const H = (xs) => BigInt(poseidon.F.toString(poseidon(xs)));

    const zeros = [0n];
    for (let i = 0; i < DEPTH; i++) zeros.push(H([zeros[i], zeros[i]]));

    // 3 a favor, 1 en contra, 1 abstención. Un crédito por votante.
    const votes = [
        [1n, 0n, 0n],
        [1n, 0n, 0n],
        [1n, 0n, 0n],
        [0n, 1n, 0n],
        [0n, 0n, 1n],
    ];
    const pubKeyX = votes.map((_, i) => 100n + BigInt(i));
    const pubKeyY = votes.map((_, i) => 200n + BigInt(i));
    const leaves = votes.map((v, i) => H([pubKeyX[i], pubKeyY[i], 1n, H(v)]));

    let level = [...leaves];
    const levels = [level];
    for (let d = 0; d < DEPTH; d++) {
        const next = [];
        for (let i = 0; i < Math.ceil(level.length / 2); i++) {
            next.push(H([level[2 * i] ?? zeros[d], level[2 * i + 1] ?? zeros[d]]));
        }
        level = next;
        levels.push(level);
    }
    const stateRoot = level[0];

    const pathElements = [];
    const pathIndices = [];
    for (let i = 0; i < BATCH; i++) {
        const el = [];
        const idx = [];
        let position = i;
        for (let d = 0; d < DEPTH; d++) {
            const sibling = position % 2 === 0 ? position + 1 : position - 1;
            el.push((levels[d][sibling] ?? zeros[d]).toString());
            idx.push(position % 2); // 0 = el nodo actual es hijo izquierdo
            position = Math.floor(position / 2);
        }
        pathElements.push(el);
        pathIndices.push(idx);
    }

    const currentResults = [0n, 0n, 0n];
    const newResults = [3n, 1n, 1n];
    const currentSalt = 111n;
    const newSalt = 222n;
    const commit = (salt, r) => H([salt, ...r]);

    return {
        commit,
        newSalt,
        votes,
        input: {
            pubKeyX: pubKeyX.map(String),
            pubKeyY: pubKeyY.map(String),
            voiceCredits: Array(BATCH).fill("1"),
            votes: votes.map((v) => v.map(String)),
            pathElements,
            pathIndices,
            currentResults: currentResults.map(String),
            currentSalt: currentSalt.toString(),
            newResults: newResults.map(String),
            newSalt: newSalt.toString(),
            stateRoot: stateRoot.toString(),
            currentResultsCommitment: commit(currentSalt, currentResults).toString(),
            newResultsCommitment: commit(newSalt, newResults).toString(),
        },
    };
}

const CASES = {
    honest: async ({ input }) => {
        await calc(input);
        return "entradas honestas: testigo generado";
    },

    totals: async ({ input, commit, newSalt }) => {
        // Publicar un total que no es la suma del lote.
        await assert.rejects(
            calc({
                ...input,
                newResults: ["99", "1", "1"],
                newResultsCommitment: commit(newSalt, [99n, 1n, 1n]).toString(),
            })
        );
        return "totales inflados: rechazado";
    },

    credits: async ({ input, commit, newSalt, votes }) => {
        // Un votante gastando 5 créditos cuando tiene 1.
        await assert.rejects(
            calc({
                ...input,
                votes: [["5", "0", "0"], ...votes.slice(1).map((v) => v.map(String))],
                newResults: ["7", "1", "1"],
                newResultsCommitment: commit(newSalt, [7n, 1n, 1n]).toString(),
            })
        );
        return "exceso de créditos: rechazado";
    },

    tree: async ({ input }) => {
        // Un votante inventado que no pertenece al estado comprometido.
        await assert.rejects(
            calc({ ...input, pubKeyX: ["999", ...input.pubKeyX.slice(1)] })
        );
        return "votante fuera del árbol: rechazado";
    },

    commitment: async ({ input }) => {
        // Aplicar el lote sobre un resultado previo distinto del anunciado.
        await assert.rejects(calc({ ...input, currentResultsCommitment: "12345" }));
        return "compromiso previo falso: rechazado";
    },
};

async function main() {
    const name = process.argv[2];
    if (!name || !CASES[name]) {
        console.error(
            `Uso: node tally-witness-check.js <${Object.keys(CASES).join("|")}>`
        );
        process.exitCode = 1;
        return;
    }
    const fixture = await buildHonestInput();
    console.log(`OK  ${await CASES[name](fixture)}`);
}

main().catch((error) => {
    console.error(`FALLO: ${error.message}`);
    process.exitCode = 1;
});
