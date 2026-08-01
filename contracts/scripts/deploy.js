const { artifacts, ethers, network } = require("hardhat");

const zkArtifactManifest = require("../../circuits/artifact-manifest.json");

const LOCAL_TOKEN_URI = "ipfs://dao-ciudadana/membership-v1";

function requiredEnvironment(name) {
    const value = process.env[name];
    if (!value) {
        throw new Error(`${name} is required on ${network.name}`);
    }
    return value;
}

async function main() {
    const [deployer] = await ethers.getSigners();
    const isLocal = network.name === "hardhat" || network.name === "localhost";

    if (!isLocal && zkArtifactManifest.productionReady !== true) {
        throw new Error(
            "The repository ZK manifest is development-only; replace it with the audited multi-party ceremony before public deployment"
        );
    }

    const adminAddress = isLocal
        ? process.env.SBT_ADMIN_ADDRESS || deployer.address
        : requiredEnvironment("SBT_ADMIN_ADDRESS");
    if (!ethers.isAddress(adminAddress) || adminAddress === ethers.ZeroAddress) {
        throw new Error("SBT_ADMIN_ADDRESS must be a non-zero address");
    }

    let verifierAddress = process.env.ZK_VERIFIER_ADDRESS;
    if (!verifierAddress) {
        if (!isLocal) {
            throw new Error(
                "ZK_VERIFIER_ADDRESS must point to the independently audited production verifier"
            );
        }
        const Verifier = await ethers.getContractFactory("Groth16Verifier");
        const verifier = await Verifier.deploy();
        await verifier.waitForDeployment();
        verifierAddress = await verifier.getAddress();
        console.log("Local development verifier:", verifierAddress);
    }

    if (!ethers.isAddress(verifierAddress)) {
        throw new Error("ZK_VERIFIER_ADDRESS is not a valid address");
    }
    const verifierCode = await ethers.provider.getCode(verifierAddress);
    if (verifierCode === "0x") {
        throw new Error("ZK_VERIFIER_ADDRESS has no deployed bytecode");
    }
    const verifierArtifact = await artifacts.readArtifact("Groth16Verifier");
    const expectedVerifierCodeHash = ethers.keccak256(
        verifierArtifact.deployedBytecode
    );
    const actualVerifierCodeHash = ethers.keccak256(verifierCode);
    if (actualVerifierCodeHash !== expectedVerifierCodeHash) {
        throw new Error(
            `Verifier bytecode mismatch: expected ${expectedVerifierCodeHash}, received ${actualVerifierCodeHash}`
        );
    }
    const tokenURI = isLocal
        ? process.env.SBT_METADATA_URI || LOCAL_TOKEN_URI
        : requiredEnvironment("SBT_METADATA_URI");

    console.log("Deploying from:", deployer.address);
    console.log("Admin / multisig:", adminAddress);
    console.log("Verifier:", verifierAddress);

    const DAOCiudadanaSBT = await ethers.getContractFactory(
        "DAOCiudadanaSBT"
    );
    const contract = await DAOCiudadanaSBT.deploy(
        adminAddress,
        verifierAddress,
        tokenURI
    );
    await contract.waitForDeployment();
    const address = await contract.getAddress();
    const scope = await contract.membershipScope();

    console.log("DAOCiudadanaSBT:", address);
    console.log("Derived membership scope:", scope.toString());
    console.log(`SBT_CONTRACT_ADDRESS=${address}`);
    console.log(
        "Before enabling minting, ROOT_MANAGER_ROLE must approve the issuer-curated identity root."
    );
    console.log(
        `Verify with constructor args: ${adminAddress} ${verifierAddress} ${JSON.stringify(tokenURI)}`
    );
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
