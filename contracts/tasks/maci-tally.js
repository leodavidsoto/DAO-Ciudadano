/**
 * `npx hardhat maci:tally` — simula el cierre de una elección MACI (D-3).
 *
 * Qué hace, en orden:
 *   1. lee las direcciones que dejó `scripts/deploy-maci.js`;
 *   2. opcionalmente monta una consulta completa (`--bootstrap`): convoca,
 *      inscribe votantes, publica mensajes cifrados mock y adelanta el reloj;
 *   3. construye el testigo de `maci_tally.circom` con el lote de votos;
 *   4. genera la prueba Groth16 y la verifica off-chain;
 *   5. la verifica ON-CHAIN contra el `TallyVerifier` desplegado;
 *   6. envía `publishTally` para cerrar la consulta.
 *
 * ESTADO CONOCIDO: el paso 6 falla hoy, y no por un error de esta tarea. El
 * contrato y el circuito no comparten las mismas señales públicas:
 *
 *     publishTally  ->  [messageChain, signUpCount, tallyCommitment]
 *     maci_tally    ->  [stateRoot, currentResultsCommitment, newResultsCommitment]
 *
 * El paso 5 demuestra que el verificador desplegado SÍ acepta la prueba del
 * circuito; el 6 demuestra que el contrato le pregunta otra cosa. La tarea
 * distingue ambos resultados en vez de reportar un fallo genérico.
 *
 * Uso:
 *   npx hardhat node
 *   MACI_MOCK_CENSUS=1 npx hardhat run scripts/deploy-maci.js --network localhost
 *   npx hardhat maci:tally --bootstrap --network localhost
 */
const fs = require("node:fs");
const path = require("node:path");
const { task, types } = require("hardhat/config");

const CIRCUITS_DIR = path.resolve(__dirname, "..", "..", "circuits");

/**
 * snarkjs y el constructor de entradas viven en `circuits/`, que tiene su
 * propio node_modules. Se resuelve explícitamente para que la ausencia de
 * `npm ci` allí dé un mensaje accionable y no un MODULE_NOT_FOUND pelado.
 */
function requireFromCircuits(specifier) {
    try {
        return require(require.resolve(specifier, {
            paths: [CIRCUITS_DIR],
        }));
    } catch (error) {
        throw new Error(
            `No se pudo cargar "${specifier}" desde ${CIRCUITS_DIR}.\n` +
            "Ejecuta `npm ci` dentro de circuits/ antes de usar maci:tally.\n" +
            `Causa: ${error.message}`
        );
    }
}

const CIPHERTEXT_LENGTH = 10;

