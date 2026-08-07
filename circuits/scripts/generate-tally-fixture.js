"use strict";
/**
 * Fixture determinista del circuito de tally (`maci_tally.circom`).
 *
 * Existe por la misma razón que `generate-test-fixture.js`: generar una prueba
 * Groth16 cuesta ~20 s, demasiado para hacerlo dentro de cada test. El fixture
 * se genera una vez, se commitea y `contracts/test/MACI.test.js` lo consume
 * para ejercitar el `TallyVerifier` REAL en vez de un mock.
 *
 * Por qué importa que sea el verificador real
 * ───────────────────────────────────────────
 * `MockTallyVerifier` devuelve lo que se le diga. Probar el flujo contra él
 * demuestra que el contrato llama al verificador, no que el verificador
 * desplegado acepte las pruebas del circuito de esta ceremonia. Son cosas
 * distintas, y la segunda es la que decide si una elección puede cerrarse.
 *
 * ATENCIÓN: el .zkey de `tally-integracion` es de una sola contribución
 * (`beacon=not-applied`, ver ceremony-manifest.txt). Sirve para integración;
 * quien lo generó puede fabricar pruebas falsas. Nunca para una elección real.
 *
 * Uso:  node scripts/generate-tally-fixture.js
 */

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const snarkjs = require("snarkjs");

const {
    buildTallyInput,
    defaultVotes,
    STATE_TREE_DEPTH,
    BATCH_SIZE,
    VOTE_OPTIONS,
    MAX_VOICE_CREDITS,
    FIELD,
} = require("./lib/tally-inputs");

const circuitDir = path.resolve(__dirname, "..");
const wasmPath = path.join(
    circuitDir, "build", "tally", "maci_tally_js", "maci_tally.wasm"
);
const ceremonyDir = path.join(
    circuitDir, "build", "trusted-setup", "tally-integracion"
);
const zkeyPath = path.join(ceremonyDir, "maci_tally_phase2.zkey");
const verificationKeyPath = path.join(ceremonyDir, "verification_key.json");
const fixturePath = path.join(
    circuitDir, "test", "fixtures", "tally-proof.json"
);

async function main() {
    for (const artifact of [wasmPath, zkeyPath, verificationKeyPath]) {
        assert.ok(fs.existsSync(artifact), `Falta el artefacto: ${artifact}`);
    }

    const votes = defaultVotes();
    const built = await buildTallyInput({ votes });

    const { proof, publicSignals } = await snarkjs.groth16.fullProve(
        built.input, wasmPath, zkeyPath
    );

    // El orden de las señales públicas es frontera de protocolo. Afirmarlo acá
    // convierte un cambio silencioso del circuito en un fallo del generador.
    assert.deepEqual(
        publicSignals, built.expectedSignals,
        "El orden de las señales públicas del circuito cambió"
    );
    for (const signal of publicSignals) {
        assert.ok(BigInt(signal) < FIELD, "Señal fuera del campo escalar");
    }

    const verificationKey = JSON.parse(
        fs.readFileSync(verificationKeyPath, "utf8")
    );
    assert.equal(
        await snarkjs.groth16.verify(verificationKey, publicSignals, proof),
        true,
        "La prueba generada no verifica contra la verification key"
    );

    // El orden de coordenadas de Fq2 en pi_b lo decide snarkjs, no nosotros:
    // invertirlo a mano es fácil de equivocar y falla de forma silenciosa.
    const calldata = await snarkjs.groth16.exportSolidityCallData(
        proof, publicSignals
    );
    const [pA, pB, pC, soliditySignals] = JSON.parse(`[${calldata}]`);
    assert.deepEqual(
        soliditySignals.map((value) => BigInt(value).toString()),
        publicSignals
    );

    const fixture = {
        warning:
            "Fixture público y determinista de integración. El .zkey es de una " +
            "sola contribución: quien lo generó puede falsificar pruebas. " +
            "Nunca usar en una elección real.",
        circuit: `MaciTally(${STATE_TREE_DEPTH},${BATCH_SIZE},${VOTE_OPTIONS},${MAX_VOICE_CREDITS})`,
        ceremony: "tally-integracion",
        signalOrder: [
            "stateRoot",
            "currentResultsCommitment",
            "newResultsCommitment",
        ],
        batch: {
            voteOptionLabels: ["a favor", "en contra", "abstención"],
            votes: votes.map((vote) => vote.map(String)),
            newResults: built.newResults.map(String),
            currentSalt: built.currentSalt.toString(),
            newSalt: built.newSalt.toString(),
        },
        stateRoot: built.stateRoot.toString(),
        currentResultsCommitment: built.currentResultsCommitment.toString(),
        newResultsCommitment: built.newResultsCommitment.toString(),
        publicSignals,
        proof,
        solidityProof: { pA, pB, pC },
    };

    fs.mkdirSync(path.dirname(fixturePath), { recursive: true });
    fs.writeFileSync(fixturePath, `${JSON.stringify(fixture, null, 2)}\n`);
    process.stdout.write(`Escrito ${fixturePath}\n`);
}

// `process.exit` explícito: snarkjs deja descriptores abiertos tras
// `fullProve` y el proceso nunca terminaría por sí solo. Mismo motivo por el
// que `tally-witness-check.js` corre cada caso en su propio proceso.
main()
    .then(() => process.exit(0))
    .catch((error) => {
        console.error(error);
        process.exit(1);
    });
