/**
 * Regenerate src/contracts/SBTContract.js from the Hardhat artifact.
 *
 * The ABI used to be maintained by hand and drifted from the deployed
 * contract (audit finding A-2): the MembershipMinted signature differed, so
 * ethers never matched the event and tokenId came back null.
 *
 *   cd contracts && npx hardhat compile
 *   cd ../frontend && npm run sync:abi
 */
const fs = require('fs');
const path = require('path');

const ARTIFACT = path.resolve(
    __dirname, '../../contracts/artifacts/contracts/DAOCiudadanaSBT.sol/DAOCiudadanaSBT.json'
);
const TARGET = path.resolve(__dirname, '../src/contracts/SBTContract.js');

if (!fs.existsSync(ARTIFACT)) {
    console.error(`No existe el artefacto: ${ARTIFACT}\nEjecuta primero: cd contracts && npx hardhat compile`);
    process.exit(1);
}

const { abi } = JSON.parse(fs.readFileSync(ARTIFACT, 'utf8'));
const current = fs.readFileSync(TARGET, 'utf8');

// Replace only the ABI block; addresses and exports below stay as they are.
const start = current.indexOf('export const SBT_CONTRACT_ABI = [');
const end = current.indexOf('];', start) + 2;
if (start === -1) {
    console.error('No se encontró el bloque SBT_CONTRACT_ABI en el destino.');
    process.exit(1);
}

const updated =
    current.slice(0, start) +
    'export const SBT_CONTRACT_ABI = ' + JSON.stringify(abi, null, 4) + ';' +
    current.slice(end);

fs.writeFileSync(TARGET, updated);
console.log(`ABI sincronizada: ${abi.length} entradas → src/contracts/SBTContract.js`);
