/**
 * Shared MetaMask and SIWE session state.
 *
 * The backend owns the short-lived JWT in an HttpOnly cookie. The frontend
 * restores session metadata through GET /wallet/session and only keeps the
 * non-authenticating CSRF value in memory.
 */
import React, {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useRef,
    useState,
} from 'react';
import { BrowserProvider, formatEther } from 'ethers';
import { walletAPI } from '../lib/api';
import {
    clearLegacySessionStorage,
    invalidateSession,
    isValidCsrfToken,
    setCsrfToken,
    subscribeSessionInvalidation,
} from '../lib/session';

const NETWORKS = {
    1: { name: 'Ethereum Mainnet', symbol: 'ETH' },
    11155111: { name: 'Sepolia Testnet', symbol: 'SepoliaETH' },
    137: { name: 'Polygon', symbol: 'MATIC' },
    80001: { name: 'Mumbai Testnet', symbol: 'MATIC' },
    80002: { name: 'Amoy Testnet', symbol: 'MATIC' },
};

const WalletSessionContext = createContext(null);

const addressesMatch = (first, second) =>
    typeof first === 'string' &&
    typeof second === 'string' &&
    first.toLowerCase() === second.toLowerCase();

const isUnauthorized = (error) => error?.response?.status === 401;

const walletErrorMessage = (error, fallback = 'Error al conectar wallet') => {
    if (error?.code === 4001) {
        return 'Conexión rechazada por el usuario';
    }
    if (error?.code === -32002) {
        return 'Ya hay una solicitud pendiente en MetaMask. Revisa la extensión.';
    }
    if (typeof error?.response?.data?.detail === 'string') {
        return error.response.data.detail;
    }
    return error?.message || fallback;
};

const acceptCookieSession = (data) => {
    if (typeof data?.address !== 'string' || !data.address) {
        throw new Error('El backend devolvió una sesión sin dirección válida.');
    }
    if (!isValidCsrfToken(data.csrf_token)) {
        throw new Error('El backend devolvió una sesión sin protección CSRF válida.');
    }
    setCsrfToken(data.csrf_token);
    return data;
};

