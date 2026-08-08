import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    AlertTriangle,
    KeyRound,
    LockKeyhole,
    Send,
    ShieldCheck,
} from 'lucide-react';
import {
    governanceAPI,
    maciAPI,
    normalizeEncryptedBallotReceipt,
} from '../../lib/api';
import MaciBallotProgress from './MaciBallotProgress';

const CHOICES = [
    { value: 'for', label: 'A favor', description: 'Apoyar la propuesta' },
    { value: 'against', label: 'En contra', description: 'Rechazar la propuesta' },
    { value: 'abstain', label: 'Abstención', description: 'Participar sin inclinar el resultado' },
];
const EVM_ADDRESS_PATTERN = /^0x[0-9a-fA-F]{40}$/;

const hasTrustedMaciDeployment = () => [
    process.env.REACT_APP_MACI_COORDINATOR_ADDRESS,
    process.env.REACT_APP_MACI_TALLY_VERIFIER_ADDRESS,
].every((address) => EVM_ADDRESS_PATTERN.test(address || ''));

const getApiError = (
    error,
    networkMessage = 'No fue posible consultar el servicio de propuestas y la urna privada.'
) => {
    if (error?.code === 4001) return 'La operación fue rechazada por la wallet.';
    const detail = error?.response?.data?.detail || error?.response?.data?.error;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (error?.response?.status) {
        return `La urna privada rechazó el mensaje (HTTP ${error.response.status}).`;
    }
    if (error?.request || error?.message === 'Network Error') {
        return networkMessage;
    }
    return error?.message || 'No fue posible enviar la papeleta cifrada.';
};

const proposalStillOpen = (proposal) => {
    if (!proposal || proposal.status !== 'active') return false;
    const closesAt = Date.parse(proposal.ends_at);
    return Number.isFinite(closesAt) && closesAt > Date.now();
};

const isDefinitiveBallotRejection = (error) => {
    const status = Number(error?.response?.status);
    if (!Number.isInteger(status) || status < 400 || status >= 500) return false;
    // These statuses can be emitted after an intermediary/backend already
    // accepted the idempotent message, so the exact ciphertext must survive.
    return ![408, 425, 429].includes(status);
};

const getMaciReadiness = (response) => {
    const status = response?.data ?? response ?? {};
    const missing = [];
    if (status.key_registry !== true) missing.push('registro de llaves');
    if (status.private_voting !== true) missing.push('votación privada');
    if (status.coordinator_configured !== true) missing.push('coordinador MACI');
    if (status.tally_proof !== true) missing.push('verificación del tally');
    if (status.poll_bound_messages !== true) missing.push('vinculación mensaje-poll');
    if (status.stateful_nonces !== true) missing.push('nonce ligado al estado');
    if (status.unique_tally_leaves !== true) missing.push('unicidad de hojas del tally');
    if (status.process_tally_linked !== true) missing.push('encadenamiento de pruebas');
    if (!hasTrustedMaciDeployment()) missing.push('manifiesto on-chain del frontend');
    return {
        ready: missing.length === 0,
        missing,
        detail: typeof status.detail === 'string' ? status.detail : '',
    };
};

