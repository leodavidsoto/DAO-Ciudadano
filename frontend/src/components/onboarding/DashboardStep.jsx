/**
 * Dashboard Step with Premium Effects
 */
import React from 'react';
import { Activity, Globe, Vote, Terminal, Users, TrendingUp, Hash } from 'lucide-react';
import { Button } from '../ui/button';
import { CyberPanel } from './CyberUI';
import { useOnboarding } from '@/context';
import { AnimatedCounter } from '@/components/effects';

const DashboardStep = () => {
    const { stats, mint } = useOnboarding();

    return (
        <CyberPanel
            title="DASHBOARD CIUDADANO ACTIVO"
            description="Métricas en tiempo real • Datos agregados de blockchain"
            icon={<Activity className="h-8 w-8 icon-pulse" />}
        >
            <div className="grid md:grid-cols-3 gap-6 mb-8">
                {/* Total Members */}
                <div className="cyber-stat-card-premium hover-lift">
                    <div className="text-center">
                        <Users className="w-8 h-8 mx-auto text-cyan-400 mb-3 icon-bounce" />
                        <div className="cyber-stat-number text-3xl">
                            <AnimatedCounter
                                target={stats.total_members}
                                duration={2000}
                            />
                        </div>
                        <div className="cyber-stat-label">MIEMBROS ACTIVOS</div>
                    </div>
                </div>

                {/* Recent Joins */}
                <div className="cyber-stat-card-premium hover-lift">
                    <div className="text-center">
                        <TrendingUp className="w-8 h-8 mx-auto text-green-400 mb-3 icon-bounce" />
                        <div className="cyber-stat-number text-3xl text-green-400">
                            <AnimatedCounter
                                target={stats.recent_joins}
                                duration={1500}
                                prefix="+"
                            />
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
                        <div className="cyber-stat-label">TU NFT ID</div>
                    </div>
                </div>
            </div>

            <div className="grid md:grid-cols-2 gap-4">
                <Button variant="outline" className="cyber-button-premium hover-glow">
                    <Globe className="w-4 h-4 mr-2" />
                    EXPLORAR BLOCKCHAIN
                </Button>
                <Button variant="outline" className="cyber-button-premium hover-glow">
                    <Vote className="w-4 h-4 mr-2" />
                    VER PROPUESTAS
                </Button>
            </div>

            <div className="mt-8 p-4 glass-dark rounded-lg corner-decoration">
                <div className="flex items-center justify-center gap-3">
                    <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                    <p className="text-xs text-cyan-400 font-mono">
                        <Terminal className="inline w-3 h-3 mr-2" />
                        Sistema operativo • Datos sincronizados con red blockchain
                    </p>
                </div>
            </div>
        </CyberPanel>
    );
};

export default DashboardStep;
