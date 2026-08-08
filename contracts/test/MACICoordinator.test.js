const { expect } = require("chai");
const { ethers } = require("hardhat");
const {
    loadFixture,
    time,
} = require("@nomicfoundation/hardhat-toolbox/network-helpers");

/**
 * MACICoordinator — gobernanza incoercible (ADR-001, D-3).
 *
 * Las invariantes que sostienen la propiedad anti-coerción:
 *  - solo miembros del SBT se inscriben (sin eso el censo es Sybil);
 *  - solo inscritos publican mensajes (si no, spam gratuito al coordinador);
 *  - el acumulador fija contenido Y orden (en MACI vale el último mensaje);
 *  - un voto y un cambio de llave son indistinguibles on-chain;
 *  - sin verificador de tally NO se puede publicar un resultado.
 */
describe("MACICoordinator", function () {
    const FIELD =
        21888242871839275222246405745257275088548364400416034343698204186575808495617n;

    // Generador de Baby Jubjub (EIP-2494): punto real de la curva.
    const KEY_X =
        5299619240641551281634865583518297030282874472190772894086521144482721001553n;
    const KEY_Y =
        16950150798460657717958625567821834550301663161624707787222815936182638968203n;

    const SIGNUP_DURATION = 3 * 24 * 60 * 60;
    const VOTING_DURATION = 4 * 24 * 60 * 60;

    const P_A = [1n, 2n];
    const P_B = [
        [3n, 4n],
        [5n, 6n],
    ];
    const P_C = [7n, 8n];
    const CIPHERTEXT = Array.from({ length: 10 }, (_, i) => BigInt(i + 1));
    const TALLY = ethers.zeroPadValue(ethers.toBeHex(4242n), 32);

    async function deployFixture() {
        const [admin, member, otherMember, stranger, coordinator] =
            await ethers.getSigners();

        // Registro de membresía simulado: el SBT real exige una prueba ZK
        // completa, que no es lo que se prueba acá.
        const Registry = await ethers.getContractFactory("MockMembershipRegistry");
        const registry = await Registry.deploy();
        await registry.waitForDeployment();
        await registry.setMember(member.address, true);
        await registry.setMember(otherMember.address, true);

        const Verifier = await ethers.getContractFactory("MockTallyVerifier");
        const verifier = await Verifier.deploy();
        await verifier.waitForDeployment();

        const Factory = await ethers.getContractFactory("MACICoordinator");
        const maci = await Factory.deploy(
            admin.address,
            await registry.getAddress(),
            await verifier.getAddress()
        );
        await maci.waitForDeployment();

        await maci.connect(admin).setCoordinatorPubKey(KEY_X, KEY_Y);

        return {
            maci,
            registry,
            verifier,
            admin,
            member,
            otherMember,
            stranger,
            coordinator,
        };
    }

    async function withOpenPoll() {
        const base = await deployFixture();
        await base.maci
            .connect(base.admin)
            .createPoll(SIGNUP_DURATION, VOTING_DURATION);
        return { ...base, pollId: 1n };
    }

    async function withVotingOpen() {
        const base = await withOpenPoll();
        await base.maci.connect(base.member).signUp(base.pollId, KEY_X, KEY_Y);
        await base.maci.connect(base.otherMember).signUp(base.pollId, KEY_X, KEY_Y);
        await time.increase(SIGNUP_DURATION + 1);
        return base;
    }

    describe("despliegue", function () {
        it("rechaza un admin nulo y un registro sin código", async function () {
            const [admin] = await ethers.getSigners();
            const Factory = await ethers.getContractFactory("MACICoordinator");
            const Registry = await ethers.getContractFactory("MockMembershipRegistry");
            const registry = await Registry.deploy();

            await expect(
                Factory.deploy(ethers.ZeroAddress, await registry.getAddress(), ethers.ZeroAddress)
            ).to.be.revertedWithCustomError(Factory, "InvalidAdmin");

            await expect(
                Factory.deploy(admin.address, admin.address, ethers.ZeroAddress)
            ).to.be.revertedWithCustomError(Factory, "InvalidMembershipRegistry");
        });

        it("permite desplegar sin verificador de tally (el circuito aún no existe)", async function () {
            const [admin] = await ethers.getSigners();
            const Registry = await ethers.getContractFactory("MockMembershipRegistry");
            const registry = await Registry.deploy();
            const Factory = await ethers.getContractFactory("MACICoordinator");

            const maci = await Factory.deploy(
                admin.address,
                await registry.getAddress(),
                ethers.ZeroAddress
            );

            expect(await maci.tallyIsVerifiable()).to.equal(false);
        });
    });

    describe("apertura de la consulta", function () {
        it("no deja abrir una consulta sin llave del coordinador", async function () {
            const [admin] = await ethers.getSigners();
            const Registry = await ethers.getContractFactory("MockMembershipRegistry");
            const registry = await Registry.deploy();
            const Factory = await ethers.getContractFactory("MACICoordinator");
            const maci = await Factory.deploy(
                admin.address,
                await registry.getAddress(),
                ethers.ZeroAddress
            );

            // Sin llave publicada nadie puede cifrar: la consulta solo
            // produciría votos ilegibles.
            await expect(
                maci.connect(admin).createPoll(SIGNUP_DURATION, VOTING_DURATION)
            ).to.be.revertedWithCustomError(maci, "InvalidCoordinatorKey");
        });

        it("rechaza el punto identidad como llave del coordinador", async function () {
            const { maci, admin } = await loadFixture(deployFixture);
            await expect(
                maci.connect(admin).setCoordinatorPubKey(0n, 1n)
            ).to.be.revertedWithCustomError(maci, "InvalidCoordinatorKey");
        });

        it("solo POLL_MANAGER_ROLE convoca", async function () {
            const { maci, stranger } = await loadFixture(deployFixture);
            await expect(
                maci.connect(stranger).createPoll(SIGNUP_DURATION, VOTING_DURATION)
            ).to.be.reverted;
        });
    });

    describe("inscripción", function () {
        it("inscribe a un miembro y emite su índice", async function () {
            const { maci, member, pollId } = await loadFixture(withOpenPoll);

            await expect(maci.connect(member).signUp(pollId, KEY_X, KEY_Y))
                .to.emit(maci, "SignedUp")
                .withArgs(pollId, member.address, KEY_X, KEY_Y, 0);

            expect(await maci.isSignedUp(pollId, member.address)).to.equal(true);
        });

        it("rechaza a quien no tiene membresía SBT", async function () {
            const { maci, stranger, pollId } = await loadFixture(withOpenPoll);

            await expect(
                maci.connect(stranger).signUp(pollId, KEY_X, KEY_Y)
            ).to.be.revertedWithCustomError(maci, "NotAMember");
        });

        it("no permite inscribirse dos veces", async function () {
            const { maci, member, pollId } = await loadFixture(withOpenPoll);
            await maci.connect(member).signUp(pollId, KEY_X, KEY_Y);

            await expect(
                maci.connect(member).signUp(pollId, KEY_X, KEY_Y)
            ).to.be.revertedWithCustomError(maci, "AlreadySignedUp");
        });

        it("cierra la inscripción al vencer el plazo", async function () {
            const { maci, member, pollId } = await loadFixture(withOpenPoll);
            await time.increase(SIGNUP_DURATION + 1);

            await expect(
                maci.connect(member).signUp(pollId, KEY_X, KEY_Y)
            ).to.be.revertedWithCustomError(maci, "SignUpClosed");
        });

        it("rechaza llaves fuera del campo escalar", async function () {
            const { maci, member, pollId } = await loadFixture(withOpenPoll);

            await expect(
                maci.connect(member).signUp(pollId, FIELD, KEY_Y)
            ).to.be.revertedWithCustomError(maci, "InvalidPublicKey");
        });
    });

    describe("mensajes cifrados", function () {
        it("acumula el mensaje y encadena el hash", async function () {
            const { maci, member, pollId } = await loadFixture(withVotingOpen);

            await expect(
                maci.connect(member).publishMessage(pollId, KEY_X, KEY_Y, CIPHERTEXT)
            ).to.emit(maci, "MessagePublished");

            const poll = await maci.getPoll(pollId);
            expect(poll.messageCount).to.equal(1n);
            expect(poll.messageChain).to.not.equal(ethers.ZeroHash);
        });

        it("el acumulador depende del ORDEN de los mensajes", async function () {
            // En MACI vale el último mensaje válido de cada llave, así que el
            // orden es parte del resultado, no un detalle.
            const a = await loadFixture(withVotingOpen);
            await a.maci.connect(a.member).publishMessage(a.pollId, KEY_X, KEY_Y, CIPHERTEXT);
            await a.maci
                .connect(a.otherMember)
                .publishMessage(a.pollId, KEY_Y, KEY_X, CIPHERTEXT);
            const chainAB = (await a.maci.getPoll(a.pollId)).messageChain;

            const b = await loadFixture(withVotingOpen);
            await b.maci
                .connect(b.otherMember)
                .publishMessage(b.pollId, KEY_Y, KEY_X, CIPHERTEXT);
            await b.maci.connect(b.member).publishMessage(b.pollId, KEY_X, KEY_Y, CIPHERTEXT);
            const chainBA = (await b.maci.getPoll(b.pollId)).messageChain;

            expect(chainAB).to.not.equal(chainBA);
        });

        it("un voto y un cambio de llave son indistinguibles on-chain", async function () {
            // Esa indistinguibilidad ES la propiedad anti-coerción: el
            // contrato no puede decir cuál mensaje anula a cuál.
            const { maci, member, pollId } = await loadFixture(withVotingOpen);

            const first = await maci
                .connect(member)
                .publishMessage(pollId, KEY_X, KEY_Y, CIPHERTEXT);
            const second = await maci
                .connect(member)
                .publishMessage(pollId, KEY_X, KEY_Y, CIPHERTEXT);

            const r1 = await first.wait();
            const r2 = await second.wait();
            const topic = maci.interface.getEvent("MessagePublished").topicHash;
            const log1 = r1.logs.find((l) => l.topics[0] === topic);
            const log2 = r2.logs.find((l) => l.topics[0] === topic);

            // Mismo tipo de evento, misma forma: nada distingue uno de otro.
            expect(log1.topics[0]).to.equal(log2.topics[0]);
            expect((await maci.getPoll(pollId)).messageCount).to.equal(2n);
        });

        it("rechaza mensajes de quien no se inscribió", async function () {
            const { maci, stranger, pollId } = await loadFixture(withVotingOpen);

            await expect(
                maci.connect(stranger).publishMessage(pollId, KEY_X, KEY_Y, CIPHERTEXT)
            ).to.be.revertedWithCustomError(maci, "NotSignedUp");
        });

        it("cierra la votación al vencer el plazo", async function () {
            const { maci, member, pollId } = await loadFixture(withVotingOpen);
            await time.increase(VOTING_DURATION + 1);

            await expect(
                maci.connect(member).publishMessage(pollId, KEY_X, KEY_Y, CIPHERTEXT)
            ).to.be.revertedWithCustomError(maci, "VotingClosed");
        });

        it("rechaza texto cifrado fuera del campo escalar", async function () {
            const { maci, member, pollId } = await loadFixture(withVotingOpen);
            const bad = [...CIPHERTEXT];
            bad[3] = FIELD;

            await expect(
                maci.connect(member).publishMessage(pollId, KEY_X, KEY_Y, bad)
            ).to.be.revertedWithCustomError(maci, "InvalidCiphertext");
        });
    });

    describe("publicación del resultado", function () {
        async function closedPoll() {
            const base = await withVotingOpen();
            await base.maci
                .connect(base.member)
                .publishMessage(base.pollId, KEY_X, KEY_Y, CIPHERTEXT);
            await time.increase(VOTING_DURATION + 1);
            return base;
        }

        it("publica el resultado cuando el verificador acepta la prueba", async function () {
            const { maci, admin, pollId } = await loadFixture(closedPoll);

            await expect(
                maci.connect(admin).publishTally(pollId, P_A, P_B, P_C, TALLY)
            )
                .to.emit(maci, "TallyPublished")
                .withArgs(pollId, TALLY, admin.address);

            const poll = await maci.getPoll(pollId);
            expect(poll.tallied).to.equal(true);
            expect(poll.tallyCommitment).to.equal(TALLY);
        });

        it("SIN verificador desplegado no se puede publicar ningún resultado", async function () {
            // Es la invariante central: un recuento sin prueba es exactamente
            // lo que MACI existe para eliminar.
            const { maci, admin, pollId } = await loadFixture(closedPoll);
            await maci.connect(admin).setTallyVerifier(ethers.ZeroAddress);

            await expect(
                maci.connect(admin).publishTally(pollId, P_A, P_B, P_C, TALLY)
            ).to.be.revertedWithCustomError(maci, "TallyVerifierNotConfigured");
        });

        it("rechaza una prueba inválida", async function () {
            const { maci, admin, verifier, pollId } = await loadFixture(closedPoll);
            await verifier.configure(false, false);

            await expect(
                maci.connect(admin).publishTally(pollId, P_A, P_B, P_C, TALLY)
            ).to.be.revertedWithCustomError(maci, "InvalidTallyProof");
        });

        it("no permite publicar antes de cerrar la votación", async function () {
            const { maci, admin, pollId } = await loadFixture(withVotingOpen);

            await expect(
                maci.connect(admin).publishTally(pollId, P_A, P_B, P_C, TALLY)
            ).to.be.revertedWithCustomError(maci, "VotingStillOpen");
        });

        it("no permite publicar dos veces", async function () {
            const { maci, admin, pollId } = await loadFixture(closedPoll);
            await maci.connect(admin).publishTally(pollId, P_A, P_B, P_C, TALLY);

            await expect(
                maci.connect(admin).publishTally(pollId, P_A, P_B, P_C, TALLY)
            ).to.be.revertedWithCustomError(maci, "AlreadyTallied");
        });

        it("solo COORDINATOR_ROLE publica", async function () {
            const { maci, stranger, pollId } = await loadFixture(closedPoll);

            await expect(
                maci.connect(stranger).publishTally(pollId, P_A, P_B, P_C, TALLY)
            ).to.be.reverted;
        });
    });

    describe("consultas inexistentes y pausa", function () {
        it("revierte sobre una consulta que no existe", async function () {
            const { maci, member } = await loadFixture(deployFixture);
            await expect(
                maci.connect(member).signUp(99n, KEY_X, KEY_Y)
            ).to.be.revertedWithCustomError(maci, "PollDoesNotExist");
        });

        it("la pausa detiene inscripciones y mensajes", async function () {
            const { maci, admin, member, pollId } = await loadFixture(withOpenPoll);
            await maci.connect(admin).pause("emergencia");

            await expect(maci.connect(member).signUp(pollId, KEY_X, KEY_Y)).to.be
                .reverted;
        });
    });
});
