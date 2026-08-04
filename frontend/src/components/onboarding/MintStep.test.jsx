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
    accountAbstraction: { status: 'idle' },
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

test('offers the subsidized authorization without asking for a traditional transaction', async () => {
    await renderStep({ loading: false });

    const button = container.querySelector('button');
    expect(button).not.toBeNull();
    expect(button.textContent).toContain(
        'Autorizar Emisión (Subsidiada por el Estado)'
    );
    expect(button.getAttribute('aria-label')).toBe(
        'AUTORIZAR EMISIÓN (SUBSIDIADA POR EL ESTADO)'
    );
    expect(container.textContent).toMatch(/No es una transacción tradicional/i);
    expect(container.textContent).toMatch(/no necesitarás ETH/i);
    expect(container.textContent).not.toMatch(/patrocina el gas/i);
});

test('prioritizes the real authorization phase over the completed ZK phase', async () => {
    await renderStep({
        zk: { status: 'ready' },
        accountAbstraction: {
            status: 'awaiting_authorization',
            chainName: 'Sepolia',
            safeAddress: '0x2222222222222222222222222222222222222222',
        },
    });

    const panel = container.querySelector('[data-aa-status="awaiting_authorization"]');
    const liveStatus = panel?.querySelector('[role="status"]');
    expect(panel).not.toBeNull();
    expect(liveStatus).not.toBeNull();
    expect(liveStatus.getAttribute('aria-live')).toBe('polite');
    expect(liveStatus.getAttribute('aria-busy')).toBeNull();
    expect(liveStatus.textContent).toMatch(/Autorización personal requerida/i);
    expect(liveStatus.textContent).toMatch(/UserOperation/i);
    expect(panel.textContent).toMatch(/Costo de red cubierto · Sepolia/i);
    expect(container.textContent).not.toContain('PRUEBA ZK VERIFICADA LOCALMENTE');
});

test('keeps a timed-out Bundler operation visible and prevents reauthorization', async () => {
    const userOperationHash = `0x${'ab'.repeat(32)}`;
    await renderStep({
        loading: false,
        accountAbstraction: {
            status: 'bundler_pending',
            userOperationHash,
            timedOut: true,
        },
    });

    const liveStatus = container.querySelector('[data-aa-status="bundler_pending"]');
    expect(liveStatus).not.toBeNull();
    expect(liveStatus.textContent).toMatch(/Confirmación aún pendiente/i);
    expect(liveStatus.textContent).toMatch(/no la reenviamos automáticamente/i);
    expect(liveStatus.textContent).toContain(userOperationHash);
    expect(liveStatus.querySelector('.civic-aa-rail .is-active')).toBeNull();
    expect(liveStatus.querySelector('[aria-current="step"]')).toBeNull();
    expect(container.querySelector('button')).toBeNull();
    expect(container.textContent).not.toMatch(/\d+\s*%/);
});

test('treats an ambiguous Bundler response as non-retryable', async () => {
    const expectedUserOperationHash = `0x${'cd'.repeat(32)}`;
    await renderStep({
        loading: false,
        accountAbstraction: {
            status: 'submission_unknown',
            verificationDelayed: true,
            expectedUserOperationHash,
        },
    });

    const liveStatus = container.querySelector('[data-aa-status="submission_unknown"]');
    expect(liveStatus).not.toBeNull();
    expect(liveStatus.textContent).toMatch(/Recepción por confirmar/i);
    expect(liveStatus.textContent).toMatch(/no pudimos confirmar si el Bundler la recibió/i);
    expect(liveStatus.textContent).toContain(expectedUserOperationHash);
    expect(liveStatus.textContent).toMatch(/Identificador UserOp previsto/i);
    expect(liveStatus.querySelector('.civic-aa-rail .is-active')).toBeNull();
    expect(container.querySelector('button')).toBeNull();
});

test('blocks reauthorization when the Bundler response fails integrity checks', async () => {
    await renderStep({
        loading: false,
        accountAbstraction: {
            status: 'integrity_error',
            expectedUserOperationHash: `0x${'cd'.repeat(32)}`,
        },
    });

    const panel = container.querySelector('[data-aa-status="integrity_error"]');
    expect(panel).not.toBeNull();
    expect(panel.textContent).toMatch(/Verificación de integridad detenida/i);
    expect(panel.textContent).toMatch(/no coincide con la operación autorizada/i);
    expect(container.querySelector('button')).toBeNull();
});