task("maci:tally", "Simula el cierre de una elección MACI y publica el resultado")
    .addOptionalParam("poll", "Id de la consulta a cerrar", 1, types.int)
    .addOptionalParam(
        "votes",
        "JSON con el lote de votos (5 votantes x 3 opciones). Por defecto, el lote del piloto.",
        undefined,
        types.string
    )
    .addOptionalParam(
        "deployment",
        "Ruta del JSON de despliegue. Por defecto deployments/maci-<red>.json",
        undefined,
        types.string
    )
    .addFlag("bootstrap", "Convoca la consulta, inscribe votantes y adelanta el reloj")
    .setAction(async (args, hre) => {
        const { ethers, network } = hre;

        const snarkjs = requireFromCircuits("snarkjs");
        const { buildTallyInput, defaultVotes, BATCH_SIZE, VOTE_OPTIONS } =
            requireFromCircuits("./scripts/lib/tally-inputs.js");

        // ── 1. Despliegue ───────────────────────────────────────────────
        const deploymentPath =
            args.deployment ||
            path.join(__dirname, "..", "deployments", `maci-${network.name}.json`);
        if (!fs.existsSync(deploymentPath)) {
            throw new Error(
                `No hay despliegue en ${deploymentPath}.\n` +
                "Corre primero: npx hardhat run scripts/deploy-maci.js --network " +
                network.name
            );
        }
        const deployment = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
        const maciAddress = deployment.contracts.MACICoordinator;
        const tallyVerifierAddress = deployment.contracts.TallyVerifier;

        console.log(`Red:              ${network.name}`);
        console.log(`MACICoordinator:  ${maciAddress}`);
        console.log(`TallyVerifier:    ${tallyVerifierAddress}`);
        console.log(`Censo:            ${deployment.censusKind}`);

        const maci = await ethers.getContractAt("MACICoordinator", maciAddress);
        const verifier = await ethers.getContractAt(
            "TallyVerifier", tallyVerifierAddress
        );
        const [coordinator, ...voters] = await ethers.getSigners();

        // ── 2. Montaje de la consulta ───────────────────────────────────
        let pollId = BigInt(args.poll);
        if (args.bootstrap) {
            pollId = await bootstrapPoll({
                hre, maci, deployment, coordinator, voters,
            });
        }

        const poll = await maci.getPoll(pollId);
        console.log(`\nConsulta #${pollId}`);
        console.log(`  inscritos: ${poll.signUpCount}  mensajes: ${poll.messageCount}`);
        console.log(`  messageChain: ${poll.messageChain}`);
        if (poll.tallied) {
            throw new Error(`La consulta #${pollId} ya fue escrutada`);
        }

        // ── 3. Testigo ──────────────────────────────────────────────────
        const votes = args.votes
            ? parseVotes(args.votes, BATCH_SIZE, VOTE_OPTIONS)
            : defaultVotes();

        console.log("\n==> Construyendo el testigo de maci_tally.circom");
        const built = await buildTallyInput({ votes });
        console.log(`    stateRoot:  ${built.stateRoot}`);
        console.log(`    resultados: ${built.newResults.map(String).join(" / ")}`);

        // ── 4. Prueba ───────────────────────────────────────────────────
        const wasmPath = path.join(
            CIRCUITS_DIR, "build", "tally", "maci_tally_js", "maci_tally.wasm"
        );
        const ceremonyDir = path.join(
            CIRCUITS_DIR, "build", "trusted-setup", "tally-integracion"
        );
        const zkeyPath = path.join(ceremonyDir, "maci_tally_phase2.zkey");
        for (const artifact of [wasmPath, zkeyPath]) {
            if (!fs.existsSync(artifact)) {
                throw new Error(
                    `Falta ${artifact}. Compila el circuito con circuits/compile.sh`
                );
            }
        }

        console.log("\n==> Generando la prueba Groth16 (tarda ~20 s)");
        const { proof, publicSignals } = await snarkjs.groth16.fullProve(
            built.input, wasmPath, zkeyPath
        );

        const verificationKey = JSON.parse(
            fs.readFileSync(path.join(ceremonyDir, "verification_key.json"), "utf8")
        );
        const validOffChain = await snarkjs.groth16.verify(
            verificationKey, publicSignals, proof
        );
        console.log(`    verifica off-chain: ${validOffChain}`);
        if (!validOffChain) {
            throw new Error("La prueba no verifica ni off-chain: revisa el circuito");
        }

        const calldata = await snarkjs.groth16.exportSolidityCallData(
            proof, publicSignals
        );
        const [pA, pB, pC] = JSON.parse(`[${calldata}]`);

        // ── 5. Verificación on-chain directa ────────────────────────────
        // Se llama al verificador por separado antes de publishTally para
        // poder distinguir "la prueba es mala" de "el contrato pregunta otra
        // cosa". Sin este paso ambos casos revierten igual.
        console.log("\n==> Verificando la prueba contra el TallyVerifier desplegado");
        const circuitSignals = publicSignals.map(BigInt);
        const acceptedOnChain = await verifier.verifyProof(pA, pB, pC, circuitSignals);
        console.log(`    verifyProof(señales del circuito) = ${acceptedOnChain}`);
        if (!acceptedOnChain) {
            throw new Error(
                "El verificador desplegado rechaza una prueba que verifica " +
                "off-chain: el TallyVerifier no corresponde a esta ceremonia."
            );
        }

        // Lo que publishTally le pasará al mismo verificador.
        const tallyCommitment = ethers.zeroPadValue(
            ethers.toBeHex(BigInt(built.newResultsCommitment)), 32
        );
        const contractSignals = [
            BigInt(poll.messageChain) % FIELD_MODULUS,
            poll.signUpCount,
            BigInt(tallyCommitment) % FIELD_MODULUS,
        ];
        const acceptsContractSignals = await verifier.verifyProof(
            pA, pB, pC, contractSignals
        );
        console.log(`    verifyProof(señales de publishTally) = ${acceptsContractSignals}`);

        // ── 6. Publicación ──────────────────────────────────────────────
        console.log("\n==> Enviando publishTally");
        try {
            const tx = await maci
                .connect(coordinator)
                .publishTally(pollId, pA, pB, pC, tallyCommitment);
            const receipt = await tx.wait();
            console.log(`    tx: ${receipt.hash}`);

            const after = await maci.getPoll(pollId);
            if (!after.tallied) {
                throw new Error("La tx pasó pero la consulta no quedó escrutada");
            }
            console.log(`    consulta #${pollId} escrutada`);
            console.log(`    tallyCommitment: ${after.tallyCommitment}`);
        } catch (error) {
            if (!isInvalidTallyProof(error, maci)) throw error;

            console.error("\n" + "─".repeat(70));
            console.error("BLOQUEO D-3: publishTally rechaza una prueba auténtica.");
            console.error("─".repeat(70));
            console.error(
                "\nNo es un fallo de esta tarea. El verificador desplegado acepta\n" +
                "la prueba (paso 5), pero el contrato le pasa otras señales:\n\n" +
                "  circuito     [0] stateRoot                = " + circuitSignals[0] + "\n" +
                "  publishTally [0] messageChain             = " + contractSignals[0] + "\n\n" +
                "  circuito     [1] currentResultsCommitment = " + circuitSignals[1] + "\n" +
                "  publishTally [1] signUpCount              = " + contractSignals[1] + "\n\n" +
                "La posición [1] es un Poseidon de ~254 bits en el circuito y el\n" +
                "número de inscritos en el contrato. Ninguna elección real puede\n" +
                "tener tantos inscritos, así que ninguna prueba puede satisfacer\n" +
                "a publishTally tal como está.\n\n" +
                "Reconciliarlo exige una decisión de protocolo: qué ancla el\n" +
                "contrato y cómo se acumulan los lotes. Ver docs/ROADMAP.md D-3."
            );
            process.exitCode = 1;
        }
    });

