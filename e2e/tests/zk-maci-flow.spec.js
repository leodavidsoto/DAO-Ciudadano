import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { getAddress, verifyTypedData } from 'ethers';
import { groth16 } from 'snarkjs';
import {
    E2E_FIXTURE,
    installBackendFixture,
    installEip1193Fixture,
} from './support/e2e-fixture.js';

const testDirectory = dirname(fileURLToPath(import.meta.url));
const verificationKeyPath = resolve(
    testDirectory,
    '../../circuits/build/verification_key.json'
);

const verifyCapturedZkProof = async (mintRequest) => {
    const verificationKey = JSON.parse(await readFile(verificationKeyPath, 'utf8'));
    const { pA, pB, pC, nullifier_hash: nullifierHash, identity_root: identityRoot } =
        mintRequest.mint;
    const snarkProof = {
        protocol: 'groth16',
        curve: 'bn128',
        pi_a: [...pA, '1'],
        // Solidity calldata reverses each Fq2 pair relative to snarkjs JSON.
        pi_b: [
            [pB[0][1], pB[0][0]],
            [pB[1][1], pB[1][0]],
            ['1', '0'],
        ],
        pi_c: [...pC, '1'],
    };
    const publicSignals = [
        identityRoot,
        BigInt(nullifierHash).toString(),
        BigInt(E2E_FIXTURE.userAddress).toString(),
        E2E_FIXTURE.membershipScope,
    ];
    return groth16.verify(verificationKey, publicSignals, snarkProof);
};

