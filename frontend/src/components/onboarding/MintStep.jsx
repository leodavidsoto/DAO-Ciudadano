/**
 * Mint SBT Step - Enhanced with premium animations
 */
import React, { useState, useEffect } from 'react';
import { Cpu, Zap, Sparkles } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { CyberPanel, CyberLoader, SuccessDisplay, DemoBadge } from './CyberUI';
import { HolographicCard } from '@/components/effects';
import { useOnboarding } from '@/context';

const MINT_STAGES = [
    { text: 'VALIDANDO SOLICITUD...', progress: 20 },
    { text: 'COMPROBANDO MEMBRESÍA...', progress: 40 },
    { text: 'PREPARANDO REGISTRO...', progress: 60 },
    { text: 'ESPERANDO RESPUESTA...', progress: 80 },
    { text: 'VERIFICANDO RESULTADO...', progress: 95 },
];

// Confetti burst effect
const Confetti = ({ show }) => {
    const [pieces, setPieces] = useState([]);

    useEffect(() => {
        if (show) {
            const colors = ['#00FFFF', '#FF00FF', '#39FF14', '#FFD700', '#FF073A'];
            const newPieces = Array.from({ length: 50 }, (_, i) => ({
                id: i,
                left: Math.random() * 100,
                delay: Math.random() * 0.5,
                duration: 2 + Math.random() * 2,
                color: colors[Math.floor(Math.random() * colors.length)],
                size: 6 + Math.random() * 8,
            }));
            setPieces(newPieces);

            const timer = setTimeout(() => setPieces([]), 4000);
            return () => clearTimeout(timer);
        }
    }, [show]);

    if (!show || pieces.length === 0) return null;

    return (
        <div className="confetti-container">
            {pieces.map((piece) => (
                <div
                    key={piece.id}
                    className="confetti-piece"
                    style={{
                        left: `${piece.left}%`,
                        width: piece.size,
                        height: piece.size,
                        background: piece.color,
                        animationDelay: `${piece.delay}s`,
                        animationDuration: `${piece.duration}s`,
                        borderRadius: Math.random() > 0.5 ? '50%' : '2px',
                        boxShadow: `0 0 10px ${piece.color}`,
                    }}
                />
            ))}
        </div>
    );
};

// Circular progress ring
const MintProgressRing = ({ progress, stage }) => {
    const radius = 52;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (progress / 100) * circumference;

    return (
        <div className="mint-animation-container">
            <div className="mint-progress-ring">
                <svg width="120" height="120" viewBox="0 0 120 120">
                    <defs>
                        <linearGradient id="mintGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" stopColor="#00FFFF" />
                            <stop offset="50%" stopColor="#FF00FF" />
                            <stop offset="100%" stopColor="#39FF14" />
                        </linearGradient>
                    </defs>
                    <circle className="bg" cx="60" cy="60" r={radius} />
                    <circle
                        className="progress"
                        cx="60"
                        cy="60"
                        r={radius}
                        strokeDasharray={circumference}
                        strokeDashoffset={offset}
                    />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                    <Cpu className="w-10 h-10 text-cyan-400 icon-pulse" />
                </div>
            </div>
            <div className="mint-stage-text">{stage}</div>
        </div>
    );
};

