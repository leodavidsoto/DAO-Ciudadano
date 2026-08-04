jest.mock('../../services/apiService', () => ({
    __esModule: true,
    default: {
        walletChallenge: jest.fn(),
        walletVerify: jest.fn(),
        setToken: jest.fn(),
        getMembershipStatus: jest.fn(),
        mintSBT: jest.fn(),
    },
}));

jest.mock('../../services/walletService', () => ({
    __esModule: true,
    default: {
        hasWallet: jest.fn(),
        loadWallet: jest.fn(),
        signMessage: jest.fn(),
        generate: jest.fn(),
        saveWallet: jest.fn(),
    },
}));

import React from 'react';
import ReactTestRenderer from 'react-test-renderer';
import apiService from '../../services/apiService';
import walletService from '../../services/walletService';
import WalletScreen from '../WalletScreen';

const mockedApi = apiService as jest.Mocked<typeof apiService>;
const mockedWallet = walletService as jest.Mocked<typeof walletService>;

function renderedText(renderer: ReactTestRenderer.ReactTestRenderer): string {
    const collect = (node: unknown): string => {
        if (typeof node === 'string' || typeof node === 'number') return String(node);
        if (Array.isArray(node)) return node.map(collect).join(' ');
        if (typeof node !== 'object' || node === null || !('children' in node)) return '';
        return collect((node as { children?: unknown }).children);
    };
    return collect(renderer.toJSON());
}

describe('WalletScreen issuance gate', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        mockedWallet.hasWallet.mockResolvedValue(true);
        mockedWallet.loadWallet.mockResolvedValue({
            address: '0x1111111111111111111111111111111111111111',
        } as never);
        mockedWallet.signMessage.mockResolvedValue('0xsigned');
        mockedApi.walletChallenge.mockResolvedValue({ message: 'SIWE challenge', nonce: 'nonce' });
        mockedApi.walletVerify.mockResolvedValue({
            token: 'session-token',
            address: '0x1111111111111111111111111111111111111111',
            expires_in: 300,
        });
        mockedApi.getMembershipStatus.mockResolvedValue({ found: false });
    });

    it('does not request minting when the signed-in wallet has no membership', async () => {
        let renderer!: ReactTestRenderer.ReactTestRenderer;
        await ReactTestRenderer.act(async () => {
            renderer = ReactTestRenderer.create(
                <WalletScreen navigation={{ navigate: jest.fn() }} />,
            );
            await new Promise(resolve => setTimeout(resolve, 0));
        });

        expect(mockedApi.getMembershipStatus).toHaveBeenCalledWith(
            '0x1111111111111111111111111111111111111111',
        );
        expect(mockedApi.mintSBT).not.toHaveBeenCalled();
        expect(renderedText(renderer)).toContain('EMISIÓN BLOQUEADA');
        expect(renderedText(renderer)).toContain('atestación');
    });
});
