/**
 * Treasury Dashboard Component
 * Full transparency view of DAO finances
 */
import React, { useState, useEffect } from 'react';
import {
    Wallet, TrendingUp, TrendingDown, DollarSign,
    ArrowUpRight, ArrowDownRight, PieChart, Clock,
    RefreshCw, ExternalLink
} from 'lucide-react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { governanceAPI } from '@/lib/api';

const formatCurrency = (amount, currency = 'USD') => {
    if (currency === 'ETH') {
        return `${amount.toFixed(4)} ETH`;
    }
    return new Intl.NumberFormat('en-US', {
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
            <div className="text-center py-12 glass-dark rounded-xl">
                <div className="animate-spin w-8 h-8 border-2 border-cyan-500 border-t-transparent rounded-full mx-auto mb-3" />
                <p className="text-gray-400">Cargando tesorería...</p>
            </div>
        );
    }

    return (
        <div className="treasury-dashboard space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <Wallet className="w-8 h-8 text-cyan-400" />
                    <div>
                        <h2 className="text-2xl font-bold text-white">Tesorería DAO</h2>
                        <p className="text-sm text-gray-400">Transparencia total en finanzas</p>
                    </div>
                </div>
                <Button onClick={loadData} variant="outline" size="sm" className="border-gray-600">
                    <RefreshCw className="w-4 h-4 mr-2" />
                    Actualizar
                </Button>
            </div>

            {/* Balance Cards */}
            <div className="grid md:grid-cols-4 gap-4">
                {/* Total Value */}
                <div className="glass-dark p-6 rounded-xl border border-cyan-500/20">
                    <div className="flex items-center justify-between mb-4">
                        <DollarSign className="w-8 h-8 text-cyan-400" />
                        <Badge className="bg-green-500/20 text-green-400 border-green-500/30">
                            Activo
                        </Badge>
                    </div>
                    <div className="text-3xl font-bold text-white mb-1">
                        {formatCurrency(treasury?.total_usd_value || 0)}
                    </div>
                    <div className="text-sm text-gray-400">
                        ≈ {treasury?.total_eth_value || 0} ETH
                    </div>
                </div>

                {/* Individual Balances */}
                {treasury?.balances && Object.entries(treasury.balances).map(([currency, balance]) => (
                    <div key={currency} className="glass-dark p-6 rounded-xl border border-gray-700">
                        <div className="text-sm text-gray-400 mb-2">{currency}</div>
                        <div className="text-2xl font-bold text-white">
                            {currency === 'ETH' ? balance.toFixed(4) : balance.toLocaleString()}
                        </div>
                    </div>
                ))}
            </div>

            {/* Analytics Row */}
            {analytics && (
                <div className="grid md:grid-cols-3 gap-4">
                    <div className="glass-dark p-4 rounded-xl flex items-center gap-4">
                        <div className="w-12 h-12 rounded-full bg-green-500/20 flex items-center justify-center">
                            <TrendingUp className="w-6 h-6 text-green-400" />
                        </div>
                        <div>
                            <div className="text-sm text-gray-400">Ingresos Totales</div>
                            <div className="text-xl font-bold text-green-400">
                                +{analytics.total_income.toLocaleString()}
                            </div>
                        </div>
                    </div>

                    <div className="glass-dark p-4 rounded-xl flex items-center gap-4">
                        <div className="w-12 h-12 rounded-full bg-red-500/20 flex items-center justify-center">
                            <TrendingDown className="w-6 h-6 text-red-400" />
                        </div>
                        <div>
                            <div className="text-sm text-gray-400">Gastos Totales</div>
                            <div className="text-xl font-bold text-red-400">
                                -{analytics.total_expenses.toLocaleString()}
                            </div>
                        </div>
                    </div>

                    <div className="glass-dark p-4 rounded-xl flex items-center gap-4">
                        <div className="w-12 h-12 rounded-full bg-purple-500/20 flex items-center justify-center">
                            <PieChart className="w-6 h-6 text-purple-400" />
                        </div>
                        <div>
                            <div className="text-sm text-gray-400">Runway</div>
                            <div className="text-xl font-bold text-purple-400">
                                {analytics.runway_months} meses
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Transactions */}
            <div className="glass-dark rounded-xl p-6 border border-gray-700">
                <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
                    <Clock className="w-5 h-5 text-cyan-400" />
                    Transacciones Recientes
                </h3>

                <div className="space-y-3">
                    {transactions.map((tx) => (
                        <div key={tx.id} className="flex items-center justify-between p-3 bg-black/30 rounded-lg">
                            <div className="flex items-center gap-3">
                                <div className={`w-10 h-10 rounded-full flex items-center justify-center ${tx.type === 'income'
                                        ? 'bg-green-500/20'
                                        : 'bg-red-500/20'
                                    }`}>
                                    {tx.type === 'income'
                                        ? <ArrowDownRight className="w-5 h-5 text-green-400" />
                                        : <ArrowUpRight className="w-5 h-5 text-red-400" />
                                    }
                                </div>
                                <div>
                                    <div className="text-white font-medium">{tx.description}</div>
                                    <div className="text-xs text-gray-500 flex items-center gap-2">
                                        <Badge variant="outline" className="text-xs border-gray-600">
                                            {tx.category}
                                        </Badge>
                                        {tx.proposal_id && (
                                            <span>Propuesta: {tx.proposal_id}</span>
                                        )}
                                    </div>
                                </div>
                            </div>
                            <div className={`text-right ${tx.type === 'income' ? 'text-green-400' : 'text-red-400'
                                }`}>
                                <div className="font-bold">
                                    {tx.type === 'income' ? '+' : '-'}{tx.amount} {tx.currency}
                                </div>
                                <div className="text-xs text-gray-500">
                                    {new Date(tx.timestamp).toLocaleDateString()}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>

                {transactions.length === 0 && (
                    <div className="text-center py-8 text-gray-500">
                        No hay transacciones registradas
                    </div>
                )}
            </div>
        </div>
    );
};

export default TreasuryDashboard;