const FIELD_MODULUS =
    21888242871839275222246405745257275088548364400416034343698204186575808495617n;

/**
 * ¿El revert fue `InvalidTallyProof()`?
 *
 * Se comprueba por selector y no solo por nombre porque un nodo externo
 * (`--network localhost`) devuelve el error sin decodificar —
 * "unrecognized custom error (return data: 0x909ea42f)"— mientras que la red
 * in-process sí lo resuelve. Mirar únicamente el mensaje haría que la tarea
 * escupiera un stack trace en vez del diagnóstico, que es justo lo que pasa
 * en el caso que más importa explicar.
 */
function isInvalidTallyProof(error, maci) {
    const selector = maci.interface.getError("InvalidTallyProof").selector;
    const haystack = `${error.message} ${error.data ?? ""} ${error.info?.error?.data ?? ""}`;
    return haystack.includes("InvalidTallyProof") || haystack.includes(selector);
}

/** Monta una consulta completa lista para escrutar. Solo en red local. */
async function bootstrapPoll({ hre, maci, deployment, coordinator, voters }) {
    const { ethers, network } = hre;

    if (!["hardhat", "localhost"].includes(network.name)) {
        throw new Error("--bootstrap manipula el reloj: solo en red local");
    }
    if (deployment.censusKind !== "MockMembershipRegistry") {
        throw new Error(
            "--bootstrap necesita un censo simulado para inscribir votantes " +
            "sin acuñar SBTs con prueba ZK.\n" +
            "Redespliega con: MACI_MOCK_CENSUS=1 npx hardhat run " +
            "scripts/deploy-maci.js --network " + network.name
        );
    }

    const registry = await ethers.getContractAt(
        "MockMembershipRegistry",
        deployment.contracts.MockMembershipRegistry
    );

    const signUpDuration = 3 * 24 * 60 * 60;
    const votingDuration = 4 * 24 * 60 * 60;

    console.log("\n==> Montando la consulta");
    const createTx = await maci.connect(coordinator).createPoll(
        signUpDuration, votingDuration
    );
    await createTx.wait();
    const pollId = await maci.pollCount();
    console.log(`    consulta #${pollId} convocada`);

    // Un votante por hoja del lote: el circuito procesa exactamente 5.
    const batch = voters.slice(0, 5);
    const keyX =
        5299619240641551281634865583518297030282874472190772894086521144482721001553n;
    const keyY =
        16950150798460657717958625567821834550301663161624707787222815936182638968203n;

    for (const voter of batch) {
        await (await registry.setMember(voter.address, true)).wait();
        await (await maci.connect(voter).signUp(pollId, keyX, keyY)).wait();
    }
    console.log(`    ${batch.length} votantes inscritos`);

    await ethers.provider.send("evm_increaseTime", [signUpDuration + 1]);
    await ethers.provider.send("evm_mine", []);

    // Mensajes cifrados mock. On-chain un voto y un cambio de llave son
    // indistinguibles, así que basta con texto cifrado bien formado: el
    // contrato solo comprueba que esté dentro del campo escalar.
    for (const [index, voter] of batch.entries()) {
        const ciphertext = Array.from(
            { length: CIPHERTEXT_LENGTH },
            (_, i) => BigInt(1 + index * CIPHERTEXT_LENGTH + i)
        );
        await (
            await maci.connect(voter).publishMessage(pollId, keyX, keyY, ciphertext)
        ).wait();
    }
    console.log(`    ${batch.length} mensajes cifrados publicados`);

    await ethers.provider.send("evm_increaseTime", [votingDuration + 1]);
    await ethers.provider.send("evm_mine", []);
    console.log("    votación cerrada");

    return pollId;
}

/** Lee y valida el lote de votos de un JSON externo. */
function parseVotes(votesPath, batchSize, voteOptions) {
    const raw = JSON.parse(fs.readFileSync(votesPath, "utf8"));
    const votes = Array.isArray(raw) ? raw : raw.votes;
    if (!Array.isArray(votes) || votes.length !== batchSize) {
        throw new Error(
            `El lote debe tener ${batchSize} votantes, tiene ${votes?.length}`
        );
    }
    return votes.map((vote, i) => {
        if (!Array.isArray(vote) || vote.length !== voteOptions) {
            throw new Error(
                `El votante ${i} debe cubrir ${voteOptions} opciones`
            );
        }
        return vote.map(BigInt);
    });
}

module.exports = {};