const MintStep = () => {
    const navigate = useNavigate();
    const { loading, mint, wallet, clave, nfc, mintSBT, setStep } = useOnboarding();
    const [mintProgress, setMintProgress] = useState(0);
    const [currentStage, setCurrentStage] = useState('');
    const [showConfetti, setShowConfetti] = useState(false);
    const hasVerifiedIdentity = nfc.verified === true && Boolean(nfc.doc_hash);

    // Simulate minting stages
    useEffect(() => {
        if (loading) {
            let stageIndex = 0;
            setMintProgress(MINT_STAGES[0].progress);
            setCurrentStage(MINT_STAGES[0].text);

            const interval = setInterval(() => {
                stageIndex++;
                if (stageIndex < MINT_STAGES.length) {
                    setMintProgress(MINT_STAGES[stageIndex].progress);
                    setCurrentStage(MINT_STAGES[stageIndex].text);
                }
            }, 600);

            return () => clearInterval(interval);
        }
    }, [loading]);

    // Show confetti when mint succeeds
    useEffect(() => {
        if (mint.token_id && !loading) {
            setMintProgress(100);
            setCurrentStage('¡COMPLETADO!');
            setShowConfetti(true);
        }
    }, [mint.token_id, loading]);

    return (
        <CyberPanel
            title={hasVerifiedIdentity ? 'CREACIÓN DE CREDENCIAL CIUDADANA' : 'LÍMITE DEL PILOTO ALCANZADO'}
            description={hasVerifiedIdentity
                ? 'El resultado indicará si existe una transacción on-chain verificable'
                : 'Los recorridos disponibles no acreditan identidad y no habilitan una membresía nueva'}
            icon={<Cpu className="h-8 w-8" />}
        >
            <Confetti show={showConfetti} />

            <div className="flex flex-col items-center gap-6">
                {/* Pre-mint state */}
                {!loading && !mint.token_id && (
                    <div className="text-center">
                        <div className="w-40 h-40 mx-auto mb-6 border-2 border-yellow-500/50 rounded-2xl flex items-center justify-center bg-gradient-to-br from-yellow-500/10 to-orange-500/10 hover-glow transition-all duration-300">
                            <Zap className="w-16 h-16 text-yellow-400 animate-pulse" />
                        </div>
                        {hasVerifiedIdentity ? (
                            <>
                                <p className="text-gray-400 text-sm mb-6 font-mono">
                                    Se solicitará tu membresía sin asumir que existe en blockchain
                                </p>
                                <Button onClick={mintSBT} className="cyber-button-premium group">
                                    <Sparkles className="w-4 h-4 mr-2 group-hover:animate-spin" />
                                    CREAR CREDENCIAL
                                </Button>
                            </>
                        ) : (
                            <div className="max-w-xl rounded-lg border border-yellow-500/40 bg-yellow-500/10 p-5">
                                <p className="font-mono text-sm font-semibold text-yellow-300">
                                    Demostración completada hasta el límite seguro disponible.
                                </p>
                                <p className="mt-3 text-sm text-gray-400">
                                    No se creó una membresía, NFT ni transacción. Para continuar haría falta
                                    una verificación de identidad real emitida por el servidor; este cliente no la simula.
                                </p>
                                <div className="mt-5 flex flex-wrap justify-center gap-3">
                                    <Button
                                        onClick={() => setStep('method')}
                                        variant="outline"
                                        className="border-yellow-500/40 text-yellow-200"
                                    >
                                        ELEGIR OTRO RECORRIDO
                                    </Button>
                                    <Button onClick={() => navigate('/')} className="cyber-button-premium">
                                        FINALIZAR Y VOLVER AL INICIO
                                    </Button>
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {/* Minting progress */}
                {loading && (
                    <MintProgressRing progress={mintProgress} stage={currentStage} />
                )}

                {/* Success state with holographic card */}
                {mint.token_id && !loading && (
                    <div className="flex flex-col items-center gap-6">
                        {mint.tx_hash ? (
                            <HolographicCard
                                tokenId={mint.token_id}
                                walletAddress={wallet.address}
                                assuranceLevel={clave?.assurance_level || 'AL1'}
                            />
                        ) : (
                            <DemoBadge label="REGISTRO PILOTO OFF-CHAIN — no es un NFT ni un SBT en blockchain" />
                        )}

                        <SuccessDisplay>
                            <div className="flex flex-wrap justify-center gap-2 mt-2">
                                <Badge className="cyber-badge success">
                                    REGISTRO CREADO
                                </Badge>
                                {mint.tx_hash ? (
                                    <Badge className="cyber-badge">
                                        TX: {mint.tx_hash.slice(0, 12)}...
                                    </Badge>
                                ) : (
                                    <Badge className="cyber-badge">
                                        SIN TX ON-CHAIN (DEMO)
                                    </Badge>
                                )}
                            </div>
                        </SuccessDisplay>
                    </div>
                )}
            </div>
        </CyberPanel>
    );
};

export default MintStep;
