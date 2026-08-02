/**
 * useWallet Hook - Real MetaMask/Web3 integration
 * Connects to Ethereum wallets and manages Web3 state
 *
 * Sesión de wallet (SIWE, cierra el hallazgo C-1): conectar MetaMask solo
 * prueba que el usuario tiene esa extensión abierta, NO que controla la
 * dirección -- cualquiera puede escribir cualquier address en un form. Tras
 * obtener la cuenta, este hook pide un desafío (POST /wallet/challenge), lo
 * firma con personal_sign vía el signer real de MetaMask, y verifica la
 * firma (POST /wallet/verify) para obtener un JWT de sesión corto. Ese JWT
 * se guarda en localStorage bajo 'auth_token' -- la misma clave que el
 * interceptor de axios en lib/api.js ya adjunta como Bearer en cada
 * request, así que mint/votar/delegar quedan autenticados automáticamente
 * sin tocar esos otros call sites.
 */
import { useState, useCallback, useEffect } from 'react';
import { BrowserProvider, formatEther } from 'ethers';
import { walletAPI } from '../lib/api';

// Supported networks
const NETWORKS = {
    1: { name: 'Ethereum Mainnet', symbol: 'ETH' },
    11155111: { name: 'Sepolia Testnet', symbol: 'SepoliaETH' },
    137: { name: 'Polygon', symbol: 'MATIC' },
    80001: { name: 'Mumbai Testnet', symbol: 'MATIC' },
    80002: { name: 'Amoy Testnet', symbol: 'MATIC' },
};

// Margen para no reutilizar un token que expira mientras el usuario completa
// la acción que acaba de iniciar.
const TOKEN_EXPIRY_SKEW_SECONDS = 30;

// El backend firma el JWT; el cliente NO lo valida (no puede, ni debe). Solo
// lee `exp` para decidir si vale la pena reutilizarlo. Sin esto, un token
// vencido en localStorage hacía que connect() reportara éxito y la UI mostrara
// la wallet conectada, mientras cada llamada real devolvía 401 y el
// interceptor de axios borraba el token en silencio: el usuario quedaba
// "conectado" sin poder mintear, votar ni delegar.
const isSessionTokenUsable = (token) => {
    try {
        const payload = token.split('.')[1];
        if (!payload) return false;
        const claims = JSON.parse(
            atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
        );
        if (typeof claims.exp !== 'number') return false;
        return claims.exp - TOKEN_EXPIRY_SKEW_SECONDS > Date.now() / 1000;
    } catch {
        return false;
    }
};

