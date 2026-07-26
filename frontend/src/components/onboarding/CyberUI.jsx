/**
 * Shared Cyber UI Components
 * Reusable cyberpunk-styled components
 */
import React from 'react';
import { CheckCircle2, Terminal, Loader2, AlertTriangle } from 'lucide-react';
import { Card, CardContent } from '../ui/card';

// Cyberpunk Step Indicator
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

// Cyberpunk Panel
export const CyberPanel = ({ title, icon, description, children, className = "" }) => (
    <Card className={`cyber-card ${className}`}>
        <CardContent className="p-6">
            <div className="flex items-start gap-4 mb-6">
                <div className="text-cyan-400 cyber-icon">
                    {icon}
                </div>
                <div className="flex-1">
                    <h2 className="cyber-title text-xl font-bold tracking-wider mb-2" data-text={title}>
                        {title}
                    </h2>
                    {description && (
                        <p className="text-gray-400 text-sm font-mono">
                            <Terminal className="inline w-3 h-3 mr-2" />
                            {description}
                        </p>
                    )}
                </div>
            </div>
            {children}
        </CardContent>
    </Card>
);

// Cyberpunk Loader
export const CyberLoader = ({ text = "PROCESANDO..." }) => (
    <div className="flex items-center gap-3">
        <div className="cyber-spinner"></div>
        <span className="font-mono text-cyan-400 text-sm animate-pulse">
            {text}
        </span>
    </div>
);

// Progress Bar
export const ProgressBar = ({ progress }) => (
    <div className="mb-8">
        <div className="cyber-progress">
            <div className="cyber-progress-fill" style={{ width: `${progress}%` }}></div>
        </div>
        <p className="text-center text-cyan-400 font-mono text-xs mt-2">
            PROGRESO: {progress}% COMPLETADO
        </p>
    </div>
);

// Error Display
export const ErrorDisplay = ({ error }) => {
    if (!error) return null;

    return (
        <div className="cyber-error mb-6">
            <strong>ERROR:</strong> {error}
        </div>
    );
};

// Success Display
export const SuccessDisplay = ({ children }) => (
    <div className="cyber-success text-center p-4 rounded-lg">
        <CheckCircle2 className="w-8 h-8 mx-auto mb-2" />
        {children}
    </div>
);

// Demo Mode Badge — marca visiblemente los pasos cuya verificación aún es simulada.
// Retirar cada uso cuando el flujo real correspondiente entre en producción (ver ROADMAP Fase 1/4).
export const DemoBadge = ({ label = "MODO DEMO — verificación simulada" }) => (
    <div
        className="flex items-center gap-2 mb-6 px-3 py-2 rounded-md border border-yellow-500/40 bg-yellow-500/10"
        role="status"
    >
        <AlertTriangle className="w-4 h-4 text-yellow-400 shrink-0" />
        <span className="text-yellow-300 text-xs font-mono tracking-wide">
            {label}
        </span>
    </div>
);

