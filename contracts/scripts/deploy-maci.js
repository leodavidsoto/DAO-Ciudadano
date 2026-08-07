/**
 * Despliegue completo de la pila MACI en la red local (ROADMAP D-3).
 *
 * Qué despliega, y en este orden porque cada uno depende del anterior:
 *
 *   1. Groth16Verifier (Verifier.sol)  — verificador del circuito de membresía
 *   2. DAOCiudadanaSBT                 — censo: quién puede inscribirse
 *   3. TallyVerifier (TallyVerifier.sol) — verificador del circuito de tally
 *   4. MACICoordinator                 — inscripciones, mensajes y publicación
 *
 * Por qué el SBT real y no MockMembershipRegistry
 * ───────────────────────────────────────────────
 * El mock deja marcar miembros a dedo. Contra el SBT real, inscribirse exige
 * haber acuñado con prueba ZK, que es la propiedad que hace que el censo no
 * sea Sybil. Un despliegue local que se salta eso no prueba el sistema que se
 * va a operar.
 *
 * Uso:
 *   npx hardhat node                                     # en otra terminal
 *   npx hardhat run scripts/deploy-maci.js --network localhost
 *
 * Variables opcionales:
 *   MACI_ADMIN                 admin de la pila (por defecto: el deployer)
 *   MACI_COORDINATOR_PUBKEY_X  llave pública Baby Jubjub del coordinador
 *   MACI_COORDINATOR_PUBKEY_Y
 *   MACI_TOKEN_URI             metadata del SBT
 */
const fs = require("node:fs");
const path = require("node:path");
const { ethers, network } = require("hardhat");

const FIELD =
    21888242871839275222246405745257275088548364400416034343698204186575808495617n;

// Generador de Baby Jubjub (EIP-2494). Es un punto real de la curva, así que
// sirve para un despliegue local; en producción la llave sale de la ceremonia
// del coordinador y jamás debe ser un valor público como este.
const DEFAULT_PUBKEY_X =
    5299619240641551281634865583518297030282874472190772894086521144482721001553n;
const DEFAULT_PUBKEY_Y =
    16950150798460657717958625567821834550301663161624707787222815936182638968203n;

// El .zkey del tally es de una sola contribución (ver ceremony-manifest.txt:
// beacon=not-applied). Quien lo generó puede fabricar un recuento falso con
// prueba válida. Desplegarlo en una red pública sería ofrecer una garantía
// que no existe, así que el script se niega.
const LOCAL_NETWORKS = new Set(["hardhat", "localhost"]);

const DEPLOYMENT_PATH = path.join(__dirname, "..", "deployments");