const useWallet = () => {
    const [address, setAddress] = useState(null);
    const [balance, setBalance] = useState(null);
    const [chainId, setChainId] = useState(null);
    const [provider, setProvider] = useState(null);
    // Keep the exact injected provider that established the SIWE session.
    // BrowserProvider is useful for ethers reads, but ERC-4337 must call
    // eth_signTypedData_v4 on this pinned EIP-1193 object instead of looking
    // up a potentially different global provider at mint time.
    const [eip1193Provider, setEip1193Provider] = useState(null);
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

    // Sesión SIWE: pide el desafío, lo firma con el signer real, verifica
    // la firma y guarda el JWT devuelto. Lanza si algo falla -- el llamador
    // decide cómo reportarlo (connect() lo trata como fallo de conexión).
    //
    // Si ya hay un token guardado para esta MISMA dirección, no se vuelve a
    // pedir firma: sin este atajo, cada recarga de página (el efecto de
    // "reconectar si MetaMask ya está autorizado", más abajo) dispararía un
    // popup de firma de MetaMask sin que el usuario haya hecho nada.
    const signInWithEthereum = useCallback(async (signerInstance, expectedAddress) => {
        const cachedAddress = localStorage.getItem('auth_address');
        const cachedToken = localStorage.getItem('auth_token');
        if (
            cachedToken &&
            cachedAddress &&
            cachedAddress.toLowerCase() === expectedAddress.toLowerCase() &&
            isSessionTokenUsable(cachedToken)
        ) {
            return { token: cachedToken, reused: true };
        }
        // Vencido o de otra wallet: se descarta antes de pedir uno nuevo, para
        // que un fallo del challenge no deje un token muerto adjuntándose a
        // cada request.
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_address');

        const { data: challenge } = await walletAPI.challenge(expectedAddress);
        const signature = await signerInstance.signMessage(challenge.message);
        const { data: session } = await walletAPI.verify(expectedAddress, challenge.nonce, signature);
        localStorage.setItem('auth_token', session.token);
        localStorage.setItem('auth_address', expectedAddress.toLowerCase());
        return session;
    }, []);

    // Connect wallet
    const connect = useCallback(async (providerOverride = null) => {
        // Pin the provider for the whole authorization flow. `providerOverride`
        // is used only when reconnecting after an event from that same object.
        const injectedProvider =
            providerOverride && typeof providerOverride.request === 'function'
                ? providerOverride
                : (typeof window !== 'undefined' ? window.ethereum : null);
        const hasMetaMask =
            injectedProvider?.isMetaMask === true &&
            typeof injectedProvider.request === 'function';

        if (!hasMetaMask) {
            const errorMsg = 'MetaMask no está instalado. Por favor instálalo desde metamask.io';
            setError(errorMsg);
            return { ok: false, error: errorMsg };
        }

        setIsConnecting(true);
        setError(null);

        try {
            // Request accounts
            const accounts = await injectedProvider.request({
                method: 'eth_requestAccounts',
            });

            if (!accounts || accounts.length === 0) {
                throw new Error('No accounts found. Please unlock MetaMask.');
            }

            // Create ethers provider
            const browserProvider = new BrowserProvider(injectedProvider);
            const signerInstance = await browserProvider.getSigner();
            const network = await browserProvider.getNetwork();
            const balanceWei = await browserProvider.getBalance(accounts[0]);

            // Prueba de propiedad de la dirección (SIWE): sin esto, conectar
            // MetaMask solo demuestra que la extensión está abierta, no que
            // el usuario controla accounts[0]. Si el usuario rechaza firmar
            // o el backend no puede emitir sesión, la conexión se considera
            // fallida -- el address quedaría "conectado" pero sin poder
            // mintear/votar (el backend rechazaría todo con 401).
            await signInWithEthereum(signerInstance, accounts[0]);

            setProvider(browserProvider);
            setEip1193Provider(injectedProvider);
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
                eip1193Provider: injectedProvider,
            };
        } catch (err) {
            console.error('Wallet connection error:', err);
            let errorMessage = 'Error al conectar wallet';

            if (err.code === 4001) {
                errorMessage = 'Conexión rechazada por el usuario';
            } else if (err.code === -32002) {
                errorMessage = 'Ya hay una solicitud pendiente en MetaMask. Por favor revisa la extensión.';
            } else if (err.response?.data?.detail) {
                // Error de sesión SIWE devuelto por el backend (challenge/verify)
                errorMessage = err.response.data.detail;
            } else if (err.message) {
                errorMessage = err.message;
            }

            localStorage.removeItem('auth_token');
            localStorage.removeItem('auth_address');
            setError(errorMessage);
            return { ok: false, error: errorMessage };
        } finally {
            setIsConnecting(false);
        }
    }, [signInWithEthereum]);

    // Disconnect wallet
    const disconnect = useCallback(() => {
        setAddress(null);
        setBalance(null);
        setChainId(null);
        setProvider(null);
        setEip1193Provider(null);
        setSigner(null);
        setError(null);
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_address');
    }, []);

    // Switch network
    const switchNetwork = useCallback(async (targetChainId) => {
        const activeProvider =
            eip1193Provider ||
            (typeof window !== 'undefined' ? window.ethereum : null);
        if (
            !isMetaMaskInstalled ||
            activeProvider?.isMetaMask !== true ||
            typeof activeProvider.request !== 'function'
        ) {
            return { ok: false, error: 'MetaMask not installed' };
        }

        try {
            await activeProvider.request({
                method: 'wallet_switchEthereumChain',
                params: [{ chainId: `0x${targetChainId.toString(16)}` }],
            });
            setChainId(targetChainId);
            return { ok: true };
        } catch (err) {
            console.error('Network switch error:', err);
            return { ok: false, error: err.message };
        }
    }, [eip1193Provider, isMetaMaskInstalled]);

    // Listen for account changes
    useEffect(() => {
        if (!isMetaMaskInstalled) return;
        const activeProvider =
            eip1193Provider ||
            (typeof window !== 'undefined' ? window.ethereum : null);
        if (!activeProvider || typeof activeProvider.on !== 'function') return;

        const handleAccountsChanged = async (accounts) => {
            if (accounts.length === 0) {
                disconnect();
            } else if (!address || accounts[0].toLowerCase() !== address.toLowerCase()) {
                // A SIWE token is bound to one wallet. Never keep showing the
                // new account with the previous account's bearer token: clear
                // all session state and ask the new account to sign its own
                // one-time challenge.
                disconnect();
                await connect(activeProvider);
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
    }, [address, connect, disconnect, eip1193Provider, isMetaMaskInstalled]);

    // Check if already connected on mount
    useEffect(() => {
        if (!isMetaMaskInstalled) return;
        // This effect is only for initial discovery. Once connect() pins the
        // provider, adding that state as a dependency would immediately call
        // connect() a second time and repeat eth_requestAccounts/RPC reads.
        const activeProvider =
            typeof window !== 'undefined' ? window.ethereum : null;
        if (!activeProvider || typeof activeProvider.request !== 'function') return;

        const checkConnection = async () => {
            try {
                const accounts = await activeProvider.request({
                    method: 'eth_accounts',
                });
                if (accounts.length > 0) {
                    await connect(activeProvider);
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
        eip1193Provider,
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
