import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserProvider, formatEther } from 'ethers';
import { walletAPI } from '../lib/api';
import {
    clearCsrfToken,
    invalidateSession,
} from '../lib/session';
import useWallet, { WalletSessionProvider } from './useWallet';

jest.mock('ethers', () => ({
    BrowserProvider: jest.fn(),
    formatEther: jest.fn(),
}));

jest.mock('../lib/api', () => ({
    walletAPI: {
        session: jest.fn(),
        challenge: jest.fn(),
        verify: jest.fn(),
        logout: jest.fn(),
    },
}));

global.IS_REACT_ACT_ENVIRONMENT = true;

const ADDRESS = '0x70997970C51812dc3A010C7d01b50e0d17dc79C8';
const CSRF = 'c'.repeat(64);
const UNAUTHORIZED = { response: { status: 401 } };

let current;
let container;
let root;
let passiveAccounts;
let requestedAccounts;
let listeners;
let ethereum;
let signer;
let browserProvider;

const Probe = () => {
    current = useWallet();
    return null;
};

const flushUpdates = () => act(async () => {
    for (let index = 0; index < 8; index += 1) {
        await Promise.resolve();
    }
});

const renderProvider = async () => {
    await act(async () => {
        root.render(
            <WalletSessionProvider>
                <Probe />
            </WalletSessionProvider>
        );
    });
    await flushUpdates();
};

beforeEach(() => {
    jest.clearAllMocks();
    clearCsrfToken();
    current = null;
    passiveAccounts = [];
    requestedAccounts = [ADDRESS];
    listeners = {};
    signer = {
        signMessage: jest.fn().mockResolvedValue('0xsig'),
    };
    browserProvider = {
        getSigner: jest.fn().mockResolvedValue(signer),
        getNetwork: jest.fn().mockResolvedValue({ chainId: 11155111n }),
        getBalance: jest.fn().mockResolvedValue(10n ** 18n),
    };
    ethereum = {
        isMetaMask: true,
        request: jest.fn(async ({ method }) => {
            if (method === 'eth_accounts') return passiveAccounts;
            if (method === 'eth_requestAccounts') return requestedAccounts;
            return null;
        }),
        on: jest.fn((event, handler) => {
            listeners[event] = handler;
        }),
        removeListener: jest.fn((event, handler) => {
            if (listeners[event] === handler) delete listeners[event];
        }),
    };
    Object.defineProperty(window, 'ethereum', {
        configurable: true,
        value: ethereum,
    });
    BrowserProvider.mockImplementation(() => browserProvider);
    formatEther.mockReturnValue('1.0');
    walletAPI.logout.mockResolvedValue({ data: { ok: true } });

    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
});

afterEach(async () => {
    if (root) {
        await act(async () => root.unmount());
    }
    container?.remove();
    delete window.ethereum;
    clearCsrfToken();
});

test('restores a matching cookie session without an interactive SIWE prompt', async () => {
    passiveAccounts = [ADDRESS];
    walletAPI.session.mockResolvedValue({
        data: { address: ADDRESS.toLowerCase(), csrf_token: CSRF },
    });

    await renderProvider();

    expect(current.isConnected).toBe(true);
    expect(current.address).toBe(ADDRESS);
    expect(current.chainId).toBe(11155111);
    expect(ethereum.request).toHaveBeenCalledWith({ method: 'eth_accounts' });
    expect(ethereum.request).not.toHaveBeenCalledWith({ method: 'eth_requestAccounts' });
    expect(walletAPI.challenge).not.toHaveBeenCalled();
    expect(walletAPI.verify).not.toHaveBeenCalled();
    expect(signer.signMessage).not.toHaveBeenCalled();
});

