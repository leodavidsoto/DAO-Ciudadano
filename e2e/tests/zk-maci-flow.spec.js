import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Keypair, Message, PCommand, PubKey } from 'maci-domainobjs';
import { groth16 } from 'snarkjs';
import {
    E2E_FIXTURE,
    getCoordinatorKeypair,
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

const decryptCapturedMaciBallot = ({ encryptedBallot, registeredKey }) => {
    const coordinator = getCoordinatorKeypair();
    const ephemeralPublicKey = new PubKey([
        BigInt(encryptedBallot.encryption_public_key.x),
        BigInt(encryptedBallot.encryption_public_key.y),
    ]);
    const sharedKey = Keypair.genEcdhSharedKey(
        coordinator.privKey,
        ephemeralPublicKey
    );
    const message = new Message(encryptedBallot.message.data.map(BigInt));
    const decrypted = PCommand.decrypt(message, sharedKey);
    const voterPublicKey = new PubKey([
        BigInt(registeredKey.public_key.x),
        BigInt(registeredKey.public_key.y),
    ]);
    return { ...decrypted, voterPublicKey };
};

test('simula emisión ZK subsidiada y publica una papeleta MACI cifrada', async ({ page, context }) => {
    test.slow();
    const browserErrors = [];
    page.on('pageerror', (error) => browserErrors.push(error.message));

    await installEip1193Fixture(page);
    const backend = await installBackendFixture(page);

    await page.goto('/unete');
    await page.getByRole('button', { name: 'PROBAR DEMOSTRACIÓN', exact: true }).click();
    await page.getByRole('checkbox').check();
    await page.locator('input[type="file"]').setInputFiles({
        name: 'imagen-fixture-e2e.png',
        mimeType: 'image/png',
        buffer: Buffer.from('fixture-e2e-no-biometrico', 'utf8'),
    });
    await page.getByRole('button', { name: 'EJECUTAR SIMULACIÓN', exact: true }).click();

    await expect(
        page.getByRole('heading', { name: 'RESUMEN Y LIMITACIONES DEL PILOTO' })
    ).toBeVisible();
    await page.getByRole('button', { name: 'CONTINUAR A LA WALLET' }).click();
    await expect(page.getByText('WALLET CONECTADA')).toBeVisible();
    await expect(page.getByText('Verificando membresía existente...')).toBeHidden();
    await page.getByRole('button', { name: 'CONTINUAR', exact: true }).click();

    await expect(
        page.getByRole('heading', { name: 'CREACIÓN DE CREDENCIAL CIUDADANA' })
    ).toBeVisible({ timeout: 60_000 });
    await page.getByRole('button', { name: 'CREAR CREDENCIAL', exact: true }).click();
    await expect(
        page.getByRole('heading', { name: 'SBT CONFIRMADO EN BLOCKCHAIN' })
    ).toBeVisible({ timeout: 120_000 });
    await expect(page.getByText(`#${E2E_FIXTURE.tokenId}`, { exact: true }).first()).toBeVisible();

    expect(backend.identityCredentialRequests).toHaveLength(1);
    expect(backend.preparedMintRequests).toHaveLength(1);
    expect(backend.submittedMintRequests).toHaveLength(1);
    expect(backend.siweChallenges).toHaveLength(1);
    expect(backend.siweVerifications).toHaveLength(1);
    expect(backend.siweVerifications[0]).toMatchObject({
        recoveredAddress: E2E_FIXTURE.userAddress,
        body: { address: E2E_FIXTURE.userAddress },
    });
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

    await page.goto('/dashboard/propuestas');
    await expect(page.getByText('Privacidad activa')).toBeVisible();
    await page.getByLabel('1. Propuesta').selectOption(E2E_FIXTURE.proposalId);
    await page.getByRole('radio', { name: /A favor/ }).check();

    // A caught crypto exception is rendered by the component and would
    // otherwise lose its stack. Keep the first browser frame so a regression
    // points to its real module instead of timing out on the success text.
    const cryptoExceptions = [];
    const cdp = await context.newCDPSession(page);
    await cdp.send('Debugger.enable');
    await cdp.send('Debugger.setPauseOnExceptions', { state: 'all' });
    cdp.on('Debugger.paused', async (event) => {
        if (event.reason === 'exception' || event.reason === 'promiseRejection') {
            const capturedException = {
                reason: event.reason,
                description: event.data?.description || '',
                value: event.data?.value,
                frames: event.callFrames.slice(0, 12).map((frame) => ({
                    functionName: frame.functionName,
                    url: frame.url,
                    line: frame.location.lineNumber + 1,
                    column: frame.location.columnNumber + 1,
                })),
            };
            if (
                /Cannot mix BigInt/i.test(capturedException.description) &&
                event.callFrames[0]
            ) {
                capturedException.runtime = {};
                for (const expression of [
                    'typeof baby_jubjub_1',
                    'String(baby_jubjub_1)',
                    'Object.prototype.toString.call(baby_jubjub_1)',
                    'baby_jubjub_1?.constructor?.name',
                    'typeof baby_jubjub_1.r',
                    'String(baby_jubjub_1.r)',
                    'Object.prototype.toString.call(baby_jubjub_1.r)',
                    'typeof baby_jubjub_1.default',
                    'String(baby_jubjub_1.default)',
                    'Object.keys(baby_jubjub_1).sort().join(",")',
                ]) {
                    const evaluation = await cdp.send(
                        'Debugger.evaluateOnCallFrame',
                        {
                            callFrameId: event.callFrames[0].callFrameId,
                            expression,
                            returnByValue: true,
                            silent: true,
                        }
                    ).catch((error) => ({
                        exceptionDetails: { text: error.message },
                    }));
                    capturedException.runtime[expression] =
                        evaluation.result?.value ??
                        evaluation.result?.description ??
                        evaluation.exceptionDetails?.text ??
                        'unavailable';
                }
            }
            cryptoExceptions.push(capturedException);
            if (cryptoExceptions.length > 30) cryptoExceptions.shift();
        }
        await cdp.send('Debugger.resume').catch(() => {});
    });
    await page.getByRole('button', { name: 'Cifrar y enviar papeleta' }).click();
    const success = page.getByText(/Mensaje cifrado recibido por la urna/);
    const ballotError = page.locator('.civic-ballot [role="alert"]');
    await Promise.race([
        success.waitFor({ state: 'visible', timeout: 120_000 }),
        ballotError.waitFor({ state: 'visible', timeout: 120_000 }),
    ]);
    if (await ballotError.isVisible()) {
        const message = await ballotError.textContent();
        const rpcLog = await page.evaluate(() => window.__E2E_RPC_LOG__ || []);
        throw new Error(
            `MACI browser flow failed: ${message}\n` +
            `Backend stage: ${JSON.stringify({
                registeredKeys: backend.registeredMaciKeys.length,
                encryptedBallots: backend.encryptedBallots.length,
            })}\n` +
            `Last RPC calls: ${JSON.stringify(rpcLog.slice(-12), null, 2)}\n` +
            `Captured exceptions: ${JSON.stringify(cryptoExceptions, null, 2)}`
        );
    }
    await expect(success).toBeVisible();
    await cdp.detach();

    expect(backend.registeredMaciKeys).toHaveLength(1);
    expect(backend.registeredMaciKeys[0].authorization).toMatch(/^Bearer /);
    expect(backend.registeredMaciKeys[0].body.wallet_address)
        .toBe(E2E_FIXTURE.userAddress);
    expect(backend.encryptedBallots).toHaveLength(1);
    const submittedBallot = backend.encryptedBallots[0];
    expect(submittedBallot.authorization).toBeNull();
    expect(submittedBallot.body).toMatchObject({
        protocol_version: 'maci-v2.5.0',
        proposal_id: E2E_FIXTURE.proposalId,
        poll_id: E2E_FIXTURE.pollId,
        coordinator_key_hash: E2E_FIXTURE.coordinatorKeyHash,
    });
    expect(submittedBallot.body.message.data).toHaveLength(10);
    expect(submittedBallot.body).not.toHaveProperty('choice');
    expect(submittedBallot.body).not.toHaveProperty('wallet_address');
    expect(submittedBallot.body).not.toHaveProperty('private_key');
    const { command, signature, voterPublicKey } = decryptCapturedMaciBallot({
        encryptedBallot: submittedBallot.body,
        registeredKey: backend.registeredMaciKeys[0].body,
    });
    expect(command.pollId).toBe(BigInt(E2E_FIXTURE.pollId));
    expect(command.stateIndex).toBe(4n);
    expect(command.voteOptionIndex).toBe(0n);
    expect(command.newVoteWeight).toBe(1n);
    expect(command.newPubKey.equals(voterPublicKey)).toBe(true);
    expect(command.verifySignature(signature, voterPublicKey)).toBe(true);
    expect(browserErrors).toEqual([]);
});
