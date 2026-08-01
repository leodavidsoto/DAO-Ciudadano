const { ethers } = require("hardhat");

async function main() {
    console.log("Deploying DAOCiudadanaSBT contract...");

    const [deployer] = await ethers.getSigners();
    console.log("Deploying with account:", deployer.address);

    const balance = await ethers.provider.getBalance(deployer.address);
    console.log("Account balance:", ethers.formatEther(balance), "ETH");

    // Deploy contract. `deployer` receives DEFAULT_ADMIN_ROLE, MINTER_ROLE,
    // PAUSER_ROLE and REVOKER_ROLE at deploy time (see constructor NatSpec).
    // In production: grant MINTER_ROLE to the backend's MINTER_PRIVATE_KEY
    // address separately, then consider moving DEFAULT_ADMIN_ROLE to a
    // multisig and renouncing it from this deployer key.
    const DAOCiudadanaSBT = await ethers.getContractFactory("DAOCiudadanaSBT");
    const contract = await DAOCiudadanaSBT.deploy(deployer.address);

    await contract.waitForDeployment();
    const address = await contract.getAddress();

    console.log("DAOCiudadanaSBT deployed to:", address);
    console.log("");
    console.log("=== DEPLOYMENT COMPLETE ===");
    console.log("Contract address:", address);
    console.log("Admin / initial minter:", deployer.address);
    console.log("");
    console.log("Add this to your backend .env (see readiness.py):");
    console.log(`SBT_CONTRACT_ADDRESS=${address}`);
    console.log("");
    console.log("If the backend mints with a DIFFERENT key than the deployer,");
    console.log("grant it MINTER_ROLE:");
    console.log(`  contract.grantRole(await contract.MINTER_ROLE(), "<backend minter address>")`);
    console.log("");
    console.log("Verify on Etherscan (Sepolia):");
    console.log(`npx hardhat verify --network sepolia ${address} ${deployer.address}`);
}

main()
    .then(() => process.exit(0))
    .catch((error) => {
        console.error(error);
        process.exit(1);
    });
