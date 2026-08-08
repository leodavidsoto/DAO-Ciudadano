import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import VotingBallot from './VotingBallot';
import {
    governanceAPI,
    maciAPI,
    normalizeEncryptedBallotReceipt,
} from '../../lib/api';
import {
    createBallotIdempotencyKey,
    createMaciKeypair,
    encryptMaciBallot,
    getMaciPublicKey,
    normalizeMaciVotingConfig,
    verifyMaciCoordinatorOnChain,
} from '../../lib/maci';

jest.mock('../../lib/api', () => ({
    governanceAPI: { getProposals: jest.fn() },
    maciAPI: {
        getStatus: jest.fn(),
        registerKey: jest.fn(),
        getVotingConfig: jest.fn(),
        submitEncryptedBallot: jest.fn(),
    },
    normalizeEncryptedBallotReceipt: jest.fn(),
}));

jest.mock('../../lib/maci', () => ({
    createBallotIdempotencyKey: jest.fn(),
    createMaciKeypair: jest.fn(),
    encryptMaciBallot: jest.fn(),
    getMaciPublicKey: jest.fn(),
    normalizeMaciVotingConfig: jest.fn(),
    verifyMaciCoordinatorOnChain: jest.fn(),
}));

global.IS_REACT_ACT_ENVIRONMENT = true;

const WALLET = '0x1111111111111111111111111111111111111111';
const EIP1193_PROVIDER = { request: jest.fn() };
const READY_STATUS = {
    key_registry: true,
    private_voting: true,
    coordinator_configured: true,
    tally_proof: true,
    poll_bound_messages: true,
    stateful_nonces: true,
    unique_tally_leaves: true,
    process_tally_linked: true,
};
const PROPOSAL = {
    id: 'proposal-1',
    title: 'Presupuesto comunal',
    description: 'Destino del presupuesto participativo',
    status: 'active',
    ends_at: '2099-01-01T00:00:00.000Z',
};
const KEYPAIR = { opaque: 'in-memory-keypair' };
const PUBLIC_KEY = { x: '11', y: '12' };
const CONFIG = {
    protocolVersion: 'maci-v2.5.0',
    proposalId: PROPOSAL.id,
    pollId: 7n,
    stateIndex: 4n,
    nonce: 1n,
    voteWeight: 1n,
    voteOptions: { for: 0n, against: 1n, abstain: 2n },
};
const ENCRYPTED = {
    protocolVersion: 'maci-v2.5.0',
    proposalId: PROPOSAL.id,
    pollId: '7',
    message: { data: Array.from({ length: 10 }, (_, index) => String(index + 20)) },
    encryptionPublicKey: { x: '21', y: '22' },
    coordinatorKeyHash: `0x${'ab'.repeat(32)}`,
};

let container;
let root;

const flush = async () => {
    await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
    });
};

beforeEach(async () => {
    jest.clearAllMocks();
    process.env.REACT_APP_MACI_COORDINATOR_ADDRESS =
        '0x2222222222222222222222222222222222222222';
    process.env.REACT_APP_MACI_TALLY_VERIFIER_ADDRESS =
        '0x3333333333333333333333333333333333333333';
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    governanceAPI.getProposals.mockResolvedValue({ data: [PROPOSAL] });
    maciAPI.getStatus.mockResolvedValue({ data: { private_voting: false } });
    createMaciKeypair.mockResolvedValue(KEYPAIR);
    getMaciPublicKey.mockReturnValue(PUBLIC_KEY);
    maciAPI.registerKey.mockResolvedValue({ data: { ok: true } });
    maciAPI.getVotingConfig.mockResolvedValue({ data: { ok: true } });
    normalizeMaciVotingConfig.mockReturnValue(CONFIG);
    verifyMaciCoordinatorOnChain.mockResolvedValue({
        coordinatorContract: '0x2222222222222222222222222222222222222222',
        tallyVerifier: '0x3333333333333333333333333333333333333333',
    });
    encryptMaciBallot.mockResolvedValue(ENCRYPTED);
    createBallotIdempotencyKey.mockReturnValue('12345678-1234-4234-9234-123456789abc');
    maciAPI.submitEncryptedBallot.mockResolvedValue({
        data: { ok: true, index: 0, message_chain: 'cd'.repeat(32) },
    });
    normalizeEncryptedBallotReceipt.mockReturnValue({
        messageId: `0x${'cd'.repeat(32)}`,
        index: 0,
        duplicate: false,
    });
});

afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
});

