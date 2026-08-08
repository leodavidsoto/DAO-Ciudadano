/**
 * Mint SBT Step - Enhanced with premium animations
 */
import React, { useState, useEffect } from 'react';
import { Cpu, Zap, Sparkles } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { CyberPanel, CyberLoader, SuccessDisplay, DemoBadge } from './CyberUI';
import AccountAbstractionProgress from './AccountAbstractionProgress';
import { HolographicCard } from '@/components/effects';
import { useOnboarding } from '@/context';

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

const ZK_LOADING_STATES = Object.freeze({
    enrolling: {
        text: 'VALIDANDO CREDENCIAL ZK…',
        detail: 'El grant de un solo uso se intercambia por una credencial ligada a esta wallet.',
    },
    generating: {
        text: 'GENERANDO PRUEBA ZK LOCALMENTE…',
        detail: 'El secreto de identidad y la ruta Merkle permanecen en este navegador.',
    },
    ready: {
        text: 'PRUEBA ZK VERIFICADA LOCALMENTE…',
        detail: 'Preparando la autorización subsidiada que firmarás en MetaMask.',
    },
});

const DEFAULT_LOADING_STATE = Object.freeze({
    text: 'PROCESANDO EMISIÓN NO CUSTODIAL…',
    detail: 'La operación solo continuará si todas las verificaciones locales son válidas.',
});

const MintStep = () => {
    const navigate = useNavigate();
    const {
        loading,
        mint,
        wallet,
        identity,
        mintSBT,
        setStep,
        zk,
        accountAbstraction,
    } = useOnboarding();
    const [showConfetti, setShowConfetti] = useState(false);
    const hasVerifiedIdentity = Boolean(identity);
    const loadingState = ZK_LOADING_STATES[zk?.status] || DEFAULT_LOADING_STATE;
    const accountAbstractionStatus = accountAbstraction?.status || 'idle';
    const hasAccountAbstractionProgress = !['idle', 'error'].includes(
        accountAbstractionStatus
    );
    const showAccountAbstractionProgress = hasAccountAbstractionProgress && (
        !mint.token_id || loading || accountAbstractionStatus === 'bundler_pending'
    );

    // Show confetti when mint succeeds
    useEffect(() => {
        if (mint.token_id && !loading) {
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
                {!loading && !mint.token_id && !hasAccountAbstractionProgress && (
                    <div className="text-center">
                        <div className="w-40 h-40 mx-auto mb-6 border-2 border-yellow-500/50 rounded-2xl flex items-center justify-center bg-gradient-to-br from-yellow-500/10 to-orange-500/10 hover-glow transition-all duration-300">
                            <Zap className="w-16 h-16 text-yellow-400 animate-pulse" />
                        </div>
                        {hasVerifiedIdentity ? (
                            <>
                                <p className="text-gray-400 text-sm mb-6 font-mono">
                                    MetaMask te pedirá una autorización personal desde tu cuenta inteligente.
                                    No es una transacción tradicional. Si el patrocinio estatal está disponible,
                                    el costo de red se cubrirá y no necesitarás ETH.
                                </p>
                                <Button
                                    onClick={mintSBT}
                                    className="civic-btn civic-btn-primary civic-aa-authorize group"
                                    aria-label="AUTORIZAR EMISIÓN (SUBSIDIADA POR EL ESTADO)"
                                >
                                    <Sparkles className="w-4 h-4 mr-2" />
                                    <span aria-hidden="true">
                                        Autorizar Emisión (Subsidiada por el Estado)
                                    </span>
                                </Button>
                            </>
                        ) : (
                            <div className="max-w-xl rounded-lg border border-yellow-500/40 bg-yellow-500/10 p-5">
                                <p className="font-mono text-sm font-semibold text-yellow-300">
                                    Demostración completada hasta el límite seguro disponible.
                                </p>
                                <p className="mt-3 text-sm text-gray-400">
                                    No se creó una membresía, NFT ni transacción. Para continuar haría falta
                                    una credencial identity firmada y su ruta Merkle emitidas por el servidor; este cliente no las simula.
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
                {loading && !hasAccountAbstractionProgress && (
                    <CyberLoader
                        className="civic-loading"
                        text={loadingState.text}
                        detail={loadingState.detail}
                    />
                )}

                {showAccountAbstractionProgress && (
                    <AccountAbstractionProgress state={accountAbstraction} />
                )}

                {/* Success state with holographic card */}
                {mint.token_id && !loading && (
                    <div className="flex flex-col items-center gap-6">
                        {mint.tx_hash ? (
                            <HolographicCard
                                tokenId={mint.token_id}
                                walletAddress={wallet.address}
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
