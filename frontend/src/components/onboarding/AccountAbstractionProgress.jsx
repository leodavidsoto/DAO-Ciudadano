import React from 'react';
import { AlertTriangle, Check, Landmark, Loader2, ShieldCheck } from 'lucide-react';

const PHASE_CONTENT = Object.freeze({
    checking_config: {
        title: 'Activando canal subsidiado',
        detail: 'Verificando la red y la disponibilidad del servicio de patrocinio.',
        milestone: 0,
    },
    deriving_safe: {
        title: 'Empaquetando la solicitud',
        detail: 'Preparando una operación de cuenta inteligente ligada a tu wallet.',
        milestone: 0,
    },
    requesting_sponsorship: {
        title: 'Solicitando estimación y patrocinio',
        detail: 'El Bundler estima la operación y el Paymaster evalúa su cobertura antes de pedir tu autorización.',
        milestone: 0,
    },
    awaiting_authorization: {
        title: 'Autorización personal requerida',
        detail: 'MetaMask firmará una UserOperation de tu cuenta inteligente. No es una transacción tradicional y no requiere ETH.',
        milestone: 1,
    },
    submitting_user_operation: {
        title: 'Enviando operación al Bundler',
        detail: 'La autorización firmada se despacha una sola vez para su empaquetado.',
        milestone: 2,
    },
    submission_unknown: {
        title: 'Recepción por confirmar',
        detail: 'Intentamos enviar la autorización, pero no pudimos confirmar si el Bundler la recibió. No vuelvas a autorizar.',
        milestone: 2,
    },
    bundler_pending: {
        title: 'Operación recibida por el Bundler',
        detail: 'Esperando inclusión y confirmación on-chain. No vuelvas a autorizar.',
        milestone: 2,
    },
    integrity_error: {
        title: 'Verificación de integridad detenida',
        detail: 'La respuesta recibida no coincide con la operación autorizada. No vuelvas a autorizar hasta revisar este incidente.',
        milestone: 2,
    },
    confirmed: {
        title: 'Emisión confirmada',
        detail: 'La credencial ya tiene una transacción verificable en la red.',
        milestone: 3,
    },
});

const MILESTONES = Object.freeze([
    'Patrocinio',
    'Autorización',
    'Bundler',
    'Confirmación',
]);

const AccountAbstractionProgress = ({ state }) => {
    const phase = PHASE_CONTENT[state?.status] || PHASE_CONTENT.checking_config;
    const isConfirmed = state?.status === 'confirmed';
    const isIntegrityError = state?.status === 'integrity_error';
    const isUncertainTerminal =
        state?.status === 'submission_unknown' || Boolean(state?.timedOut);
    const isActive = !isConfirmed && !isIntegrityError && !isUncertainTerminal;
    const hasValidatedSponsorship = phase.milestone > 0 || isConfirmed;
    const displayedHash =
        state?.userOperationHash || state?.expectedUserOperationHash;
    const title = state?.timedOut
        ? 'Confirmación aún pendiente'
        : phase.title;
    const detail = state?.timedOut
        ? 'El Bundler ya recibió la operación. Conservamos su identificador y no la reenviamos automáticamente.'
        : phase.detail;

    return (
        <section
            className="civic-aa-terminal"
            aria-label="Estado de la emisión subsidiada"
            data-aa-status={state?.status}
        >
            <header className="civic-aa-header">
                <span className="civic-aa-seal" aria-hidden="true">
                    <Landmark />
                </span>
                <span
                    className="civic-aa-heading"
                    role="status"
                    aria-live="polite"
                    aria-atomic="true"
                >
                    <span className="civic-aa-kicker">Canal de emisión subsidiada</span>
                    <strong>{title}</strong>
                    <span>{detail}</span>
                </span>
                <span
                    className={`civic-aa-signal ${
                        isConfirmed
                            ? 'is-confirmed'
                            : isIntegrityError
                                ? 'is-error'
                                : isActive
                                    ? 'is-active'
                                    : 'is-warning'
                    }`}
                    aria-hidden="true"
                >
                    {isConfirmed
                        ? <ShieldCheck />
                        : isActive
                            ? <Loader2 />
                            : <AlertTriangle />}
                </span>
            </header>

            {hasValidatedSponsorship && (
                <p className="civic-aa-sponsorship">
                    <ShieldCheck aria-hidden="true" />
                    Costo de red cubierto{state?.chainName ? ` · ${state.chainName}` : ''}
                </p>
            )}

            <ol className="civic-aa-rail" aria-label="Progreso de la emisión subsidiada">
                {MILESTONES.map((label, index) => {
                    const isComplete = isConfirmed || index < phase.milestone;
                    const isMilestoneActive = isActive && index === phase.milestone;
                    return (
                        <li
                            key={label}
                            className={
                                isComplete
                                    ? 'is-complete'
                                    : isMilestoneActive
                                        ? 'is-active'
                                        : ''
                            }
                            aria-current={isMilestoneActive ? 'step' : undefined}
                        >
                            <span className="civic-aa-marker" aria-hidden="true">
                                {isComplete ? <Check /> : index + 1}
                            </span>
                            <span>{label}</span>
                        </li>
                    );
                })}
            </ol>

            {displayedHash && (
                <div className="civic-aa-identifier">
                    <span>
                        {state?.userOperationHash
                            ? 'Identificador UserOp'
                            : 'Identificador UserOp previsto'}
                    </span>
                    <code>{displayedHash}</code>
                </div>
            )}
        </section>
    );
};

export default AccountAbstractionProgress;
