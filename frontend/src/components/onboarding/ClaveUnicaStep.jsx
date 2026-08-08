import React from 'react';
import { useOnboarding } from '@/context';

const ACTIVE_STATES = new Set([
    'checking',
    'starting',
    'redirecting',
    'validating',
]);

const STATUS_COPY = {
    checking: {
        title: 'Comprobando el canal oficial',
        detail: 'Verificamos PKCE S256, binding hasta el canje final y grant de un solo uso.',
    },
    starting: {
        title: 'Preparando autorización protegida',
        detail: 'El backend está creando un intento OIDC de vigencia corta.',
    },
    redirecting: {
        title: 'Abriendo ClaveÚnica',
        detail: 'Continúa únicamente en el dominio oficial que abrirá tu navegador.',
    },
    validating: {
        title: 'Validando el retorno criptográfico',
        detail: 'Comprobamos state, binding de pestaña, firma del proveedor y vigencia.',
    },
};

const ClaveUnicaStep = () => {
    const {
        claveUnicaFlow,
        authenticateClaveUnica,
        setStep,
    } = useOnboarding();
    const isActive = ACTIVE_STATES.has(claveUnicaFlow.status);
    const statusCopy = STATUS_COPY[claveUnicaFlow.status];

    return (
        <section className="civic-oidc" aria-labelledby="clave-unica-title">
            <div className="civic-card civic-card-pad civic-oidc-panel">
                <div className="civic-oidc-heading">
                    <div className="civic-oidc-seal" aria-hidden="true">
                        <i className="ph-bold ph-shield-check" />
                    </div>
                    <div>
                        <span className="civic-eyebrow">Canal de identidad estatal</span>
                        <h2 id="clave-unica-title">Acceso con ClaveÚnica</h2>
                        <p>
                            Serás redirigido al proveedor oficial. EstamosDAO nunca solicita,
                            procesa ni almacena tu contraseña de ClaveÚnica.
                        </p>
                    </div>
                </div>

                <div className="civic-oidc-rail" aria-label="Garantías del acceso">
                    <div>
                        <i className="ph-bold ph-key" aria-hidden="true" />
                        <span><strong>PKCE S256</strong> protege el código de autorización.</span>
                    </div>
                    <div>
                        <i className="ph-bold ph-browser" aria-hidden="true" />
                        <span><strong>Mismo navegador</strong> para iniciar, retornar y canjear el grant.</span>
                    </div>
                    <div>
                        <i className="ph-bold ph-eraser" aria-hidden="true" />
                        <span><strong>Retorno efímero</strong> eliminado de la barra de direcciones.</span>
                    </div>
                </div>

                {statusCopy && (
                    <div className="civic-loading civic-oidc-loading" role="status" aria-live="polite">
                        <span className="civic-spinner" aria-hidden="true" />
                        <span className="civic-loading-copy">
                            <span className="civic-loading-title">{statusCopy.title}</span>
                            <span className="civic-loading-detail">{statusCopy.detail}</span>
                        </span>
                    </div>
                )}

                {!isActive && claveUnicaFlow.status === 'error' && (
                    <div className="civic-note civic-note-error" role="alert">
                        <i className="ph-bold ph-warning-octagon" aria-hidden="true" />
                        <span>
                            El acceso permanece bloqueado. No se usará una simulación ni un
                            proveedor degradado como reemplazo.
                        </span>
                    </div>
                )}

                <div className="civic-oidc-actions">
                    <button
                        type="button"
                        className="civic-btn civic-btn-primary"
                        onClick={authenticateClaveUnica}
                        disabled={isActive}
                    >
                        <i className="ph-bold ph-sign-in" aria-hidden="true" />
                        {claveUnicaFlow.status === 'error'
                            ? 'REINTENTAR CON CLAVEÚNICA'
                            : 'CONTINUAR A CLAVEÚNICA'}
                    </button>
                    <button
                        type="button"
                        className="civic-btn civic-btn-quiet"
                        onClick={() => setStep('method')}
                        disabled={isActive}
                    >
                        VOLVER A MÉTODOS
                    </button>
                </div>

                <p className="civic-oidc-privacy">
                    <i className="ph-bold ph-lock-key" aria-hidden="true" />
                    El grant civil no se escribe en la URL, sessionStorage ni localStorage;
                    permanece en memoria hasta su canje único después de SIWE.
                </p>
            </div>
        </section>
    );
};

export default ClaveUnicaStep;
