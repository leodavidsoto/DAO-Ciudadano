const { ethers, network } = require("hardhat");

const REQUIRED_ROLES = [
    { name: "DEFAULT_ADMIN_ROLE", id: ethers.ZeroHash }, // 0x00...
    { name: "ROOT_MANAGER_ROLE", id: ethers.id("ROOT_MANAGER_ROLE") },
    { name: "PAUSER_ROLE", id: ethers.id("PAUSER_ROLE") },
    { name: "REVOKER_ROLE", id: ethers.id("REVOKER_ROLE") }
];

async function main() {
    console.log("=== FASE 5.1: Transición de Gobernanza a Safe Multisig ===");

    const [deployer] = await ethers.getSigners();
    console.log("Current EOA (Ejecutor):", deployer.address);

    const contractAddress = process.env.SBT_CONTRACT_ADDRESS;
    const defaultSafe = process.env.TREASURY_SAFE_ADDRESS;

    if (!contractAddress || !ethers.isAddress(contractAddress)) {
        throw new Error("Se requiere SBT_CONTRACT_ADDRESS en el entorno.");
    }
    if (!defaultSafe || !ethers.isAddress(defaultSafe)) {
        throw new Error("Se requiere TREASURY_SAFE_ADDRESS (Multisig base) en el entorno.");
    }

    const roleAddresses = {
        DEFAULT_ADMIN_ROLE: defaultSafe,
        ROOT_MANAGER_ROLE: process.env.ROOT_MANAGER_SAFE_ADDRESS || defaultSafe,
        PAUSER_ROLE: process.env.PAUSER_SAFE_ADDRESS || defaultSafe,
        REVOKER_ROLE: process.env.REVOKER_SAFE_ADDRESS || defaultSafe
    };

    if (deployer.address.toLowerCase() === defaultSafe.toLowerCase()) {
        throw new Error("El ejecutor no puede ser el mismo Safe Multisig. Este script transfiere desde una EOA a un Safe.");
    }

    console.log("Contrato DAOCiudadanaSBT:", contractAddress);
    console.log("Destino base (Safe Multisig):", defaultSafe);

    const sbt = await ethers.getContractAt("DAOCiudadanaSBT", contractAddress);

    // 1. Validar que la EOA tenga el rol de admin actual, si no, no puede transferir nada.
    const isAdmin = await sbt.hasRole(REQUIRED_ROLES[0].id, deployer.address);
    if (!isAdmin) {
        throw new Error(`La EOA ${deployer.address} no tiene el DEFAULT_ADMIN_ROLE. No puede transferir la propiedad.`);
    }

    console.log("\nOtorgando roles a los Safe Multisigs...");
    for (const role of REQUIRED_ROLES) {
        const targetAddress = roleAddresses[role.name];
        const hasRole = await sbt.hasRole(role.id, targetAddress);
        if (!hasRole) {
            console.log(`Otorgando ${role.name} a ${targetAddress}...`);
            const tx = await sbt.grantRole(role.id, targetAddress);
            await tx.wait();
        } else {
            console.log(`El Safe ${targetAddress} ya tiene el rol ${role.name}.`);
        }
    }

    console.log("\nVerificando que el Safe principal tenga el DEFAULT_ADMIN_ROLE antes de renunciar...");
    const safeIsAdmin = await sbt.hasRole(REQUIRED_ROLES[0].id, defaultSafe);
    if (!safeIsAdmin) {
        throw new Error("¡Error Crítico! El Safe no recibió el DEFAULT_ADMIN_ROLE. Abortando renuncia para no bloquear el contrato.");
    }

    console.log("\nRenunciando a los roles desde la EOA original (Descentralización)...");
    for (const role of REQUIRED_ROLES) {
        const hasRole = await sbt.hasRole(role.id, deployer.address);
        if (hasRole) {
            console.log(`Renunciando a ${role.name}...`);
            // Usamos renounceRole(role, account) 
            const tx = await sbt.renounceRole(role.id, deployer.address);
            await tx.wait();
        }
    }

    console.log("\n✅ Transición completa. La EOA original ya no tiene privilegios.");
    console.log("El contrato ahora es gobernado exclusivamente por las carteras designadas.");
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
