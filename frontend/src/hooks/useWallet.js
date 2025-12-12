/**
 * useWallet Hook - Real MetaMask/Web3 integration
 * Connects to Ethereum wallets and manages Web3 state
 */
import { useState, useCallback, useEffect } from 'react';
import { BrowserProvider, formatEther } from 'ethers';

// Supported networks
const NETWORKS = {
    1: { name: 'Ethereum Mainnet', symbol: 'ETH' },
    11155111: { name: 'Sepolia Testnet', symbol: 'SepoliaETH' },
    137: { name: 'Polygon', symbol: 'MATIC' },
    80001: { name: 'Mumbai Testnet', symbol: 'MATIC' },
    80002: { name: 'Amoy Testnet', symbol: 'MATIC' },
};

const useWallet = () => {
    const [address, setAddress] = useState(null);
    const [balance, setBalance] = useState(null);
    const [chainId, setChainId] = useState(null);
    const [provider, setProvider] = useState(null);
    const [signer, setSigner] = useState(null);
    const [isConnecting, setIsConnecting] = useState(false);
    const [error, setError] = useState(null);
    const [isMetaMaskInstalled, setIsMetaMaskInstalled] = useState(false);

    // Check if MetaMask is installed (with better detection)
    useEffect(() => {
        const checkMetaMask = () => {
            if (typeof window !== 'undefined') {
                // Check for ethereum provider
                const hasEthereum = typeof window.ethereum !== 'undefined';
                // Check if it's actually MetaMask (not another provider)
                const isMetaMask = hasEthereum && window.ethereum.isMetaMask;
                setIsMetaMaskInstalled(hasEthereum && isMetaMask);
            }
        };

        // Check immediately
        checkMetaMask();

        // Also check after a short delay (MetaMask can take time to inject)
        const timeout = setTimeout(checkMetaMask, 500);

        // Listen for ethereum provider injection
        if (typeof window !== 'undefined') {
            window.addEventListener('ethereum#initialized', checkMetaMask);
        }

        return () => {
            clearTimeout(timeout);
            if (typeof window !== 'undefined') {
                window.removeEventListener('ethereum#initialized', checkMetaMask);
            }
        };
    }, []);

    // Get network info
    const getNetworkInfo = (id) => NETWORKS[id] || { name: `Chain ${id}`, symbol: 'ETH' };

    // Connect wallet
    const connect = useCallback(async () => {
        // Re-check MetaMask installation
        const hasMetaMask = typeof window !== 'undefined' &&
            typeof window.ethereum !== 'undefined' &&
            window.ethereum.isMetaMask;

        if (!hasMetaMask) {
            const errorMsg = 'MetaMask no está instalado. Por favor instálalo desde metamask.io';
            setError(errorMsg);
            return { ok: false, error: errorMsg };
        }

        setIsConnecting(true);
        setError(null);

        try {
            // Request accounts
            const accounts = await window.ethereum.request({
                method: 'eth_requestAccounts',
            });

            if (!accounts || accounts.length === 0) {
                throw new Error('No accounts found. Please unlock MetaMask.');
            }

            // Create ethers provider
            const browserProvider = new BrowserProvider(window.ethereum);
            const signerInstance = await browserProvider.getSigner();
            const network = await browserProvider.getNetwork();
            const balanceWei = await browserProvider.getBalance(accounts[0]);

            setProvider(browserProvider);
            setSigner(signerInstance);
            setAddress(accounts[0]);
            setChainId(Number(network.chainId));
            setBalance(formatEther(balanceWei));
            setIsMetaMaskInstalled(true);

            console.log('Wallet connected:', accounts[0]);

            return {
                ok: true,
                address: accounts[0],
                chainId: Number(network.chainId),
            };
        } catch (err) {
            console.error('Wallet connection error:', err);
            let errorMessage = 'Error al conectar wallet';

            if (err.code === 4001) {
                errorMessage = 'Conexión rechazada por el usuario';
            } else if (err.code === -32002) {
                errorMessage = 'Ya hay una solicitud pendiente en MetaMask. Por favor revisa la extensión.';
            } else if (err.message) {
                errorMessage = err.message;
            }

            setError(errorMessage);
            return { ok: false, error: errorMessage };
        } finally {
            setIsConnecting(false);
        }
    }, []);

    // Disconnect wallet
    const disconnect = useCallback(() => {
        setAddress(null);
        setBalance(null);
        setChainId(null);
        setProvider(null);
        setSigner(null);
        setError(null);
    }, []);

    // Switch network
    const switchNetwork = useCallback(async (targetChainId) => {
        if (!isMetaMaskInstalled) return { ok: false, error: 'MetaMask not installed' };

        try {
            await window.ethereum.request({
                method: 'wallet_switchEthereumChain',
                params: [{ chainId: `0x${targetChainId.toString(16)}` }],
            });
            setChainId(targetChainId);
            return { ok: true };
        } catch (err) {
            console.error('Network switch error:', err);
            return { ok: false, error: err.message };
        }
    }, [isMetaMaskInstalled]);

    // Listen for account changes
    useEffect(() => {
        if (!isMetaMaskInstalled) return;

        const handleAccountsChanged = (accounts) => {
            if (accounts.length === 0) {
                disconnect();
            } else if (accounts[0] !== address) {
                setAddress(accounts[0]);
            }
        };

        const handleChainChanged = (chainIdHex) => {
            setChainId(parseInt(chainIdHex, 16));
        };

        window.ethereum.on('accountsChanged', handleAccountsChanged);
        window.ethereum.on('chainChanged', handleChainChanged);

        return () => {
            window.ethereum.removeListener('accountsChanged', handleAccountsChanged);
            window.ethereum.removeListener('chainChanged', handleChainChanged);
        };
    }, [address, disconnect, isMetaMaskInstalled]);

    // Check if already connected on mount
    useEffect(() => {
        if (!isMetaMaskInstalled) return;

        const checkConnection = async () => {
            try {
                const accounts = await window.ethereum.request({
                    method: 'eth_accounts',
                });
                if (accounts.length > 0) {
                    await connect();
                }
            } catch (err) {
                console.error('Check connection error:', err);
            }
        };

        checkConnection();
    }, [connect, isMetaMaskInstalled]);

    return {
        // State
        address,
        balance,
        chainId,
        provider,
        signer,
        isConnecting,
        error,
        isConnected: !!address,
        isMetaMaskInstalled,
        networkInfo: chainId ? getNetworkInfo(chainId) : null,

        // Actions
        connect,
        disconnect,
        switchNetwork,

        // Utils
        shortAddress: address ? `${address.slice(0, 6)}...${address.slice(-4)}` : null,
    };
};

export default useWallet;
