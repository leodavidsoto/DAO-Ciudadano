/**
 * Vote Delegation Component
 * Delegate your voting power to another member
 */
import React, { useState, useEffect } from 'react';
import { Users, ArrowRight, X, Check, AlertCircle, Zap } from 'lucide-react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { governanceAPI } from '@/lib/api';

const VoteDelegation = ({ walletAddress }) => {
    const [delegation, setDelegation] = useState(null);
    const [delegators, setDelegators] = useState([]);
    const [delegateInput, setDelegateInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [success, setSuccess] = useState('');

    useEffect(() => {
        if (walletAddress) {
            loadDelegation();
        }
    }, [walletAddress]);

    const loadDelegation = async () => {
        try {
            const [delegationRes, delegatorsRes] = await Promise.all([
                governanceAPI.getDelegation(walletAddress),
                governanceAPI.getDelegators(walletAddress),
            ]);
            setDelegation(delegationRes.data);
            setDelegators(delegatorsRes.data.delegators || []);
        } catch (err) {
            console.error('Error loading delegation:', err);
        }
    };

    // Validate Ethereum address format
    const isValidAddress = (address) => {
        return /^0x[a-fA-F0-9]{40}$/.test(address);
    };

    const handleDelegate = async () => {
        const trimmedInput = delegateInput.trim();

        if (!trimmedInput) {
            setError('Ingresa una dirección válida');
            return;
        }

        if (!isValidAddress(trimmedInput)) {
            setError('Formato de dirección inválido. Debe ser una dirección Ethereum (0x...)');
            return;
        }

        if (trimmedInput.toLowerCase() === walletAddress?.toLowerCase()) {
            setError('No puedes delegarte el voto a ti mismo');
            return;
        }

        setLoading(true);
        setError('');
        setSuccess('');

        try {
            const response = await governanceAPI.delegate(walletAddress, trimmedInput);
            if (response.data.ok) {
                setSuccess('¡Voto delegado exitosamente!');
                setDelegateInput('');
                loadDelegation();
            } else {
                setError(response.data.error);
            }
        } catch (err) {
            setError('Error al delegar voto');
        } finally {
            setLoading(false);
        }
    };

    const handleRevoke = async () => {
        setLoading(true);
        setError('');

        try {
            const response = await governanceAPI.revokeDelegation(walletAddress);
            if (response.data.ok) {
                setSuccess('Delegación revocada');
                loadDelegation();
            } else {
                setError(response.data.error);
            }
        } catch (err) {
            setError('Error al revocar');
        } finally {
            setLoading(false);
        }
    };

    const votingPower = delegators.length + 1;

    return (
        <div className="vote-delegation glass-dark rounded-xl p-6 border border-purple-500/20">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                    <Users className="w-6 h-6 text-purple-400" />
                    <h3 className="text-lg font-bold text-white">Delegación de Voto</h3>
                </div>
                <div className="flex items-center gap-2">
                    <Zap className="w-4 h-4 text-yellow-400" />
                    <span className="text-yellow-400 font-bold">
                        Poder de voto: {votingPower}x
                    </span>
                </div>
            </div>

            {/* Current Delegation Status */}
            {delegation?.delegated ? (
                <div className="bg-purple-500/10 border border-purple-500/30 rounded-lg p-4 mb-6">
                    <div className="flex items-center justify-between">
                        <div>
                            <div className="text-sm text-gray-400 mb-1">Tu voto está delegado a:</div>
                            <div className="flex items-center gap-2">
                                <code className="text-purple-400 text-sm">
                                    {delegation.delegate?.slice(0, 10)}...{delegation.delegate?.slice(-8)}
                                </code>
                                <Badge className="bg-purple-500/20 text-purple-400 border-purple-500/30">
                                    Activo
                                </Badge>
                            </div>
                        </div>
                        <Button
                            onClick={handleRevoke}
                            variant="outline"
                            size="sm"
                            disabled={loading}
                            className="border-red-500/50 text-red-400 hover:bg-red-500/10"
                        >
                            <X className="w-4 h-4 mr-1" />
                            Revocar
                        </Button>
                    </div>
                </div>
            ) : (
                /* Delegate Form */
                <div className="mb-6">
                    <label className="text-sm text-gray-400 mb-2 block">
                        Delegar mi voto a:
                    </label>
                    <div className="flex gap-2">
                        <input
                            type="text"
                            value={delegateInput}
                            onChange={(e) => setDelegateInput(e.target.value)}
                            placeholder="0x..."
                            className="cyber-input flex-1"
                        />
                        <Button
                            onClick={handleDelegate}
                            disabled={loading || !delegateInput}
                            className="cyber-button-premium"
                        >
                            {loading ? (
                                <div className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
                            ) : (
                                <>
                                    <ArrowRight className="w-4 h-4 mr-1" />
                                    Delegar
                                </>
                            )}
                        </Button>
                    </div>
                </div>
            )}

            {/* Messages */}
            {error && (
                <div className="flex items-center gap-2 text-red-400 text-sm mb-4">
                    <AlertCircle className="w-4 h-4" />
                    {error}
                </div>
            )}
            {success && (
                <div className="flex items-center gap-2 text-green-400 text-sm mb-4">
                    <Check className="w-4 h-4" />
                    {success}
                </div>
            )}

            {/* Delegators List */}
            {delegators.length > 0 && (
                <div>
                    <div className="text-sm text-gray-400 mb-2">
                        Miembros que te han delegado su voto:
                    </div>
                    <div className="space-y-2">
                        {delegators.map((addr, i) => (
                            <div key={i} className="flex items-center gap-2 text-sm">
                                <div className="w-2 h-2 rounded-full bg-cyan-400" />
                                <code className="text-cyan-400">
                                    {addr.slice(0, 10)}...{addr.slice(-6)}
                                </code>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Info */}
            <div className="mt-4 p-3 bg-black/30 rounded-lg text-xs text-gray-500">
                <p>💡 Al delegar, tu representante votará por ti en todas las propuestas.</p>
                <p className="mt-1">Puedes revocar la delegación en cualquier momento.</p>
            </div>
        </div>
    );
};

export default VoteDelegation;
