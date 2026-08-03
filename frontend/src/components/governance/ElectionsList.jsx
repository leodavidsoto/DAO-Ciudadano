/**
 * Elections — representative elections: nominations, voting and results.
 *
 * Phases come from the backend (`status`), which derives them from dates.
 * Nothing here is fabricated: with no data we render an honest empty state.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Vote, Users, Clock, Trophy, UserPlus, Plus, ArrowLeft, AlertCircle, Check } from 'lucide-react';
import { electionsAPI } from '@/lib/api';
import useWallet from '@/hooks/useWallet';

const STATUS_META = {
    nominations: { label: 'Candidaturas abiertas', cls: 'civic-tag-blue' },
    voting: { label: 'Votación en curso', cls: 'civic-tag-green' },
    closed: { label: 'Cerrada', cls: 'civic-tag-neutral' },
};

const formatDate = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return isNaN(d) ? '—' : d.toLocaleDateString('es-CL', { day: '2-digit', month: 'short', year: 'numeric' });
};

const shortAddr = (a) => (a ? a.slice(0, 6) + '…' + a.slice(-4) : '—');

const errText = (err, fallback) => {
    const d = err?.response?.data?.detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d) && d[0]?.msg) return d[0].msg;
    return fallback;
};

// === Convocatoria ===

const CAMPOS = [
    ['seats', 'Escaños'],
    ['nominations_days', 'Días de candidaturas'],
    ['voting_days', 'Días de votación'],
    ['term_months', 'Meses de mandato'],
];

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
        <form onSubmit={submit} className="civic-card civic-card-pad space-y-4">
            <h3 className="civic-section-title" style={{ fontSize: 17 }}>
                <Plus className="w-4 h-4" />
                Convocar elección
            </h3>

            <div>
                <label htmlFor="eleccion-titulo" className="civic-label">Título</label>
                <input
                    id="eleccion-titulo"
                    className="civic-field"
                    value={form.title}
                    onChange={(e) => setForm({ ...form, title: e.target.value })}
                    placeholder="Ej: Consejo Ciudadano 2026"
                    required
                />
            </div>

            <div>
                <label htmlFor="eleccion-desc" className="civic-label">Descripción</label>
                <textarea
                    id="eleccion-desc"
                    className="civic-field"
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    placeholder="Qué cargos se eligen, qué atribuciones tienen y por qué se convoca."
                    rows={4}
                    required
                />
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {CAMPOS.map(([key, label]) => (
                    <div key={key}>
                        <label htmlFor={`eleccion-${key}`} className="civic-label">{label}</label>
                        <input
                            id={`eleccion-${key}`}
                            className="civic-field"
                            type="number"
                            min={1}
                            value={form[key]}
                            onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                            required
                        />
                    </div>
                ))}
            </div>

            {error && (
                <div className="civic-note civic-note-error">
                    <AlertCircle className="w-4 h-4" />
                    {error}
                </div>
            )}

            <div className="flex gap-3 flex-wrap">
                <button type="submit" disabled={submitting} className="civic-btn civic-btn-primary">
                    {submitting && <span className="civic-spinner" style={{ borderTopColor: '#fff', borderColor: 'rgba(255,255,255,.4)' }} />}
                    Convocar
                </button>
                <button type="button" onClick={onCancel} className="civic-btn civic-btn-quiet">
                    Cancelar
                </button>
            </div>
        </form>
    );
};

// === Detalle ===

const ElectionDetail = ({ election, walletAddress, onBack, onChanged }) => {
    const { signer } = useWallet();
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

    const actVote = async (electionId, candidateAddress) => {
        setBusy(true); setError(''); setNotice('');
        try {
            const schemaRes = await electionsAPI.getBallotSchema();
            const schema = schemaRes.data;
            let signature = null;
            let nonce = null;

            if (schema.signed_ballots_required) {
                if (!signer) throw new Error("Billetera no conectada para firmar");
                nonce = Date.now().toString() + Math.random().toString(36).substring(2, 7);
                const message = {
                    electionId: electionId,
                    voter: walletAddress,
                    candidate: candidateAddress,
                    nonce: nonce,
                };
                // Ethers v6 signTypedData signature: domain, types, message
                // However, we need to strip EIP712Domain from types as Ethers adds it automatically
                const types = { ...schema.types };
                delete types.EIP712Domain;
                
                signature = await signer.signTypedData(schema.domain, types, message);
            }

            await electionsAPI.vote(electionId, walletAddress, candidateAddress, nonce, signature);
            setNotice('Voto registrado');
            await load();
            if (onChanged) onChanged();
        } catch (err) {
            if (err?.code === 4001 || err?.message?.includes('user rejected')) {
                setError('Firma rechazada por el usuario.');
            } else {
                setError(errText(err, 'La operación de voto falló'));
            }
        } finally {
            setBusy(false);
        }
    };

    const meta = STATUS_META[election.status] || STATUS_META.closed;
    const alreadyCandidate = candidacies.some(
        (c) => (c.candidate_address || '').toLowerCase() === (walletAddress || '').toLowerCase()
    );

    const DATOS = [
        ['Escaños', election.seats],
        ['Mandato', `${election.term_months} meses`],
        ['Candidaturas hasta', formatDate(election.nominations_end_at)],
        ['Votación hasta', formatDate(election.voting_end_at)],
    ];

    return (
        <div className="space-y-5">
            <button onClick={onBack} className="civic-btn civic-btn-sm civic-btn-quiet">
                <ArrowLeft className="w-4 h-4" />
                Volver
            </button>

            <div className="civic-card civic-card-pad">
                <div className="flex items-start justify-between gap-4 mb-3 flex-wrap">
                    <h2 className="civic-section-title" style={{ fontSize: 19 }}>{election.title}</h2>
                    <span className={`civic-tag ${meta.cls}`}>{meta.label}</span>
                </div>
                <p className="civic-muted text-sm mb-4 whitespace-pre-line">{election.description}</p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                    {DATOS.map(([label, value]) => (
                        <div key={label}>
                            <div className="civic-faint text-xs">{label}</div>
                            <div className="civic-ink font-semibold">{value}</div>
                        </div>
                    ))}
                </div>
            </div>

            {error && (
                <div className="civic-note civic-note-error">
                    <AlertCircle className="w-4 h-4" />
                    {error}
                </div>
            )}
            {notice && (
                <div className="civic-note civic-note-ok">
                    <Check className="w-4 h-4" />
                    {notice}
                </div>
            )}

            {election.status === 'nominations' && !alreadyCandidate && (
                <div className="civic-card civic-card-pad space-y-3">
                    <h3 className="civic-section-title" style={{ fontSize: 17 }}>
                        <UserPlus className="w-4 h-4" />
                        Postularse
                    </h3>
                    <textarea
                        className="civic-field"
                        value={statement}
                        onChange={(e) => setStatement(e.target.value)}
                        placeholder="Tu programa: qué propones y por qué deberían elegirte."
                        rows={4}
                        aria-label="Programa de candidatura"
                    />
                    <button
                        disabled={busy || !statement.trim() || !walletAddress}
                        onClick={() => act(
                            () => electionsAPI.runForOffice(election.id, walletAddress, statement),
                            'Candidatura registrada'
                        )}
                        className="civic-btn civic-btn-primary"
                    >
                        Presentar candidatura
                    </button>
                </div>
            )}

            <div>
                <h3 className="civic-section-title mb-3" style={{ fontSize: 17 }}>
                    <Users className="w-4 h-4" />
                    Candidaturas ({candidacies.length})
                </h3>

                {loading ? (
                    <div className="civic-loading">
                        <span className="civic-spinner" />
                        Cargando…
                    </div>
                ) : candidacies.length === 0 ? (
                    <div className="civic-empty">
                        <Users className="w-10 h-10" />
                        <p className="civic-empty-title">Todavía no hay candidaturas</p>
                        <p className="civic-empty-desc">
                            Cualquier miembro activo puede postularse mientras el período siga abierto.
                        </p>
                    </div>
                ) : (
                    <div className="space-y-3">
                        {candidacies.map((c) => (
                            <div key={c.id} className="civic-card civic-card-pad">
                                <div className="flex items-start justify-between gap-4 flex-wrap">
                                    <div className="flex-1 min-w-0">
                                        <p className="civic-mono civic-ink font-semibold mb-1">
                                            {shortAddr(c.candidate_address)}
                                        </p>
                                        <p className="civic-muted text-sm whitespace-pre-line">{c.statement}</p>
                                    </div>
                                    {election.status === 'voting' && (
                                        <button
                                            disabled={busy || !walletAddress}
                                            onClick={() => actVote(election.id, c.candidate_address)}
                                            className="civic-btn civic-btn-primary civic-btn-sm shrink-0"
                                        >
                                            <Vote className="w-4 h-4" />
                                            Votar
                                        </button>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {election.status === 'closed' && results && (
                <div>
                    <h3 className="civic-section-title mb-2" style={{ fontSize: 17 }}>
                        <Trophy className="w-4 h-4" />
                        Resultados
                    </h3>
                    <p className="civic-muted text-xs mb-3">
                        {results.total_votes_cast} votantes · {results.total_weight_cast} de peso total
                    </p>
                    {(results.results || []).length === 0 ? (
                        <div className="civic-empty">
                            <Trophy className="w-10 h-10" />
                            <p className="civic-empty-title">La elección cerró sin votos registrados</p>
                            <p className="civic-empty-desc">Nadie ocupa un escaño: no se elige a quien no recibió votos.</p>
                        </div>
                    ) : (
                        <div className="space-y-2">
                            {results.results.map((r, i) => (
                                <div
                                    key={r.candidate_address}
                                    className="civic-card civic-card-pad flex items-center justify-between gap-4 flex-wrap"
                                    style={r.elected ? { borderColor: '#BFD9C9', background: '#F6FAF7' } : undefined}
                                >
                                    <div className="flex items-center gap-3 flex-wrap">
                                        <span className="civic-faint civic-mono">#{i + 1}</span>
                                        <span className="civic-mono civic-ink font-semibold">
                                            {shortAddr(r.candidate_address)}
                                        </span>
                                        {r.elected && <span className="civic-tag civic-tag-green">Electo</span>}
                                    </div>
                                    <span className="civic-ink font-semibold" style={{ fontFamily: 'Poppins, sans-serif' }}>
                                        {r.votes} votos
                                    </span>
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
        <section className="space-y-5">
            <div className="flex items-center justify-between gap-4 flex-wrap">
                <h2 className="civic-section-title">
                    <Vote className="w-5 h-5" />
                    Elecciones de representantes
                </h2>
                {walletAddress && !creating && (
                    <button onClick={() => setCreating(true)} className="civic-btn civic-btn-primary civic-btn-sm">
                        <Plus className="w-4 h-4" />
                        Convocar
                    </button>
                )}
            </div>

            {creating && (
                <CreateElectionForm walletAddress={walletAddress}
                                    onCreated={() => { setCreating(false); load(); }}
                                    onCancel={() => setCreating(false)} />
            )}

            {loading ? (
                <div className="civic-loading">
                    <span className="civic-spinner" />
                    Cargando elecciones…
                </div>
            ) : elections.length === 0 ? (
                <div className="civic-empty">
                    <Vote className="w-10 h-10" />
                    <p className="civic-empty-title">No hay elecciones convocadas</p>
                    <p className="civic-empty-desc">
                        Cualquier miembro activo puede convocar una desde este panel.
                    </p>
                </div>
            ) : (
                <div className="space-y-3">
                    {elections.map((e) => {
                        const meta = STATUS_META[e.status] || STATUS_META.closed;
                        return (
                            <button
                                key={e.id}
                                onClick={() => setSelected(e)}
                                className="w-full text-left civic-card civic-card-pad civic-card-hover"
                            >
                                <div className="flex items-start justify-between gap-4 mb-2 flex-wrap">
                                    <h3 className="civic-ink font-semibold" style={{ fontFamily: 'Poppins, sans-serif' }}>
                                        {e.title}
                                    </h3>
                                    <span className={`civic-tag ${meta.cls}`}>{meta.label}</span>
                                </div>
                                <p className="civic-muted text-sm mb-3">{e.description}</p>
                                <div className="flex flex-wrap gap-4 civic-faint text-xs">
                                    <span className="flex items-center gap-1"><Users className="w-3 h-3" /> {e.candidacy_count || 0} candidaturas</span>
                                    <span className="flex items-center gap-1"><Trophy className="w-3 h-3" /> {e.seats} escaños</span>
                                    <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> hasta {formatDate(e.voting_end_at)}</span>
                                </div>
                            </button>
                        );
                    })}
                </div>
            )}
        </section>
    );
};

export default ElectionsList;
