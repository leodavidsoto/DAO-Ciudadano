import { Base8, r as BABY_JUB_FIELD_MODULUS } from './babyJubjub';
import { Interface } from 'ethers';
import { deriveSecretScalar, verifySignature } from '@zk-kit/eddsa-poseidon';
import { Keypair, PubKey } from 'maci-domainobjs';
import {
    poseidon2,
    poseidon3,
    poseidon4,
    poseidon6,
    poseidon10,
} from 'poseidon-lite';
import {
    MACI_PROTOCOL_VERSION,
    createMaciKeypair,
    deriveMaciPublicKeyHash,
    encryptMaciBallot,
    getMaciReadiness,
    getMaciPublicKey,
    normalizeMaciPublicKey,
    normalizeMaciVotingConfig,
    verifyMaciCoordinatorOnChain,
} from './maci';

const fs = require('fs');
const os = require('os');
const path = require('path');
const snarkjs = require('snarkjs');

global.setImmediate = global.setImmediate || ((callback, ...args) =>
    setTimeout(callback, 0, ...args));

const PROPOSAL_ID = 'proposal-1';
const CHAIN_ID = 11155111;
const COORDINATOR_CONTRACT = '0x2222222222222222222222222222222222222222';
const TALLY_VERIFIER = '0x3333333333333333333333333333333333333333';

const rawConfig = (coordinatorPublicKey) => ({
    protocol_version: MACI_PROTOCOL_VERSION,
    proposal_id: PROPOSAL_ID,
    poll_id: '7',
    state_index: '4',
    nonce: '1',
    vote_weight: '1',
    vote_options: {
        for: '0',
        against: '1',
        abstain: '2',
    },
    coordinator_contract: COORDINATOR_CONTRACT,
    coordinator_public_key: coordinatorPublicKey,
    coordinator_key_hash: deriveMaciPublicKeyHash(coordinatorPublicKey),
    chain_id: String(CHAIN_ID),
    accepting_messages: true,
    deadline: '2099-01-01T00:00:00.000Z',
});

const coordinatorInterface = new Interface([
    'function coordinatorPubKeyX() view returns (uint256)',
    'function coordinatorPubKeyY() view returns (uint256)',
    'function tallyVerifier() view returns (address)',
]);

const createCoordinatorProvider = (publicKey) => ({
    request: jest.fn(async ({ method, params }) => {
        if (method === 'eth_chainId') return `0x${CHAIN_ID.toString(16)}`;
        if (method === 'eth_getCode') return '0x60006000';
        if (method === 'eth_call') {
            const selector = params[0].data.slice(0, 10);
            if (selector === coordinatorInterface.getFunction('coordinatorPubKeyX').selector) {
                return coordinatorInterface.encodeFunctionResult(
                    'coordinatorPubKeyX',
                    [BigInt(publicKey.x)]
                );
            }
            if (selector === coordinatorInterface.getFunction('coordinatorPubKeyY').selector) {
                return coordinatorInterface.encodeFunctionResult(
                    'coordinatorPubKeyY',
                    [BigInt(publicKey.y)]
                );
            }
            if (selector === coordinatorInterface.getFunction('tallyVerifier').selector) {
                return coordinatorInterface.encodeFunctionResult(
                    'tallyVerifier',
                    [TALLY_VERIFIER]
                );
            }
        }
        throw new Error(`Unexpected JSON-RPC method ${method}`);
    }),
});

test('accepts prime-subgroup Baby Jubjub keys and rejects low-order points', () => {
    expect(normalizeMaciPublicKey({
        x: Base8[0].toString(),
        y: Base8[1].toString(),
    })).toEqual(Base8);
    expect(() => normalizeMaciPublicKey({ x: '0', y: '1' }))
        .toThrow(/punto Baby Jubjub válido/i);
    expect(() => normalizeMaciPublicKey({
        x: '0',
        y: (BABY_JUB_FIELD_MODULUS - 1n).toString(),
    })).toThrow(/subgrupo primo/i);
    expect(() => normalizeMaciPublicKey({
        x: '0',
        y: (BABY_JUB_FIELD_MODULUS * 2n - 1n).toString(),
    })).toThrow(/fuera del campo/i);
});

