/**
 * Wallet session (EIP-4361 / SIWE).
 *
 * The backend takes the acting address from the session token, never from the
 * request body, so without a session every mutating call returns 401. This
 * hook performs the handshake: ask for a nonce, sign it, exchange the
 * signature for a token.
 *
 * The token lives in sessionStorage, not localStorage: it should not outlive
 * the browser session, and a shorter-lived credential is a smaller target.
 */
import { useCallback, useEffect, useState } from 'react';

import { sessionAPI, setAuthToken, getAuthToken, clearAuthToken } from '@/lib/api';

const decodeAddress = (token) => {
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        if (payload.exp && payload.exp * 1000 < Date.now()) return null;
        return payload.sub || null;
    } catch {
        return null;
    }
};

const useSession = () => {
    const [address, setAddress] = useState(null);
    const [isSigningIn, setIsSigningIn] = useState(false);
    const [error, setError] = useState(null);

    // Restore an existing session on mount. The token is only trusted for
    // display: the backend re-validates it on every request.
    useEffect(() => {
        const token = getAuthToken();
        if (!token) return;
        const subject = decodeAddress(token);
        if (subject) {
            setAddress(subject);
        } else {
            clearAuthToken();
        }
    }, []);

    const signIn = useCallback(async (walletAddress) => {
        if (!walletAddress) {
            setError('Conecta tu wallet antes de iniciar sesión');
            return { ok: false };
        }
        if (!window.ethereum) {
            setError('No se detectó una wallet en este navegador');
            return { ok: false };
        }

        setIsSigningIn(true);
        setError(null);
        try {
            const { data: challenge } = await sessionAPI.challenge(walletAddress);

            // personal_sign shows the message text in the wallet, so the person
            // can read what they are approving before signing.
            const signature = await window.ethereum.request({
                method: 'personal_sign',
                params: [challenge.message, walletAddress],
            });

            const { data } = await sessionAPI.verify(walletAddress, signature);
            if (!data.ok) {
                setError(data.error || 'No se pudo verificar la firma');
                return { ok: false };
            }

            setAuthToken(data.token);
            setAddress(data.address);
            return { ok: true, address: data.address };
        } catch (err) {
            // 4001 is the wallet's "user rejected" code: not an error to shout about.
            if (err?.code === 4001) {
                setError('Firma cancelada');
            } else {
                setError(err.response?.data?.detail || err.message || 'Error iniciando sesión');
            }
            return { ok: false };
        } finally {
            setIsSigningIn(false);
        }
    }, []);

    const signOut = useCallback(() => {
        clearAuthToken();
        setAddress(null);
        setError(null);
    }, []);

    return {
        address,
        isSignedIn: !!address,
        isSigningIn,
        error,
        signIn,
        signOut,
    };
};

export default useSession;
