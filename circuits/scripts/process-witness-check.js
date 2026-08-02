"use strict";
/**
 * Verifica processMessages.circom con criptografía real: ECDH sobre Baby
 * Jubjub, firma EdDSA-Poseidon y árbol de estado auténtico.
 *
 * Lo que se comprueba no es que compile, sino que las restricciones aten lo
 * que deben: si el circuito no obligara a descifrar con la llave del
 * coordinador, o no exigiera la firma del votante, el coordinador podría
 * fabricar el resultado de una elección con una prueba impecable.
 *
 * Cada caso corre en su propio proceso: snarkjs deja un FileHandle abierto en
 * la ruta de error y Node 25 lo convierte en excepción durante el GC.
 */
const assert = require("node:assert/strict");
const os = require("node:os");
const path = require("node:path");
const { buildPoseidon, buildEddsa, buildBabyjub } = require("circomlibjs");
const snarkjs = require("snarkjs");

const DEPTH = 10;
const OPTIONS = 3;
const MSG_LENGTH = 10;

const wasm = path.join(
    __dirname, "..", "build", "process", "processMessages_js", "processMessages.wasm"
);

let counter = 0;
const calc = (input) =>
    snarkjs.wtns.calculate(
        input,
        wasm,
        path.join(os.tmpdir(), `process-wtns-${process.pid}-${counter++}.wtns`)
    );

async function buildFixture() {
    const poseidon = await buildPoseidon();
    const eddsa = await buildEddsa();
    const babyjub = await buildBabyjub();
    const F = poseidon.F;
    const H = (xs) => BigInt(F.toString(poseidon(xs)));
    const toBig = (x) => BigInt(babyjub.F.toString(x));

    // Llaves del coordinador y efímera del votante. Escalares pequeños: el
    // circuito solo exige que quepan en 253 bits.
    const coordinatorPrivKey = 987654321n;
    const ephemeralPrivKey = 123456789n;

    const coordinatorPub = babyjub.mulPointEscalar(babyjub.Base8, coordinatorPrivKey);
    const ephemeralPub = babyjub.mulPointEscalar(babyjub.Base8, ephemeralPrivKey);

    // ECDH: ambos lados llegan al mismo punto.
    const sharedFromCoordinator = babyjub.mulPointEscalar(ephemeralPub, coordinatorPrivKey);
    const sharedFromVoter = babyjub.mulPointEscalar(coordinatorPub, ephemeralPrivKey);
    assert.equal(
        toBig(sharedFromCoordinator[0]), toBig(sharedFromVoter[0]),
        "ECDH no converge: el cliente y el coordinador derivarían claves distintas"
    );
    const sharedX = toBig(sharedFromCoordinator[0]);
    const sharedY = toBig(sharedFromCoordinator[1]);

    // Llave EdDSA del votante (su llave MACI registrada).
    const voterPrv = Buffer.from(
        "0001020304050607080900010203040506070809000102030405060708090001", "hex"
    );
    const voterPub = eddsa.prv2pub(voterPrv);
    const voterPubX = toBig(voterPub[0]);
    const voterPubY = toBig(voterPub[1]);

    // Comando: votar la opción 0 con peso 1, nonce 1, sin rotar la llave.
    const command = [
        1n,          // stateIndex (el índice 0 lo reserva MACI)
        0n,          // voteOption
        1n,          // voteWeight
        1n,          // nonce
        voterPubX,   // newPubKeyX (misma llave: no hay rotación)
        voterPubY,   // newPubKeyY
    ];
    const commandHash = H(command);
    const signature = eddsa.signPoseidon(voterPrv, F.e(commandHash));

    const plaintext = [
        ...command,
        toBig(signature.R8[0]),
        toBig(signature.R8[1]),
        BigInt(signature.S),
        0n, // relleno hasta los 10 elementos que acepta el contrato
    ];

    // Cifrado de flujo aditivo: c[i] = p[i] + Poseidon(sx, sy, i).
    const FIELD = BigInt(F.toString(F.negone)) + 1n;
    const ciphertext = plaintext.map(
        (value, i) => (value + H([sharedX, sharedY, BigInt(i)])) % FIELD
    );

    // Árbol de estado con el votante en el índice 1.
    const zeros = [0n];
    for (let i = 0; i < DEPTH; i++) zeros.push(H([zeros[i], zeros[i]]));

    const currentVotes = [0n, 0n, 0n];
    const newVotes = [1n, 0n, 0n];
    const leafOf = (votes) => H([voterPubX, voterPubY, 1n, H(votes)]);

    const LEAF_INDEX = 1;
    const pathElements = [];
    const pathIndices = [];
    let position = LEAF_INDEX;
    for (let d = 0; d < DEPTH; d++) {
        pathElements.push(zeros[d].toString());
        pathIndices.push(position % 2);
        position = Math.floor(position / 2);
    }

    const rootOf = (leaf) => {
        let current = leaf;
        let pos = LEAF_INDEX;
        for (let d = 0; d < DEPTH; d++) {
            current = pos % 2 === 0 ? H([current, zeros[d]]) : H([zeros[d], current]);
            pos = Math.floor(pos / 2);
        }
        return current;
    };

    const messageHash = H([
        toBig(ephemeralPub[0]),
        toBig(ephemeralPub[1]),
        H(ciphertext),
    ]);

    return {
        H, FIELD, sharedX, sharedY,
        input: {
            coordinatorPrivKey: coordinatorPrivKey.toString(),
            ephemeralPubKey: [toBig(ephemeralPub[0]).toString(), toBig(ephemeralPub[1]).toString()],
            ciphertext: ciphertext.map(String),
            voterPubKey: [voterPubX.toString(), voterPubY.toString()],
            voiceCredits: "1",
            currentVotes: currentVotes.map(String),
            currentNonce: "0",
            pathElements,
            pathIndices,
            currentStateRoot: rootOf(leafOf(currentVotes)).toString(),
            newStateRoot: rootOf(leafOf(newVotes)).toString(),
            messageHash: messageHash.toString(),
        },
    };
}

