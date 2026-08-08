import path from 'path';
import { readFile } from 'fs/promises';
import { Wallet } from 'ethers';
import { poseidon2 } from 'poseidon-lite/poseidon2';
import { poseidon3 } from 'poseidon-lite/poseidon3';

// jsdom does not expose Node's scheduling primitive, while snarkjs/fastfile
// uses it to yield during proving.
global.setImmediate ||= (callback, ...args) =>
    setTimeout(callback, 0, ...args);

const RECIPIENT = '0x70997970C51812dc3A010C7d01b50e0d17dc79C8';
const IDENTITY_SECRET = '18374686479671623683';
const SCOPE =
    '16645906639000314148974453730666249407391726919646577242780652979940179738392';
const DEPTH = 25;
const MEMBERSHIP_CONTRACT = '0xA15BB66138824a1c7167f5E85b957d04Dd34E468';
const issuer = new Wallet(
    '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80'
);

const circuitBuild = path.resolve(process.cwd(), '..', 'circuits', 'build');
process.env.REACT_APP_ZK_WASM_URL = path.join(
    circuitBuild,
    'verify_identity_js',
    'verify_identity.wasm'
);
process.env.REACT_APP_ZK_ZKEY_URL = path.join(
    circuitBuild,
    'verify_identity_final.zkey'
);
process.env.REACT_APP_ZK_VKEY_URL = path.join(
    circuitBuild,
    'verification_key.json'
);
process.env.REACT_APP_ZK_IDENTITY_ISSUER_ADDRESS = issuer.address;
process.env.REACT_APP_MEMBERSHIP_CONTRACT_ADDRESS = MEMBERSHIP_CONTRACT;

const {
    buildIdentityCredentialMessage,
    generateIdentityProof,
    importSecret,
    normalizeIdentityCredential,
    readMembershipDeployment,
    releaseZkResources,
    verifyProofLocally,
    ZkProofError,
} = require('./zk');

jest.setTimeout(120000);

const responseHeaders = (contentType) => ({
    get: (name) =>
        name.toLowerCase() === 'content-type' ? contentType : null,
});

async function buildCredential() {
    const hash = (inputs) => {
        const hasher = inputs.length === 2 ? poseidon2 : poseidon3;
        return hasher(inputs.map((value) => BigInt(value)));
    };

    const zeroHashes = [0n];
    for (let level = 0; level < DEPTH; level += 1) {
        zeroHashes.push(hash([zeroHashes[level], zeroHashes[level]]));
    }

    const commitment = hash([IDENTITY_SECRET, BigInt(RECIPIENT), SCOPE]);
    let root = commitment;
    const pathElements = [];
    for (let level = 0; level < DEPTH; level += 1) {
        pathElements.push(zeroHashes[level].toString());
        root = hash([root, zeroHashes[level]]);
    }

    const credential = {
        identity_root: root.toString(),
        identity_commitment: commitment.toString(),
        membership_scope: SCOPE,
        wallet_address: RECIPIENT,
        path_elements: pathElements,
        path_indices: Array(DEPTH).fill(0),
    };
    credential.signature = await issuer.signMessage(
        buildIdentityCredentialMessage({
            recipient: credential.wallet_address,
            identityRoot: credential.identity_root,
            scope: credential.membership_scope,
            commitment: credential.identity_commitment,
        })
    );
    return credential;
}

beforeEach(() => {
    localStorage.clear();
    global.fetch = jest.fn(async (url, options = {}) => {
        if (options.method === 'HEAD') {
            return {
                ok: true,
                headers: responseHeaders('application/octet-stream'),
            };
        }
        if (url === process.env.REACT_APP_ZK_VKEY_URL) {
            const raw = await readFile(url, 'utf8');
            return {
                ok: true,
                headers: responseHeaders('application/json'),
                json: async () => JSON.parse(raw),
            };
        }
        throw new Error(`Unexpected fetch: ${url}`);
    });
});

afterEach(() => {
    delete global.fetch;
});

afterAll(async () => {
    await releaseZkResources();
    const snarkjs = await import('snarkjs');
    const curve = await snarkjs.curves.getCurveFromName('bn128');
    await curve.terminate();
});

test('generates and locally verifies contract-ready wallet-bound calldata', async () => {
    importSecret(IDENTITY_SECRET);
    const identity = await buildCredential();

    const result = await generateIdentityProof({
        identity,
        recipient: RECIPIENT,
        expectedScope: SCOPE,
    });

    expect(result.publicSignals).toHaveLength(4);
    expect(result.publicSignals[0]).toBe(identity.identity_root);
    expect(result.publicSignals[2]).toBe(BigInt(RECIPIENT).toString());
    expect(result.publicSignals[3]).toBe(SCOPE);
    expect(result.nullifierHash).toBe(
        '0x14c965acb271496fccb44287ebe44ff7ecaad175934a714b26838f8018126378'
    );
    expect(result.pA).toHaveLength(2);
    expect(result.pB).toHaveLength(2);
    expect(result.pB.every((row) => row.length === 2)).toBe(true);
    expect(result.pC).toHaveLength(2);
    const solidityCoordinates = [
        ...result.pA,
        ...result.pB.flat(),
        ...result.pC,
    ];
    expect(solidityCoordinates.every((value) => /^\d+$/.test(value))).toBe(true);
    expect(await verifyProofLocally(result.proof, result.publicSignals)).toBe(true);

    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain(identity.signature);
    expect(serialized).not.toContain('path_elements');
    expect(serialized).not.toContain(IDENTITY_SECRET);
});

test('rejects an issuer credential bound to another wallet before proving', async () => {
    const identity = await buildCredential();
    expect(() =>
        normalizeIdentityCredential(
            identity,
            '0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC'
        )
    ).toThrow(ZkProofError);
});

test('rejects a credential with a tampered issuer signature', async () => {
    importSecret(IDENTITY_SECRET);
    const identity = await buildCredential();
    identity.signature = `${identity.signature.slice(0, -2)}00`;

    await expect(generateIdentityProof({
        identity,
        recipient: RECIPIENT,
        expectedScope: SCOPE,
    })).rejects.toThrow(/firma|emisor/i);
});

test('requires the EIP-1193 provider pinned by the wallet session for deployment reads', async () => {
    await expect(readMembershipDeployment(
        11155111,
        null,
        RECIPIENT,
        null
    )).rejects.toThrow(/proveedor EIP-1193 fijado/i);
});

test('rejects a credential issued for a different local secret', async () => {
    importSecret('123456789');
    const identity = await buildCredential();

    await expect(generateIdentityProof({
        identity,
        recipient: RECIPIENT,
        expectedScope: SCOPE,
    })).rejects.toThrow(/secreto local/i);
});
