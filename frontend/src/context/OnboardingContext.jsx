/**
 * Onboarding Context
 * Manages the state of the citizen onboarding flow
 */
import React, {
    createContext,
    useContext,
    useState,
    useCallback,
    useMemo,
    useRef,
} from 'react';
import { authAPI, membershipAPI, dashboardAPI } from '../lib/api';
import {
    generateIdentityProof,
    deriveIdentityCommitment,
    readMembershipDeployment,
    verifyIdentityCredential,
    verifyProofLocally,
    checkZkAvailability,
    ZkNotProvisionedError,
} from '../lib/zk';

const OnboardingContext = createContext(null);

const isRecord = (value) =>
    Boolean(value) && typeof value === 'object' && !Array.isArray(value);

/**
 * Capture the issuer credential while accepting the snake_case shape emitted
 * by FastAPI. The signed identity and its Merkle witness remain in memory and
 * are never copied into the mint payload.
 */
export const extractIdentityCredential = (data) => {
    if (!isRecord(data)) return null;

    const identityRecord =
        (isRecord(data.identity) && data.identity) ||
        (isRecord(data.identity_claim) && data.identity_claim) ||
        (isRecord(data.zk_identity) && data.zk_identity) ||
        null;

    const signedIdentity =
        (typeof data.identity === 'string' && data.identity) ||
        (typeof data.identity_claim === 'string' && data.identity_claim) ||
        (typeof data.signed_identity === 'string' && data.signed_identity) ||
        null;
    const witness =
        (isRecord(data.identity_witness) && data.identity_witness) ||
        (isRecord(data.zk_witness) && data.zk_witness) ||
        (isRecord(data.membership_witness) && data.membership_witness) ||
        null;

    if (identityRecord) {
        return witness ? { ...witness, ...identityRecord } : identityRecord;
    }
    if (signedIdentity && witness) {
        return { ...witness, signature: signedIdentity };
    }
    return null;
};

/**
 * Opaque, short-lived proof that the civil verification flow completed. It is
 * deliberately kept in memory and exchanged exactly once after SIWE.
 */
export const extractIdentityGrant = (data) => {
    if (!isRecord(data)) return null;
    const grant = data.identity_grant;
    return typeof grant === 'string' && grant.trim() ? grant.trim() : null;
};

const withoutIdentityGrant = (data) => {
    if (!isRecord(data)) return data;
    const safeData = { ...data };
    delete safeData.identity_grant;
    return safeData;
};

