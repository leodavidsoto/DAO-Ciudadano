/**
 * Citizen dashboard — governance shell.
 *
 * Mounts the governance components that existed in the repo but were never
 * rendered anywhere (audit finding M-10), plus the elections module.
 *
 * The wallet address comes from useWallet, never from a form: the acting
 * address must be one the user actually controls.
 */
import React from 'react';
import { NavLink, Outlet, useOutletContext } from 'react-router-dom';
import { Shield, FileText, Vote, Coins, Users, Home, Wallet } from 'lucide-react';
import { useWallet } from '@/hooks';
import {
    ProposalsList,
    TreasuryDashboard,
    VoteDelegation,
    ElectionsList,
    RepresentativesPanel,
} from '@/components/governance';
import { ParticlesBackground, ScanlineOverlay } from '@/components/effects';

const NAV = [
    { to: '/dashboard', end: true, label: 'RESUMEN', icon: Home },
    { to: '/dashboard/propuestas', label: 'PROPUESTAS', icon: FileText },
    { to: '/dashboard/elecciones', label: 'ELECCIONES', icon: Vote },
    { to: '/dashboard/delegacion', label: 'DELEGACIÓN', icon: Users },
    { to: '/dashboard/tesoreria', label: 'TESORERÍA', icon: Coins },
];

const DashboardLayout = () => {
    const { address, shortAddress, isConnected, connect, isConnecting } = useWallet();

    return (
        <div className="min-h-screen relative overflow-hidden">
            <ParticlesBackground count={25} />
            <ScanlineOverlay opacity={0.04} />

            <div className="mx-auto max-w-6xl px-4 py-8 relative z-10">
                <header className="mb-8">
                    <div className="flex items-center justify-between gap-4 flex-wrap mb-6">
                        <div className="flex items-center gap-3">
                            <div className="w-11 h-11 rounded-full bg-gradient-to-r from-cyan-400 via-purple-500 to-pink-500 flex items-center justify-center p-0.5">
                                <div className="w-full h-full rounded-full bg-cyber-dark flex items-center justify-center">
                                    <Shield className="h-6 w-6 text-cyan-400" />
                                </div>
                            </div>
                            <div>
                                <h1 className="cyber-title text-2xl font-black tracking-wider" data-text="DAO CIUDADANA">
                                    DAO CIUDADANA
                                </h1>
                                <p className="text-cyan-400/70 font-mono text-xs tracking-wider">
                                    GOBERNANZA CIUDADANA
                                </p>
                            </div>
                        </div>

                        {isConnected ? (
                            <div className="cyber-badge flex items-center gap-2">
                                <Wallet className="w-3 h-3" />
                                <span className="font-mono text-xs">{shortAddress}</span>
                            </div>
                        ) : (
                            <button onClick={connect} disabled={isConnecting} className="cyber-button text-xs">
                                {isConnecting ? 'CONECTANDO...' : 'CONECTAR WALLET'}
                            </button>
                        )}
                    </div>

                    <nav className="flex flex-wrap gap-2">
                        {NAV.map(({ to, end, label, icon: Icon }) => (
                            <NavLink
                                key={to}
                                to={to}
                                end={end}
                                className={({ isActive }) =>
                                    'flex items-center gap-2 px-4 py-2 rounded-lg font-mono text-xs tracking-wide border transition-colors ' +
                                    (isActive
                                        ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-300'
                                        : 'border-gray-700 text-gray-400 hover:border-cyan-500/30 hover:text-cyan-400')
                                }
                            >
                                <Icon className="w-4 h-4" />
                                {label}
                            </NavLink>
                        ))}
                    </nav>
                </header>

                {!isConnected && (
                    <div className="mb-6 p-4 rounded-lg border border-yellow-500/40 bg-yellow-500/10">
                        <p className="text-yellow-300 text-xs font-mono">
                            Conecta tu wallet para participar. Puedes leer todo sin conectarla,
                            pero crear propuestas, votar y postularte requieren una membresía activa.
                        </p>
                    </div>
                )}

                <main className="pb-12">
                    <Outlet context={{ walletAddress: address }} />
                </main>

                <footer className="text-center text-gray-600 font-mono text-[11px] pb-6">
                    Sistema DAO Ciudadana • Gobernanza • Código Abierto • v1.0.0
                </footer>
            </div>
        </div>
    );
};

// === Sections ===

const OverviewSection = () => {
    const { walletAddress } = useOutletContext();
    return (
        <div className="space-y-8">
            <RepresentativesPanel />
            <ProposalsList walletAddress={walletAddress} />
        </div>
    );
};

const ProposalsSection = () => {
    const { walletAddress } = useOutletContext();
    return <ProposalsList walletAddress={walletAddress} />;
};

const ElectionsSection = () => {
    const { walletAddress } = useOutletContext();
    return (
        <div className="space-y-8">
            <ElectionsList walletAddress={walletAddress} />
            <RepresentativesPanel />
        </div>
    );
};

const DelegationSection = () => {
    const { walletAddress } = useOutletContext();
    return <VoteDelegation walletAddress={walletAddress} />;
};

const TreasurySection = () => <TreasuryDashboard />;

export {
    DashboardLayout,
    OverviewSection,
    ProposalsSection,
    ElectionsSection,
    DelegationSection,
    TreasurySection,
};

export default DashboardLayout;
