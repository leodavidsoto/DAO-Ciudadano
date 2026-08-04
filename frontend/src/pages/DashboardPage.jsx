/**
 * Citizen dashboard — governance shell.
 *
 * Mounts the governance components that existed in the repo but were never
 * rendered anywhere (audit finding M-10), plus the elections module.
 *
 * The wallet address comes from useWallet, never from a form: the acting
 * address must be one the user actually controls.
 *
 * Identidad visual: continúa la landing pública (styles/civic.css) — fondo
 * claro, azul #003897, rojo #CB2C27, Poppins + Open Sans. Antes era el tema
 * cyberpunk (partículas, scanlines, cian sobre negro) y quien llegaba desde
 * la portada sentía que había cambiado de sitio.
 */
import React from 'react';
import { NavLink, Outlet, useOutletContext, useNavigate } from 'react-router-dom';
import { FileText, Vote, Coins, Users, Home, Wallet, Info, LogOut, AlertCircle } from 'lucide-react';
import { useWallet } from '@/hooks';
import {
    ProposalsList,
    TreasuryDashboard,
    VoteDelegation,
    ElectionsList,
    RepresentativesPanel,
    VotingBallot,
} from '@/components/governance';
import '../styles/civic.css';

const NAV = [
    { to: '/dashboard', end: true, label: 'Resumen', icon: Home },
    { to: '/dashboard/propuestas', label: 'Propuestas', icon: FileText },
    { to: '/dashboard/elecciones', label: 'Elecciones', icon: Vote },
    { to: '/dashboard/delegacion', label: 'Delegación', icon: Users },
    { to: '/dashboard/tesoreria', label: 'Tesorería', icon: Coins },
];

const DashboardLayout = () => {
    const {
        address,
        shortAddress,
        chainId,
        eip1193Provider,
        isConnected,
        connect,
        disconnect,
        isConnecting,
        isDisconnecting,
        error,
    } = useWallet();
    const navigate = useNavigate();

    return (
        <div className="civic-app">
            <header className="civic-header">
                <div className="civic-shell">
                    <div className="civic-header-inner">
                        <button
                            type="button"
                            className="civic-brand"
                            onClick={() => navigate('/')}
                            aria-label="Ir a la portada de EstamosDAO"
                        >
                            <img
                                src="/assets/logo-mark.png"
                                alt="EstamosDAO Logo"
                                style={{ width: 42, height: 42, objectFit: 'contain', display: 'block' }}
                            />
                            <span>
                                <h1 className="civic-brand-name">EstamosDAO</h1>
                                <p className="civic-brand-sub">Gobernanza ciudadana</p>
                            </span>
                        </button>

                        {isConnected ? (
                            <div className="flex flex-wrap items-center justify-end gap-2">
                                <span className="civic-wallet">
                                    <Wallet className="w-3.5 h-3.5" />
                                    {shortAddress}
                                </span>
                                <button
                                    type="button"
                                    onClick={() => void disconnect()}
                                    disabled={isDisconnecting}
                                    aria-busy={isDisconnecting}
                                    className="civic-btn civic-btn-quiet civic-btn-sm"
                                >
                                    <LogOut className="w-4 h-4" />
                                    {isDisconnecting ? 'Cerrando…' : 'Cerrar sesión'}
                                </button>
                            </div>
                        ) : (
                            <button
                                type="button"
                                onClick={() => void connect()}
                                disabled={isConnecting}
                                className="civic-btn civic-btn-primary civic-btn-sm"
                            >
                                <Wallet className="w-4 h-4" />
                                {isConnecting ? 'Conectando…' : 'Conectar billetera'}
                            </button>
                        )}
                    </div>

                    <nav className="civic-nav" aria-label="Secciones del panel">
                        {NAV.map(({ to, end, label, icon: Icon }) => (
                            <NavLink
                                key={to}
                                to={to}
                                end={end}
                                className={({ isActive }) =>
                                    'civic-nav-item' + (isActive ? ' is-active' : '')
                                }
                            >
                                <Icon className="w-4 h-4" />
                                {label}
                            </NavLink>
                        ))}
                    </nav>
                </div>
            </header>

            <div className="civic-shell">
                {error && (
                    <div
                        className="civic-note civic-note-error"
                        style={{ marginTop: 24 }}
                        role="alert"
                    >
                        <AlertCircle className="w-4 h-4" />
                        <span>{error}</span>
                    </div>
                )}

                {!isConnected && (
                    <div className="civic-note civic-note-info" style={{ marginTop: 24 }}>
                        <Info className="w-4 h-4" />
                        <span>
                            Puedes leer todo el panel sin conectar tu billetera. Crear
                            propuestas, votar y postularte requieren una membresía activa.
                        </span>
                    </div>
                )}

                <main style={{ padding: '28px 0 48px' }}>
                    <Outlet context={{
                        walletAddress: address,
                        chainId,
                        eip1193Provider,
                    }} />
                </main>

                <footer className="civic-footer">
                    EstamosDAO · Piloto de gobernanza ciudadana · Código abierto · v1.0.0
                </footer>
            </div>
        </div>
    );
};

// === Sections ===

const OverviewSection = () => {
    const { walletAddress } = useOutletContext();
    return (
        <div className="space-y-10">
            <RepresentativesPanel />
            <ProposalsList walletAddress={walletAddress} />
        </div>
    );
};

const ProposalsSection = () => {
    const { walletAddress, chainId, eip1193Provider } = useOutletContext();
    return (
        <div className="space-y-10">
            <VotingBallot
                walletAddress={walletAddress}
                chainId={chainId}
                eip1193Provider={eip1193Provider}
            />
            <ProposalsList walletAddress={walletAddress} />
        </div>
    );
};

const ElectionsSection = () => {
    const { walletAddress } = useOutletContext();
    return (
        <div className="space-y-10">
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
