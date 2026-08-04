import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import ElectionsList from './ElectionsList';
import { electionsAPI } from '@/lib/api';

jest.mock('@/lib/api', () => ({
    electionsAPI: {
        list: jest.fn(),
        listCandidacies: jest.fn(),
        results: jest.fn(),
        create: jest.fn(),
        runForOffice: jest.fn(),
    },
}));

global.IS_REACT_ACT_ENVIRONMENT = true;

const WALLET = '0x1111111111111111111111111111111111111111';
const CANDIDATE = '0x2222222222222222222222222222222222222222';
const ELECTION = {
    id: 'election-1',
    title: 'Consejo ciudadano',
    description: 'Elección de representantes del piloto',
    seats: 1,
    term_months: 12,
    status: 'voting',
    candidacy_count: 1,
    nominations_end_at: '2026-08-01T00:00:00.000Z',
    voting_end_at: '2099-08-10T00:00:00.000Z',
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

beforeEach(() => {
    jest.clearAllMocks();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    electionsAPI.list.mockResolvedValue({ data: [ELECTION] });
    electionsAPI.listCandidacies.mockResolvedValue({
        data: [{
            id: 'candidacy-1',
            candidate_address: CANDIDATE,
            statement: 'Programa ciudadano verificable',
        }],
    });
});

afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
});

test('blocks the legacy plaintext election vote until an election MACI poll exists', async () => {
    await act(async () => {
        root.render(<ElectionsList walletAddress={WALLET} />);
    });
    await flush();

    const electionButton = Array.from(container.querySelectorAll('button'))
        .find((button) => button.textContent.includes(ELECTION.title));
    expect(electionButton).toBeDefined();
    await act(async () => {
        electionButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();

    expect(electionsAPI.listCandidacies).toHaveBeenCalledWith(ELECTION.id);
    expect(container.textContent).toMatch(/Urna MACI obligatoria/i);
    expect(container.textContent).toMatch(/no enviará tu wallet, candidato ni firma EIP-712/i);
    expect(container.textContent).toMatch(/Urna privada pendiente/i);
    expect(Array.from(container.querySelectorAll('button'))
        .some((button) => /^Votar$/i.test(button.textContent.trim()))).toBe(false);
    expect(electionsAPI.vote).toBeUndefined();
});
