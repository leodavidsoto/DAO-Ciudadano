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
        claveUnicaStatus: jest.fn(),
        claveUnicaAuthorize: jest.fn(),
        claveUnicaCallback: jest.fn(),
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
    window.sessionStorage.clear();
    window.history.replaceState({}, '', '/unete');
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
        EIP1193_PROVIDER,
        expect.any(Function)
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
    expect(context.accountAbstraction).toEqual(expect.objectContaining({
        status: 'confirmed',
        tokenId: 1,
        transactionHash: '0xtx',
    }));
});

test('exposes transport-driven sponsorship and authorization phases', async () => {
    let releaseMint;
    let progressObserved;
    const observed = new Promise((resolve) => {
        progressObserved = resolve;
    });
    membershipAPI.mintWithProof.mockImplementation((proofPayload, provider, onProgress) => {
        onProgress({ status: 'checking_config' });
        onProgress({
            status: 'requesting_sponsorship',
            chainId: 11155111,
            chainName: 'Sepolia',
            safeAddress: '0x2222222222222222222222222222222222222222',
        });
        onProgress({
            status: 'awaiting_authorization',
            safeAddress: '0x2222222222222222222222222222222222222222',
        });
        progressObserved();
        return new Promise((resolve) => {
            releaseMint = resolve;
        });
    });

    let mintPromise;
    await act(async () => {
        mintPromise = context.mintSBT();
        await observed;
    });

    expect(context.loading).toBe(true);
    expect(context.accountAbstraction).toEqual(expect.objectContaining({
        status: 'awaiting_authorization',
        chainName: 'Sepolia',
        safeAddress: '0x2222222222222222222222222222222222222222',
    }));
    await act(async () => {
        await context.mintSBT();
    });
    expect(membershipAPI.mintWithProof).toHaveBeenCalledTimes(1);

    await act(async () => {
        releaseMint({
            data: {
                ok: true,
                token_id: 3,
                tx_hash: `0x${'cd'.repeat(32)}`,
                user_operation_hash: `0x${'ab'.repeat(32)}`,
            },
        });
        await mintPromise;
    });

    expect(context.accountAbstraction).toEqual(expect.objectContaining({
        status: 'confirmed',
        tokenId: 3,
        userOperationHash: `0x${'ab'.repeat(32)}`,
    }));
});

test('keeps an accepted UserOperation pending instead of enabling a resubmit', async () => {
    const userOperationHash = `0x${'ab'.repeat(32)}`;
    membershipAPI.mintWithProof.mockImplementation(async (
        proofPayload,
        provider,
        onProgress
    ) => {
        onProgress({
            status: 'bundler_pending',
            userOperationHash,
            safeAddress: '0x2222222222222222222222222222222222222222',
        });
        const error = new Error('La operación sigue pendiente.');
        error.code = 'USER_OPERATION_PENDING';
        throw error;
    });

    await act(async () => {
        await context.mintSBT();
    });

    expect(context.loading).toBe(false);
    expect(context.error).toBe('');
    expect(context.step).toBe('method');
    expect(context.accountAbstraction).toEqual(expect.objectContaining({
        status: 'bundler_pending',
        userOperationHash,
        timedOut: true,
    }));
    expect(window.sessionStorage.length).toBe(1);
    const storedRecovery = window.sessionStorage.getItem(
        window.sessionStorage.key(0)
    );
    expect(storedRecovery).toContain(userOperationHash);
    expect(storedRecovery).not.toContain(IDENTITY.signature);

    await act(async () => root.unmount());
    context = null;
    root = createRoot(container);
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
    });

    expect(context.accountAbstraction).toEqual(expect.objectContaining({
        status: 'bundler_pending',
        userOperationHash,
        timedOut: true,
    }));
});