const CASES = {
    honest: async ({ input }) => {
        await calc(input);
        return "mensaje honesto: descifrado, firma verificada y estado avanzado";
    },

    wrongkey: async ({ input }) => {
        // Otro coordinador: el ECDH da otro punto, el descifrado produce basura
        // y la firma deja de verificar.
        await assert.rejects(calc({ ...input, coordinatorPrivKey: "42" }));
        return "llave de coordinador incorrecta: rechazado";
    },

    forged: async ({ input }) => {
        // Alterar el texto cifrado equivale a fabricar un comando sin firma.
        const tampered = [...input.ciphertext];
        tampered[2] = (BigInt(tampered[2]) + 1n).toString();
        await assert.rejects(calc({ ...input, ciphertext: tampered }));
        return "comando manipulado sin firma válida: rechazado";
    },

    replay: async ({ input }) => {
        // Reprocesar con el nonce ya consumido.
        await assert.rejects(calc({ ...input, currentNonce: "1" }));
        return "replay de nonce: rechazado";
    },

    stateroot: async ({ input }) => {
        // Publicar un estado final que no resulta de aplicar el mensaje.
        await assert.rejects(calc({ ...input, newStateRoot: "12345" }));
        return "estado final inventado: rechazado";
    },

    message: async ({ input }) => {
        // Procesar un mensaje que la cadena nunca registró.
        await assert.rejects(calc({ ...input, messageHash: "999" }));
        return "mensaje no publicado on-chain: rechazado";
    },
};

async function main() {
    const name = process.argv[2];
    if (!name || !CASES[name]) {
        console.error(`Uso: node process-witness-check.js <${Object.keys(CASES).join("|")}>`);
        process.exitCode = 1;
        return;
    }
    console.log(`OK  ${await CASES[name](await buildFixture())}`);
}

main().catch((error) => {
    console.error(`FALLO: ${error.message}`);
    process.exitCode = 1;
});
