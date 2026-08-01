/**
 * Flujo de verificación ciudadana (/unete).
 *
 * Rediseñado para continuar la identidad visual de la landing pública
 * (styles/landing.css): azul #003897, rojo #CB2C27, Poppins + Open Sans,
 * sobre fondo claro. Antes era un tema cyberpunk (cian sobre negro,
 * partículas, scanlines, lluvia matrix) que no tenía relación con la
 * portada — quien entraba desde "ÚNETE A LA RED" sentía que había
 * cambiado de sitio.
 *
 * Los componentes de cada paso NO se tocaron: siguen usando su vocabulario
 * de clases `cyber-*`, que styles/onboarding-estamosdao.css redefine
 * dentro del contenedor `.estamosdao-flow`. Así el rediseño no arriesga la
 * lógica del flujo (NFC, liveness, wallet, minteo), que es la parte
 * delicada.
 */
import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOnboarding } from '@/context';
import {
    CyberStep,
    ErrorDisplay,
    MethodSelector,
    CivicMethodSelector,
    ClaveUnicaStep,
    RegistrationStep,
    NFCStep,
    LivenessStep,
    ConsentStep,
    WalletStep,
    MintStep,
    SuccessStep,
    DashboardStep,
} from '@/components/onboarding';
import '../styles/onboarding-estamosdao.css';

const AZUL = '#003897';
const TINTA = '#0B2545';

/** Etapas visibles del recorrido. `match` son los `step` del contexto que
 *  caen en esa etapa; `after`, los que ya la dejaron atrás. */
const ETAPAS = [
    { n: 1, title: 'Método', match: ['method', 'registro'], after: ['clave', 'nfc', 'selfie', 'consent', 'wallet', 'mint', 'success', 'dashboard'] },
    { n: 2, title: 'Identidad', match: ['clave', 'nfc', 'selfie'], after: ['consent', 'wallet', 'mint', 'success', 'dashboard'] },
    { n: 3, title: 'Consentimiento', match: ['consent'], after: ['wallet', 'mint', 'success', 'dashboard'] },
    { n: 4, title: 'Billetera', match: ['wallet'], after: ['mint', 'success', 'dashboard'] },
    { n: 5, title: 'Credencial', match: ['mint'], after: ['success', 'dashboard'] },
];