test('rejects stale, mismatched and overflowing poll configuration', async () => {
    const coordinator = await createMaciKeypair();
    const publicKey = getMaciPublicKey(coordinator);
    expect(() => normalizeMaciVotingConfig(rawConfig(publicKey), {
        proposalId: 'another-proposal',
        chainId: CHAIN_ID,
    })).toThrow(/no corresponde/i);
    expect(() => normalizeMaciVotingConfig({
        ...rawConfig(publicKey),
        state_index: (1n << 50n).toString(),
    }, {
        proposalId: PROPOSAL_ID,
        chainId: CHAIN_ID,
    })).toThrow(/50 bits/i);
    expect(() => normalizeMaciVotingConfig({
        ...rawConfig(publicKey),
        deadline: '2020-01-01T00:00:00.000Z',
    }, {
        proposalId: PROPOSAL_ID,
        chainId: CHAIN_ID,
    })).toThrow(/plazo/i);
});

test('does not treat legacy readiness flags as a reviewed private-voting pipeline', () => {
    const readiness = getMaciReadiness({
        key_registry: true,
        private_voting: true,
        coordinator_configured: true,
        tally_proof: true,
    });
    expect(readiness.ready).toBe(false);
    expect(readiness.missing).toEqual(expect.arrayContaining([
        'vinculación mensaje-poll',
        'nonce ligado al estado',
        'unicidad de hojas del tally',
        'encadenamiento de pruebas',
    ]));
});

test('anchors the coordinator key and tally verifier to the trusted on-chain deployment', async () => {
    const coordinator = await createMaciKeypair();
    const publicKey = getMaciPublicKey(coordinator);
    const config = normalizeMaciVotingConfig(rawConfig(publicKey), {
        proposalId: PROPOSAL_ID,
        chainId: CHAIN_ID,
    });

    await expect(verifyMaciCoordinatorOnChain({
        config,
        ethereum: createCoordinatorProvider(publicKey),
        expectedAddress: '0x4444444444444444444444444444444444444444',
        expectedTallyVerifier: TALLY_VERIFIER,
    })).rejects.toThrow(/no coincide con el despliegue confiable/i);

    await expect(verifyMaciCoordinatorOnChain({
        config,
        ethereum: createCoordinatorProvider(publicKey),
        expectedAddress: COORDINATOR_CONTRACT,
        expectedTallyVerifier: TALLY_VERIFIER,
    })).resolves.toEqual({
        coordinatorContract: COORDINATOR_CONTRACT,
        tallyVerifier: TALLY_VERIFIER,
    });
});

test('produces the approved ten-field stream message that the coordinator decrypts', async () => {
    const voter = await createMaciKeypair();
    const coordinator = await createMaciKeypair();
    const config = normalizeMaciVotingConfig(
        rawConfig(getMaciPublicKey(coordinator)),
        { proposalId: PROPOSAL_ID, chainId: CHAIN_ID }
    );
    const encrypted = await encryptMaciBallot({
        voterKeypair: voter,
        config,
        choice: 'against',
    });

    expect(encrypted.message.data).toHaveLength(10);
    expect(encrypted.message.data.every((value) => /^(?:0|[1-9][0-9]*)$/.test(value)))
        .toBe(true);
    const ephemeralPublicKey = new PubKey([
        BigInt(encrypted.encryptionPublicKey.x),
        BigInt(encrypted.encryptionPublicKey.y),
    ]);
    const coordinatorSharedKey = Keypair.genEcdhSharedKey(
        coordinator.privKey,
        ephemeralPublicKey
    );
    const plaintext = encrypted.message.data.map((value, index) => {
        const pad = poseidon3([
            coordinatorSharedKey[0],
            coordinatorSharedKey[1],
            BigInt(index),
        ]);
        return (BigInt(value) - pad + BABY_JUB_FIELD_MODULUS) %
            BABY_JUB_FIELD_MODULUS;
    });

    expect(plaintext.slice(0, 6)).toEqual([
        4n,
        1n,
        1n,
        1n,
        ...voter.pubKey.rawPubKey,
    ]);
    expect(plaintext[9]).toBe(0n);
    const signature = {
        R8: [plaintext[6], plaintext[7]],
        S: plaintext[8],
    };
    expect(verifySignature(
        poseidon6(plaintext.slice(0, 6)),
        signature,
        voter.pubKey.rawPubKey
    )).toBe(true);

    const serialized = JSON.stringify(encrypted);
    expect(serialized).not.toContain('against');
    expect(serialized).not.toContain('privKey');
    expect(serialized).not.toContain('sharedKey');
    expect(serialized).not.toContain('signature');
});

