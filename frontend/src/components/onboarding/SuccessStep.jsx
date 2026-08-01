/**
 * Success Step - Enhanced with premium UI
 */
import React, { useEffect, useState } from 'react';
import { CheckCircle2, Leaf, Vote, Shield, Terminal, ExternalLink } from 'lucide-react';
import { Button } from '../ui/button';
import { CyberPanel } from './CyberUI';
import { HolographicCard } from '@/components/effects';
import { MembershipQR } from '@/components/membership';
import { useOnboarding } from '@/context';

const SuccessStep = () => {
    const { mint, wallet, clave, setStep, loadStats } = useOnboarding();
    const [showCard, setShowCard] = useState(false);
    const [showQR, setShowQR] = useState(false);
    const isOnChain = Boolean(mint.tx_hash);

    useEffect(() => {
        // Animate card entrance
        const timer = setTimeout(() => setShowCard(true), 300);
        const qrTimer = setTimeout(() => setShowQR(true), 600);
        return () => {
            clearTimeout(timer);
            clearTimeout(qrTimer);
        };
    }, []);

    const handleGoToDashboard = () => {
        loadStats();
        setStep('dashboard');
    };

    const StatCard = ({ icon: Icon, color, title, value, items }) => (
        <div className={`cyber-stat-card-premium bg-gradient-to-br ${color} tilt-effect`}>
            <div className="text-center relative z-10">
                <Icon className="w-8 h-8 mx-auto mb-3 icon-pulse" style={{ color: 'inherit' }} />
                <div className="cyber-stat-number text-xl">{value}</div>
                <div className="cyber-stat-label">{title}</div>
                {items && (
                    <div className="mt-3 space-y-1">
                        {items.map((item, i) => (
                            <p key={i} className="text-xs text-gray-400 font-mono">• {item}</p>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );

    return (
        <CyberPanel
            title={isOnChain ? 'SBT CONFIRMADO EN BLOCKCHAIN' : 'REGISTRO DE PILOTO CREADO'}
            description={isOnChain
                ? 'La transacción on-chain puede verificarse de forma independiente'
                : 'Guardado en el backend • sin NFT ni transacción blockchain'}
            icon={<CheckCircle2 className="h-8 w-8" />}
        >
            <div className="flex flex-col items-center gap-8">
                {isOnChain ? (
                    /* Holographic SBT card and verifiable QR side by side */
                    <div className="grid md:grid-cols-2 gap-6 w-full">
                        <div
                            className={`transition-all duration-700 ${showCard
                                ? 'opacity-100 transform translate-y-0'
                                : 'opacity-0 transform translate-y-8'
                                }`}
                        >
                            <HolographicCard
                                tokenId={mint.token_id}
                                walletAddress={wallet.address}
                                assuranceLevel={clave?.assurance_level || 'AL1'}
                            />
                        </div>

                        <div
                            className={`transition-all duration-700 delay-200 ${showQR
                                ? 'opacity-100 transform translate-y-0'
                                : 'opacity-0 transform translate-y-8'
                                }`}
                        >
                            <MembershipQR
                                tokenId={mint.token_id}
                                walletAddress={wallet.address}
                                assuranceLevel={clave?.assurance_level || 'AL1'}
                                memberName={clave?.nombre}
                            />
                        </div>
                    </div>
                ) : (
                    <div className="w-full rounded-xl border border-yellow-500/40 bg-yellow-500/10 p-6 text-center">
                        <Shield className="mx-auto mb-3 h-9 w-9 text-yellow-400" />
                        <p className="font-semibold text-yellow-300">Membresía de piloto, no credencial blockchain</p>
                        <p className="mt-2 text-sm text-gray-400">
                            El identificador #{mint.token_id} existe solo en la base de datos del servicio.
                            No se generó un token y no debe presentarse como prueba verificable.
                        </p>
                    </div>
                )}

                {/* Stats Grid */}
                <div className="grid md:grid-cols-3 gap-4 w-full">
                    <StatCard
                        icon={Leaf}
                        color="from-cyan-500/10 to-blue-500/10 border-cyan-500/30 text-cyan-400"
                        title={isOnChain ? 'SBT ON-CHAIN' : 'REGISTRO PILOTO'}
                        value={`#${mint.token_id || '—'}`}
                    />
                    <StatCard
                        icon={Vote}
                        color="from-purple-500/10 to-pink-500/10 border-purple-500/30 text-purple-400"
                        title="ENTORNO"
                        value={isOnChain ? 'SEPOLIA' : 'OFF-CHAIN'}
                        items={['Propuestas', 'Votaciones', 'Tesorería']}
                    />
                    <StatCard
                        icon={Shield}
                        color="from-green-500/10 to-teal-500/10 border-green-500/30 text-green-400"
                        title="EVIDENCIA"
                        value={isOnChain ? 'TX REAL' : 'SIN TX'}
                        items={isOnChain ? ['Hash de transacción', 'Consulta pública'] : ['No verificable on-chain']}
                    />
                </div>

                {/* Transaction Link */}
                {mint.tx_hash && (
                    <div className="flex items-center gap-2 text-xs text-gray-500 font-mono">
                        <span>TX:</span>
                        <a
                            href={`https://sepolia.etherscan.io/tx/${mint.tx_hash}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-cyan-400 hover:text-cyan-300 transition-colors flex items-center gap-1"
                        >
                            {mint.tx_hash.slice(0, 16)}...
                            <ExternalLink className="w-3 h-3" />
                        </a>
                    </div>
                )}

                {/* Dashboard Button */}
                <Button
                    onClick={handleGoToDashboard}
                    className="cyber-button-premium"
                >
                    <Terminal className="w-4 h-4 mr-2" />
                    ACCEDER AL DASHBOARD
                </Button>
            </div>
        </CyberPanel>
    );
};

export default SuccessStep;
