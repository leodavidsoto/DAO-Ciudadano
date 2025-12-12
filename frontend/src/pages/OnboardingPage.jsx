/**
 * OnboardingPage with Premium Effects
 * Full onboarding flow for DAO citizenship with enhanced UI
 */
import React, { useEffect } from 'react';
import { Shield } from 'lucide-react';
import { useOnboarding, STEPS } from '@/context';
import {
    CyberStep,
    ProgressBar,
    ErrorDisplay,
    MethodSelector,
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
import {
    ParticlesBackground,
    ScanlineOverlay,
    TypingText
} from '@/components/effects';

const OnboardingPage = () => {
    const { step, progress, error, loadStats } = useOnboarding();

    // Load stats on mount
    useEffect(() => {
        loadStats();
    }, [loadStats]);

    // Render the current step component
    const renderStep = () => {
        switch (step) {
            case 'method': return <MethodSelector />;
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
        <div className="min-h-screen relative overflow-hidden">
            {/* Premium Background Effects */}
            <ParticlesBackground count={40} />
            <ScanlineOverlay opacity={0.05} />

            {/* Matrix Rain Background Effect */}
            <div className="matrix-rain"></div>

            <div className="mx-auto max-w-6xl px-4 py-8 relative z-10">
                {/* Cyberpunk Header with Premium Styling */}
                <header className="mb-10 text-center">
                    <div className="flex items-center justify-center gap-4 mb-4">
                        {/* Animated Logo */}
                        <div className="w-14 h-14 rounded-full bg-gradient-to-r from-cyan-400 via-purple-500 to-pink-500 flex items-center justify-center hover-scale corner-decoration p-0.5">
                            <div className="w-full h-full rounded-full bg-cyber-dark flex items-center justify-center">
                                <Shield className="h-7 w-7 text-cyan-400 icon-pulse" />
                            </div>
                        </div>

                        <div>
                            <h1 className="cyber-title text-3xl md:text-4xl font-black tracking-wider" data-text="DAO CIUDADANA">
                                DAO CIUDADANA
                            </h1>
                            <p className="text-cyan-400 font-mono text-sm tracking-wider mt-1">
                                <TypingText
                                    text="SISTEMA DE MEMBRESÍA DIGITAL • BLOCKCHAIN GOVERNANCE"
                                    speed={30}
                                    delay={500}
                                    showCursor={false}
                                />
                            </p>
                        </div>

                        <div className="cyber-badge bg-gradient-to-r from-cyan-500/20 to-purple-500/20 hover-glow">
                            v1.0
                        </div>
                    </div>

                    {/* Step Indicators - Hidden on mobile */}
                    <div className="hidden lg:flex items-center justify-center gap-8 mt-8">
                        <CyberStep
                            n={1}
                            title="Método"
                            active={step === 'method'}
                            done={['clave', 'nfc', 'selfie', 'consent', 'wallet', 'mint', 'success', 'dashboard'].includes(step)}
                        />
                        <div className="w-8 h-0.5 bg-gradient-to-r from-cyan-500 to-transparent opacity-50" />
                        <CyberStep
                            n={2}
                            title="Identidad"
                            active={['clave', 'nfc', 'selfie'].includes(step)}
                            done={['consent', 'wallet', 'mint', 'success', 'dashboard'].includes(step)}
                        />
                        <div className="w-8 h-0.5 bg-gradient-to-r from-cyan-500 to-purple-500 opacity-50" />
                        <CyberStep
                            n={3}
                            title="Consentimiento"
                            active={step === 'consent'}
                            done={['wallet', 'mint', 'success', 'dashboard'].includes(step)}
                        />
                        <div className="w-8 h-0.5 bg-gradient-to-r from-purple-500 to-pink-500 opacity-50" />
                        <CyberStep
                            n={4}
                            title="Wallet"
                            active={step === 'wallet'}
                            done={['mint', 'success', 'dashboard'].includes(step)}
                        />
                        <div className="w-8 h-0.5 bg-gradient-to-r from-pink-500 to-green-500 opacity-50" />
                        <CyberStep
                            n={5}
                            title="NFT"
                            active={step === 'mint'}
                            done={['success', 'dashboard'].includes(step)}
                        />
                    </div>
                </header>

                {/* Premium Progress Bar */}
                <div className="mb-8">
                    <div className="cyber-progress-premium">
                        <div
                            className="cyber-progress-premium-fill"
                            style={{ width: `${progress}%` }}
                        />
                    </div>
                    <p className="text-center text-cyan-400 font-mono text-xs mt-3 tracking-widest">
                        PROGRESO: <span className="text-white font-bold">{progress}%</span> COMPLETADO
                    </p>
                </div>

                {/* Error Display */}
                <ErrorDisplay error={error} />

                {/* Current Step with Animation */}
                <div className="animate-fadeIn">
                    {renderStep()}
                </div>

                {/* Cyberpunk Footer */}
                <footer className="cyber-footer mt-16 glass-dark rounded-lg">
                    <div className="flex items-center justify-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                        <span>Sistema DAO Ciudadana • Blockchain Governance • Código Abierto • v1.0.0</span>
                    </div>
                </footer>
            </div>
        </div>
    );
};

export default OnboardingPage;
