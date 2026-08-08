import React from 'react';
import { useOnboarding } from '@/context';

const ConsentStep = () => {
    const { clave, setStep } = useOnboarding();
    const hasVerifiedClaveUnica =
        clave.authenticated === true && clave.assurance_level === 'CLAVE_UNICA';

    return (
        <section className="civic-consent" aria-labelledby="identity-summary-title">
            <div className="civic-card civic-card-pad civic-consent-panel">
                <span className="civic-eyebrow">Resumen verificable</span>
                <h2 id="identity-summary-title" className="civic-section-title">
                    Estado de la acreditación
                </h2>

                {hasVerifiedClaveUnica ? (
                    <div className="civic-note civic-note-ok" role="status">
                        <i className="ph-bold ph-seal-check" aria-hidden="true" />
                        <span>
                            ClaveÚnica confirmó el acceso mediante el canal OIDC protegido.
                            El grant civil está en memoria y aún debe ligarse a tu wallet con SIWE.
                        </span>
                    </div>
                ) : (
                    <div className="civic-note civic-note-warn" role="status">
                        <i className="ph-bold ph-warning" aria-hidden="true" />
                        <span>
                            Este recorrido no acreditó identidad civil. No existe un grant válido
                            para emitir la credencial ciudadana.
                        </span>
                    </div>
                )}

                <div className="civic-consent-grid">
                    <div>
                        <h3>
                            <i className="ph-bold ph-lock-key" aria-hidden="true" />
                            Garantías activas
                        </h3>
                        <ul>
                            <li>El código y state OIDC se retiraron de la URL antes del canje.</li>
                            <li>El grant no se persiste en almacenamiento web.</li>
                            <li>La wallet deberá demostrar control mediante SIWE.</li>
                            <li>La prueba ZK se generará localmente antes de una emisión.</li>
                        </ul>
                    </div>
                    <div>
                        <h3>
                            <i className="ph-bold ph-warning-circle" aria-hidden="true" />
                            Límites vigentes
                        </h3>
                        <ul>
                            <li>NFC web e imagen continúan como demostraciones sin assurance civil.</li>
                            <li>El piloto aún no es una credencial de identidad civil.</li>
                            <li>Faltan evaluación legal, despliegue compatible y operación productiva.</li>
                            <li>La emisión falla cerrada si alguna dependencia no está provisionada.</li>
                        </ul>
                    </div>
                </div>

                <div className="civic-oidc-actions">
                    {hasVerifiedClaveUnica ? (
                        <button
                            type="button"
                            onClick={() => setStep('wallet')}
                            className="civic-btn civic-btn-primary"
                        >
                            <i className="ph-bold ph-wallet" aria-hidden="true" />
                            CONTINUAR A LA WALLET
                        </button>
                    ) : (
                        <button
                            type="button"
                            onClick={() => setStep('clave')}
                            className="civic-btn civic-btn-primary"
                        >
                            <i className="ph-bold ph-shield-check" aria-hidden="true" />
                            ACREDITAR CON CLAVEÚNICA
                        </button>
                    )}
                    <button
                        type="button"
                        onClick={() => setStep('method')}
                        className="civic-btn civic-btn-quiet"
                    >
                        REVISAR MÉTODOS
                    </button>
                </div>
            </div>
        </section>
    );
};

export default ConsentStep;
