/**
 * Onboarding Context
 * Manages the state of the citizen onboarding flow
 */
import React, { createContext, useContext, useState, useCallback, useMemo } from 'react';
import { authAPI, membershipAPI, dashboardAPI } from '../lib/api';

const OnboardingContext = createContext(null);

// All steps in order
export const STEPS = [
    'method',
    'clave',
    'nfc',
    'selfie',
    'consent',
    'wallet',
    'mint',
    'success',
    'dashboard'
];

export const OnboardingProvider = ({ children }) => {
    // Current step
    const [step, setStep] = useState('method');

    // Loading and error states
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    // Form data
    const [rut, setRut] = useState('');
    const [selectedFile, setSelectedFile] = useState(null);

    // API response data
    const [clave, setClave] = useState({});
    const [nfc, setNfc] = useState({});
    const [selfie, setSelfie] = useState({});
    const [wallet, setWallet] = useState({});
    const [mint, setMint] = useState({});
    // Real figures only: null until the API responds (never seed fake numbers)
    const [stats, setStats] = useState({ total_members: null, recent_joins: null });

    // Progress calculation
    const progress = useMemo(() => {
        const idx = Math.max(0, STEPS.indexOf(step));
        return Math.round(((idx + 1) / STEPS.length) * 100);
    }, [step]);

    // === API Actions ===

    const authenticateClaveUnica = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            const response = await authAPI.claveUnica(rut);
            if (response.data.ok) {
                setClave(response.data);
                setStep('nfc');
            } else {
                setError(response.data.error || 'Error en ClaveÚnica');
            }
        } catch (err) {
            setError('Error de conexión con ClaveÚnica');
        } finally {
            setLoading(false);
        }
    }, [rut]);

    const authenticateNFC = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            const response = await authAPI.nfc();
            if (response.data.ok) {
                setNfc(response.data);
                setStep('selfie');
            } else {
                setError(response.data.error || 'Error en lectura NFC');
            }
        } catch (err) {
            setError('Error de conexión con NFC');
        } finally {
            setLoading(false);
        }
    }, []);

    const analyzeLiveness = useCallback(async () => {
        if (!selectedFile) {
            setError('Por favor selecciona una imagen');
            return;
        }

        setLoading(true);
        setError('');
        try {
            const response = await authAPI.liveness(selectedFile);
            if (response.data.ok) {
                setSelfie(response.data);
                setStep('consent');
            } else {
                setError(response.data.error || 'Error en detección de vida');
            }
        } catch (err) {
            setError('Error de conexión en análisis de selfie');
        } finally {
            setLoading(false);
        }
    }, [selectedFile]);

    // NOTA: la conexión de wallet real (MetaMask + sesión SIWE) vive en
    // hooks/useWallet.js y se usa directamente desde WalletStep.jsx -- no
    // hay una acción `connectWallet` acá. La que había antes llamaba al
    // endpoint mock deprecado POST /wallet/connect (dirección inventada por
    // el servidor, sin firma) y no la usaba ningún componente.

    const loadStats = useCallback(async () => {
        try {
            const response = await dashboardAPI.getStats();
            setStats(response.data);
        } catch (err) {
            console.error('Error loading stats:', err);
        }
    }, []);

    /**
     * Look up an existing membership for a wallet.
     *
     * Re-entering the flow with a wallet that already holds an SBT used to walk
     * straight into the mint step and fail with "Ya existe un SBT para esta
     * wallet": correct on the backend, useless to the user. Returns the member
     * document when found so the caller can skip minting.
     */
    const fetchExistingMembership = useCallback(async (address) => {
        if (!address) return null;
        try {
            const response = await membershipAPI.getByWallet(address);
            return response.data?.found ? response.data.member : null;
        } catch (err) {
            // A lookup failure must not block onboarding: fall through to mint,
            // where the backend still enforces uniqueness.
            console.error('Error checking existing membership:', err);
            return null;
        }
    }, []);

    const mintSBT = useCallback(async () => {
        if (!wallet.address) return;

        setLoading(true);
        setError('');
        try {
            const response = await membershipAPI.mint(
                wallet.address,
                clave.assurance_level || 'AL1',
                nfc.doc_hash || '0xDOC'
            );

            if (response.data.ok) {
                setMint(response.data);
                await loadStats();
                setStep('success');
            } else {
                // The wallet may already hold an SBT (backend rejects duplicates).
                // Recover it and continue instead of dead-ending on the error.
                const existing = await fetchExistingMembership(wallet.address);
                if (existing) {
                    setMint({ ok: true, token_id: existing.token_id, tx_hash: existing.tx_hash || null });
                    await loadStats();
                    setStep('success');
                } else {
                    setError(response.data.error || 'Error minteando SBT');
                }
            }
        } catch (err) {
            setError('Error de conexión en mint');
        } finally {
            setLoading(false);
        }
    }, [wallet.address, clave.assurance_level, nfc.doc_hash, fetchExistingMembership, loadStats]);


    // File handling
    const handleFileSelect = useCallback((event) => {
        const file = event.target.files[0];
        if (file) {
            if (file.size > 10 * 1024 * 1024) {
                setError('Archivo muy grande (máximo 10MB)');
                return;
            }
            if (!file.type.startsWith('image/')) {
                setError('El archivo debe ser una imagen');
                return;
            }
            setSelectedFile(file);
            setError('');
        }
    }, []);

    // Reset flow
    const reset = useCallback(() => {
        setStep('method');
        setError('');
        setRut('');
        setSelectedFile(null);
        setClave({});
        setNfc({});
        setSelfie({});
        setWallet({});
        setMint({});
    }, []);

    const value = {
        // State
        step, setStep,
        loading, setLoading,
        error, setError,
        progress,

        // Form data
        rut, setRut,
        selectedFile, handleFileSelect,

        // API responses
        clave, setClave,
        nfc, setNfc,
        selfie, setSelfie,
        wallet, setWallet,
        mint, setMint,
        stats,

        // Actions
        authenticateClaveUnica,
        authenticateNFC,
        analyzeLiveness,
        mintSBT,
        fetchExistingMembership,
        loadStats,
        reset,
    };

    return (
        <OnboardingContext.Provider value={value}>
            {children}
        </OnboardingContext.Provider>
    );
};

export const useOnboarding = () => {
    const context = useContext(OnboardingContext);
    if (!context) {
        throw new Error('useOnboarding must be used within OnboardingProvider');
    }
    return context;
};

export default OnboardingContext;
