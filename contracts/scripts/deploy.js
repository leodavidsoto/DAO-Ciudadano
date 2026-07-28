/**
 * Deploy DAOCiudadanaSBT.
 *
 * Roles (ADR 0001, decision D-1): minting is separated from administration.
 *   ADMIN_ROLE  → pause, revoke, grant roles. Should be a Safe multisig.
 *   MINTER_ROLE → mint only. The backend's key, ideally held in a KMS.
 *
 * Configure both in .env; the deployer is NOT used as a default on purpose —
 * silently granting full control to whatever key happens to run the script is
 * how a "DAO" ends up depending on one person's laptop.
 *
 *   ADMIN_ADDRESS=0x...   # multisig
 *   MINTER_ADDRESS=0x...  # backend signer
 */
const { ethers } = require("hardhat");

async function main() {
    const admin = process.env.ADMIN_ADDRESS;
    const minter = process.env.MINTER_ADDRESS;

    if (!admin || !minter) {
        throw new Error(
            "Faltan ADMIN_ADDRESS y/o MINTER_ADDRESS en el entorno. " +
            "Ver contracts/.env.example y docs/adr/0001-decisiones-fase-1.md"
        );
    }
    if (admin.toLowerCase() === minter.toLowerCase()) {
        console.warn(
            "\n⚠️  ADMIN_ADDRESS y MINTER_ADDRESS son la misma dirección.\n" +
            "   Eso anula la separación de roles: una llave de acuñación\n" +
            "   filtrada podría además pausar y revocar. Aceptable solo en\n" +
            "   pruebas locales.\n"
        );
    }

    const [deployer] = await ethers.getSigners();
    const balance = await ethers.provider.getBalance(deployer.address);
    console.log("Desplegando con:", deployer.address);
    console.log("Saldo:", ethers.formatEther(balance), "ETH");
    console.log("Admin  (multisig):", admin);
    console.log("Minter (backend):", minter);

    const Factory = await ethers.getContractFactory("DAOCiudadanaSBT");
    const contract = await Factory.deploy(admin, minter);
    await contract.waitForDeployment();
    const address = await contract.getAddress();

    console.log("\n=== DESPLIEGUE COMPLETO ===");
    console.log("Contrato:", address);
    console.log("\nActualiza:");
    console.log(`  frontend/.env  → REACT_APP_SBT_CONTRACT_SEPOLIA=${address}`);
    console.log(`  backend (Render) → SBT_CONTRACT_ADDRESS=${address}`);
    console.log(`\nVerificar:\n  npx hardhat verify --network sepolia ${address} ${admin} ${minter}`);

    // The deployer keeps no role: whoever ran the script must not retain
    // power over the contract just for having deployed it.
    const adminRole = await contract.DEFAULT_ADMIN_ROLE();
    if (!(await contract.hasRole(adminRole, deployer.address))) {
        console.log("\n✓ El desplegador no conserva ningún rol.");
    }
}

main()
    .then(() => process.exit(0))
    .catch((error) => {
        console.error(error);
        process.exit(1);
    });
