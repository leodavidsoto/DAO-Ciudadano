/**
 * Elections — representative elections: nominations, voting and results.
 *
 * Phases come from the backend (`status`), which derives them from dates.
 * Nothing here is fabricated: with no data we render an honest empty state.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Vote, Users, Clock, Trophy, UserPlus, Plus, Loader2 } from 'lucide-react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Textarea } from '../ui/textarea';
import { electionsAPI } from '@/lib/api';

const STATUS_META = {
    nominations: { label: 'CANDIDATURAS ABIERTAS', cls: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40' },
    voting: { label: 'VOTACIÓN EN CURSO', cls: 'bg-green-500/20 text-green-300 border-green-500/40' },
    closed: { label: 'CERRADA', cls: 'bg-gray-500/20 text-gray-400 border-gray-500/40' },
};

const formatDate = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return isNaN(d) ? '—' : d.toLocaleDateString('es-CL', { day: '2-digit', month: 'short', year: 'numeric' });
};

const shortAddr = (a) => (a ? a.slice(0, 6) + '...' + a.slice(-4) : '—');

const errText = (err, fallback) => {
    const d = err?.response?.data?.detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d) && d[0]?.msg) return d[0].msg;
    return fallback;
};

// === Convocatoria ===

const CreateElectionForm = ({ walletAddress, onCreated, onCancel }) => {
    const [form, setForm] = useState({
        title: '', description: '', seats: 1,
        nominations_days: 7, voting_days: 7, term_months: 12,
    });
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState('');

    const submit = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        setError('');
        try {
            await electionsAPI.create({
                title: form.title,
                description: form.description,
                seats: Number(form.seats),
                nominationsDays: Number(form.nominations_days),
                votingDays: Number(form.voting_days),
                termMonths: Number(form.term_months),
                creatorAddress: walletAddress,
            });
            onCreated();
        } catch (err) {
            setError(errText(err, 'No se pudo convocar la elección'));
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <form onSubmit={submit} className="glass-dark p-6 rounded-xl border border-cyan-500/30 space-y-4">
            <h3 className="text-cyan-300 font-mono tracking-wide">CONVOCAR ELECCIÓN</h3>

            <div>
                <Label className="cyber-label">TÍTULO</Label>
                <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
                       placeholder="Ej: Consejo Ciudadano 2026" required />
            </div>

            <div>
                <Label className="cyber-label">DESCRIPCIÓN</Label>
                <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
                          placeholder="Qué cargos se eligen, qué atribuciones tienen y por qué se convoca." rows={4} required />
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {[['seats', 'ESCAÑOS'], ['nominations_days', 'DÍAS CANDIDATURAS'],
                  ['voting_days', 'DÍAS VOTACIÓN'], ['term_months', 'MESES MANDATO']].map(([key, label]) => (
                    <div key={key}>
                        <Label className="cyber-label text-[10px]">{label}</Label>
                        <Input type="number" min={1} value={form[key]}
                               onChange={(e) => setForm({ ...form, [key]: e.target.value })} required />
                    </div>
                ))}
            </div>

            {error && <p className="text-red-400 text-sm font-mono">{error}</p>}

            <div className="flex gap-3">
                <Button type="submit" disabled={submitting} className="cyber-button-premium">
                    {submitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                    CONVOCAR
                </Button>
                <Button type="button" onClick={onCancel} className="cyber-button">CANCELAR</Button>
            </div>
        </form>
    );
};

// === Detalle ===

const ElectionDetail = ({ election, walletAddress, onBack, onChanged }) => {
    const [candidacies, setCandidacies] = useState([]);
    const [results, setResults] = useState(null);
    const [loading, setLoading] = useState(true);
    const [statement, setStatement] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const [cRes, rRes] = await Promise.all([
                electionsAPI.listCandidacies(election.id),
                election.status === 'closed' ? electionsAPI.results(election.id) : Promise.resolve({ data: null }),
            ]);
            setCandidacies(cRes.data || []);
            setResults(rRes.data);
        } catch (err) {
            console.error('Error loading election detail:', err);
        } finally {
            setLoading(false);
        }
    }, [election.id, election.status]);

    useEffect(() => { load(); }, [load]);

    const act = async (fn, successMsg) => {
        setBusy(true); setError(''); setNotice('');
        try {
            await fn();
            setNotice(successMsg);
            await load();
            if (onChanged) onChanged();
        } catch (err) {
            setError(errText(err, 'La operación falló'));
        } finally {
            setBusy(false);
        }
    };

    const meta = STATUS_META[election.status] || STATUS_META.closed;
    const alreadyCandidate = candidacies.some(
        (c) => (c.candidate_address || '').toLowerCase() === (walletAddress || '').toLowerCase()
    );

    return (
        <div className="space-y-5">
            <Button onClick={onBack} className="cyber-button text-xs">← VOLVER</Button>

            <div className="glass-dark p-6 rounded-xl border border-gray-700">
                <div className="flex items-start justify-between gap-4 mb-3">
                    <h2 className="text-xl font-bold text-white">{election.title}</h2>
                    <Badge className={meta.cls}>{meta.label}</Badge>
                </div>
                <p className="text-gray-400 text-sm mb-4 whitespace-pre-line">{election.description}</p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs font-mono">
                    <div><span className="text-gray-500">Escaños:</span> <span className="text-cyan-300">{election.seats}</span></div>
                    <div><span className="text-gray-500">Mandato:</span> <span className="text-cyan-300">{election.term_months} meses</span></div>
                    <div><span className="text-gray-500">Candidaturas hasta:</span> <span className="text-cyan-300">{formatDate(election.nominations_end_at)}</span></div>
                    <div><span className="text-gray-500">Votación hasta:</span> <span className="text-cyan-300">{formatDate(election.voting_end_at)}</span></div>
                </div>
            </div>

            {error && <p className="text-red-400 text-sm font-mono">{error}</p>}
            {notice && <p className="text-green-400 text-sm font-mono">{notice}</p>}

            {election.status === 'nominations' && !alreadyCandidate && (
                <div className="glass-dark p-6 rounded-xl border border-cyan-500/30 space-y-3">
                    <h3 className="text-cyan-300 font-mono flex items-center gap-2">
                        <UserPlus className="w-4 h-4" /> POSTULARSE
                    </h3>
                    <Textarea value={statement} onChange={(e) => setStatement(e.target.value)}
                              placeholder="Tu programa: qué propones y por qué deberían elegirte." rows={4} />
                    <Button disabled={busy || !statement.trim() || !walletAddress}
                            onClick={() => act(() => electionsAPI.runForOffice(election.id, walletAddress, statement),
                                               'Candidatura registrada')}
                            className="cyber-button-premium">
                        PRESENTAR CANDIDATURA
                    </Button>
                </div>
            )}

            <div>
                <h3 className="text-gray-300 font-mono text-sm mb-3 flex items-center gap-2">
                    <Users className="w-4 h-4" /> CANDIDATURAS ({candidacies.length})
                </h3>

                {loading ? (
                    <div className="text-center py-8 text-gray-500 font-mono text-sm">Cargando...</div>
                ) : candidacies.length === 0 ? (
                    <div className="glass-dark p-8 rounded-xl text-center text-gray-500 font-mono text-sm">
                        Todavía no hay candidaturas.
                    </div>
                ) : (
                    <div className="space-y-3">
                        {candidacies.map((c) => (
                            <div key={c.id} className="glass-dark p-4 rounded-xl border border-gray-700">
                                <div className="flex items-start justify-between gap-4">
                                    <div className="flex-1">
                                        <p className="font-mono text-cyan-300 text-sm mb-1">{shortAddr(c.candidate_address)}</p>
                                        <p className="text-gray-400 text-sm whitespace-pre-line">{c.statement}</p>
                                    </div>
                                    {election.status === 'voting' && (
                                        <Button disabled={busy || !walletAddress}
                                                onClick={() => act(() => electionsAPI.vote(election.id, walletAddress, c.candidate_address),
                                                                   'Voto registrado')}
                                                className="cyber-button-premium shrink-0">
                                            <Vote className="w-4 h-4 mr-1" /> VOTAR
                                        </Button>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {election.status === 'closed' && results && (
                <div>
                    <h3 className="text-gray-300 font-mono text-sm mb-3 flex items-center gap-2">
                        <Trophy className="w-4 h-4" /> RESULTADOS
                    </h3>
                    <p className="text-xs font-mono text-gray-500 mb-3">
                        {results.total_votes_cast} votantes · {results.total_weight_cast} de peso total
                    </p>
                    {(results.results || []).length === 0 ? (
                        <div className="glass-dark p-8 rounded-xl text-center text-gray-500 font-mono text-sm">
                            La elección cerró sin votos registrados.
                        </div>
                    ) : (
                        <div className="space-y-2">
                            {results.results.map((r, i) => (
                                <div key={r.candidate_address}
                                     className={'glass-dark p-4 rounded-xl border flex items-center justify-between ' +
                                                (r.elected ? 'border-green-500/40' : 'border-gray-700')}>
                                    <div className="flex items-center gap-3">
                                        <span className="text-gray-500 font-mono text-sm">#{i + 1}</span>
                                        <span className="font-mono text-cyan-300 text-sm">{shortAddr(r.candidate_address)}</span>
                                        {r.elected && (
                                            <Badge className="bg-green-500/20 text-green-300 border-green-500/40">ELECTO</Badge>
                                        )}
                                    </div>
                                    <span className="font-mono text-white">{r.votes} votos</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

// === Listado ===

const ElectionsList = ({ walletAddress }) => {
    const [elections, setElections] = useState([]);
    const [selected, setSelected] = useState(null);
    const [loading, setLoading] = useState(true);
    const [creating, setCreating] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const res = await electionsAPI.list();
            setElections(res.data || []);
        } catch (err) {
            console.error('Error loading elections:', err);
            setElections([]);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    if (selected) {
        const fresh = elections.find((e) => e.id === selected.id) || selected;
        return (
            <ElectionDetail election={fresh} walletAddress={walletAddress}
                            onBack={() => setSelected(null)} onChanged={load} />
        );
    }

    return (
        <div className="space-y-5">
            <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                    <Vote className="w-5 h-5 text-cyan-400" /> ELECCIONES DE REPRESENTANTES
                </h2>
                {walletAddress && !creating && (
                    <Button onClick={() => setCreating(true)} className="cyber-button-premium">
                        <Plus className="w-4 h-4 mr-1" /> CONVOCAR
                    </Button>
                )}
            </div>

            {creating && (
                <CreateElectionForm walletAddress={walletAddress}
                                    onCreated={() => { setCreating(false); load(); }}
                                    onCancel={() => setCreating(false)} />
            )}

            {loading ? (
                <div className="text-center py-12 glass-dark rounded-xl">
                    <Loader2 className="animate-spin w-8 h-8 text-cyan-500 mx-auto mb-3" />
                    <p className="text-gray-400 font-mono text-sm">Cargando elecciones...</p>
                </div>
            ) : elections.length === 0 ? (
                <div className="glass-dark p-10 rounded-xl text-center">
                    <Vote className="w-10 h-10 text-gray-600 mx-auto mb-3" />
                    <p className="text-gray-400 font-mono text-sm">No hay elecciones convocadas.</p>
                </div>
            ) : (
                <div className="space-y-3">
                    {elections.map((e) => {
                        const meta = STATUS_META[e.status] || STATUS_META.closed;
                        return (
                            <button key={e.id} onClick={() => setSelected(e)}
                                    className="w-full text-left glass-dark p-5 rounded-xl border border-gray-700 hover:border-cyan-500/40 transition-colors">
                                <div className="flex items-start justify-between gap-4 mb-2">
                                    <h3 className="font-bold text-white">{e.title}</h3>
                                    <Badge className={meta.cls}>{meta.label}</Badge>
                                </div>
                                <p className="text-gray-400 text-sm mb-3">{e.description}</p>
                                <div className="flex flex-wrap gap-4 text-xs font-mono text-gray-500">
                                    <span className="flex items-center gap-1"><Users className="w-3 h-3" /> {e.candidacy_count || 0} candidaturas</span>
                                    <span className="flex items-center gap-1"><Trophy className="w-3 h-3" /> {e.seats} escaños</span>
                                    <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> hasta {formatDate(e.voting_end_at)}</span>
                                </div>
                            </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
};

export default ElectionsList;