const OnboardingPage = ({ appearance }) => {
    const { step, progress, error, loadStats } = useOnboarding();
    const navigate = useNavigate();

    useEffect(() => {
        loadStats();
    }, [loadStats]);

    const renderStep = () => {
        switch (step) {
            case 'method': return appearance === 'civic' ? <CivicMethodSelector /> : <MethodSelector />;
            case 'registro': return <RegistrationStep />;
            case 'clave': return <ClaveUnicaStep />;
            case 'nfc': return <NFCStep />;
            case 'selfie': return <LivenessStep />;
            case 'consent': return <ConsentStep />;
            case 'wallet': return <WalletStep />;
            case 'mint': return <MintStep />;
            case 'success': return <SuccessStep />;
            case 'dashboard': return <DashboardStep />;
            default: return <MethodSelector />;
        }
    };

    return (
        <div className={`estamosdao-flow ${appearance === 'civic' ? 'civic-onboarding' : ''}`}>
            {/* ===== Cabecera: misma marca y misma altura que la landing ===== */}
            <header
                style={{
                    position: 'sticky', top: 0, zIndex: 20, display: 'flex', alignItems: 'center',
                    gap: 16, padding: '14px clamp(22px, 4vw, 48px)',
                    background: 'rgba(255,255,255,0.94)', backdropFilter: 'blur(10px)',
                    borderBottom: '1px solid #E5EBF5',
                }}
            >
                <button
                    type="button"
                    onClick={() => navigate('/')}
                    aria-label="Volver al inicio"
                    style={{ display: 'flex', alignItems: 'center', gap: 12, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                >
                    <img
                        src="/assets/logo-mark.png"
                        alt="EstamosDAO Chile"
                        style={{ width: 42, height: 42, objectFit: 'contain', display: 'block' }}
                    />
                    <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1, textAlign: 'left' }}>
                        <span style={{ fontFamily: 'Poppins, sans-serif', fontSize: 19, letterSpacing: '-0.02em', color: TINTA }}>
                            Estamos<span style={{ fontWeight: 700, color: AZUL }}>DAO</span>
                        </span>
                        <span style={{ fontFamily: 'Poppins, sans-serif', fontSize: 9.5, fontWeight: 500, letterSpacing: '0.28em', color: '#5C7099', marginTop: 3 }}>
                            CHILE
                        </span>
                    </span>
                </button>

                <div style={{ flex: 1 }} />

                <button
                    type="button"
                    onClick={() => navigate('/')}
                    style={{
                        display: 'inline-flex', alignItems: 'center', gap: 8, cursor: 'pointer',
                        fontFamily: 'Poppins, sans-serif', fontSize: 12.5, fontWeight: 600,
                        letterSpacing: '0.06em', padding: '11px 20px', borderRadius: 999,
                        border: '1.5px solid #C2D2EC', background: 'rgba(255,255,255,0.7)', color: AZUL,
                    }}
                >
                    <i className="ph-bold ph-arrow-left" style={{ fontSize: 14 }} /> VOLVER AL INICIO
                </button>
            </header>

            <div style={{ maxWidth: 1080, margin: '0 auto', padding: 'clamp(28px, 5vw, 56px) clamp(22px, 4vw, 48px) 72px' }}>

                {/* ===== Título ===== */}
                <div style={{ textAlign: 'center', maxWidth: 640, margin: '0 auto' }}>
                    <div style={{
                        display: 'inline-flex', alignItems: 'center', gap: 9, background: '#ffffff',
                        border: '1px solid #DCE5F3', borderRadius: 999, padding: '7px 15px 7px 11px',
                        fontFamily: 'Poppins, sans-serif', fontSize: 11.5, fontWeight: 500,
                        letterSpacing: '0.06em', color: '#33456B', boxShadow: '0 2px 8px rgba(11,37,69,0.05)',
                    }}>
                        <i className="ph-bold ph-shield-check" style={{ fontSize: 14, color: AZUL }} />
                        UNA PERSONA, UN VOTO
                    </div>

                    <h1 style={{
                        fontFamily: 'Poppins, sans-serif', fontWeight: 600, fontSize: 'clamp(28px, 4.4vw, 42px)',
                        lineHeight: 1.12, letterSpacing: '-0.02em', color: AZUL, margin: '18px 0 0',
                    }}>
                        Verifica tu identidad
                    </h1>
                    <p style={{ fontSize: 16.5, lineHeight: 1.6, color: '#46536E', margin: '14px auto 0', maxWidth: 520 }}>
                        Una sola vez. Recibes una credencial que no se puede vender ni transferir,
                        y con ella participas en cada votación.
                    </p>
                </div>

                {/* ===== Indicador de etapas (escritorio) ===== */}
                <div
                    className="hidden lg:flex"
                    style={{ alignItems: 'center', justifyContent: 'center', gap: 18, marginTop: 40, flexWrap: 'wrap' }}
                >
                    {ETAPAS.map((e, i) => (
                        <React.Fragment key={e.n}>
                            <CyberStep
                                n={e.n}
                                title={e.title}
                                active={e.match.includes(step)}
                                done={e.after.includes(step)}
                            />
                            {i < ETAPAS.length - 1 && (
                                <span aria-hidden="true" style={{ width: 34, height: 0, borderTop: '2px dashed #C6D5EC' }} />
                            )}
                        </React.Fragment>
                    ))}
                </div>

                {/* ===== Progreso ===== */}
                <div style={{ marginTop: 34, maxWidth: 560, marginLeft: 'auto', marginRight: 'auto' }}>
                    <div className="cyber-progress-premium">
                        <div className="cyber-progress-premium-fill" style={{ width: `${progress}%` }} />
                    </div>
                    <p style={{
                        textAlign: 'center', fontFamily: 'Poppins, sans-serif', fontSize: 12,
                        color: '#6B7894', marginTop: 10, letterSpacing: '0.04em',
                    }}>
                        Progreso: <strong style={{ color: TINTA, fontWeight: 600 }}>{progress}%</strong>
                    </p>
                </div>

                <div style={{ marginTop: 26 }}>
                    <ErrorDisplay error={error} />
                </div>

                {/* ===== Paso actual ===== */}
                <div style={{ marginTop: 12 }}>
                    {renderStep()}
                </div>

                {/* ===== Pie ===== */}
                <footer style={{
                    marginTop: 56, paddingTop: 22, borderTop: '1px solid #E5EBF5',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 9,
                    fontSize: 13, color: '#8090AD', textAlign: 'center', flexWrap: 'wrap',
                }}>
                    <i className="ph ph-lock-simple" style={{ fontSize: 15 }} />
                    Tus datos se cifran antes de guardarse. EstamosDAO Chile · código abierto
                </footer>
            </div>
        </div>
    );
};

export default OnboardingPage;
