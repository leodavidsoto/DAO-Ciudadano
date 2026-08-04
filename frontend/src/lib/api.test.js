import {
    buildEncryptedBallotPayload,
    buildIdentityCredentialRequest,
    buildZkMintPayload,
    electionsAPI,
    normalizeEncryptedBallotReceipt,
} from './api';

test('builds the one-time credential exchange without identity secret or PII', () => {
    const payload = buildIdentityCredentialRequest({
        walletAddress: '0x0000000000000000000000000000000000000001',
        identityCommitment: '11',
        membershipScope: '12',
        membershipContract: '0x0000000000000000000000000000000000000002',
        chainId: '11155111',
        identityGrant: 'opaque-one-time-grant',
        identitySecret: 'must-not-leak',
        rut: 'must-not-leak',
    });

    expect(payload).toEqual({
        wallet_address: '0x0000000000000000000000000000000000000001',
        identity_commitment: '11',
        membership_scope: '12',
        membership_contract: '0x0000000000000000000000000000000000000002',
        chain_id: '11155111',
        identity_grant: 'opaque-one-time-grant',
    });
});

test('builds the exact relayer payload without private identity material', () => {
    const payload = buildZkMintPayload({
        walletAddress: '0x0000000000000000000000000000000000000001',
        pA: ['1', '2'],
        pB: [['3', '4'], ['5', '6']],
        pC: ['7', '8'],
        nullifierHash: `0x${'09'.repeat(32)}`,
        identityRoot: '10',
        signature: 'must-not-leak',
        pathElements: ['must-not-leak'],
        identitySecret: 'must-not-leak',
        publicSignals: ['must-not-leak'],
    });

    expect(payload).toEqual({
        wallet_address: '0x0000000000000000000000000000000000000001',
        pA: ['1', '2'],
        pB: [['3', '4'], ['5', '6']],
        pC: ['7', '8'],
        nullifier_hash: `0x${'09'.repeat(32)}`,
        identity_root: '10',
    });
});

test('builds only the public MACI wire message', () => {
    const ciphertext = Array.from({ length: 10 }, (_, index) => String(index + 20));
    const payload = buildEncryptedBallotPayload({
        protocolVersion: 'maci-v2.5.0',
        proposalId: 'proposal-1',
        pollId: '7',
        message: { data: ciphertext },
        encryptionPublicKey: { x: '11', y: '12' },
        coordinatorKeyHash: `0x${'ab'.repeat(32)}`,
        idempotencyKey: '12345678-1234-4234-9234-123456789abc',
        choice: 'for',
        walletAddress: 'must-not-leak',
        voterPrivateKey: 'must-not-leak',
        sharedKey: 'must-not-leak',
        signature: 'must-not-leak',
    });

    expect(payload).toEqual({
        protocol_version: 'maci-v2.5.0',
        proposal_id: 'proposal-1',
        poll_id: '7',
        message: { data: ciphertext },
        encryption_public_key: { x: '11', y: '12' },
        coordinator_key_hash: `0x${'ab'.repeat(32)}`,
        idempotency_key: '12345678-1234-4234-9234-123456789abc',
    });
    const serialized = JSON.stringify(payload);
    expect(serialized).not.toContain('must-not-leak');
    expect(serialized).not.toContain('choice');
    expect(serialized).not.toContain('wallet');
});

test('rejects malformed MACI ciphertext before transport', () => {
    expect(() => buildEncryptedBallotPayload({
        protocolVersion: 'maci-v2.5.0',
        proposalId: 'proposal-1',
        pollId: '7',
        message: { data: ['1', '2'] },
        encryptionPublicKey: { x: '11', y: '12' },
        coordinatorKeyHash: `0x${'ab'.repeat(32)}`,
        idempotencyKey: '12345678-1234-4234-9234-123456789abc',
    })).toThrow(/diez elementos/i);

    expect(() => buildEncryptedBallotPayload({
        protocolVersion: 'maci-v1',
        proposalId: 'proposal-1',
        pollId: '7',
        message: { data: Array(10).fill('1') },
        encryptionPublicKey: { x: '11', y: '12' },
        coordinatorKeyHash: `0x${'ab'.repeat(32)}`,
        idempotencyKey: '12345678-1234-4234-9234-123456789abc',
    })).toThrow(/versión MACI no es compatible/i);

    expect(() => buildEncryptedBallotPayload({
        protocolVersion: 'maci-v2.5.0',
        proposalId: 'proposal-1',
        pollId: '7',
        message: {
            data: [
                '21888242871839275222246405745257275088548364400416034343698204186575808495617',
                ...Array(9).fill('1'),
            ],
        },
        encryptionPublicKey: { x: '11', y: '12' },
        coordinatorKeyHash: `0x${'ab'.repeat(32)}`,
        idempotencyKey: '12345678-1234-4234-9234-123456789abc',
    })).toThrow(/diez elementos decimales/i);
});

test('accepts only the real indexed MACI message-chain receipt', () => {
    expect(normalizeEncryptedBallotReceipt({
        data: {
            ok: true,
            index: 3,
            message_chain: 'AB'.repeat(32),
            duplicate: true,
        },
    })).toEqual({
        messageId: `0x${'ab'.repeat(32)}`,
        index: 3,
        duplicate: true,
    });

    expect(() => normalizeEncryptedBallotReceipt({
        data: { ok: true, message_id: 'not-the-backend-contract' },
    })).toThrow(/índice verificable/i);
});

test('does not expose the legacy plaintext election-vote transport', () => {
    expect(electionsAPI.vote).toBeUndefined();
    expect(electionsAPI.getBallotSchema).toBeUndefined();
});
