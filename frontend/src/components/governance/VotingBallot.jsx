import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    AlertTriangle,
    CheckCircle2,
    KeyRound,
    LockKeyhole,
    Send,
    ShieldCheck,
} from 'lucide-react';
import { governanceAPI, maciAPI } from '../../lib/api';

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
    return ![408, 409, 425, 429].includes(status);
};

const getMaciReadiness = (response) => {
    const status = response?.data ?? response ?? {};
    const missing = [];
    if (status.key_registry !== true) missing.push('registro de llaves');
    if (status.private_voting !== true) missing.push('votación privada');
    if (status.coordinator_configured !== true) missing.push('coordinador MACI');
    if (status.tally_proof !== true) missing.push('verificación del tally');
    if (!hasTrustedMaciDeployment()) missing.push('manifiesto on-chain del frontend');
    return {
        ready: missing.length === 0,
        missing,
        detail: typeof status.detail === 'string' ? status.detail : '',
    };
};

const VotingBallot = ({ walletAddress, chainId }) => {
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
    const [receipt, setReceipt] = useState(null);
    const voterKeypairRef = useRef(null);
    const pendingBallotRef = useRef(null);
    const submittingRef = useRef(false);
    const activeOperationRef = useRef(null);
    const walletSessionRef = useRef(walletSessionKey);
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
        setReceipt(null);
        setSubmitting(false);
    }, [walletSessionKey]);

    const selectedProposal = useMemo(
        () => proposals.find((proposal) => String(proposal.id) === proposalId) || null,
        [proposalId, proposals]
    );

    const canSubmit = Boolean(
        walletAddress &&
        chainId != null &&
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
        setReceipt(null);
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
        setReceipt(null);
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
            } else {
                // Load ~400 kB of MACI/BabyJub/Poseidon only for an actual
                // ballot; browsing proposals must not pay that bundle cost.
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
                await maciAPI.registerKey(walletAddress, voterPublicKey);
                assertCurrentSession();
                const configResponse = await maciAPI.getVotingConfig(selectedProposal.id);
                assertCurrentSession();
                const config = normalizeMaciVotingConfig(configResponse, {
                    proposalId: selectedProposal.id,
                    chainId,
                });
                await verifyMaciCoordinatorOnChain({ config });
                assertCurrentSession();
                if (!proposalStillOpen(selectedProposal)) {
                    throw new Error('La propuesta cerró antes de publicar el mensaje cifrado.');
                }
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
            const response = await maciAPI.submitEncryptedBallot(ballotPayload);
            assertCurrentSession();
            const data = response?.data ?? response;
            if (!data || data.ok === false) {
                throw new Error(data?.error || 'La urna no confirmó la recepción del mensaje.');
            }
            const messageId = data.message_id || data.message_hash || data.tx_hash;
            if (typeof messageId !== 'string' || !messageId.trim()) {
                throw new Error('La urna respondió sin una referencia verificable del mensaje.');
            }
            if (!mountedRef.current) return;
            pendingBallotRef.current = null;
            setReceipt({ messageId });
            setChoice('');
        } catch (submitError) {
            const isCurrentOperation =
                mountedRef.current &&
                walletSessionRef.current === submittedSessionKey &&
                activeOperationRef.current === operationToken;
            if (isCurrentOperation) {
                // Only an ambiguous transport failure may reuse an identical
                // ciphertext. A backend rejection needs a fresh poll/config.
                if (isDefinitiveBallotRejection(submitError)) {
                    pendingBallotRef.current = null;
                }
                setError(getApiError(
                    submitError,
                    'No fue posible contactar la urna. Puedes reintentar sin crear otra papeleta.'
                ));
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
                        La papeleta se cifra en este dispositivo. El transporte recibe sólo
                        el ciphertext; el coordinador lo procesa dentro del tally verificable.
                    </p>
                </div>
                <span className={`civic-tag ${readiness.ready ? 'civic-tag-green' : 'civic-tag-amber'}`}>
                    {readiness.ready ? <ShieldCheck className="w-3 h-3" /> : <KeyRound className="w-3 h-3" />}
                    {readiness.ready ? 'Privacidad activa' : 'Verificación pendiente'}
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
                                            setReceipt(null);
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
                            La llave privada permanece sólo en esta sesión. No cierres esta
                            pantalla hasta recibir la referencia de tu mensaje cifrado.
                        </span>
                    </div>

                    {error && (
                        <div className="civic-note civic-note-error" role="alert">
                            <AlertTriangle className="w-4 h-4" />
                            <span>{error}</span>
                        </div>
                    )}
                    {receipt && (
                        <div className="civic-note civic-note-ok" role="status">
                            <CheckCircle2 className="w-4 h-4" />
                            <span>
                                Mensaje cifrado recibido por la urna.
                                {receipt.messageId
                                    ? ` Referencia ${String(receipt.messageId).slice(0, 18)}…`
                                    : ' Su inclusión y tally aún deben verificarse.'}
                            </span>
                        </div>
                    )}

                    <button
                        type="submit"
                        className="civic-btn civic-btn-primary civic-ballot-submit"
                        disabled={!canSubmit}
                        aria-busy={submitting}
                    >
                        {submitting ? <span className="civic-spinner civic-spinner-light" /> : <Send className="w-4 h-4" />}
                        {submitting ? 'Cifrando y enviando…' : 'Cifrar y enviar papeleta'}
                    </button>
                </form>
            )}
        </section>
    );
};

export default VotingBallot;