test('the browser ciphertext produces a valid processMessages circuit witness', async () => {
    const voter = await createMaciKeypair();
    const coordinator = await createMaciKeypair();
    const config = normalizeMaciVotingConfig(
        rawConfig(getMaciPublicKey(coordinator)),
        { proposalId: PROPOSAL_ID, chainId: CHAIN_ID }
    );
    const encrypted = await encryptMaciBallot({
        voterKeypair: voter,
        config,
        choice: 'against',
    });

    const depth = 10;
    const zeros = [0n];
    for (let level = 0; level < depth; level += 1) {
        zeros.push(poseidon2([zeros[level], zeros[level]]));
    }
    const currentVotes = [0n, 0n, 0n];
    const newVotes = [0n, 1n, 0n];
    const voterPublicKey = voter.pubKey.rawPubKey;
    const leafOf = (votes) => poseidon4([
        voterPublicKey[0],
        voterPublicKey[1],
        1n,
        poseidon3(votes),
    ]);
    const pathElements = [];
    const pathIndices = [];
    let position = Number(config.stateIndex);
    for (let level = 0; level < depth; level += 1) {
        pathElements.push(zeros[level].toString());
        pathIndices.push(position % 2);
        position = Math.floor(position / 2);
    }
    const rootOf = (leaf) => {
        let current = leaf;
        let index = Number(config.stateIndex);
        for (let level = 0; level < depth; level += 1) {
            current = index % 2 === 0
                ? poseidon2([current, zeros[level]])
                : poseidon2([zeros[level], current]);
            index = Math.floor(index / 2);
        }
        return current;
    };
    const ephemeralPublicKey = [
        BigInt(encrypted.encryptionPublicKey.x),
        BigInt(encrypted.encryptionPublicKey.y),
    ];
    const ciphertext = encrypted.message.data.map((value) => BigInt(value));
    const messageHash = poseidon3([
        ephemeralPublicKey[0],
        ephemeralPublicKey[1],
        poseidon10(ciphertext),
    ]);
    const input = {
        coordinatorPrivKey: deriveSecretScalar(
            coordinator.privKey.rawPrivKey.toString()
        ).toString(),
        ephemeralPubKey: ephemeralPublicKey.map(String),
        ciphertext: encrypted.message.data,
        voterPubKey: voterPublicKey.map(String),
        voiceCredits: '1',
        currentVotes: currentVotes.map(String),
        currentNonce: (config.nonce - 1n).toString(),
        pathElements,
        pathIndices,
        currentStateRoot: rootOf(leafOf(currentVotes)).toString(),
        newStateRoot: rootOf(leafOf(newVotes)).toString(),
        messageHash: messageHash.toString(),
    };

    const wasmPath = path.resolve(
        __dirname,
        '../../../circuits/build/process/processMessages_js/processMessages.wasm'
    );
    const witnessPath = path.join(os.tmpdir(), `frontend-maci-${process.pid}.wtns`);
    await expect(snarkjs.wtns.calculate(input, wasmPath, witnessPath)).resolves.toBeUndefined();
}, 30000);