const VotingBallot = ({ walletAddress, chainId, eip1193Provider }) => {
    const walletSessionKey = `${walletAddress?.trim().toLowerCase() || ''}:${
        chainId == null ? '' : String(chainId)
    }`;
    const [proposals, setProposals] = useState([]);
    const [readiness, setReadiness] = useState({
        ready: false,
        missing: [],
        detail: '',
    });
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState('');
    const [proposalId, setProposalId] = useState('');
    const [choice, setChoice] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState('');
    const [cryptoState, setCryptoState] = useState(null);
    const voterKeypairRef = useRef(null);
    const pendingBallotRef = useRef(null);
    const submittingRef = useRef(false);
    const activeOperationRef = useRef(null);
    const walletSessionRef = useRef(walletSessionKey);
    const cryptoPhaseRef = useRef(null);
    const mountedRef = useRef(true);

    const loadBallot = useCallback(async () => {
        setLoading(true);
        setLoadError('');
        try {
            const [proposalResponse, statusResponse] = await Promise.all([
                governanceAPI.getProposals('active'),
                maciAPI.getStatus(),
            ]);
            if (!mountedRef.current) return;
            const activeProposals = Array.isArray(proposalResponse.data)
                ? proposalResponse.data.filter((proposal) => proposal.status === 'active')
                : [];
            setProposals(activeProposals);
            setReadiness(getMaciReadiness(statusResponse));
        } catch (loadFailure) {
            if (!mountedRef.current) return;
            setLoadError(getApiError(loadFailure));
            setProposals([]);
            setReadiness({ ready: false, missing: ['servicio MACI'], detail: '' });
        } finally {
            if (mountedRef.current) setLoading(false);
        }
    }, []);

    useEffect(() => {
        mountedRef.current = true;
        loadBallot();
        return () => {
            mountedRef.current = false;
            activeOperationRef.current = null;
            voterKeypairRef.current = null;
            pendingBallotRef.current = null;
        };
    }, [loadBallot]);

    useEffect(() => {
        // A MACI key and an ambiguous transport retry belong to exactly one
        // wallet + chain session. Never carry either across accountsChanged or
        // chainChanged, and invalidate an in-flight async submit immediately.
        walletSessionRef.current = walletSessionKey;
        activeOperationRef.current = null;
        submittingRef.current = false;
        voterKeypairRef.current = null;
        pendingBallotRef.current = null;
        setProposalId('');
        setChoice('');
        setError('');
        setCryptoState(null);
        cryptoPhaseRef.current = null;
        setSubmitting(false);
    }, [eip1193Provider, walletSessionKey]);

    const selectedProposal = useMemo(
        () => proposals.find((proposal) => String(proposal.id) === proposalId) || null,
        [proposalId, proposals]
    );

    const canSubmit = Boolean(
        walletAddress &&
        chainId != null &&
        eip1193Provider &&
        typeof eip1193Provider.request === 'function' &&
        readiness.ready &&
        selectedProposal &&
        choice &&
        proposalStillOpen(selectedProposal) &&
        !submitting
    );

    const handleProposalChange = (event) => {
        setProposalId(event.target.value);
        setChoice('');
        setError('');
        setCryptoState(null);
        cryptoPhaseRef.current = null;
        pendingBallotRef.current = null;
    };

    const handleSubmit = async (event) => {
        event.preventDefault();
        if (submittingRef.current || !canSubmit) return;
        if (!proposalStillOpen(selectedProposal)) {
            setError('La propuesta cerró antes de cifrar la papeleta.');
            return;
        }

        submittingRef.current = true;
        const operationToken = {};
        const submittedSessionKey = walletSessionKey;
        activeOperationRef.current = operationToken;
        const assertCurrentSession = () => {
            if (
                !mountedRef.current ||
                walletSessionRef.current !== submittedSessionKey ||
                activeOperationRef.current !== operationToken
            ) {
                throw new Error('La wallet o la red cambió durante el envío de la papeleta.');
            }
        };
        setSubmitting(true);
        setError('');
        setCryptoState(null);
        cryptoPhaseRef.current = null;
        let dispatchAttempted = false;
        const advanceCryptoPhase = (status, extra = {}) => {
            cryptoPhaseRef.current = status;
            if (mountedRef.current) setCryptoState({ status, ...extra });
        };
        try {
            let ballotPayload = null;
            const pending = pendingBallotRef.current;
            if (
                pending?.proposalId === String(selectedProposal.id) &&
                pending?.choice === choice &&
                pending?.walletSessionKey === submittedSessionKey
            ) {
                // A timeout after transport must retry the exact same
                // ciphertext and idempotency key, never create another vote.
                ballotPayload = pending.payload;
                advanceCryptoPhase('retrying_same');
            } else {
                // Load ~400 kB of MACI/BabyJub/Poseidon only for an actual
                // ballot; browsing proposals must not pay that bundle cost.
                advanceCryptoPhase('preparing_key');
                const {
                    createBallotIdempotencyKey,
                    createMaciKeypair,
                    encryptMaciBallot,
                    getMaciPublicKey,
                    normalizeMaciVotingConfig,
                    verifyMaciCoordinatorOnChain,
                } = await import('../../lib/maci');
                assertCurrentSession();
                const voterKeypair =
                    voterKeypairRef.current || await createMaciKeypair();
                assertCurrentSession();
                voterKeypairRef.current = voterKeypair;
                const voterPublicKey = getMaciPublicKey(voterKeypair);

                // Registration remains SIWE-bound. The subsequent ciphertext
                // uses the separate bearer-free transport in api.js.
                advanceCryptoPhase('registering_key');
                await maciAPI.registerKey(walletAddress, voterPublicKey);
                assertCurrentSession();
                advanceCryptoPhase('loading_poll');
                const configResponse = await maciAPI.getVotingConfig(selectedProposal.id);
                assertCurrentSession();
                const config = normalizeMaciVotingConfig(configResponse, {
                    proposalId: selectedProposal.id,
                    chainId,
                });
                advanceCryptoPhase('verifying_coordinator');
                await verifyMaciCoordinatorOnChain({
                    config,
                    ethereum: eip1193Provider,
                });
                assertCurrentSession();
                if (!proposalStillOpen(selectedProposal)) {
                    throw new Error('La propuesta cerró antes de publicar el mensaje cifrado.');
                }
                advanceCryptoPhase('encrypting');
                const encryptedBallot = await encryptMaciBallot({
                    voterKeypair,
                    config,
                    choice,
                });
                assertCurrentSession();
                ballotPayload = {
                    ...encryptedBallot,
                    idempotencyKey: createBallotIdempotencyKey(),
                };
                pendingBallotRef.current = {
                    proposalId: String(selectedProposal.id),
                    choice,
                    walletSessionKey: submittedSessionKey,
                    payload: ballotPayload,
                };
            }
            assertCurrentSession();
            if (cryptoPhaseRef.current !== 'retrying_same') {
                advanceCryptoPhase('publishing');
            }
            dispatchAttempted = true;
            const response = await maciAPI.submitEncryptedBallot(ballotPayload);
            assertCurrentSession();
            const ballotReceipt = normalizeEncryptedBallotReceipt(response);
            if (!mountedRef.current) return;
            pendingBallotRef.current = null;
            advanceCryptoPhase('received', {
                messageId: ballotReceipt.messageId,
                messageIndex: ballotReceipt.index,
                duplicate: ballotReceipt.duplicate,
            });
            setChoice('');
        } catch (submitError) {
            const isCurrentOperation =
                mountedRef.current &&
                walletSessionRef.current === submittedSessionKey &&
                activeOperationRef.current === operationToken;
            if (isCurrentOperation) {
                // Only an ambiguous transport failure may reuse an identical
                // ciphertext. A backend rejection needs a fresh poll/config.
                const definitiveRejection = isDefinitiveBallotRejection(submitError);
                if (definitiveRejection) {
                    pendingBallotRef.current = null;
                }
                const errorMessage = getApiError(
                    submitError,
                    'No fue posible contactar la urna. Puedes reintentar sin crear otra papeleta.'
                );
                setError(errorMessage);
                if (dispatchAttempted && !definitiveRejection) {
                    setCryptoState({
                        status: 'delivery_unknown',
                        lastStatus: cryptoPhaseRef.current,
                    });
                } else {
                    setCryptoState({
                        status: 'failed',
                        lastStatus: cryptoPhaseRef.current,
                        errorMessage,
                    });
                }
            }
        } finally {
            if (activeOperationRef.current === operationToken) {
                activeOperationRef.current = null;
                submittingRef.current = false;
                if (mountedRef.current) setSubmitting(false);
            }
        }
    };

    return (
        <section className="civic-ballot" aria-labelledby="private-ballot-title">
            <div className="civic-ballot-heading">
                <div>
                    <p className="civic-eyebrow">Urna privada</p>
                    <h2 id="private-ballot-title" className="civic-section-title">
                        <LockKeyhole className="w-5 h-5" />
                        Emitir voto cifrado
                    </h2>
                    <p className="civic-muted civic-ballot-intro">
                        La preferencia se cifra en este dispositivo con la llave pública del
                        coordinador. El transporte recibe sólo el sobre MACI; la recepción no
                        demuestra inclusión ni un tally válido.
                    </p>
                </div>
                <span className={`civic-tag ${readiness.ready ? 'civic-tag-green' : 'civic-tag-amber'}`}>
                    {readiness.ready ? <ShieldCheck className="w-3 h-3" /> : <KeyRound className="w-3 h-3" />}
                    {readiness.ready ? 'Canal preparado' : 'Canal no disponible'}
                </span>
            </div>

            {loading ? (
                <div className="civic-loading" role="status">
                    <span className="civic-spinner" />
                    Consultando la urna…
                </div>
            ) : loadError ? (
                <div className="civic-note civic-note-error" role="alert">
                    <AlertTriangle className="w-4 h-4" />
                    <span>{loadError}</span>
                </div>
            ) : (
                <form onSubmit={handleSubmit} className="civic-ballot-form">
                    {!walletAddress && (
                        <div className="civic-note civic-note-info">
                            <KeyRound className="w-4 h-4" />
                            <span>Conecta y firma tu sesión de wallet para habilitar la urna.</span>
                        </div>
                    )}

                    {walletAddress && (!eip1193Provider || typeof eip1193Provider.request !== 'function') && (
                        <div className="civic-note civic-note-warn" role="status">
                            <AlertTriangle className="w-4 h-4" />
                            <span>La sesión no expone el proveedor fijado que debe verificar el coordinador on-chain.</span>
                        </div>
                    )}

                    {!readiness.ready && (
                        <div className="civic-note civic-note-warn" role="status">
                            <AlertTriangle className="w-4 h-4" />
                            <span>
                                El envío permanece bloqueado hasta verificar: {readiness.missing.join(', ')}.
                                {readiness.detail ? ` ${readiness.detail}` : ''}
                                {' '}No se enviará un voto alternativo en texto plano.
                            </span>
                        </div>
                    )}

                    <div>
                        <label htmlFor="maci-proposal" className="civic-label">
                            1. Propuesta
                        </label>
                        <select
                            id="maci-proposal"
                            name="proposal"
                            className="civic-field"
                            value={proposalId}
                            onChange={handleProposalChange}
                            disabled={!walletAddress || submitting || proposals.length === 0}
                        >
                            <option value="">Selecciona una propuesta activa</option>
                            {proposals.map((proposal) => (
                                <option key={proposal.id} value={String(proposal.id)}>
                                    {proposal.title}
                                </option>
                            ))}
                        </select>
                        {proposals.length === 0 && (
                            <p className="civic-help">No hay propuestas abiertas en este momento.</p>
                        )}
                    </div>

                    <fieldset disabled={!selectedProposal || !readiness.ready || submitting}>
                        <legend className="civic-label">2. Preferencia</legend>
                        <div className="civic-ballot-options">
                            {CHOICES.map((option) => (
                                <label
                                    key={option.value}
                                    className={`civic-ballot-option ${choice === option.value ? 'is-selected' : ''}`}
                                >
                                    <input
                                        type="radio"
                                        name="choice"
                                        value={option.value}
                                        checked={choice === option.value}
                                        onChange={(event) => {
                                            setChoice(event.target.value);
                                            setError('');
                                            setCryptoState(null);
                                            cryptoPhaseRef.current = null;
                                            pendingBallotRef.current = null;
                                        }}
                                    />
                                    <span>
                                        <strong>{option.label}</strong>
                                        <small>{option.description}</small>
                                    </span>
                                </label>
                            ))}
                        </div>
                    </fieldset>

                    <div className="civic-ballot-privacy">
                        <ShieldCheck className="w-4 h-4" />
                        <span>
                            El registro SIWE asocia tu wallet sólo con la llave pública MACI.
                            La llave privada permanece en esta pestaña y el sobre cifrado se
                            publica después por un transporte sin credenciales.
                        </span>
                    </div>

                    <div className="civic-note civic-note-info">
                        <AlertTriangle className="w-4 h-4" />
                        <span>
                            Piloto no vinculante: el coordinador descifra para procesar el
                            tally y todavía debes verificar inclusión y prueba final.
                        </span>
                    </div>

                    <MaciBallotProgress state={cryptoState} />

                    {error && (
                        <div className="civic-note civic-note-error" role="alert">
                            <AlertTriangle className="w-4 h-4" />
                            <span>{error}</span>
                        </div>
                    )}
                    <button
                        type="submit"
                        className="civic-btn civic-btn-primary civic-ballot-submit"
                        disabled={!canSubmit}
                        aria-busy={submitting}
                    >
                        {submitting ? <span className="civic-spinner civic-spinner-light" /> : <Send className="w-4 h-4" />}
                        {submitting
                            ? cryptoState?.status === 'publishing' || cryptoState?.status === 'retrying_same'
                                ? 'Publicando sobre cifrado…'
                                : 'Blindando papeleta…'
                            : 'Blindar y enviar papeleta'}
                    </button>
                </form>
            )}
        </section>
    );
};

export default VotingBallot;
