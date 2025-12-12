const { ethers } = require("hardhat");

async function main() {
    console.log("Deploying DAOCiudadanaSBT contract...");

    const [deployer] = await ethers.getSigners();
    console.log("Deploying with account:", deployer.address);

    const balance = await ethers.provider.getBalance(deployer.address);
    console.log("Account balance:", ethers.formatEther(balance), "ETH");

    // Deploy contract
    const DAOCiudadanaSBT = await ethers.getContractFactory("DAOCiudadanaSBT");
    const contract = await DAOCiudadanaSBT.deploy();

    await contract.waitForDeployment();
    const address = await contract.getAddress();

    console.log("DAOCiudadanaSBT deployed to:", address);
    console.log("");
    console.log("=== DEPLOYMENT COMPLETE ===");
    console.log("Contract address:", address);
    console.log("Owner:", deployer.address);
    console.log("");
    console.log("Add this to your frontend .env:");
    console.log(`REACT_APP_SBT_CONTRACT_ADDRESS=${address}`);
    console.log("");
    console.log("Verify on Etherscan (Sepolia):");
    console.log(`npx hardhat verify --network sepolia ${address}`);
}

main()
    .then(() => process.exit(0))
    .catch((error) => {
        console.error(error);
        process.exit(1);
    });
