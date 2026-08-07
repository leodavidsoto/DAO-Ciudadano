const { expect } = require("chai");
const { ethers } = require("hardhat");
const {
    loadFixture,
    time,
} = require("@nomicfoundation/hardhat-toolbox/network-helpers");

const tallyFixture = require("../../circuits/test/fixtures/tally-proof.json");

/**
 * MACI de extremo a extremo contra el verificador de tally REAL (ROADMAP D-3).
 *
 * Qué añade sobre MACICoordinator.test.js
 * ───────────────────────────────────────
 * Aquel suite usa `MockTallyVerifier`, que devuelve lo que se le pida. Prueba
 * que el contrato LLAMA al verificador, no que el verificador desplegado
 * acepte las pruebas que produce `maci_tally.circom`. Por eso `TallyVerifier`
 * estaba al 0% de cobertura: nunca se ejecutaba su bytecode.
 *
 * Este suite despliega el `TallyVerifier.sol` de la ceremonia y le pasa una
 * prueba Groth16 auténtica generada por el circuito
 * (`circuits/scripts/generate-tally-fixture.js`).
 *
 * Y al hacerlo documenta el hallazgo que bloquea D-3: el contrato y el
 * circuito NO comparten las mismas señales públicas. Ver el último describe.
 */
describe("MACI — pila completa con verificador real", function () {
    const FIELD =
        21888242871839275222246405745257275088548364400416034343698204186575808495617n;

    // Generador de Baby Jubjub (EIP-2494).
    const KEY_X =
        5299619240641551281634865583518297030282874472190772894086521144482721001553n;
    const KEY_Y =
        16950150798460657717958625567821834550301663161624707787222815936182638968203n;

    const SIGNUP_DURATION = 3 * 24 * 60 * 60;
    const VOTING_DURATION = 4 * 24 * 60 * 60;
    const CIPHERTEXT = Array.from({ length: 10 }, (_, i) => BigInt(i + 1));

    const PROOF = tallyFixture.solidityProof;
    const SIGNALS = tallyFixture.publicSignals.map(BigInt);

    /** Las tres señales del circuito, tal cual las espera TallyVerifier. */
    function circuitSignals(overrides = {}) {
        const signals = [...SIGNALS];
        for (const [index, value] of Object.entries(overrides)) {
            signals[Number(index)] = value;
        }
        return signals;
    }

    async function deployTallyVerifier() {
        const Factory = await ethers.getContractFactory("TallyVerifier");
        const verifier = await Factory.deploy();
        await verifier.waitForDeployment();
        return { verifier };
    }

    async function deployStack() {
        const [admin, member, otherMember, stranger] = await ethers.getSigners();

        const Registry = await ethers.getContractFactory("MockMembershipRegistry");
        const registry = await Registry.deploy();
        await registry.waitForDeployment();
        await registry.setMember(member.address, true);
        await registry.setMember(otherMember.address, true);

        const Verifier = await ethers.getContractFactory("TallyVerifier");
        const verifier = await Verifier.deploy();
        await verifier.waitForDeployment();

        const Factory = await ethers.getContractFactory("MACICoordinator");
        const maci = await Factory.deploy(
            admin.address,
            await registry.getAddress(),
            await verifier.getAddress()
        );
        await maci.waitForDeployment();

        return { maci, verifier, registry, admin, member, otherMember, stranger };
    }

    async function withVotingClosed() {
        const base = await deployStack();
        await base.maci.connect(base.admin).setCoordinatorPubKey(KEY_X, KEY_Y);
        await base.maci.connect(base.admin).createPoll(SIGNUP_DURATION, VOTING_DURATION);
        const pollId = 1n;

        await base.maci.connect(base.member).signUp(pollId, KEY_X, KEY_Y);
        await base.maci.connect(base.otherMember).signUp(pollId, KEY_X, KEY_Y);
        await time.increase(SIGNUP_DURATION + 1);

        await base.maci.connect(base.member).publishMessage(pollId, KEY_X, KEY_Y, CIPHERTEXT);
        await time.increase(VOTING_DURATION + 1);

        return { ...base, pollId };
    }

    // ───────────────────────────────────────────────────────────────────
    // 1. El verificador de la ceremonia, ejercitado directamente.
    // ───────────────────────────────────────────────────────────────────
    describe("TallyVerifier.sol (ceremonia tally-integracion)", function () {
        it("acepta la prueba auténtica del circuito", async function () {
            const { verifier } = await loadFixture(deployTallyVerifier);
            expect(
                await verifier.verifyProof(PROOF.pA, PROOF.pB, PROOF.pC, circuitSignals())
            ).to.equal(true);
        });

        it("rechaza si se altera cualquiera de las tres señales públicas", async function () {
            const { verifier } = await loadFixture(deployTallyVerifier);

            // Una a una: si alguna no estuviera realmente atada a la prueba,
            // el circuito no estaría restringiendo lo que creemos.
            for (let index = 0; index < 3; index += 1) {
                expect(
                    await verifier.verifyProof(
                        PROOF.pA,
                        PROOF.pB,
                        PROOF.pC,
                        circuitSignals({ [index]: SIGNALS[index] + 1n })
                    ),
                    `la señal ${tallyFixture.signalOrder[index]} no está atada a la prueba`
                ).to.equal(false);
            }
        });

        it("rechaza un resultado distinto del probado", async function () {
            const { verifier } = await loadFixture(deployTallyVerifier);

            // Cambiar el compromiso del resultado es exactamente el ataque que
            // el tally debe impedir: publicar un recuento que nadie probó.
            expect(
                await verifier.verifyProof(
                    PROOF.pA,
                    PROOF.pB,
                    PROOF.pC,
                    circuitSignals({ 2: 12345n })
                )
            ).to.equal(false);
        });

        it("rechaza puntos de la prueba manipulados", async function () {
            const { verifier } = await loadFixture(deployTallyVerifier);

            expect(
                await verifier.verifyProof(
                    [PROOF.pA[0], BigInt(PROOF.pA[1]) + 1n],
                    PROOF.pB,
                    PROOF.pC,
                    circuitSignals()
                )
            ).to.equal(false);

            expect(
                await verifier.verifyProof(
                    PROOF.pA,
                    PROOF.pB,
                    [PROOF.pC[0], BigInt(PROOF.pC[1]) + 1n],
                    circuitSignals()
                )
            ).to.equal(false);
        });

        it("rechaza señales fuera del campo escalar sin revertir", async function () {
            const { verifier } = await loadFixture(deployTallyVerifier);

            // `checkField` devuelve false en vez de revertir. Importa que sea
            // así: MACICoordinator interpreta el false como prueba inválida, y
            // un revert dejaría la consulta bloqueada en vez de rechazar el
            // resultado.
            expect(
                await verifier.verifyProof(
                    PROOF.pA, PROOF.pB, PROOF.pC, circuitSignals({ 0: FIELD })
                )
            ).to.equal(false);
        });

        it("rechaza intercambiar el orden de las señales", async function () {
            const { verifier } = await loadFixture(deployTallyVerifier);

            // El orden es frontera de protocolo: si permutarlo verificara,
            // un lote podría aplicarse sobre el resultado equivocado.
            expect(
                await verifier.verifyProof(PROOF.pA, PROOF.pB, PROOF.pC, [
                    SIGNALS[0], SIGNALS[2], SIGNALS[1],
                ])
            ).to.equal(false);
        });
    });

    // ───────────────────────────────────────────────────────────────────
    // 2. Flujo de la consulta con el verificador real conectado.
    // ───────────────────────────────────────────────────────────────────
    describe("registro de llaves, inscripción y mensajes", function () {
        it("publica la llave del coordinador antes de poder convocar", async function () {
            const { maci, admin } = await loadFixture(deployStack);

            await expect(maci.connect(admin).createPoll(SIGNUP_DURATION, VOTING_DURATION))
                .to.be.revertedWithCustomError(maci, "InvalidCoordinatorKey");

            await expect(maci.connect(admin).setCoordinatorPubKey(KEY_X, KEY_Y))
                .to.emit(maci, "CoordinatorKeyUpdated").withArgs(KEY_X, KEY_Y);

            await expect(maci.connect(admin).createPoll(SIGNUP_DURATION, VOTING_DURATION))
                .to.emit(maci, "PollCreated");
        });

        it("inscribe solo a miembros y acumula los mensajes en orden", async function () {
            const { maci, admin, member, otherMember, stranger } =
                await loadFixture(deployStack);
            await maci.connect(admin).setCoordinatorPubKey(KEY_X, KEY_Y);
            await maci.connect(admin).createPoll(SIGNUP_DURATION, VOTING_DURATION);
            const pollId = 1n;

            await expect(maci.connect(stranger).signUp(pollId, KEY_X, KEY_Y))
                .to.be.revertedWithCustomError(maci, "NotAMember");

            await maci.connect(member).signUp(pollId, KEY_X, KEY_Y);
            await maci.connect(otherMember).signUp(pollId, KEY_X, KEY_Y);
            await time.increase(SIGNUP_DURATION + 1);

            const before = await maci.getPoll(pollId);
            await maci.connect(member).publishMessage(pollId, KEY_X, KEY_Y, CIPHERTEXT);
            await maci.connect(otherMember).publishMessage(pollId, KEY_X, KEY_Y, CIPHERTEXT);
            const after = await maci.getPoll(pollId);

            expect(after.signUpCount).to.equal(2n);
            expect(after.messageCount).to.equal(2n);
            expect(after.messageChain).to.not.equal(before.messageChain);
        });

        it("no permite publicar el resultado antes de cerrar la votación", async function () {
            const { maci, admin, member } = await loadFixture(deployStack);
            await maci.connect(admin).setCoordinatorPubKey(KEY_X, KEY_Y);
            await maci.connect(admin).createPoll(SIGNUP_DURATION, VOTING_DURATION);
            await maci.connect(member).signUp(1n, KEY_X, KEY_Y);

            await expect(
                maci.connect(admin).publishTally(
                    1n, PROOF.pA, PROOF.pB, PROOF.pC, ethers.zeroPadValue("0x2a", 32)
                )
            ).to.be.revertedWithCustomError(maci, "VotingStillOpen");
        });

        it("solo el COORDINATOR_ROLE publica el resultado", async function () {
            const { maci, stranger, pollId } = await loadFixture(withVotingClosed);

            await expect(
                maci.connect(stranger).publishTally(
                    pollId, PROOF.pA, PROOF.pB, PROOF.pC, ethers.zeroPadValue("0x2a", 32)
                )
            ).to.be.revertedWithCustomError(
                maci, "AccessControlUnauthorizedAccount"
            );
        });
    });

    // ───────────────────────────────────────────────────────────────────
    // 3. EL BLOQUEO DE D-3. Este describe no prueba una funcionalidad:
    //    fija un defecto para que nadie lo dé por resuelto.
    // ───────────────────────────────────────────────────────────────────
    describe("frontera rota entre publishTally y maci_tally.circom", function () {
        /**
         * `MACICoordinator.publishTally` pasa al verificador:
         *     [messageChain, signUpCount, tallyCommitment]
         *
         * `maci_tally.circom` expone:
         *     [stateRoot, currentResultsCommitment, newResultsCommitment]
         *
         * No es un desajuste de nombres: son magnitudes distintas. La posición
         * [1] del circuito es un Poseidon de ~254 bits, y el contrato pone ahí
         * el número de inscritos. Ninguna prueba del circuito puede satisfacer
         * lo que el contrato pregunta, y ninguna consulta real puede tener
         * tantos inscritos.
         *
         * Consecuencia: `publishTally` NO puede cerrar una elección hoy.
         * Reconciliarlo exige decidir qué ancla el contrato (ver informe).
         */
        it("la señal [1] del circuito no es un número de inscritos", async function () {
            const currentResultsCommitment = SIGNALS[1];

            // Cota generosísima: más inscritos que personas en el planeta.
            const inscritosPlausiblesMax = 10n ** 10n;
            expect(currentResultsCommitment).to.be.greaterThan(inscritosPlausiblesMax);
            expect(currentResultsCommitment).to.be.lessThan(FIELD);
        });

        it("una prueba auténtica es rechazada por publishTally", async function () {
            const { maci, admin, pollId } = await loadFixture(withVotingClosed);

            // La misma prueba que TallyVerifier acepta arriba.
            await expect(
                maci.connect(admin).publishTally(
                    pollId,
                    PROOF.pA,
                    PROOF.pB,
                    PROOF.pC,
                    ethers.zeroPadValue(ethers.toBeHex(SIGNALS[2]), 32)
                )
            ).to.be.revertedWithCustomError(maci, "InvalidTallyProof");

            const poll = await maci.getPoll(pollId);
            expect(poll.tallied).to.equal(false);
        });

        it("el contrato pasa señales que el circuito nunca produce", async function () {
            const { maci, verifier, pollId } = await loadFixture(withVotingClosed);
            const poll = await maci.getPoll(pollId);

            // Reconstrucción exacta de lo que publishTally arma internamente.
            const tallyCommitment = ethers.zeroPadValue(ethers.toBeHex(SIGNALS[2]), 32);
            const contractSignals = [
                BigInt(poll.messageChain) % FIELD,
                poll.signUpCount,
                BigInt(tallyCommitment) % FIELD,
            ];

            expect(contractSignals[1]).to.equal(2n);
            expect(contractSignals[1]).to.not.equal(SIGNALS[1]);

            // Y el verificador real, coherentemente, las rechaza.
            expect(
                await verifier.verifyProof(PROOF.pA, PROOF.pB, PROOF.pC, contractSignals)
            ).to.equal(false);
        });

        it("el fixture corresponde al circuito y ceremonia esperados", async function () {
            // Si alguien recompila el circuito o rehace la ceremonia sin
            // regenerar el fixture, los tests de arriba pasarían a probar otra
            // cosa en silencio. Esto lo convierte en un fallo.
            expect(tallyFixture.circuit).to.equal("MaciTally(10,5,3,1)");
            expect(tallyFixture.ceremony).to.equal("tally-integracion");
            expect(tallyFixture.signalOrder).to.deep.equal([
                "stateRoot",
                "currentResultsCommitment",
                "newResultsCommitment",
            ]);
        });
    });
});
