/**
 * Treasury Dashboard Component
 * Full transparency view of DAO finances
 */
import React, { useState, useEffect } from 'react';
import {
    Wallet, TrendingUp, TrendingDown, DollarSign,
    ArrowUpRight, ArrowDownRight, PieChart, Clock,
    RefreshCw, Info
} from 'lucide-react';
import { governanceAPI } from '@/lib/api';

const formatCurrency = (amount, currency = 'USD') => {
    if (currency === 'ETH') {
        return `${amount.toFixed(4)} ETH`;
    }
    return new Intl.NumberFormat('es-CL', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
    }).format(amount);
};

const TreasuryDashboard = () => {
    const [treasury, setTreasury] = useState(null);
    const [transactions, setTransactions] = useState([]);
    const [analytics, setAnalytics] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        setLoading(true);
        try {
            const [treasuryRes, txRes, analyticsRes] = await Promise.all([
                governanceAPI.getTreasury(),
                governanceAPI.getTreasuryTransactions(),
                governanceAPI.getTreasuryAnalytics(),
            ]);
            setTreasury(treasuryRes.data);
            setTransactions(txRes.data);
            setAnalytics(analyticsRes.data);
        } catch (err) {
            console.error('Error loading treasury:', err);
        } finally {
            setLoading(false);
        }
    };

    if (loading) {
        return (
            <div className="civic-loading">
                <span className="civic-spinner" />
                Cargando tesorería…
            </div>
        );
    }

    // The backend reports `configured: false` with null balances until a real
    // on-chain source is wired (ROADMAP 3.6). Never render 0 as if it were a
    // real balance: an empty treasury and an unconfigured one are different things.
    const isConfigured = treasury?.configured === true && treasury?.balances != null;

    return (
        <section className="space-y-6">
            <div className="flex items-center justify-between gap-4 flex-wrap">
                <div>
                    <h2 className="civic-section-title">
                        <Wallet className="w-5 h-5" />
                        Tesorería
                    </h2>
                    <p className="civic-muted text-sm mt-1">
                        Solo se muestran fondos y movimientos con respaldo real.
                    </p>
                </div>
                <button onClick={loadData} className="civic-btn civic-btn-sm civic-btn-quiet">
                    <RefreshCw className="w-4 h-4" />
                    Actualizar
                </button>
            </div>

            {!isConfigured && (
                <div className="civic-note civic-note-warn">
                    <Info className="w-4 h-4" />
                    <span>
                        Todavía no hay una fuente de saldos conectada (falta el multisig
                        Safe). Los saldos se muestran vacíos a propósito: mostrar un 0
                        sugeriría que la tesorería está confirmada y en cero.
                    </span>
                </div>
            )}

            <div className="grid md:grid-cols-4 gap-4">
                <div className="civic-stat">
                    <div className="flex items-center justify-between mb-3">
                        <DollarSign className="w-6 h-6" style={{ color: '#003897' }} />
                        <span className={`civic-tag ${isConfigured ? 'civic-tag-green' : 'civic-tag-neutral'}`}>
                            {isConfigured ? 'Activo' : 'Sin configurar'}
                        </span>
                    </div>
                    {isConfigured ? (
                        <>
                            <div className="civic-stat-value">
                                {formatCurrency(treasury.total_usd_value)}
                            </div>
                            <div className="civic-stat-label">≈ {treasury.total_eth_value} ETH</div>
                        </>
                    ) : (
                        <>
                            <div className="civic-stat-value civic-faint">—</div>
                            <div className="civic-stat-label">Sin fuente de saldos conectada</div>
                        </>
                    )}
                </div>

                {treasury?.balances && Object.entries(treasury.balances).map(([currency, balance]) => (
                    <div key={currency} className="civic-stat">
                        <div className="civic-stat-label" style={{ marginTop: 0, marginBottom: 6 }}>{currency}</div>
                        <div className="civic-stat-value">
                            {currency === 'ETH' ? balance.toFixed(4) : balance.toLocaleString('es-CL')}
                        </div>
                    </div>
                ))}
            </div>

            {analytics && (
                <div className="grid md:grid-cols-3 gap-4">
                    <div className="civic-card civic-card-pad flex items-center gap-4">
                        <span
                            className="w-11 h-11 rounded-full flex items-center justify-center shrink-0"
                            style={{ background: '#E9F1EC' }}
                        >
                            <TrendingUp className="w-5 h-5" style={{ color: '#1F6B45' }} />
                        </span>
                        <div>
                            <div className="civic-stat-label" style={{ marginTop: 0 }}>Ingresos registrados</div>
                            <div className="civic-stat-value" style={{ fontSize: 20, color: '#1F6B45' }}>
                                +{analytics.total_income.toLocaleString('es-CL')}
                            </div>
                        </div>
                    </div>

                    <div className="civic-card civic-card-pad flex items-center gap-4">
                        <span
                            className="w-11 h-11 rounded-full flex items-center justify-center shrink-0"
                            style={{ background: '#FBEAE8' }}
                        >
                            <TrendingDown className="w-5 h-5" style={{ color: '#A9211D' }} />
                        </span>
                        <div>
                            <div className="civic-stat-label" style={{ marginTop: 0 }}>Gastos registrados</div>
                            <div className="civic-stat-value" style={{ fontSize: 20, color: '#A9211D' }}>
                                -{analytics.total_expenses.toLocaleString('es-CL')}
                            </div>
                        </div>
                    </div>

                    <div className="civic-card civic-card-pad flex items-center gap-4">
                        <span
                            className="w-11 h-11 rounded-full flex items-center justify-center shrink-0"
                            style={{ background: '#EAF0FB' }}
                        >
                            <PieChart className="w-5 h-5" style={{ color: '#003897' }} />
                        </span>
                        <div>
                            <div className="civic-stat-label" style={{ marginTop: 0 }}>Autonomía</div>
                            <div className="civic-stat-value" style={{ fontSize: 20 }}>
                                {analytics.runway_months != null
                                    ? `${analytics.runway_months} meses`
                                    : '—'}
                            </div>
                        </div>
                    </div>
                </div>
            )}

            <div className="civic-card civic-card-pad">
                <h3 className="civic-section-title mb-4" style={{ fontSize: 17 }}>
                    <Clock className="w-4 h-4" />
                    Movimientos recientes
                </h3>

                {transactions.length === 0 ? (
                    <div className="civic-empty">
                        <Clock className="w-10 h-10" />
                        <p className="civic-empty-title">No hay movimientos registrados</p>
                        <p className="civic-empty-desc">
                            Aparecerán aquí cuando existan transacciones reales de tesorería.
                        </p>
                    </div>
                ) : (
                    <div className="space-y-3">
                        {transactions.map((tx) => {
                            const ingreso = tx.type === 'income';
                            return (
                                <div
                                    key={tx.id}
                                    className="flex items-center justify-between gap-4 p-3 rounded-lg"
                                    style={{ background: '#F7F9FC', border: '1px solid #E5EBF5' }}
                                >
                                    <div className="flex items-center gap-3 min-w-0">
                                        <span
                                            className="w-9 h-9 rounded-full flex items-center justify-center shrink-0"
                                            style={{ background: ingreso ? '#E9F1EC' : '#FBEAE8' }}
                                        >
                                            {ingreso
                                                ? <ArrowDownRight className="w-4 h-4" style={{ color: '#1F6B45' }} />
                                                : <ArrowUpRight className="w-4 h-4" style={{ color: '#A9211D' }} />}
                                        </span>
                                        <div className="min-w-0">
                                            <div className="civic-ink font-medium text-sm truncate">{tx.description}</div>
                                            <div className="flex items-center gap-2 mt-1 flex-wrap">
                                                <span className="civic-tag civic-tag-neutral">{tx.category}</span>
                                                {tx.proposal_id && (
                                                    <span className="civic-faint text-xs">
                                                        Propuesta: {tx.proposal_id}
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                    <div className="text-right shrink-0">
                                        <div
                                            className="font-semibold text-sm"
                                            style={{ color: ingreso ? '#1F6B45' : '#A9211D', fontFamily: 'Poppins, sans-serif' }}
                                        >
                                            {ingreso ? '+' : '-'}{tx.amount} {tx.currency}
                                        </div>
                                        <div className="civic-faint text-xs">
                                            {new Date(tx.timestamp).toLocaleDateString('es-CL')}
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </section>
    );
};

export default TreasuryDashboard;
