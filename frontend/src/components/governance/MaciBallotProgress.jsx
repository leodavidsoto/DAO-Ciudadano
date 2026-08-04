import React from 'react';
import {
    AlertTriangle,
    Check,
    Landmark,
    Loader2,
    ShieldCheck,
    XCircle,
} from 'lucide-react';

const PHASE_CONTENT = Object.freeze({
    preparing_key: {
        title: 'Preparando llave de votación',
        detail: 'La llave privada se genera localmente y permanece en esta pestaña.',
        milestone: 0,
    },
    registering_key: {
        title: 'Registrando llave pública',
        detail: 'La sesión registra solo la llave pública; tu preferencia todavía no se envía.',
        milestone: 0,
    },
    loading_poll: {
        title: 'Cargando parámetros del poll',
        detail: 'Comprobando plazo, nonce y opciones publicadas para esta consulta.',
        milestone: 1,
    },
    verifying_coordinator: {
        title: 'Verificando anclaje on-chain',
        detail: 'Contrastando red, coordinador y verificador de tally antes de cifrar.',
        milestone: 2,
    },
    encrypting: {
        title: 'Cifrando preferencia localmente',
        detail: 'La opción elegida se convierte en un mensaje MACI dentro de este dispositivo.',
        milestone: 3,
    },
    publishing: {
        title: 'Publicando mensaje cifrado',
        detail: 'Se envían únicamente el ciphertext y la llave pública efímera.',
        milestone: 4,
    },
    retrying_same: {
        title: 'Reintentando el mismo mensaje',
        detail: 'Se reutilizan el ciphertext y la clave de idempotencia; no se crea otra papeleta.',
        milestone: 4,
    },
    delivery_unknown: {
        title: 'Recepción sin confirmar',
        detail: 'No se pudo comprobar si la urna recibió el mensaje. No vuelvas a cifrar otra papeleta.',
        milestone: 4,
    },
    failed: {
        title: 'La papeleta no fue enviada',
        detail: 'El proceso se detuvo antes de obtener una referencia verificable.',
        milestone: 0,
    },
    received: {
        title: 'Mensaje cifrado recibido',
        detail: 'La referencia confirma recepción, no inclusión en el tally ni un resultado verificado.',
        milestone: 4,
    },
});

const ACTIVE_STATUSES = new Set([
    'preparing_key',
    'registering_key',
    'loading_poll',
    'verifying_coordinator',
    'encrypting',
    'publishing',
    'retrying_same',
]);

const MILESTONES = Object.freeze(['Llave', 'Poll', 'Anclaje', 'Cifrado', 'Urna']);

const getMilestoneLabel = ({ isComplete, isActive, isWarning, isError }) => {
    if (isComplete) return 'completo';
    if (isActive) return 'en curso';
    if (isWarning) return 'recepción por confirmar';
    if (isError) return 'interrumpido';
    return 'pendiente';
};

const MaciBallotProgress = ({ state }) => {
    const status = state?.status;
    const phase = PHASE_CONTENT[status];
    if (!phase) return null;

    const lastActivePhase = ACTIVE_STATUSES.has(state?.lastStatus)
        ? PHASE_CONTENT[state.lastStatus]
        : null;
    const milestone = status === 'failed' && lastActivePhase
        ? lastActivePhase.milestone
        : phase.milestone;
    const isReceived = status === 'received';
    const isFailed = status === 'failed';
    const isDeliveryUnknown = status === 'delivery_unknown';
    const isRetrying = status === 'retrying_same';
    const isActive = ACTIVE_STATUSES.has(status);
    const errorMessage = typeof state?.errorMessage === 'string'
        ? state.errorMessage.trim()
        : '';
    const detail = isFailed && errorMessage ? errorMessage : phase.detail;
    const messageId = typeof state?.messageId === 'string'
        ? state.messageId.trim()
        : '';
    const messageIndex = Number.isSafeInteger(state?.messageIndex) && state.messageIndex >= 0
        ? state.messageIndex
        : null;

    return (
        <section
            className="civic-maci-progress"
            aria-label="Estado de la papeleta cifrada"
            data-maci-status={status}
        >
            <header className="civic-maci-progress-header">
                <span className="civic-maci-progress-seal" aria-hidden="true">
                    <Landmark />
                </span>
                <span
                    className="civic-maci-progress-copy"
                    role={isFailed ? 'alert' : 'status'}
                    aria-live={isFailed ? 'assertive' : 'polite'}
                    aria-atomic="true"
                >
                    <span className="civic-maci-progress-kicker">Urna cifrada MACI</span>
                    <strong>{phase.title}</strong>
                    <span>{detail}</span>
                </span>
                <span
                    className={`civic-maci-progress-signal ${
                        isReceived
                            ? 'is-received'
                            : isFailed
                                ? 'is-failed'
                                : isDeliveryUnknown
                                    ? 'is-warning'
                                    : isRetrying
                                        ? 'is-retrying'
                                        : 'is-active'
                    }`}
                    aria-hidden="true"
                >
                    {isReceived
                        ? <ShieldCheck />
                        : isFailed
                            ? <XCircle />
                            : isDeliveryUnknown
                                ? <AlertTriangle />
                                : <Loader2 />}
                </span>
            </header>

            <ol className="civic-maci-rail" aria-label="Progreso de la papeleta cifrada">
                {MILESTONES.map((label, index) => {
                    const isComplete = isReceived || index < milestone;
                    const isMilestoneActive = isActive && index === milestone;
                    const isWarning = isDeliveryUnknown && index === milestone;
                    const isError = isFailed && index === milestone;
                    const className = isComplete
                        ? 'is-complete'
                        : isMilestoneActive
                            ? 'is-active'
                            : isWarning
                                ? 'is-warning'
                                : isError
                                    ? 'is-error'
                                    : '';

                    return (
                        <li
                            key={label}
                            className={className}
                            aria-current={isMilestoneActive ? 'step' : undefined}
                            aria-label={`${label}: ${getMilestoneLabel({
                                isComplete,
                                isActive: isMilestoneActive,
                                isWarning,
                                isError,
                            })}`}
                        >
                            <span className="civic-maci-marker" aria-hidden="true">
                                {isComplete ? <Check /> : index + 1}
                            </span>
                            <span>{label}</span>
                        </li>
                    );
                })}
            </ol>

            {messageId && (
                <div className="civic-maci-reference">
                    <span>Referencia del mensaje cifrado</span>
                    <code>{messageId}</code>
                    {messageIndex !== null && (
                        <small>Posición confirmada en la cola: {messageIndex}</small>
                    )}
                </div>
            )}
        </section>
    );
};

export default MaciBallotProgress;
