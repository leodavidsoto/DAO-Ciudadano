/**
 * Despliega el TallyVerifier de MACI y lo conecta al MACICoordinator.
 *
 * Se ejecuta DESPUÉS de la ceremonia de `maci_tally.circom`, que produce el
 * `TallyVerifier.sol` que este script compila y despliega.
 *
 * Deliberadamente separado de `deploy.js`: aquél despliega el sistema de
 * membresía completo, y volver a correrlo para añadir un verificador crearía
 * contratos nuevos y huérfanos.
 *
 * Uso:
 *   npx hardhat run scripts/deploy-tally-verifier.js --network sepolia
 *
 * Variables:
 *   MACI_COORDINATOR_ADDRESS  contrato al que conectar el verificador
 */
const { ethers, network } = require("hardhat");

async function main() {
    const coordinatorAddress = process.env.MACI_COORDINATOR_ADDRESS;
    if (!coordinatorAddress) {
        throw new Error("MACI_COORDINATOR_ADDRESS es obligatoria");
    }

    const [deployer] = await ethers.getSigners();
    console.log(`Red:      ${network.name}`);
    console.log(`Deployer: ${deployer.address}`);
    console.log(
        `Saldo:    ${ethers.formatEther(
            await ethers.provider.getBalance(deployer.address)
        )} ETH`
    );

    const coordinator = await ethers.getContractAt(
        "MACICoordinator",
        coordinatorAddress
    );

    // El despliegue sería inútil si esta cuenta no puede conectarlo después.
    // Comprobarlo antes evita dejar un contrato huérfano pagado.
    const adminRole = await coordinator.DEFAULT_ADMIN_ROLE();
    if (!(await coordinator.hasRole(adminRole, deployer.address))) {
        throw new Error(
            `${deployer.address} no tiene DEFAULT_ADMIN_ROLE en ${coordinatorAddress}: ` +
            "el verificador quedaría desplegado pero sin poder conectarse"
        );
    }

    if (await coordinator.tallyIsVerifiable()) {
        console.log(
            `\nYa hay un verificador conectado: ${await coordinator.tallyVerifier()}`
        );
        console.log("Reemplazarlo invalida las pruebas generadas contra el anterior.");
    }

    console.log("\n==> Desplegando TallyVerifier");
    const Verifier = await ethers.getContractFactory("TallyVerifier");
    const verifier = await Verifier.deploy();
    await verifier.waitForDeployment();
    const verifierAddress = await verifier.getAddress();
    console.log(`    TallyVerifier: ${verifierAddress}`);

    console.log("\n==> Conectándolo al MACICoordinator");
    const tx = await coordinator.setTallyVerifier(verifierAddress);
    const receipt = await tx.wait();
    console.log(`    tx: ${receipt.hash}`);

    // Se comprueba contra la cadena, no contra el recibo: un recibo con
    // status 1 no garantiza que el estado quedara como se pretendía.
    const stored = await coordinator.tallyVerifier();
    const verifiable = await coordinator.tallyIsVerifiable();

    console.log("\n==> Verificación posterior");
    console.log(`    tallyVerifier():     ${stored}`);
    console.log(`    tallyIsVerifiable(): ${verifiable}`);

    if (stored.toLowerCase() !== verifierAddress.toLowerCase() || !verifiable) {
        throw new Error("El estado on-chain no refleja el verificador desplegado");
    }

    console.log("\nListo. Recuerda que el tally solo es verificable frente al");
    console.log("circuito de ESTA ceremonia: regenerarla exige redesplegar.");
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
