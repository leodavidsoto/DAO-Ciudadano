import { Base8, r as BABY_JUB_FIELD_MODULUS } from './babyJubjub';
import { Interface } from 'ethers';
import { Keypair, Message, PCommand, PubKey } from 'maci-domainobjs';
import {
    MACI_PROTOCOL_VERSION,
    createMaciKeypair,
    deriveMaciPublicKeyHash,
    encryptMaciBallot,
    getMaciPublicKey,
    normalizeMaciPublicKey,
    normalizeMaciVotingConfig,
    verifyMaciCoordinatorOnChain,
} from './maci';

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

test('produces an official ten-field PCommand message that the coordinator decrypts', async () => {
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
    const message = new Message(encrypted.message.data.map(BigInt));
    const { command, signature } = PCommand.decrypt(message, coordinatorSharedKey);

    expect(command.stateIndex).toBe(4n);
    expect(command.pollId).toBe(7n);
    expect(command.voteOptionIndex).toBe(1n);
    expect(command.newVoteWeight).toBe(1n);
    expect(command.verifySignature(signature, voter.pubKey)).toBe(true);
    expect(command.newPubKey.equals(voter.pubKey)).toBe(true);

    const serialized = JSON.stringify(encrypted);
    expect(serialized).not.toContain('against');
    expect(serialized).not.toContain('privKey');
    expect(serialized).not.toContain('sharedKey');
    expect(serialized).not.toContain('signature');
});