const WalletSessionProvider = ({ children }) => {
    const [address, setAddress] = useState(null);
    const [balance, setBalance] = useState(null);
    const [chainId, setChainId] = useState(null);
    const [provider, setProvider] = useState(null);
    // ERC-4337 must sign through the exact injected EIP-1193 provider that
    // established the SIWE session, never through a later global lookup.
    const [eip1193Provider, setEip1193Provider] = useState(null);
    const [signer, setSigner] = useState(null);
    const [isConnecting, setIsConnecting] = useState(false);
    const [isDisconnecting, setIsDisconnecting] = useState(false);
    const [isRestoring, setIsRestoring] = useState(false);
    const [error, setError] = useState(null);
    const [isMetaMaskInstalled, setIsMetaMaskInstalled] = useState(false);
    const operationId = useRef(0);

    const clearWalletState = useCallback((nextError = null) => {
        setAddress(null);
        setBalance(null);
        setChainId(null);
        setProvider(null);
        setEip1193Provider(null);
        setSigner(null);
        setError(nextError);
    }, []);

    useEffect(() => subscribeSessionInvalidation(() => {
        clearWalletState();
    }), [clearWalletState]);

    useEffect(() => {
        clearLegacySessionStorage();

        const checkMetaMask = () => {
            const injected = typeof window !== 'undefined' ? window.ethereum : null;
            setIsMetaMaskInstalled(
                injected?.isMetaMask === true && typeof injected.request === 'function'
            );
        };

        checkMetaMask();
        const timeout = setTimeout(checkMetaMask, 500);
        if (typeof window !== 'undefined') {
            window.addEventListener?.('ethereum#initialized', checkMetaMask);
        }

        return () => {
            clearTimeout(timeout);
            if (typeof window !== 'undefined') {
                window.removeEventListener?.('ethereum#initialized', checkMetaMask);
            }
        };
    }, []);

    const readCookieSession = useCallback(async () => {
        try {
            const { data } = await walletAPI.session();
            return acceptCookieSession(data);
        } catch (sessionError) {
            if (isUnauthorized(sessionError)) return null;
            throw sessionError;
        }
    }, []);

    const createWalletSnapshot = useCallback(async (injectedProvider, account) => {
        const browserProvider = new BrowserProvider(injectedProvider);
        const signerInstance = await browserProvider.getSigner(account);
        const [network, balanceWei] = await Promise.all([
            browserProvider.getNetwork(),
            browserProvider.getBalance(account),
        ]);

        return {
            address: account,
            balance: formatEther(balanceWei),
            chainId: Number(network.chainId),
            provider: browserProvider,
            eip1193Provider: injectedProvider,
            signer: signerInstance,
        };
    }, []);

    const applyWalletSnapshot = useCallback((snapshot) => {
        setProvider(snapshot.provider);
        setEip1193Provider(snapshot.eip1193Provider);
        setSigner(snapshot.signer);
        setAddress(snapshot.address);
        setChainId(snapshot.chainId);
        setBalance(snapshot.balance);
        setIsMetaMaskInstalled(true);
        setError(null);
    }, []);

    const signInWithEthereum = useCallback(async (signerInstance, expectedAddress) => {
        let verifyStarted = false;
        try {
            const { data: challenge } = await walletAPI.challenge(expectedAddress);
            if (typeof challenge?.message !== 'string' || !challenge.message ||
                typeof challenge?.nonce !== 'string' || !challenge.nonce) {
                throw new Error('El backend devolvió un desafío SIWE inválido.');
            }

            const signature = await signerInstance.signMessage(challenge.message);
            verifyStarted = true;
            const { data: issuedSession } = await walletAPI.verify(
                expectedAddress,
                challenge.nonce,
                signature
            );

            // Cookie mode must never expose a readable JWT in the response.
            if (typeof issuedSession?.token === 'string' && issuedSession.token) {
                throw new Error('El backend devolvió un JWT legible en modo cookie.');
            }
            const verified = acceptCookieSession(issuedSession);
            if (!addressesMatch(verified.address, expectedAddress)) {
                throw new Error('La sesión SIWE no corresponde a la cuenta seleccionada.');
            }

            // Do not expose authenticated UI or the ERC-4337 signer until the
            // browser proves that it stored and can resend the HttpOnly cookie.
            const confirmed = await readCookieSession();
            if (!confirmed || !addressesMatch(confirmed.address, expectedAddress)) {
                throw new Error('El navegador no pudo conservar la cookie de sesión segura.');
            }
            return confirmed;
        } catch (signInError) {
            if (verifyStarted) {
                try {
                    await walletAPI.logout();
                } catch {
                    // The original SIWE error remains the actionable one.
                }
                invalidateSession('verification-failed');
            }
            throw signInError;
        }
    }, [readCookieSession]);

    const ensureSessionForAccount = useCallback(async (signerInstance, account) => {
        const existingSession = await readCookieSession();
        if (existingSession && addressesMatch(existingSession.address, account)) {
            return existingSession;
        }

        if (existingSession) {
            // Never let an account selected in MetaMask act through a cookie
            // bound to a different address.
            await walletAPI.logout();
            invalidateSession('account-mismatch');
        }

        return signInWithEthereum(signerInstance, account);
    }, [readCookieSession, signInWithEthereum]);

    const connect = useCallback(async (providerOverride = null) => {
        if (isConnecting || isDisconnecting) {
            return { ok: false, error: 'Ya hay una operación de sesión en curso.' };
        }

        const injectedProvider =
            providerOverride && typeof providerOverride.request === 'function'
                ? providerOverride
                : (typeof window !== 'undefined' ? window.ethereum : null);
        const hasMetaMask =
            injectedProvider?.isMetaMask === true &&
            typeof injectedProvider.request === 'function';

        if (!hasMetaMask) {
            const message = 'MetaMask no está instalado. Instálalo desde metamask.io.';
            setError(message);
            return { ok: false, error: message };
        }

        const currentOperation = ++operationId.current;
        setIsRestoring(false);
        setIsConnecting(true);
        setError(null);

        try {
            const accounts = await injectedProvider.request({
                method: 'eth_requestAccounts',
            });
            if (!accounts?.length) {
                throw new Error('No se encontró una cuenta. Desbloquea MetaMask.');
            }

            const snapshot = await createWalletSnapshot(injectedProvider, accounts[0]);
            await ensureSessionForAccount(snapshot.signer, snapshot.address);

            if (currentOperation !== operationId.current) {
                throw new Error('La conexión fue cancelada por un cambio de sesión.');
            }
            applyWalletSnapshot(snapshot);

            return {
                ok: true,
                address: snapshot.address,
                chainId: snapshot.chainId,
                eip1193Provider: injectedProvider,
            };
        } catch (connectionError) {
            const message = walletErrorMessage(connectionError);
            if (currentOperation === operationId.current) {
                clearWalletState(message);
            }
            return { ok: false, error: message };
        } finally {
            setIsConnecting(false);
        }
    }, [
        applyWalletSnapshot,
        clearWalletState,
        createWalletSnapshot,
        ensureSessionForAccount,
        isConnecting,
        isDisconnecting,
    ]);

    const disconnect = useCallback(async () => {
        if (isDisconnecting) {
            return { ok: false, error: 'El cierre de sesión ya está en curso.' };
        }

        ++operationId.current;
        setIsRestoring(false);
        setIsDisconnecting(true);
        setError(null);
        let logoutError = null;

        try {
            await walletAPI.logout();
        } catch (remoteError) {
            logoutError = walletErrorMessage(
                remoteError,
                'No se pudo confirmar el cierre de sesión con el servidor.'
            );
        } finally {
            // Local authenticated state must disappear even if the network is
            // unavailable. A returned failure makes the remote uncertainty
            // explicit instead of pretending that the cookie was cleared.
            invalidateSession('logout');
            clearLegacySessionStorage();
            clearWalletState(logoutError);
            setIsDisconnecting(false);
        }

        return logoutError
            ? { ok: false, error: logoutError }
            : { ok: true };
    }, [clearWalletState, isDisconnecting]);

    const switchNetwork = useCallback(async (targetChainId) => {
        const activeProvider =
            eip1193Provider ||
            (typeof window !== 'undefined' ? window.ethereum : null);
        if (
            !isMetaMaskInstalled ||
            activeProvider?.isMetaMask !== true ||
            typeof activeProvider.request !== 'function'
        ) {
            return { ok: false, error: 'MetaMask no está instalado.' };
        }

        try {
            await activeProvider.request({
                method: 'wallet_switchEthereumChain',
                params: [{ chainId: `0x${targetChainId.toString(16)}` }],
            });
            setChainId(targetChainId);
            return { ok: true };
        } catch (switchError) {
            return { ok: false, error: walletErrorMessage(switchError, 'No se pudo cambiar de red.') };
        }
    }, [eip1193Provider, isMetaMaskInstalled]);

    const restoreSession = useCallback(async (injectedProvider) => {
        const currentOperation = ++operationId.current;
        setIsRestoring(true);

        try {
            const accounts = await injectedProvider.request({ method: 'eth_accounts' });
            if (!accounts?.length) {
                clearWalletState();
                return;
            }

            const existingSession = await readCookieSession();
            if (!existingSession) {
                clearWalletState();
                return;
            }
            if (!addressesMatch(existingSession.address, accounts[0])) {
                try {
                    await walletAPI.logout();
                    invalidateSession('account-mismatch');
                    clearWalletState();
                } catch (logoutFailure) {
                    invalidateSession('account-mismatch');
                    clearWalletState(walletErrorMessage(
                        logoutFailure,
                        'No se pudo limpiar una sesión asociada a otra cuenta.'
                    ));
                }
                return;
            }

            const snapshot = await createWalletSnapshot(injectedProvider, accounts[0]);
            if (currentOperation === operationId.current) {
                applyWalletSnapshot(snapshot);
            }
        } catch (restoreError) {
            if (currentOperation === operationId.current) {
                clearWalletState(walletErrorMessage(
                    restoreError,
                    'No se pudo restaurar la sesión segura.'
                ));
            }
        } finally {
            if (currentOperation === operationId.current) {
                setIsRestoring(false);
            }
        }
    }, [
        applyWalletSnapshot,
        clearWalletState,
        createWalletSnapshot,
        readCookieSession,
    ]);

    useEffect(() => {
        if (!isMetaMaskInstalled) return;
        const injectedProvider = typeof window !== 'undefined' ? window.ethereum : null;
        if (!injectedProvider || typeof injectedProvider.request !== 'function') return;
        void restoreSession(injectedProvider);
    }, [isMetaMaskInstalled, restoreSession]);

    useEffect(() => {
        if (!isMetaMaskInstalled) return;
        const activeProvider =
            eip1193Provider ||
            (typeof window !== 'undefined' ? window.ethereum : null);
        if (!activeProvider || typeof activeProvider.on !== 'function') return;

        const handleAccountsChanged = async (accounts) => {
            if (!accounts?.length) {
                await disconnect();
                return;
            }
            if (address && !addressesMatch(accounts[0], address)) {
                const result = await disconnect();
                if (result.ok) {
                    setError('La cuenta de MetaMask cambió. Vuelve a conectar para firmar una sesión nueva.');
                }
            }
        };

        const handleChainChanged = (chainIdHex) => {
            setChainId(parseInt(chainIdHex, 16));
        };

        activeProvider.on('accountsChanged', handleAccountsChanged);
        activeProvider.on('chainChanged', handleChainChanged);

        return () => {
            activeProvider.removeListener?.('accountsChanged', handleAccountsChanged);
            activeProvider.removeListener?.('chainChanged', handleChainChanged);
        };
    }, [address, disconnect, eip1193Provider, isMetaMaskInstalled]);

    const value = {
        address,
        balance,
        chainId,
        provider,
        eip1193Provider,
        signer,
        isConnecting,
        isDisconnecting,
        isRestoring,
        error,
        isConnected: Boolean(address),
        isMetaMaskInstalled,
        networkInfo: chainId ? NETWORKS[chainId] || {
            name: `Chain ${chainId}`,
            symbol: 'ETH',
        } : null,
        connect,
        disconnect,
        switchNetwork,
        shortAddress: address
            ? `${address.slice(0, 6)}...${address.slice(-4)}`
            : null,
    };

    return (
        <WalletSessionContext.Provider value={value}>
            {children}
        </WalletSessionContext.Provider>
    );
};

const useWallet = () => {
    const context = useContext(WalletSessionContext);
    if (!context) {
        throw new Error('useWallet must be used within WalletSessionProvider.');
    }
    return context;
};

export { WalletSessionProvider };
export default useWallet;