async function main() {
    if (!LOCAL_NETWORKS.has(network.name)) {
        throw new Error(
            `Este script solo despliega en red local (recibido: "${network.name}").\n` +
            "El verificador de tally proviene de una ceremonia de una sola\n" +
            "contribución y no ofrece garantía real. Para una red pública hace\n" +
            "falta una ceremonia con beacon y usar deploy-tally-verifier.js."
        );
    }

    const [deployer] = await ethers.getSigners();
    const admin = process.env.MACI_ADMIN || deployer.address;

    const pubKeyX = process.env.MACI_COORDINATOR_PUBKEY_X
        ? BigInt(process.env.MACI_COORDINATOR_PUBKEY_X)
        : DEFAULT_PUBKEY_X;
    const pubKeyY = process.env.MACI_COORDINATOR_PUBKEY_Y
        ? BigInt(process.env.MACI_COORDINATOR_PUBKEY_Y)
        : DEFAULT_PUBKEY_Y;

    // Se valida acá y no solo on-chain: `setCoordinatorPubKey` rechaza esto
    // mismo, pero fallar antes de gastar cuatro despliegues es más barato.
    if (pubKeyX >= FIELD || pubKeyY >= FIELD) {
        throw new Error("La llave del coordinador está fuera del campo escalar");
    }
    if (pubKeyX === 0n && pubKeyY === 1n) {
        throw new Error("La llave del coordinador es el punto identidad");
    }

    console.log(`Red:      ${network.name}`);
    console.log(`Deployer: ${deployer.address}`);
    console.log(`Admin:    ${admin}`);
    console.log(
        `Saldo:    ${ethers.formatEther(
            await ethers.provider.getBalance(deployer.address)
        )} ETH`
    );

    console.log("\n==> 1/4 Groth16Verifier (circuito de membresía)");
    const Groth16 = await ethers.getContractFactory("Groth16Verifier");
    const membershipVerifier = await Groth16.deploy();
    await membershipVerifier.waitForDeployment();
    const membershipVerifierAddress = await membershipVerifier.getAddress();
    console.log(`    ${membershipVerifierAddress}`);

    // El censo por defecto es el SBT real: inscribirse exige haber acuñado
    // con prueba ZK, que es lo que impide un padrón Sybil. El mock existe
    // solo para que `maci:tally --bootstrap` pueda simular una elección sin
    // acuñar membresías, y queda registrado en el JSON para que nadie
    // confunda un despliegue de simulación con uno operable.
    const mockCensus = process.env.MACI_MOCK_CENSUS === "1";

    let censusAddress;
    let sbt = null;
    if (mockCensus) {
        console.log("\n==> 2/4 MockMembershipRegistry (censo SIMULADO)");
        const Registry = await ethers.getContractFactory("MockMembershipRegistry");
        const registry = await Registry.deploy();
        await registry.waitForDeployment();
        censusAddress = await registry.getAddress();
        console.log(`    ${censusAddress}`);
        console.log("    AVISO: censo sin prueba ZK. Solo para simulación.");
    } else {
        console.log("\n==> 2/4 DAOCiudadanaSBT (censo)");
        const SBT = await ethers.getContractFactory("DAOCiudadanaSBT");
        sbt = await SBT.deploy(
            admin,
            membershipVerifierAddress,
            process.env.MACI_TOKEN_URI || "ipfs://dao-ciudadana-membership-local"
        );
        await sbt.waitForDeployment();
        censusAddress = await sbt.getAddress();
        console.log(`    ${censusAddress}`);
    }
    const sbtAddress = censusAddress;

    console.log("\n==> 3/4 TallyVerifier (circuito de tally)");
    const Tally = await ethers.getContractFactory("TallyVerifier");
    const tallyVerifier = await Tally.deploy();
    await tallyVerifier.waitForDeployment();
    const tallyVerifierAddress = await tallyVerifier.getAddress();
    console.log(`    ${tallyVerifierAddress}`);

    console.log("\n==> 4/4 MACICoordinator");
    const Coordinator = await ethers.getContractFactory("MACICoordinator");
    const maci = await Coordinator.deploy(admin, sbtAddress, tallyVerifierAddress);
    await maci.waitForDeployment();
    const maciAddress = await maci.getAddress();
    console.log(`    ${maciAddress}`);

    console.log("\n==> Publicando la llave del coordinador");
    const adminSigner = await resolveAdminSigner(admin, deployer);
    const tx = await maci.connect(adminSigner).setCoordinatorPubKey(pubKeyX, pubKeyY);
    await tx.wait();
    console.log(`    tx: ${tx.hash}`);

    // Se comprueba contra la cadena, no contra los recibos: un status 1 no
    // garantiza que el estado quedara como se pretendía.
    console.log("\n==> Verificación posterior");
    const checks = {
        "maci.membership()": [await maci.membership(), sbtAddress],
        "maci.tallyVerifier()": [await maci.tallyVerifier(), tallyVerifierAddress],
    };
    if (sbt !== null) {
        checks["sbt.membershipVerifier()"] = [
            await sbt.membershipVerifier(),
            membershipVerifierAddress,
        ];
    }
    for (const [label, [actual, expected]] of Object.entries(checks)) {
        const ok = actual.toLowerCase() === expected.toLowerCase();
        console.log(`    ${ok ? "OK " : "MAL"} ${label} = ${actual}`);
        if (!ok) throw new Error(`${label} apunta a ${actual}, se esperaba ${expected}`);
    }

    const verifiable = await maci.tallyIsVerifiable();
    const storedX = await maci.coordinatorPubKeyX();
    console.log(`    ${verifiable ? "OK " : "MAL"} maci.tallyIsVerifiable() = ${verifiable}`);
    console.log(`    ${storedX === pubKeyX ? "OK " : "MAL"} maci.coordinatorPubKeyX() publicada`);
    if (!verifiable || storedX !== pubKeyX) {
        throw new Error("El estado on-chain no refleja lo desplegado");
    }

    const record = {
        network: network.name,
        chainId: Number((await ethers.provider.getNetwork()).chainId),
        deployedAt: new Date().toISOString(),
        deployer: deployer.address,
        admin,
        censusKind: mockCensus ? "MockMembershipRegistry" : "DAOCiudadanaSBT",
        contracts: {
            Groth16Verifier: membershipVerifierAddress,
            [mockCensus ? "MockMembershipRegistry" : "DAOCiudadanaSBT"]: sbtAddress,
            TallyVerifier: tallyVerifierAddress,
            MACICoordinator: maciAddress,
        },
        coordinatorPubKey: { x: pubKeyX.toString(), y: pubKeyY.toString() },
        tallyCeremony: "tally-integracion (una sola contribución, sin beacon)",
    };
    fs.mkdirSync(DEPLOYMENT_PATH, { recursive: true });
    const outPath = path.join(DEPLOYMENT_PATH, `maci-${network.name}.json`);
    fs.writeFileSync(outPath, `${JSON.stringify(record, null, 2)}\n`);

    console.log(`\nDirecciones escritas en ${outPath}`);
    console.log("`npx hardhat maci:tally` las lee de ahí.");
}

/**
 * El admin puede no ser una cuenta que este nodo controle. Si lo es, se usa;
 * si no, se falla acá en vez de dejar la pila desplegada pero sin llave y sin
 * decir por qué.
 */
async function resolveAdminSigner(admin, deployer) {
    if (admin.toLowerCase() === deployer.address.toLowerCase()) return deployer;
    const signers = await ethers.getSigners();
    const match = signers.find(
        (s) => s.address.toLowerCase() === admin.toLowerCase()
    );
    if (!match) {
        throw new Error(
            `MACI_ADMIN (${admin}) no es una cuenta de este nodo: no se puede ` +
            "publicar la llave del coordinador. Hazlo aparte con set_coordinator.js."
        );
    }
    return match;
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
