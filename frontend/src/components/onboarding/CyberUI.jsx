/**
 * Primitivas de interfaz compartidas por el flujo de alta.
 *
 * El nombre del archivo y de los componentes es histórico (venían del tema
 * cyberpunk). El aspecto ya es el cívico de la landing: fondo claro, azul
 * #003897 y rojo #CB2C27 (ver styles/civic.css). Se conservan los nombres
 * exportados para no tocar los once pasos que los importan, donde vive la
 * lógica delicada de NFC, liveness, wallet y minteo.
 */
import React from 'react';
import { CheckCircle2, Loader2, AlertTriangle } from 'lucide-react';

// Indicador de paso
export const CyberStep = ({ n, title, active = false, done = false }) => (
    <div className="cyber-step">
        <div className={`cyber-step-number ${done ? 'completed' : active ? 'active' : 'pending'}`}>
            {done ? <CheckCircle2 className="h-4 w-4" /> : n}
        </div>
        <span className={`cyber-step-title ${done ? 'completed' : active ? 'active' : ''}`}>
            {title}
        </span>
    </div>
);

// Panel de contenido
export const CyberPanel = ({ title, icon, description, children, className = "" }) => (
    <section className={`civic-card ${className}`}>
        <div className="civic-card-pad" style={{ padding: 24 }}>
            <div className="flex items-start gap-4 mb-6">
                {icon && (
                    <span
                        className="flex items-center justify-center rounded-lg shrink-0"
                        style={{ width: 46, height: 46, background: '#EAF0FB', color: '#003897' }}
                    >
                        {icon}
                    </span>
                )}
                <div className="flex-1 min-w-0">
                    <h2
                        className="civic-ink font-bold mb-1"
                        style={{ fontFamily: 'Poppins, sans-serif', fontSize: 19 }}
                    >
                        {title}
                    </h2>
                    {description && (
                        <p className="civic-muted text-sm">{description}</p>
                    )}
                </div>
            </div>
            {children}
        </div>
    </section>
);

// Indicador de carga
export const CyberLoader = ({ text = "Procesando…" }) => (
    <div className="flex items-center gap-3">
        <Loader2 className="w-4 h-4 animate-spin" style={{ color: '#003897' }} />
        <span className="civic-muted text-sm">{text}</span>
    </div>
);

// Barra de progreso del flujo
export const ProgressBar = ({ progress }) => (
    <div className="mb-8">
        <div className="civic-bar">
            <div className="civic-bar-blue" style={{ width: `${progress}%` }} />
        </div>
        <p className="civic-muted text-xs mt-2 text-center">
            Progreso: {progress}% completado
        </p>
    </div>
);

// Error
export const ErrorDisplay = ({ error }) => {
    if (!error) return null;

    return (
        <div className="civic-note civic-note-error mb-6" role="alert">
            <AlertTriangle className="w-4 h-4" />
            <span>{error}</span>
        </div>
    );
};

// Éxito
export const SuccessDisplay = ({ children }) => (
    <div className="civic-note civic-note-ok" style={{ display: 'block', textAlign: 'center' }}>
        <CheckCircle2 className="w-8 h-8 mx-auto mb-2" />
        {children}
    </div>
);

// Marca visible de los pasos cuya verificación aún es simulada.
// Retirar cada uso cuando el flujo real correspondiente entre en producción
// (ver ROADMAP Fase 1/4).
export const DemoBadge = ({ label = "Modo demo — verificación simulada" }) => (
    <div className="civic-note civic-note-warn mb-6" role="status">
        <AlertTriangle className="w-4 h-4" />
        <span>{label}</span>
    </div>
);