test('lists real active proposals but fails closed while MACI is not ready', async () => {
    await act(async () => {
        root.render(<VotingBallot walletAddress={WALLET} chainId={11155111}
                                  eip1193Provider={EIP1193_PROVIDER} />);
    });
    await flush();

    expect(governanceAPI.getProposals).toHaveBeenCalledWith('active');
    expect(maciAPI.getStatus).toHaveBeenCalledTimes(1);
    expect(container.querySelector('select[name="proposal"]')).not.toBeNull();
    const submit = container.querySelector('button[type="submit"]');
    expect(submit.disabled).toBe(true);
    expect(container.textContent).toMatch(/No se enviará un voto alternativo en texto plano/i);
    expect(createMaciKeypair).not.toHaveBeenCalled();
    expect(maciAPI.submitEncryptedBallot).not.toHaveBeenCalled();
});

test('fails closed when the trusted on-chain deployment manifest is missing', async () => {
    delete process.env.REACT_APP_MACI_COORDINATOR_ADDRESS;
    maciAPI.getStatus.mockResolvedValue({
        data: READY_STATUS,
    });
    await act(async () => {
        root.render(<VotingBallot walletAddress={WALLET} chainId={11155111}
                                  eip1193Provider={EIP1193_PROVIDER} />);
    });
    await flush();

    expect(container.textContent).toMatch(/manifiesto on-chain del frontend/i);
    expect(container.querySelector('button[type="submit"]').disabled).toBe(true);
});