test('does not open a signing prompt during passive restore without a session', async () => {
    passiveAccounts = [ADDRESS];
    walletAPI.session.mockRejectedValue(UNAUTHORIZED);

    await renderProvider();

    expect(current.isConnected).toBe(false);
    expect(current.address).toBeNull();
    expect(walletAPI.challenge).not.toHaveBeenCalled();
    expect(walletAPI.verify).not.toHaveBeenCalled();
    expect(signer.signMessage).not.toHaveBeenCalled();
    expect(ethereum.request).not.toHaveBeenCalledWith({ method: 'eth_requestAccounts' });
});

test('performs explicit SIWE, confirms the cookie, and never stores a JWT', async () => {
    walletAPI.session
        .mockRejectedValueOnce(UNAUTHORIZED)
        .mockResolvedValueOnce({
            data: { address: ADDRESS.toLowerCase(), csrf_token: CSRF },
        });
    walletAPI.challenge.mockResolvedValue({
        data: { message: 'Sign this SIWE challenge', nonce: 'nonce-1' },
    });
    walletAPI.verify.mockResolvedValue({
        data: {
            address: ADDRESS.toLowerCase(),
            expires_in: 3600,
            csrf_token: CSRF,
            token: null,
        },
    });
    const getItem = jest.spyOn(Storage.prototype, 'getItem');
    const setItem = jest.spyOn(Storage.prototype, 'setItem');

    await renderProvider();
    let result;
    await act(async () => {
        result = await current.connect();
    });

    expect(result).toEqual(expect.objectContaining({ ok: true, address: ADDRESS }));
    expect(walletAPI.challenge).toHaveBeenCalledWith(ADDRESS);
    expect(signer.signMessage).toHaveBeenCalledWith('Sign this SIWE challenge');
    expect(walletAPI.verify).toHaveBeenCalledWith(ADDRESS, 'nonce-1', '0xsig');
    expect(walletAPI.session).toHaveBeenCalledTimes(2);
    expect(current.isConnected).toBe(true);
    expect(current.eip1193Provider).toBe(ethereum);
    expect(getItem).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
});

test('calls remote logout before clearing local React state', async () => {
    passiveAccounts = [ADDRESS];
    walletAPI.session.mockResolvedValue({
        data: { address: ADDRESS.toLowerCase(), csrf_token: CSRF },
    });
    let resolveLogout;
    walletAPI.logout.mockImplementation(() => new Promise((resolve) => {
        resolveLogout = resolve;
    }));
    await renderProvider();

    let logoutPromise;
    await act(async () => {
        logoutPromise = current.disconnect();
        await Promise.resolve();
    });
    expect(walletAPI.logout).toHaveBeenCalledTimes(1);
    expect(current.isConnected).toBe(true);

    let result;
    await act(async () => {
        resolveLogout({ data: { ok: true } });
        result = await logoutPromise;
    });
    expect(result).toEqual({ ok: true });
    expect(current.isConnected).toBe(false);
    expect(current.address).toBeNull();
    expect(current.provider).toBeNull();
    expect(current.signer).toBeNull();
});

test('clears local state but reports uncertainty when remote logout fails', async () => {
    passiveAccounts = [ADDRESS];
    walletAPI.session.mockResolvedValue({
        data: { address: ADDRESS.toLowerCase(), csrf_token: CSRF },
    });
    walletAPI.logout.mockRejectedValue(new Error('network unavailable'));
    await renderProvider();

    let result;
    await act(async () => {
        result = await current.disconnect();
    });

    expect(result).toEqual({ ok: false, error: 'network unavailable' });
    expect(current.isConnected).toBe(false);
    expect(current.error).toBe('network unavailable');
});

test('invalidates React wallet state when an authenticated API call returns 401', async () => {
    passiveAccounts = [ADDRESS];
    walletAPI.session.mockResolvedValue({
        data: { address: ADDRESS.toLowerCase(), csrf_token: CSRF },
    });
    await renderProvider();
    expect(current.isConnected).toBe(true);

    await act(async () => {
        invalidateSession('unauthorized');
    });

    expect(current.isConnected).toBe(false);
    expect(current.address).toBeNull();
    expect(walletAPI.logout).not.toHaveBeenCalled();
});