test('cumple el contrato OIDC fixture, emite ZK subsidiado y mantiene MACI cerrado', async ({ page, context }) => {
    test.slow();
    const browserErrors = [];
    page.on('pageerror', (error) => browserErrors.push(error.message));

    await installEip1193Fixture(page);
    const backend = await installBackendFixture(page);

    await page.goto('/unete');
    await page.getByRole('button', { name: 'INGRESAR CON CLAVEÚNICA', exact: true }).click();
    await page.getByRole('button', { name: 'CONTINUAR A CLAVEÚNICA', exact: true }).click();

    await expect(
        page.getByRole('heading', { name: 'Estado de la acreditación' })
    ).toBeVisible();
    await page.getByRole('button', { name: 'CONTINUAR A LA WALLET' }).click();
    // Passive restoration must never open an unsolicited SIWE signature. A
    // clean browser session requires an explicit citizen action.
    await page.getByRole('button', { name: 'CONECTAR METAMASK', exact: true }).click();
    await expect(page.getByText('WALLET CONECTADA')).toBeVisible();
    await expect(page.getByText('Verificando membresía existente...')).toBeHidden();
    await page.getByRole('button', { name: 'CONTINUAR', exact: true }).click();

    await expect(
        page.getByRole('heading', { name: 'CREACIÓN DE CREDENCIAL CIUDADANA' })
    ).toBeVisible({ timeout: 60_000 });

    // Replace the ambient provider after the SIWE-bound instance has been
    // stored in onboarding state. Any regression to globalThis.ethereum will
    // hit this trap; the non-custodial flow must keep using the pinned object.
    await page.evaluate(() => {
        window.__E2E_REPLACEMENT_RPC_LOG__ = [];
        window.ethereum = {
            isMetaMask: true,
            async request(payload) {
                window.__E2E_REPLACEMENT_RPC_LOG__.push(payload);
                if (['personal_sign', 'eth_sign', 'eth_signTypedData_v4']
                    .includes(payload.method)) {
                    throw new Error('The mint asked the unpinned global provider to sign');
                }
                // Public deployment reads may still discover the ambient RPC.
                // Forward those so this trap isolates the custody boundary:
                // authorization must stay on the SIWE-pinned provider.
                return window.__E2E_PINNED_PROVIDER__.request(payload);
            },
        };
    });
    await page.getByRole('button', {
        name: 'AUTORIZAR EMISIÓN (SUBSIDIADA POR EL ESTADO)',
        exact: true,
    }).click();
    await expect(
        page.getByRole('heading', { name: 'SBT CONFIRMADO EN BLOCKCHAIN' })
    ).toBeVisible({ timeout: 120_000 });
    await expect(page.getByText(`#${E2E_FIXTURE.tokenId}`, { exact: true }).first()).toBeVisible();

    const replacementRpcLog = await page.evaluate(() => {
        const calls = window.__E2E_REPLACEMENT_RPC_LOG__ || [];
        window.ethereum = window.__E2E_PINNED_PROVIDER__;
        return calls;
    });
    // Zero calls is the strongest valid outcome: all reads and authorization
    // stayed on the SIWE-pinned provider. If the replacement is ever touched,
    // it must still never receive a signing method.
    expect(replacementRpcLog.filter(({ method }) =>
        ['personal_sign', 'eth_sign', 'eth_signTypedData_v4'].includes(method)
    )).toEqual([]);

    expect(backend.identityCredentialRequests).toHaveLength(1);
    expect(backend.oidcCallbackRequests).toHaveLength(1);
    expect(backend.preparedMintRequests).toHaveLength(1);
    expect(backend.submittedMintRequests).toHaveLength(1);
    expect(backend.siweChallenges).toHaveLength(1);
    expect(backend.siweVerifications).toHaveLength(1);
    expect(backend.siweVerifications[0]).toMatchObject({
        recoveredAddress: E2E_FIXTURE.userAddress,
        body: {
            address: E2E_FIXTURE.userAddress,
            session_transport: 'cookie',
        },
    });
    expect(backend.sessionReads.some(({ cookie }) =>
        cookie?.includes('dao_session=e2e-http-only-session')
    )).toBe(true);
    expect(await page.evaluate(() => ({
        token: localStorage.getItem('auth_token'),
        address: localStorage.getItem('auth_address'),
    }))).toEqual({ token: null, address: null });
    expect((await context.cookies()).find(({ name }) => name === 'dao_session'))
        .toMatchObject({ httpOnly: true, sameSite: 'Lax' });
    const credentialRequest = backend.identityCredentialRequests[0];
    expect(credentialRequest).toMatchObject({
        wallet_address: E2E_FIXTURE.userAddress,
        membership_scope: E2E_FIXTURE.membershipScope,
        membership_contract: E2E_FIXTURE.membershipContract,
        identity_grant: E2E_FIXTURE.identityGrant,
    });
    expect(Object.keys(credentialRequest).sort()).toEqual([
        'chain_id',
        'identity_commitment',
        'identity_grant',
        'membership_contract',
        'membership_scope',
        'wallet_address',
    ]);
    const preparedMint = backend.preparedMintRequests[0];
    expect(preparedMint.mint.wallet_address).toBe(E2E_FIXTURE.userAddress);
    expect(preparedMint.mint.pA).toHaveLength(2);
    expect(preparedMint.mint.pB).toHaveLength(2);
    expect(preparedMint.mint.pC).toHaveLength(2);
    expect(Object.keys(preparedMint.mint).sort()).toEqual([
        'identity_root',
        'nullifier_hash',
        'pA',
        'pB',
        'pC',
        'wallet_address',
    ]);
    expect(await verifyCapturedZkProof(preparedMint)).toBe(true);
    expect(JSON.stringify(preparedMint)).not.toContain(E2E_FIXTURE.identityGrant);
    expect(preparedMint).not.toHaveProperty('identity');
    expect(backend.submittedMintRequests[0].user_operation.signature)
        .not.toBe(preparedMint.user_operation.signature);

    const rpcLog = await page.evaluate(() => window.__E2E_RPC_LOG__ || []);
    const safeSignatureCalls = rpcLog.filter(
        ({ method }) => method === 'eth_signTypedData_v4'
    );
    expect(safeSignatureCalls).toHaveLength(1);
    const safeSignatureCall = safeSignatureCalls[0];
    expect(getAddress(safeSignatureCall.params[0])).toBe(E2E_FIXTURE.userAddress);
    const safeTypedData = typeof safeSignatureCall.params[1] === 'string'
        ? JSON.parse(safeSignatureCall.params[1])
        : safeSignatureCall.params[1];
    expect(safeTypedData.primaryType).toBe('SafeOp');
    expect(getAddress(safeTypedData.domain.verifyingContract))
        .toBe(E2E_FIXTURE.safe4337Module);
    expect(Number(safeTypedData.domain.chainId)).toBe(E2E_FIXTURE.chainId);
    expect(getAddress(safeTypedData.message.entryPoint))
        .toBe(E2E_FIXTURE.entryPoint);
    expect(getAddress(safeTypedData.message.safe))
        .toBe(getAddress(backend.submittedMintRequests[0].safe_address));
    const safeTypes = { ...safeTypedData.types };
    delete safeTypes.EIP712Domain;
    expect(getAddress(verifyTypedData(
        safeTypedData.domain,
        safeTypes,
        safeTypedData.message,
        safeSignatureCall.result
    ))).toBe(E2E_FIXTURE.userAddress);

    await page.goto('/dashboard/propuestas');
    await expect(page.getByText('Canal no disponible')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Blindar y enviar papeleta' }))
        .toBeDisabled();
    expect(backend.registeredMaciKeys).toHaveLength(0);
    expect(backend.encryptedBallots).toHaveLength(0);

    await page.getByRole('button', { name: 'Cerrar sesión', exact: true }).click();
    await expect(
        page.getByRole('button', { name: 'Conectar billetera', exact: true })
    ).toBeVisible();
    expect(backend.logouts).toHaveLength(1);
    expect(backend.logouts[0].cookie)
        .toContain('dao_session=e2e-http-only-session');
    expect(backend.logouts[0].csrf).toMatch(/^c{64}$/);
    expect((await context.cookies()).find(({ name }) => name === 'dao_session'))
        .toBeUndefined();
    expect(await page.evaluate(() => ({
        token: localStorage.getItem('auth_token'),
        address: localStorage.getItem('auth_address'),
    }))).toEqual({ token: null, address: null });
    expect(browserErrors).toEqual([]);
});
