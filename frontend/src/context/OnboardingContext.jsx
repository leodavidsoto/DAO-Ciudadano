/**
 * Onboarding Context
 * Manages the state of the citizen onboarding flow
 */
import React, { createContext, useContext, useState, useCallback, useMemo } from 'react';
import { authAPI, walletAPI, membershipAPI, dashboardAPI } from '../lib/api';

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
    const [stats, setStats] = useState({ total_members: 1432, recent_joins: 32 });

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

    const connectWallet = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            const response = await walletAPI.connect();
            if (response.data.ok) {
                setWallet(response.data);
                setStep('mint');
            } else {
                setError(response.data.error || 'Error conectando wallet');
            }
        } catch (err) {
            setError('Error de conexión con wallet');
        } finally {
            setLoading(false);
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
                setError(response.data.error || 'Error minteando SBT');
            }
        } catch (err) {
            setError('Error de conexión en mint');
        } finally {
            setLoading(false);
        }
    }, [wallet.address, clave.assurance_level, nfc.doc_hash]);

    const loadStats = useCallback(async () => {
        try {
            const response = await dashboardAPI.getStats();
            setStats(response.data);
        } catch (err) {
            console.error('Error loading stats:', err);
        }
    }, []);

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
        connectWallet,
        mintSBT,
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
