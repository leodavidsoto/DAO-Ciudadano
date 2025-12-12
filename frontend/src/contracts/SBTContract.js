/**
 * DAOCiudadanaSBT Contract ABI (simplified for frontend)
 * Full ABI generated after compile: contracts/artifacts/DAOCiudadanaSBT.json
 */

export const SBT_CONTRACT_ABI = [
    // Mint
    {
        "inputs": [
            { "name": "to", "type": "address" },
            { "name": "identityHash", "type": "string" },
            { "name": "assuranceLevel", "type": "string" },
            { "name": "uri", "type": "string" }
        ],
        "name": "mintMembership",
        "outputs": [{ "name": "", "type": "uint256" }],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    // View functions
    {
        "inputs": [{ "name": "member", "type": "address" }],
        "name": "hasMembership",
        "outputs": [{ "name": "", "type": "bool" }],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{ "name": "member", "type": "address" }],
        "name": "getMembershipToken",
        "outputs": [{ "name": "", "type": "uint256" }],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{ "name": "tokenId", "type": "uint256" }],
        "name": "getIdentityHash",
        "outputs": [{ "name": "", "type": "string" }],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{ "name": "tokenId", "type": "uint256" }],
        "name": "getAssuranceLevel",
        "outputs": [{ "name": "", "type": "string" }],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{ "name": "", "type": "uint256" }],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{ "name": "tokenId", "type": "uint256" }],
        "name": "ownerOf",
        "outputs": [{ "name": "", "type": "address" }],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{ "name": "tokenId", "type": "uint256" }],
        "name": "tokenURI",
        "outputs": [{ "name": "", "type": "string" }],
        "stateMutability": "view",
        "type": "function"
    },
    // Events
    {
        "anonymous": false,
        "inputs": [
            { "indexed": true, "name": "member", "type": "address" },
            { "indexed": false, "name": "tokenId", "type": "uint256" },
            { "indexed": false, "name": "assuranceLevel", "type": "string" }
        ],
        "name": "MembershipMinted",
        "type": "event"
    }
];

// Default contract addresses per network
export const SBT_CONTRACT_ADDRESSES = {
    // Sepolia testnet - DEPLOYED
    11155111: "0x813fd379F715107b2451553d97f29408d8185f0e",
    // Polygon mainnet - Update after deployment
    137: process.env.REACT_APP_SBT_CONTRACT_POLYGON || null,
    // Localhost
    31337: "0x5FbDB2315678afecb367f032d93F642f64180aa3", // Default Hardhat
};

export default SBT_CONTRACT_ABI;
