import {
    buildIdentityCredentialRequest,
    buildZkMintPayload,
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
