/**
 * Representatives — currently seated representatives with an active term.
 * Reads /governance/representatives. Empty state when nobody has been elected.
 */
import React, { useState, useEffect } from 'react';
import { Trophy, Calendar } from 'lucide-react';
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
            <div className="civic-loading">
                <span className="civic-spinner" />
                Cargando representantes…
            </div>
        );
    }

    return (
        <section>
            <h2 className="civic-section-title mb-4">
                <Trophy className="w-5 h-5" />
                Representantes vigentes
            </h2>

            {reps.length === 0 ? (
                <div className="civic-empty">
                    <Trophy className="w-10 h-10" />
                    <p className="civic-empty-title">Todavía no hay representantes electos</p>
                    <p className="civic-empty-desc">
                        Aparecerán aquí cuando una elección cierre con votos registrados.
                    </p>
                </div>
            ) : (
                <div className="space-y-3">
                    {reps.map((r) => (
                        <div
                            key={`${r.election_id}-${r.address}`}
                            className="civic-card civic-card-pad"
                        >
                            <div className="flex items-start justify-between gap-4 flex-wrap">
                                <div>
                                    <p className="civic-mono civic-ink font-semibold">
                                        {r.address.slice(0, 6)}…{r.address.slice(-4)}
                                    </p>
                                    {r.election_title && (
                                        <p className="civic-muted text-xs mt-1">{r.election_title}</p>
                                    )}
                                </div>
                                <div className="text-right">
                                    <p className="civic-ink text-sm font-semibold" style={{ fontFamily: 'Poppins, sans-serif' }}>
                                        {r.votes} votos
                                    </p>
                                    <p className="civic-faint text-xs flex items-center gap-1 justify-end mt-1">
                                        <Calendar className="w-3 h-3" />
                                        {formatDate(r.term_start)} → {formatDate(r.term_end)}
                                    </p>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </section>
    );
};

export default RepresentativesPanel;