test('blocks reauthorization when the Bundler response is ambiguous', async () => {
    const expectedUserOperationHash = `0x${'cd'.repeat(32)}`;
    membershipAPI.mintWithProof.mockImplementation(async (
        proofPayload,
        provider,
        onProgress
    ) => {
        onProgress({
            status: 'submitting_user_operation',
            expectedUserOperationHash,
        });
        throw new Error('Network response lost');
    });

    await act(async () => {
        await context.mintSBT();
    });

    expect(context.loading).toBe(false);
    expect(context.error).toBe('');
    expect(context.accountAbstraction).toEqual(expect.objectContaining({
        status: 'submission_unknown',
        verificationDelayed: true,
        expectedUserOperationHash,
    }));
});

test('surfaces an integrity failure without reopening authorization', async () => {
    const expectedUserOperationHash = `0x${'cd'.repeat(32)}`;
    membershipAPI.mintWithProof.mockImplementation(async (
        proofPayload,
        provider,
        onProgress
    ) => {
        onProgress({
            status: 'submitting_user_operation',
            expectedUserOperationHash,
        });
        const error = new Error('El Bundler devolvió un hash distinto.');
        error.code = 'USER_OPERATION_INTEGRITY_ERROR';
        throw error;
    });

    await act(async () => {
        await context.mintSBT();
    });

    expect(context.loading).toBe(false);
    expect(context.error).toMatch(/hash distinto/i);
    expect(context.accountAbstraction).toEqual(expect.objectContaining({
        status: 'integrity_error',
        expectedUserOperationHash,
        errorCode: 'USER_OPERATION_INTEGRITY_ERROR',
    }));
});

