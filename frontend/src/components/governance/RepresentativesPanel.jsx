/**
 * Representatives — currently seated representatives with an active term.
 * Reads /governance/representatives. Empty state when nobody has been elected.
 */
import React, { useState, useEffect } from 'react';
import { Trophy, Calendar, Loader2 } from 'lucide-react';
import { electionsAPI } from '@/lib/api';

const formatDate = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return isNaN(d) ? '—' : d.toLocaleDateString('es-CL', { day: '2-digit', month: 'short', year: 'numeric' });
};

const RepresentativesPanel = () => {
    const [reps, setReps] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let alive = true;
        electionsAPI.representatives()
            .then((res) => { if (alive) setReps(res.data || []); })
            .catch((err) => { console.error('Error loading representatives:', err); if (alive) setReps([]); })
            .finally(() => { if (alive) setLoading(false); });
        return () => { alive = false; };
    }, []);

    if (loading) {
        return (
            <div className="text-center py-8 glass-dark rounded-xl">
                <Loader2 className="animate-spin w-6 h-6 text-cyan-500 mx-auto mb-2" />
                <p className="text-gray-400 font-mono text-xs">Cargando representantes...</p>
            </div>
        );
    }

    return (
        <div>
            <h3 className="text-gray-300 font-mono text-sm mb-3 flex items-center gap-2">
                <Trophy className="w-4 h-4 text-cyan-400" /> REPRESENTANTES VIGENTES
            </h3>

            {reps.length === 0 ? (
                <div className="glass-dark p-8 rounded-xl text-center text-gray-500 font-mono text-sm">
                    Todavía no hay representantes electos.
                </div>
            ) : (
                <div className="space-y-2">
                    {reps.map((r) => (
                        <div key={`${r.election_id}-${r.address}`}
                             className="glass-dark p-4 rounded-xl border border-green-500/30">
                            <div className="flex items-start justify-between gap-4 flex-wrap">
                                <div>
                                    <p className="font-mono text-cyan-300 text-sm">
                                        {r.address.slice(0, 6)}...{r.address.slice(-4)}
                                    </p>
                                    {r.election_title && (
                                        <p className="text-gray-500 text-xs mt-1">{r.election_title}</p>
                                    )}
                                </div>
                                <div className="text-right">
                                    <p className="font-mono text-white text-sm">{r.votes} votos</p>
                                    <p className="text-gray-500 text-xs flex items-center gap-1 justify-end mt-1">
                                        <Calendar className="w-3 h-3" />
                                        {formatDate(r.term_start)} → {formatDate(r.term_end)}
                                    </p>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default RepresentativesPanel;
