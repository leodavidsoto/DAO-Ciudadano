import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { OnboardingProvider, useOnboarding } from './OnboardingContext';
import { authAPI, membershipAPI, dashboardAPI } from '../lib/api';
import {
    checkZkAvailability,
    deriveIdentityCommitment,
    generateIdentityProof,
    readMembershipDeployment,
    verifyIdentityCredential,
    verifyProofLocally,
} from '../lib/zk';

jest.mock('../lib/api', () => ({
    authAPI: {
        claveUnica: jest.fn(),
        nfc: jest.fn(),
        liveness: jest.fn(),
        issueIdentityCredential: jest.fn(),
    },
    membershipAPI: {
        mintWithProof: jest.fn(),
        getByWallet: jest.fn(),
    },
    dashboardAPI: {
        getStats: jest.fn(),
    },
}));

jest.mock('../lib/zk', () => {
    class ZkNotProvisionedError extends Error {
        constructor(message, missing = []) {
            super(message);
            this.missing = missing;
        }
    }
    return {
        generateIdentityProof: jest.fn(),
        deriveIdentityCommitment: jest.fn(),
        readMembershipDeployment: jest.fn(),
        verifyIdentityCredential: jest.fn(),
        verifyProofLocally: jest.fn(),
        checkZkAvailability: jest.fn(),
        ZkNotProvisionedError,
    };
});

global.IS_REACT_ACT_ENVIRONMENT = true;

const WALLET = '0x70997970C51812dc3A010C7d01b50e0d17dc79C8';
const MEMBERSHIP_CONTRACT = '0x0000000000000000000000000000000000000002';
const EIP1193_PROVIDER = {
    isMetaMask: true,
    request: jest.fn(),
};
const IDENTITY = {
    signature: 'private-signed-identity',
    identityRoot: '11',
    commitment: '12',
    scope: '13',
    recipient: WALLET,
    pathElements: Array(25).fill('0'),
    pathIndices: Array(25).fill('0'),
};
const PROOF_RESULT = {
    proof: { pi_a: ['raw-private-proof'] },
    publicSignals: ['11', '14', BigInt(WALLET).toString(), '13'],
    pA: ['1', '2'],
    pB: [['3', '4'], ['5', '6']],
    pC: ['7', '8'],
    nullifierHash: `0x${'09'.repeat(32)}`,
    identityRoot: '11',
    recipient: WALLET,
    scope: '13',
};

let context;
let container;
let root;

const Probe = () => {
    context = useOnboarding();
    return null;
};

beforeEach(async () => {
    jest.clearAllMocks();
    context = null;
    container = document.createElement('div');
    root = createRoot(container);
    readMembershipDeployment.mockResolvedValue({
        scope: '13',
        contractAddress: MEMBERSHIP_CONTRACT,
        chainId: '11155111',
    });
    checkZkAvailability.mockResolvedValue({ ready: true, missing: [] });
    deriveIdentityCommitment.mockResolvedValue('12');
    verifyIdentityCredential.mockReturnValue({ identityRoot: '11' });
    generateIdentityProof.mockResolvedValue(PROOF_RESULT);
    verifyProofLocally.mockResolvedValue(true);
    membershipAPI.mintWithProof.mockResolvedValue({
        data: { ok: true, token_id: 1, tx_hash: '0xtx' },
    });
    dashboardAPI.getStats.mockResolvedValue({
        data: { total_members: 1, recent_joins: 1 },
    });

    await act(async () => {
        root.render(
            <OnboardingProvider>
                <Probe />
            </OnboardingProvider>
        );
    });
    await act(async () => {
        context.setWallet({
            address: WALLET,
            chainId: 11155111,
            eip1193Provider: EIP1193_PROVIDER,
        });
        context.setIdentity(IDENTITY);
    });
});

afterEach(async () => {
    await act(async () => root.unmount());
});