test('treats an explicit submit 4xx as rejected instead of ambiguously sent', async () => {
    membershipAPI.mintWithProof.mockImplementation(async (
        proofPayload,
        provider,
        onProgress
    ) => {
        onProgress({
            status: 'submitting_user_operation',
            expectedUserOperationHash: `0x${'cd'.repeat(32)}`,
        });
        const error = new Error('Request rejected');
        error.response = {
            status: 422,
            data: { detail: 'El patrocinio rechazó la operación.' },
        };
        throw error;
    });

    await act(async () => {
        await context.mintSBT();
    });

    expect(context.accountAbstraction.status).toBe('error');
    expect(context.error).toMatch(/patrocinio rechazó/i);
    expect(window.sessionStorage.length).toBe(0);
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
    authAPI.claveUnicaStatus.mockResolvedValue({
        data: {
            available: true,
            protocol_version: 'clave-unica-oidc-pkce-v1',
            pkce_method: 'S256',
            browser_bound: true,
            credential_exchange_browser_bound: true,
            callback_idempotent: true,
            grant_single_use: true,
            redirect_transport: 'frontend-post',
            grant_ttl_seconds: 300,
        },
    });
    authAPI.claveUnicaCallback.mockResolvedValue({
        data: {
            ok: true,
            identity_grant: 'opaque-one-time-grant',
            identity_grant_expires_in: 300,
            assurance_level: 'CLAVE_UNICA',
            name: 'Ciudadana',
        },
    });
    authAPI.issueIdentityCredential.mockResolvedValue({
        data: { ok: true, identity: rawCredential },
    });

    const state = 'state_1234567890abcdefghijklmnopqrstuvwxyz';
    window.sessionStorage.setItem(
        'dao-ciudadano:clave-unica:oidc-attempt:v1',
        JSON.stringify({
            version: 1,
            state,
            expiresAt: Date.now() + 60_000,
        })
    );
    window.history.replaceState(
        {},
        '',
        `/unete/clave-unica/callback?code=one-time-code&state=${state}`
    );
    await act(async () => {
        await context.completeClaveUnicaCallback();
    });
    expect(window.location.search).toBe('');
    expect(context.claveUnicaFlow.status).toBe('authenticated');
    expect(context.step).toBe('consent');
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

test('refuses to exchange an OIDC code when browser binding is not published', async () => {
    const state = 'state_1234567890abcdefghijklmnopqrstuvwxyz';
    window.sessionStorage.setItem(
        'dao-ciudadano:clave-unica:oidc-attempt:v1',
        JSON.stringify({
            version: 1,
            state,
            expiresAt: Date.now() + 60_000,
        })
    );
    window.history.replaceState(
        {},
        '',
        `/unete/clave-unica/callback?code=one-time-code&state=${state}`
    );
    authAPI.claveUnicaStatus.mockResolvedValue({
        data: {
            available: true,
            protocol_version: 'clave-unica-oidc-pkce-v1',
            pkce_method: 'S256',
            browser_bound: false,
            credential_exchange_browser_bound: true,
            callback_idempotent: true,
            grant_single_use: true,
            redirect_transport: 'frontend-post',
            grant_ttl_seconds: 300,
        },
    });

    await act(async () => {
        await context.completeClaveUnicaCallback();
    });

    expect(authAPI.claveUnicaCallback).not.toHaveBeenCalled();
    expect(context.claveUnicaFlow.status).toBe('error');
    expect(context.error).toMatch(/garantías de seguridad/i);
    expect(window.location.search).toBe('');
});

test('never promotes a grant returned by the NFC demonstration', async () => {
    authAPI.nfc.mockResolvedValue({
        data: { ok: true, identity_grant: 'must-not-be-trusted' },
    });

    await act(async () => {
        await context.authenticateNFC();
    });
    await act(async () => {
        await context.requestIdentityCredential();
    });

    expect(JSON.stringify(context.nfc)).not.toContain('must-not-be-trusted');
    expect(authAPI.issueIdentityCredential).not.toHaveBeenCalled();
    expect(context.error).toMatch(/grant de identidad/i);
});

test('never promotes a grant returned by the liveness demonstration', async () => {
    authAPI.liveness.mockResolvedValue({
        data: { ok: true, identity_grant: 'must-not-be-trusted' },
    });
    const file = new File(['image'], 'selfie.jpg', { type: 'image/jpeg' });

    await act(async () => {
        context.handleFileSelect({ target: { files: [file] } });
    });
    await act(async () => {
        await context.analyzeLiveness(true);
    });
    await act(async () => {
        await context.requestIdentityCredential();
    });

    expect(JSON.stringify(context.selfie)).not.toContain('must-not-be-trusted');
    expect(authAPI.issueIdentityCredential).not.toHaveBeenCalled();
    expect(context.error).toMatch(/grant de identidad/i);
});

test('clears a prior civil grant when the citizen selects a demo method', async () => {
    const state = 'state_1234567890abcdefghijklmnopqrstuvwxyz';
    window.sessionStorage.setItem(
        'dao-ciudadano:clave-unica:oidc-attempt:v1',
        JSON.stringify({
            version: 1,
            state,
            expiresAt: Date.now() + 60_000,
        })
    );
    window.history.replaceState(
        {},
        '',
        `/unete/clave-unica/callback?code=one-time-code&state=${state}`
    );
    authAPI.claveUnicaStatus.mockResolvedValue({
        data: {
            available: true,
            protocol_version: 'clave-unica-oidc-pkce-v1',
            pkce_method: 'S256',
            browser_bound: true,
            credential_exchange_browser_bound: true,
            callback_idempotent: true,
            grant_single_use: true,
            redirect_transport: 'frontend-post',
            grant_ttl_seconds: 300,
        },
    });
    authAPI.claveUnicaCallback.mockResolvedValue({
        data: {
            ok: true,
            identity_grant: 'opaque-one-time-grant',
            identity_grant_expires_in: 300,
            assurance_level: 'CLAVE_UNICA',
            name: 'Ciudadana',
        },
    });

    await act(async () => {
        await context.completeClaveUnicaCallback();
    });
    await act(async () => {
        context.selectIdentityMethod('nfc');
        await context.requestIdentityCredential();
    });

    expect(context.step).toBe('nfc');
    expect(context.clave).toEqual({});
    expect(authAPI.issueIdentityCredential).not.toHaveBeenCalled();
    expect(context.error).toMatch(/grant de identidad/i);
});
