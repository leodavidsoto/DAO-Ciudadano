import React, { act } from 'react';
import { createRoot } from 'react-dom/client';

jest.mock('react-router-dom', () => ({
    useNavigate: () => jest.fn(),
}));

jest.mock('@/context', () => ({
    useOnboarding: jest.fn(),
}), { virtual: true });

jest.mock('@/components/effects', () => ({
    HolographicCard: () => <div data-testid="holographic-card" />,
}), { virtual: true });

const { useOnboarding } = require('@/context');
const MintStep = require('./MintStep').default;

global.IS_REACT_ACT_ENVIRONMENT = true;

const BASE_CONTEXT = {
    loading: true,
    mint: {},
    wallet: { address: '0x70997970C51812dc3A010C7d01b50e0d17dc79C8' },
    identity: { identityRoot: '11' },
    mintSBT: jest.fn(),
    setStep: jest.fn(),
    zk: { status: 'idle' },
};

let container;
let root;

const renderStep = async (contextOverrides = {}) => {
    useOnboarding.mockReturnValue({
        ...BASE_CONTEXT,
        ...contextOverrides,
    });
    await act(async () => {
        root.render(<MintStep />);
    });
};

beforeEach(() => {
    jest.clearAllMocks();
    container = document.createElement('div');
    root = createRoot(container);
});

afterEach(async () => {
    await act(async () => root.unmount());
});

test.each([
    [
        'generating',
        'GENERANDO PRUEBA ZK LOCALMENTE…',
        'El secreto de identidad y la ruta Merkle permanecen en este navegador.',
    ],
    [
        'ready',
        'PRUEBA ZK VERIFICADA LOCALMENTE…',
        'Preparando la autorización subsidiada que firmarás en MetaMask.',
    ],
])('renders an honest accessible %s state', async (status, title, detail) => {
    await renderStep({ zk: { status } });

    const liveStatus = container.querySelector('[role="status"]');
    expect(liveStatus).not.toBeNull();
    expect(liveStatus.getAttribute('aria-live')).toBe('polite');
    expect(liveStatus.getAttribute('aria-busy')).toBe('true');
    expect(liveStatus.classList.contains('civic-loading')).toBe(true);
    expect(liveStatus.textContent).toContain(title);
    expect(liveStatus.textContent).toContain(detail);
});

test('does not present a fabricated percentage while proof work is indeterminate', async () => {
    await renderStep({ zk: { status: 'generating' } });

    expect(container.querySelector('.mint-progress-ring')).toBeNull();
    expect(container.textContent).not.toMatch(/65\s*%/);
});
