require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
    solidity: {
        version: "0.8.20",
        settings: {
            optimizer: {
                enabled: true,
                runs: 200
            }
        }
    },
    networks: {
        localhost: {
            url: "http://127.0.0.1:8545"
        },
        sepolia: {
            url: process.env.SEPOLIA_RPC_URL || "",
            accounts: process.env.SEPOLIA_PRIVATE_KEY ? [process.env.SEPOLIA_PRIVATE_KEY] : [],
            chainId: 11155111
        },
        polygon: {
            url: process.env.POLYGON_RPC_URL || "",
            accounts: process.env.POLYGON_PRIVATE_KEY ? [process.env.POLYGON_PRIVATE_KEY] : [],
            chainId: 137
        }
    },
    etherscan: {
        apiKey: {
            sepolia: process.env.ETHERSCAN_API_KEY || "",
            polygon: process.env.POLYGONSCAN_API_KEY || ""
        }
    },
    // Sourcify no pide API key, así que la verificación del código no depende de
    // que alguien haya cargado ETHERSCAN_API_KEY. Importa para este proyecto:
    // un contrato de identidad civil cuyo bytecode nadie puede contrastar con
    // su fuente es indistinguible de uno que hace otra cosa.
    sourcify: {
        enabled: true
    },
    paths: {
        sources: "./contracts",
        tests: "./test",
        cache: "./cache",
        artifacts: "./artifacts"
    }
};