test('registers a public voter key and sends only the encrypted MACI envelope', async () => {
    maciAPI.getStatus.mockResolvedValue({
        data: READY_STATUS,
    });
    await act(async () => {
        root.render(<VotingBallot walletAddress={WALLET} chainId={11155111}
                                  eip1193Provider={EIP1193_PROVIDER} />);
    });
    await flush();

    const select = container.querySelector('select[name="proposal"]');
    await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(
            HTMLSelectElement.prototype,
            'value'
        ).set;
        setter.call(select, PROPOSAL.id);
        select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const radio = container.querySelector('input[name="choice"][value="against"]');
    await act(async () => {
        radio.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    const submit = container.querySelector('button[type="submit"]');
    expect(submit.disabled).toBe(false);
    await act(async () => {
        submit.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();

    expect(maciAPI.registerKey).toHaveBeenCalledWith(WALLET, PUBLIC_KEY);
    expect(maciAPI.getVotingConfig).toHaveBeenCalledWith(PROPOSAL.id);
    expect(normalizeMaciVotingConfig).toHaveBeenCalledWith(
        expect.anything(),
        { proposalId: PROPOSAL.id, chainId: 11155111 }
    );
    expect(verifyMaciCoordinatorOnChain).toHaveBeenCalledWith({
        config: CONFIG,
        ethereum: EIP1193_PROVIDER,
    });
    expect(encryptMaciBallot).toHaveBeenCalledWith({
        voterKeypair: KEYPAIR,
        config: CONFIG,
        choice: 'against',
    });
    expect(maciAPI.submitEncryptedBallot).toHaveBeenCalledWith({
        ...ENCRYPTED,
        idempotencyKey: '12345678-1234-4234-9234-123456789abc',
    });
    expect(JSON.stringify(maciAPI.submitEncryptedBallot.mock.calls[0][0]))
        .not.toContain('in-memory-keypair');
    expect(normalizeEncryptedBallotReceipt).toHaveBeenCalledWith(expect.anything());
    expect(container.textContent).toMatch(/Mensaje cifrado recibido/i);
    expect(container.textContent).toContain(`0x${'cd'.repeat(32)}`);
});

test('discards the private key and ambiguous retry after a wallet change', async () => {
    const nextWallet = '0x2222222222222222222222222222222222222222';
    maciAPI.getStatus.mockResolvedValue({
        data: READY_STATUS,
    });
    maciAPI.submitEncryptedBallot
        .mockRejectedValueOnce({ request: {}, message: 'Network Error' })
        .mockResolvedValueOnce({ data: { ok: true, message_id: 'message-wallet-b' } });

    await act(async () => {
        root.render(<VotingBallot walletAddress={WALLET} chainId={11155111}
                                  eip1193Provider={EIP1193_PROVIDER} />);
    });
    await flush();

    const selectAndVote = async () => {
        const select = container.querySelector('select[name="proposal"]');
        await act(async () => {
            Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')
                .set.call(select, PROPOSAL.id);
            select.dispatchEvent(new Event('change', { bubbles: true }));
        });
        await act(async () => {
            container.querySelector('input[name="choice"][value="for"]')
                .dispatchEvent(new MouseEvent('click', { bubbles: true }));
        });
    };

    await selectAndVote();
    await act(async () => {
        container.querySelector('button[type="submit"]')
            .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();

    await act(async () => {
        root.render(<VotingBallot walletAddress={nextWallet} chainId={11155111}
                                  eip1193Provider={EIP1193_PROVIDER} />);
    });
    await flush();
    expect(container.querySelector('select[name="proposal"]').value).toBe('');

    await selectAndVote();
    await act(async () => {
        container.querySelector('button[type="submit"]')
            .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();

    expect(createMaciKeypair).toHaveBeenCalledTimes(2);
    expect(encryptMaciBallot).toHaveBeenCalledTimes(2);
    expect(maciAPI.registerKey).toHaveBeenNthCalledWith(2, nextWallet, PUBLIC_KEY);
    expect(maciAPI.submitEncryptedBallot.mock.calls[1][0])
        .not.toBe(maciAPI.submitEncryptedBallot.mock.calls[0][0]);
    expect(container.textContent).toMatch(/Mensaje cifrado recibido/i);
});

test('regenerates a ballot after a definitive backend rejection', async () => {
    maciAPI.getStatus.mockResolvedValue({
        data: READY_STATUS,
    });
    maciAPI.submitEncryptedBallot
        .mockRejectedValueOnce({ response: { status: 422, data: { detail: 'Poll stale' } } })
        .mockResolvedValueOnce({ data: { ok: true, message_id: 'message-fresh' } });
    await act(async () => {
        root.render(<VotingBallot walletAddress={WALLET} chainId={11155111}
                                  eip1193Provider={EIP1193_PROVIDER} />);
    });
    await flush();

    const select = container.querySelector('select[name="proposal"]');
    await act(async () => {
        Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')
            .set.call(select, PROPOSAL.id);
        select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await act(async () => {
        container.querySelector('input[name="choice"][value="against"]')
            .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    const submit = container.querySelector('button[type="submit"]');
    await act(async () => {
        submit.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();
    await act(async () => {
        submit.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();

    expect(encryptMaciBallot).toHaveBeenCalledTimes(2);
    expect(createBallotIdempotencyKey).toHaveBeenCalledTimes(2);
    expect(maciAPI.submitEncryptedBallot.mock.calls[1][0])
        .not.toBe(maciAPI.submitEncryptedBallot.mock.calls[0][0]);
});

test('retries ambiguous network and 5xx failures with the same ciphertext and idempotency key', async () => {
    maciAPI.getStatus.mockResolvedValue({
        data: READY_STATUS,
    });
    maciAPI.submitEncryptedBallot
        .mockRejectedValueOnce({ request: {}, message: 'Network Error' })
        .mockRejectedValueOnce({ response: { status: 503, data: {} } })
        .mockResolvedValueOnce({
            data: { ok: true, message_id: 'message-1' },
        });
    await act(async () => {
        root.render(<VotingBallot walletAddress={WALLET} chainId={11155111}
                                  eip1193Provider={EIP1193_PROVIDER} />);
    });
    await flush();

    const select = container.querySelector('select[name="proposal"]');
    await act(async () => {
        Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')
            .set.call(select, PROPOSAL.id);
        select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await act(async () => {
        container.querySelector('input[name="choice"][value="for"]')
            .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    const submit = container.querySelector('button[type="submit"]');
    await act(async () => {
        submit.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();
    expect(container.textContent).toMatch(/No fue posible contactar la urna/i);

    await act(async () => {
        submit.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();

    expect(container.textContent).toMatch(/HTTP 503/i);
    await act(async () => {
        submit.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();

    expect(encryptMaciBallot).toHaveBeenCalledTimes(1);
    expect(createBallotIdempotencyKey).toHaveBeenCalledTimes(1);
    expect(maciAPI.registerKey).toHaveBeenCalledTimes(1);
    expect(maciAPI.submitEncryptedBallot).toHaveBeenCalledTimes(3);
    expect(maciAPI.submitEncryptedBallot.mock.calls[1][0])
        .toBe(maciAPI.submitEncryptedBallot.mock.calls[0][0]);
    expect(maciAPI.submitEncryptedBallot.mock.calls[2][0])
        .toBe(maciAPI.submitEncryptedBallot.mock.calls[0][0]);
    expect(container.textContent).toMatch(/Mensaje cifrado recibido/i);
});