test('mint sends only contract arguments after a positive local verification', async () => {
    await act(async () => {
        await context.mintSBT();
    });

    expect(membershipAPI.mintWithProof).toHaveBeenCalledTimes(1);
    expect(membershipAPI.mintWithProof).toHaveBeenCalledWith(
        {
            walletAddress: WALLET,
            membershipContract: MEMBERSHIP_CONTRACT,
            chainId: '11155111',
            pA: PROOF_RESULT.pA,
            pB: PROOF_RESULT.pB,
            pC: PROOF_RESULT.pC,
            nullifierHash: PROOF_RESULT.nullifierHash,
            identityRoot: PROOF_RESULT.identityRoot,
        },
        EIP1193_PROVIDER
    );
    expect(JSON.stringify(membershipAPI.mintWithProof.mock.calls[0][0]))
        .not.toContain(IDENTITY.signature);
    expect(readMembershipDeployment).toHaveBeenCalledWith(
        11155111,
        '11',
        WALLET,
        EIP1193_PROVIDER
    );
    expect(context.step).toBe('success');
});

test.each([false, null])(
    'local verification result %s blocks the relayer request',
    async (verificationResult) => {
        verifyProofLocally.mockResolvedValue(verificationResult);

        await act(async () => {
            await context.mintSBT();
        });

        expect(membershipAPI.mintWithProof).not.toHaveBeenCalled();
        expect(context.zk.status).toBe('error');
    }
);

test('exposes generating while the local prover is pending and does not contact the relayer', async () => {
    let resolveProof;
    generateIdentityProof.mockReturnValue(new Promise((resolve) => {
        resolveProof = resolve;
    }));

    let proofPromise;
    await act(async () => {
        proofPromise = context.generateProof();
        await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(context.zk.status).toBe('generating');
    expect(membershipAPI.mintWithProof).not.toHaveBeenCalled();

    await act(async () => {
        resolveProof(PROOF_RESULT);
        await proofPromise;
    });

    expect(context.zk.status).toBe('ready');
});

test('mint fails closed when the pinned MetaMask provider is missing', async () => {
    await act(async () => {
        context.setWallet({ address: WALLET, chainId: 11155111 });
    });

    await act(async () => {
        await context.mintSBT();
    });

    expect(membershipAPI.mintWithProof).not.toHaveBeenCalled();
    expect(generateIdentityProof).not.toHaveBeenCalled();
    expect(context.error).toMatch(/proveedor MetaMask/i);
});

test('does not ask the issuer for a credential without a civil grant', async () => {
    await act(async () => {
        await context.requestIdentityCredential();
    });

    expect(authAPI.issueIdentityCredential).not.toHaveBeenCalled();
    expect(context.error).toMatch(/grant de identidad/i);
});

test('exchanges an in-memory civil grant for a sanitized signed credential', async () => {
    const rawCredential = {
        ...IDENTITY,
        accidental_pii: 'must-not-remain-in-state',
    };
    const normalizedCredential = {
        signature: IDENTITY.signature,
        identityRoot: '11',
        commitment: '12',
        scope: '13',
        recipient: WALLET,
        recipientSignal: BigInt(WALLET).toString(),
        pathElements: IDENTITY.pathElements,
        pathIndices: IDENTITY.pathIndices,
    };
    readMembershipDeployment.mockResolvedValue({
        scope: '13',
        contractAddress: '0x0000000000000000000000000000000000000002',
        chainId: '11155111',
    });
    verifyIdentityCredential.mockReturnValue(normalizedCredential);
    authAPI.claveUnica.mockResolvedValue({
        data: { ok: true, identity_grant: 'opaque-one-time-grant' },
    });
    authAPI.issueIdentityCredential.mockResolvedValue({
        data: { ok: true, identity: rawCredential },
    });

    await act(async () => {
        context.setRut('11111111-1');
    });
    await act(async () => {
        await context.authenticateClaveUnica(true);
    });
    await act(async () => {
        await context.requestIdentityCredential();
    });

    expect(authAPI.issueIdentityCredential).toHaveBeenCalledWith({
        walletAddress: WALLET,
        identityCommitment: '12',
        membershipScope: '13',
        membershipContract: '0x0000000000000000000000000000000000000002',
        chainId: '11155111',
        identityGrant: 'opaque-one-time-grant',
    });
    expect(context.identity).toEqual({
        ...normalizedCredential,
        chainId: '11155111',
    });
    expect(JSON.stringify(context.identity)).not.toContain('accidental_pii');
    expect(JSON.stringify(context.clave)).not.toContain('opaque-one-time-grant');

    await act(async () => {
        await context.requestIdentityCredential();
    });
    expect(authAPI.issueIdentityCredential).toHaveBeenCalledTimes(1);
});
