/**
 * Vote Delegation Component
 * Delegate your voting power to another member
 *
 * El poder de voto se toma de `voting_power` que devuelve la API, no de
 * `delegators.length + 1`: el backend solo cuenta delegantes que siguen
 * siendo miembros activos, así que contarlos todos acá mostraba un poder
 * mayor al que realmente se aplica al votar.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Users, ArrowRight, X, Check, AlertCircle, Info } from 'lucide-react';
import { governanceAPI } from '@/lib/api';

const VoteDelegation = ({ walletAddress }) => {
    const [delegation, setDelegation] = useState(null);
    const [delegators, setDelegators] = useState([]);
    const [activeDelegators, setActiveDelegators] = useState([]);
    const [votingPower, setVotingPower] = useState(null);
    const [delegateInput, setDelegateInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [success, setSuccess] = useState('');

    const loadDelegation = useCallback(async () => {
        if (!walletAddress) return;
        try {
            const [delegationRes, delegatorsRes] = await Promise.all([
                governanceAPI.getDelegation(walletAddress),
                governanceAPI.getDelegators(walletAddress),
            ]);
            setDelegation(delegationRes.data);
            setDelegators(delegatorsRes.data.delegators || []);
            setActiveDelegators(delegatorsRes.data.active_delegators || []);
            setVotingPower(delegatorsRes.data.voting_power ?? null);
        } catch (err) {
            console.error('Error loading delegation:', err);
        }
    }, [walletAddress]);

    useEffect(() => {
        loadDelegation();
    }, [loadDelegation]);

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
                setSuccess('Voto delegado correctamente.');
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
                setSuccess('Delegación revocada.');
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

    const inactivos = delegators.length - activeDelegators.length;

    return (
        <section className="civic-card civic-card-pad">
            <div className="flex items-center justify-between gap-4 flex-wrap mb-5">
                <h2 className="civic-section-title">
                    <Users className="w-5 h-5" />
                    Delegación de voto
                </h2>
                <span className="civic-tag civic-tag-blue">
                    Poder de voto: {votingPower ?? '—'}
                </span>
            </div>

            {delegation?.delegated ? (
                <div className="civic-note civic-note-info mb-5">
                    <div className="flex items-center justify-between gap-4 flex-wrap w-full">
                        <div>
                            <div className="civic-muted text-xs mb-1">Tu voto está delegado a:</div>
                            <code className="civic-mono civic-ink font-semibold">
                                {delegation.delegate?.slice(0, 10)}…{delegation.delegate?.slice(-8)}
                            </code>
                        </div>
                        <button
                            onClick={handleRevoke}
                            disabled={loading}
                            className="civic-btn civic-btn-sm civic-btn-quiet"
                        >
                            <X className="w-4 h-4" />
                            Revocar
                        </button>
                    </div>
                </div>
            ) : (
                <div className="mb-5">
                    <label htmlFor="delegate-address" className="civic-label">
                        Delegar mi voto a
                    </label>
                    <div className="flex gap-2 flex-wrap">
                        <input
                            id="delegate-address"
                            type="text"
                            value={delegateInput}
                            onChange={(e) => setDelegateInput(e.target.value)}
                            placeholder="0x…"
                            className="civic-field"
                            style={{ flex: '1 1 240px' }}
                        />
                        <button
                            onClick={handleDelegate}
                            disabled={loading || !delegateInput}
                            className="civic-btn civic-btn-primary"
                        >
                            {loading ? (
                                <span className="civic-spinner" style={{ borderTopColor: '#fff', borderColor: 'rgba(255,255,255,.4)' }} />
                            ) : (
                                <>
                                    <ArrowRight className="w-4 h-4" />
                                    Delegar
                                </>
                            )}
                        </button>
                    </div>
                </div>
            )}

            {error && (
                <div className="civic-note civic-note-error mb-4">
                    <AlertCircle className="w-4 h-4" />
                    {error}
                </div>
            )}
            {success && (
                <div className="civic-note civic-note-ok mb-4">
                    <Check className="w-4 h-4" />
                    {success}
                </div>
            )}

            {delegators.length > 0 && (
                <div className="mb-5">
                    <p className="civic-eyebrow mb-2">Miembros que te delegaron su voto</p>
                    <div className="space-y-2">
                        {delegators.map((addr) => {
                            const activo = activeDelegators.includes(addr);
                            return (
                                <div key={addr} className="flex items-center gap-2 text-sm">
                                    <span
                                        className="w-2 h-2 rounded-full shrink-0"
                                        style={{ background: activo ? '#2E8B57' : '#C2D2EC' }}
                                    />
                                    <code className="civic-mono civic-ink">
                                        {addr.slice(0, 10)}…{addr.slice(-6)}
                                    </code>
                                    {!activo && (
                                        <span className="civic-tag civic-tag-neutral">Sin membresía activa</span>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                    {inactivos > 0 && (
                        <p className="civic-help">
                            {inactivos} delegación(es) no suman poder de voto porque quien delegó
                            ya no es miembro activo.
                        </p>
                    )}
                </div>
            )}

            <div className="civic-note civic-note-info">
                <Info className="w-4 h-4" />
                <span>
                    Al delegar, tu representante vota por ti en todas las propuestas y no
                    podrás votar directamente hasta revocar. La delegación no es transitiva:
                    tu voto llega a quien elegiste, no a quien esa persona delegue.
                </span>
            </div>
        </section>
    );
};

export default VoteDelegation;
