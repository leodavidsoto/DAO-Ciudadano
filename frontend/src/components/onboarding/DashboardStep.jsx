/**
 * Dashboard Step with Premium Effects
 */
import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, Globe, Vote, Terminal, Users, TrendingUp, Hash } from 'lucide-react';
import { Button } from '../ui/button';
import { CyberPanel } from './CyberUI';
import { useOnboarding } from '@/context';
import { AnimatedCounter } from '@/components/effects';

const DashboardStep = () => {
    const navigate = useNavigate();
    const { stats, mint } = useOnboarding();
    const isOnChain = Boolean(mint.tx_hash);

    return (
        <CyberPanel
            title={isOnChain ? 'DASHBOARD CIUDADANO ON-CHAIN' : 'DASHBOARD DEL PILOTO'}
            description={isOnChain
                ? 'Métricas del servicio • membresía confirmada con transacción'
                : 'Métricas del backend • membresía todavía no registrada en blockchain'}
            icon={<Activity className="h-8 w-8 icon-pulse" />}
        >
            <div className="grid md:grid-cols-3 gap-6 mb-8">
                {/* Total Members */}
                <div className="cyber-stat-card-premium hover-lift">
                    <div className="text-center">
                        <Users className="w-8 h-8 mx-auto text-cyan-400 mb-3 icon-bounce" />
                        <div className="cyber-stat-number text-3xl">
                            {typeof stats.total_members === 'number' ? (
                                <AnimatedCounter
                                    target={stats.total_members}
                                    duration={2000}
                                />
                            ) : (
                                <span>—</span>
                            )}
                        </div>
                        <div className="cyber-stat-label">
                            {isOnChain ? 'MEMBRESÍAS VÁLIDAS' : 'REGISTROS DEL PILOTO'}
                        </div>
                    </div>
                </div>

                {/* Recent Joins */}
                <div className="cyber-stat-card-premium hover-lift">
                    <div className="text-center">
                        <TrendingUp className="w-8 h-8 mx-auto text-green-400 mb-3 icon-bounce" />
                        <div className="cyber-stat-number text-3xl text-green-400">
                            {typeof stats.recent_joins === 'number' ? (
                                <AnimatedCounter
                                    target={stats.recent_joins}
                                    duration={1500}
                                    prefix="+"
                                />
                            ) : (
                                <span>—</span>
                            )}
                        </div>
                        <div className="cyber-stat-label">NUEVOS (30D)</div>
                    </div>
                </div>

                {/* Your Token ID */}
                <div className="cyber-stat-card-premium hover-lift bg-gradient-to-br from-purple-500/10 to-pink-500/10">
                    <div className="text-center">
                        <Hash className="w-8 h-8 mx-auto text-purple-400 mb-3 icon-pulse" />
                        <div className="cyber-stat-number text-3xl text-purple-400">
                            {mint.token_id ? (
                                <AnimatedCounter
                                    target={mint.token_id}
                                    duration={1000}
                                    prefix="#"
                                />
                            ) : '—'}
                        </div>
                        <div className="cyber-stat-label">TU MEMBRESÍA ID</div>
                    </div>
                </div>
            </div>

            <div className="grid md:grid-cols-2 gap-4">
                {isOnChain ? (
                    <Button
                        variant="outline"
                        className="cyber-button-premium hover-glow"
                        onClick={() => window.open(
                            `https://sepolia.etherscan.io/tx/${mint.tx_hash}`,
                            '_blank',
                            'noopener,noreferrer'
                        )}
                    >
                        <Globe className="w-4 h-4 mr-2" />
                        VER TRANSACCIÓN EN SEPOLIA
                    </Button>
                ) : (
                    <Button variant="outline" className="cyber-button-premium" disabled>
                        <Globe className="w-4 h-4 mr-2" />
                        SIN CONTRATO PARA ESTE REGISTRO
                    </Button>
                )}
                <Button
                    variant="outline"
                    className="cyber-button-premium hover-glow"
                    onClick={() => navigate('/dashboard/propuestas')}
                >
                    <Vote className="w-4 h-4 mr-2" />
                    VER PROPUESTAS
                </Button>
            </div>

            <div className="mt-8 p-4 glass-dark rounded-lg corner-decoration">
                <div className="flex items-center justify-center gap-3">
                    <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                    <p className="text-xs text-cyan-400 font-mono">
                        <Terminal className="inline w-3 h-3 mr-2" />
                        {isOnChain
                            ? 'Transacción on-chain confirmada'
                            : 'Modo piloto • datos del backend, sin sincronización blockchain'}
                    </p>
                </div>
            </div>
        </CyberPanel>
    );
};

export default DashboardStep;