const apiErrorMessage = (err, connectionFallback, rejectionLabel) => {
    const apiMessage = err.response?.data?.detail || err.response?.data?.error;
    if (typeof apiMessage === 'string' && apiMessage.trim()) {
        return apiMessage;
    }
    if (err.response) {
        return `${rejectionLabel} (HTTP ${err.response.status}).`;
    }
    return connectionFallback;
};

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
    // Signed issuer credential plus private Merkle witness. It lives only in
    // memory and must never be included in the relayer request.
    const [identity, setIdentity] = useState(null);
    const identityGrantRef = useRef(null);
    const identityEnrollmentInFlight = useRef(false);
    // Prueba de conocimiento cero generada localmente (ADR-001, D-2).
    // `status`: idle | enrolling | generating | ready | unavailable | error
    const [zk, setZk] = useState({ status: 'idle' });
    // Real figures only: null until the API responds (never seed fake numbers)
    const [stats, setStats] = useState({ total_members: null, recent_joins: null });

    // Progress calculation
    const progress = useMemo(() => {
        const idx = Math.max(0, STEPS.indexOf(step));
        return Math.round(((idx + 1) / STEPS.length) * 100);
    }, [step]);

    // === API Actions ===

    const captureIdentityGrant = useCallback((data) => {
        const grant = extractIdentityGrant(data);
        if (grant) identityGrantRef.current = grant;
        return grant;
    }, []);

    const authenticateClaveUnica = useCallback(async (processingAccepted = false) => {
        if (!processingAccepted) {
            setError('Confirma la advertencia de tratamiento antes de enviar el RUT al backend.');
            return;
        }
        setLoading(true);
        setError('');
        try {
            const response = await authAPI.claveUnica(rut);
            if (response.data.ok) {
                captureIdentityGrant(response.data);
                setClave(withoutIdentityGrant(response.data));
                setStep('nfc');
            } else {
                setError(response.data.error || 'Error en ClaveÚnica');
            }
        } catch (err) {
            setError(apiErrorMessage(
                err,
                'No fue posible contactar al servicio de ClaveÚnica simulado.',
                'El servicio rechazó la simulación de ClaveÚnica'
            ));
        } finally {
            setLoading(false);
        }
    }, [rut, captureIdentityGrant]);

    const authenticateNFC = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            const response = await authAPI.nfc();
            if (response.data.ok) {
                captureIdentityGrant(response.data);
                setNfc(withoutIdentityGrant(response.data));
                setStep('selfie');
            } else {
                setError(response.data.error || 'Error en lectura NFC');
            }
        } catch (err) {
            setError(apiErrorMessage(
                err,
                'No fue posible contactar al servicio NFC simulado.',
                'El servicio rechazó la simulación NFC'
            ));
        } finally {
            setLoading(false);
        }
    }, [captureIdentityGrant]);

    const analyzeLiveness = useCallback(async (processingAccepted = false) => {
        if (!processingAccepted) {
            setError('Confirma la advertencia de tratamiento antes de enviar la imagen al backend.');
            return;
        }
        if (!selectedFile) {
            setError('Por favor selecciona una imagen');
            return;
        }

        setLoading(true);
        setError('');
        try {
            const response = await authAPI.liveness(selectedFile);
            if (response.data.ok) {
                captureIdentityGrant(response.data);
                setSelfie(withoutIdentityGrant(response.data));
                setStep('consent');
            } else {
                setError(response.data.error || 'Error en detección de vida');
            }
        } catch (err) {
            setError(apiErrorMessage(
                err,
                'No fue posible contactar al servicio de análisis de imagen.',
                'El servicio rechazó el análisis de imagen'
            ));
        } finally {
            setLoading(false);
        }
    }, [selectedFile, captureIdentityGrant]);

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

    /**
     * Comprueba si este despliegue puede generar pruebas ZK, sin generarlas.
     * Sirve para que la interfaz diga la verdad antes de que el ciudadano
     * llegue al paso de minteo.
     */
    const refreshZkAvailability = useCallback(async () => {
        const { ready, missing } = await checkZkAvailability();
        setZk((prev) =>
            prev.status === 'ready'
                ? prev
                : { status: ready ? 'idle' : 'unavailable', missing }
        );
        return ready;
    }, []);

    /**
     * Complete the post-SIWE enrollment handshake. The client reads scope from
     * the connected contract, derives a wallet-bound commitment locally and
     * sends only that public commitment to the issuer. The returned signed
     * identity/witness stays in memory.
     */
    const requestIdentityCredential = useCallback(async (walletOverride = null) => {
        if (identityEnrollmentInFlight.current) return null;
        const targetWallet = walletOverride || wallet;
        if (!targetWallet?.address || targetWallet.chainId == null) {
            setError('Conecta una wallet y una red antes de solicitar la credencial identity.');
            return null;
        }
        const identityGrant = identityGrantRef.current;
        if (!identityGrant) {
            setError(
                'La verificación civil no entregó un grant de identidad de un solo uso; no se puede emitir la credencial ZK.'
            );
            return null;
        }

        identityEnrollmentInFlight.current = true;
        setZk({ status: 'enrolling' });
        setError('');
        try {
            const availability = await checkZkAvailability();
            if (!availability.ready) {
                throw new ZkNotProvisionedError(
                    'Este despliegue no publicó la configuración y los artefactos exactos del circuito ZK.',
                    availability.missing
                );
            }
            const deployment = await readMembershipDeployment(
                targetWallet.chainId,
                null,
                targetWallet.address
            );
            const identityCommitment = await deriveIdentityCommitment({
                recipient: targetWallet.address,
                scope: deployment.scope,
            });
            const response = await authAPI.issueIdentityCredential({
                walletAddress: targetWallet.address,
                identityCommitment,
                membershipScope: deployment.scope,
                membershipContract: deployment.contractAddress,
                chainId: deployment.chainId,
                identityGrant,
            });
            if (!response.data?.ok) {
                throw new Error(
                    response.data?.error ||
                    'El emisor rechazó la solicitud de credencial identity.'
                );
            }
            const rawCredential = extractIdentityCredential(response.data);
            if (!rawCredential) {
                throw new Error(
                    'El emisor no devolvió una identity firmada junto con su ruta Merkle.'
                );
            }
            const normalized = verifyIdentityCredential(
                rawCredential,
                targetWallet.address
            );
            if (
                normalized.scope !== deployment.scope ||
                normalized.commitment !== identityCommitment
            ) {
                setIdentity(null);
                throw new Error(
                    'La credencial emitida no coincide con el commitment o scope solicitado.'
                );
            }
            await readMembershipDeployment(
                targetWallet.chainId,
                normalized.identityRoot,
                targetWallet.address
            );

            const credential = {
                ...normalized,
                chainId: deployment.chainId,
            };
            setIdentity(credential);
            // Clear the bearer grant only after the signed credential, local
            // binding and approved root have all passed validation.
            identityGrantRef.current = null;
            setZk({ status: 'idle' });
            return credential;
        } catch (err) {
            setIdentity(null);
            if (err instanceof ZkNotProvisionedError) {
                setZk({ status: 'unavailable', missing: err.missing });
            } else {
                setZk({ status: 'error' });
            }
            const apiMessage =
                err.response?.data?.detail || err.response?.data?.error;
            setError(
                (typeof apiMessage === 'string' && apiMessage.trim()) ||
                (err.response
                    ? `El emisor rechazó la credencial identity (HTTP ${err.response.status}).`
                    : err.message || 'No se pudo obtener la credencial identity.')
            );
            return null;
        } finally {
            identityEnrollmentInFlight.current = false;
        }
    }, [wallet]);

    /**
     * Genera la prueba de identidad LOCALMENTE (ADR-001, D-2).
     *
     * The identity secret, signed claim and Merkle path never leave this
     * browser. Only the contract arguments are sent to the relayer.
     *
     * Devuelve la prueba, o `null` si no se pudo generar. Nunca devuelve algo
     * que se parezca a una prueba sin serlo.
     */
    const generateProof = useCallback(async (identityOverride = null) => {
        const activeIdentity = isRecord(identityOverride)
            ? identityOverride
            : identity;
        if (!wallet.address) {
            setError('Conecta la wallet receptora antes de generar la prueba.');
            return null;
        }
        if (!activeIdentity) {
            setError(
                'El emisor todavía no entregó una credencial identity firmada con su ruta Merkle.'
            );
            return null;
        }

        setZk({ status: 'generating' });
        setError('');
        try {
            const normalizedIdentity = verifyIdentityCredential(
                activeIdentity,
                wallet.address
            );
            const deployment = await readMembershipDeployment(
                wallet.chainId,
                normalizedIdentity.identityRoot,
                wallet.address
            );
            const result = await generateIdentityProof({
                identity: activeIdentity,
                recipient: wallet.address,
                expectedScope: deployment.scope,
            });

            // Fail closed: a missing verification key is not a successful
            // self-check and must not consume a sponsored transaction.
            const selfCheck = await verifyProofLocally(result.proof, result.publicSignals);
            if (selfCheck !== true) {
                setZk({ status: 'error' });
                setError(
                    selfCheck === false
                        ? 'La prueba generada no pasó la verificación local; no se enviará.'
                        : 'No se pudo cargar la clave de verificación local; la prueba no se enviará.'
                );
                return null;
            }

            setZk({
                status: 'ready',
                nullifierHash: result.nullifierHash,
                identityRoot: result.identityRoot,
                recipient: result.recipient,
                scope: result.scope,
                pA: result.pA,
                pB: result.pB,
                pC: result.pC,
                locallyVerified: true,
            });
            return result;
        } catch (err) {
            if (err instanceof ZkNotProvisionedError) {
                setZk({ status: 'unavailable', missing: err.missing });
                setError(err.message);
                return null;
            }
            setZk({ status: 'error' });
            setError(err.message || 'No se pudo generar la prueba de identidad.');
            return null;
        }
    }, [identity, wallet.address, wallet.chainId]);

    const mintSBT = useCallback(async () => {
        if (!wallet.address) return;
        setLoading(true);
        setError('');
        try {
            const activeIdentity = identity || await requestIdentityCredential();
            if (!activeIdentity) {
                return;
            }
            const proofResult = await generateProof(activeIdentity);
            if (!proofResult) {
                return;
            }
            const currentDeployment = await readMembershipDeployment(
                wallet.chainId,
                proofResult.identityRoot,
                wallet.address
            );
            if (currentDeployment.scope !== proofResult.scope) {
                throw new Error(
                    'La red o el contrato cambiaron después de generar la prueba; no se enviará.'
                );
            }
            const response = await membershipAPI.mintWithProof({
                walletAddress: wallet.address,
                pA: proofResult.pA,
                pB: proofResult.pB,
                pC: proofResult.pC,
                nullifierHash: proofResult.nullifierHash,
                identityRoot: proofResult.identityRoot,
            });

            if (response.data.ok) {
                setMint({ ...response.data, status: 'active' });
                await loadStats();
                setStep('success');
            } else {
                // The wallet may already hold an SBT (backend rejects duplicates).
                // Recover it and continue instead of dead-ending on the error.
                const existing = await fetchExistingMembership(wallet.address);
                if (existing?.status === 'active' && existing?.valid === true) {
                    setMint({
                        ok: true,
                        token_id: existing.token_id,
                        tx_hash: existing.tx_hash || null,
                        status: 'active',
                    });
                    await loadStats();
                    setStep('success');
                } else if (existing) {
                    setError(
                        `La membresía #${existing.token_id} no es válida (${existing.status || 'estado desconocido'}). ` +
                        'No puede presentarse ni reutilizarse como una membresía vigente.'
                    );
                } else {
                    setError(response.data.error || 'Error creando la credencial');
                }
            }
        } catch (err) {
            const apiMessage = err.response?.data?.detail || err.response?.data?.error;
            if (typeof apiMessage === 'string' && apiMessage.trim()) {
                setError(apiMessage);
            } else if (err.response) {
                setError(`El servicio rechazó la creación de la credencial (HTTP ${err.response.status}).`);
            } else {
                setError(
                    err.message ||
                    'No fue posible contactar al servicio de membresía.'
                );
            }
        } finally {
            setLoading(false);
        }
    }, [
        wallet.address,
        wallet.chainId,
        identity,
        fetchExistingMembership,
        loadStats,
        generateProof,
        requestIdentityCredential,
    ]);


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
        setIdentity(null);
        identityGrantRef.current = null;
        // El secreto ZK NO se borra acá a propósito: es lo que ata al ciudadano
        // con su nullifier. Perderlo le daría un nullifier distinto para la
        // misma cédula. Se olvida solo con `forgetSecret()` explícito.
        setZk({ status: 'idle' });
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
        identity, setIdentity,
        stats,

        // Prueba ZK local (ADR-001)
        zk,
        zkMintEnabled: true,

        // Actions
        authenticateClaveUnica,
        authenticateNFC,
        analyzeLiveness,
        generateProof,
        refreshZkAvailability,
        requestIdentityCredential,
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
