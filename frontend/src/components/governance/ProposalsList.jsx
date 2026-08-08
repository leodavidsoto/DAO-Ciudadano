/**
 * Proposals List Component
 * Display and vote on governance proposals
 *
 * Estilo cívico (styles/civic.css): fondo claro, azul/rojo de la bandera.
 * El verde solo marca resultados favorables; nunca es un color de marca.
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
    Vote,
    Clock, Users, CheckCircle, XCircle, Timer,
    LockKeyhole, PlusCircle
} from 'lucide-react';
import { governanceAPI } from '@/lib/api';
import CreateProposalModal from './CreateProposalModal';

const CATEGORIAS = {
    general: 'General',
    treasury: 'Tesorería',
    membership: 'Membresía',
    technical: 'Técnico',
};

const ESTADOS = {
    active: { tag: 'civic-tag-blue', label: 'En votación', icon: <Clock className="w-3 h-3" /> },
    passed: { tag: 'civic-tag-green', label: 'Aprobada', icon: <CheckCircle className="w-3 h-3" /> },
    rejected: { tag: 'civic-tag-red', label: 'Rechazada', icon: <XCircle className="w-3 h-3" /> },
    expired: { tag: 'civic-tag-neutral', label: 'Expirada', icon: <Timer className="w-3 h-3" /> },
};

const ProposalCard = ({ proposal, walletAddress, chainId, eip1193Provider, onVoteSuccess }) => {
    const totalVotes = proposal.votes_for + proposal.votes_against + proposal.votes_abstain;
    const forPercent = totalVotes > 0 ? (proposal.votes_for / totalVotes) * 100 : 0;
    const againstPercent = totalVotes > 0 ? (proposal.votes_against / totalVotes) * 100 : 0;

    const estado = ESTADOS[proposal.status] || ESTADOS.expired;

    
    const [voting, setVoting] = useState(false);
    const handlePublicVote = async (choice) => {
        if (!eip1193Provider) return alert('No eip1193Provider');
        setVoting(true);
        try {
            const schemaRes = await governanceAPI.getBallotSchema();
            const { types, primaryType, domainName, domainVersion } = schemaRes.data;
            const nonce = crypto.randomUUID();
            const domain = {
                name: domainName || "DAO Ciudadana",
                version: domainVersion || "1",
                chainId: Number(chainId || 11155111)
            };
            const message = {
                proposalId: proposal.id,
                voter: walletAddress,
                choice: choice,
                nonce: nonce
            };
            const payload = {
                types: types,
                primaryType: primaryType,
                domain: domain,
                message: message
            };
            
            const signature = await eip1193Provider.request({
                method: 'eth_signTypedData_v4',
                params: [walletAddress, JSON.stringify(payload)]
            });
            await governanceAPI.vote(proposal.id, walletAddress, choice, nonce, signature);
            if (onVoteSuccess) onVoteSuccess();
        } catch (err) {
            console.error(err);
            alert('Error al votar: ' + err.message);
        } finally {
            setVoting(false);
        }
    };

    const endsAt = new Date(proposal.ends_at);
    const timeLeft = Math.max(0, Math.floor((endsAt - new Date()) / (1000 * 60 * 60 * 24)));

    return (
        <article className="civic-card civic-card-pad civic-card-hover">
            <div className="flex items-start justify-between gap-4 mb-3">
                <div className="flex-1 min-w-0">
                    <h3 className="civic-ink font-semibold text-base mb-2" style={{ fontFamily: 'Poppins, sans-serif' }}>
                        {proposal.title}
                    </h3>
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className={`civic-tag ${estado.tag}`}>
                            {estado.icon}
                            {estado.label}
                        </span>
                        <span className="civic-faint text-xs">
                            {CATEGORIAS[proposal.category] || proposal.category}
                        </span>
                    </div>
                </div>
                {proposal.status === 'active' && (
                    <div className="text-right shrink-0">
                        <div className="civic-faint text-xs">Cierra en</div>
                        <div className="civic-ink font-bold" style={{ fontFamily: 'Poppins, sans-serif' }}>
                            {timeLeft}d
                        </div>
                    </div>
                )}
            </div>

            <p className="civic-muted text-sm mb-4 line-clamp-2">{proposal.description}</p>

            {proposal.status === 'active' ? (
                <div className="civic-sealed-tally" role="note">
                    <LockKeyhole className="w-4 h-4" />
                    <span>
                        <strong>Sin recuento parcial</strong>
                        Las preferencias no se publican mientras la urna está abierta.
                        El resultado requiere cierre y tally verificable.
                    </span>
                </div>
            ) : (
                <div className="mb-4">
                    <div className="flex justify-between text-xs mb-1.5">
                        <span style={{ color: '#1F6B45' }}>A favor: {proposal.votes_for}</span>
                        <span style={{ color: '#A9211D' }}>En contra: {proposal.votes_against}</span>
                    </div>
                    <div className="civic-bar">
                        <div className="civic-bar-for" style={{ width: `${forPercent}%` }} />
                        <div className="civic-bar-against" style={{ width: `${againstPercent}%` }} />
                    </div>
                    <div className="flex justify-between civic-faint text-xs mt-1.5">
                        <span><Users className="inline w-3 h-3 mr-1" />{totalVotes} votos</span>
                        <span>Quórum: {proposal.quorum_required}</span>
                    </div>
                </div>
            )}

        
            {proposal.status === 'active' && walletAddress && (
                <div style={{ marginTop: '16px', borderTop: '1px solid #eaeaea', paddingTop: '16px' }}>
                    <p className="civic-eyebrow mb-2">Voto EIP-712 (Público)</p>
                    <div className="flex gap-2">
                        <button disabled={voting} onClick={() => handlePublicVote('for')} className="civic-btn civic-btn-sm" style={{borderColor: '#1F6B45', color: '#1F6B45'}}>Votar A favor</button>
                        <button disabled={voting} onClick={() => handlePublicVote('against')} className="civic-btn civic-btn-sm" style={{borderColor: '#A9211D', color: '#A9211D'}}>Votar En contra</button>
                    </div>
                </div>
            )}

        </article>
    );
};

const ProposalsList = ({ walletAddress, chainId, eip1193Provider }) => {
    const [proposals, setProposals] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState(null);
    const [showCreateModal, setShowCreateModal] = useState(false);

    const loadProposals = useCallback(async () => {
        setLoading(true);
        try {
            const response = await governanceAPI.getProposals(filter);
            setProposals(response.data);
        } catch (err) {
            console.error('Error loading proposals:', err);
        } finally {
            setLoading(false);
        }
    }, [filter]);

    useEffect(() => {
        loadProposals();
    }, [loadProposals]);

    const filters = [
        { value: null, label: 'Todas' },
        { value: 'active', label: 'En votación' },
        { value: 'passed', label: 'Aprobadas' },
        { value: 'rejected', label: 'Rechazadas' },
    ];

    return (
        <section>
            <div className="flex items-center justify-between gap-4 flex-wrap mb-5">
                <h2 className="civic-section-title">
                    <Vote className="w-5 h-5" />
                    Propuestas
                </h2>
                {walletAddress && (
                    <button
                        onClick={() => setShowCreateModal(true)}
                        className="civic-btn civic-btn-primary civic-btn-sm"
                    >
                        <PlusCircle className="w-4 h-4" />
                        Nueva propuesta
                    </button>
                )}
            </div>

            <div className="flex gap-2 mb-5 overflow-x-auto pb-1">
                {filters.map(f => (
                    <button
                        key={f.value || 'all'}
                        onClick={() => setFilter(f.value)}
                        className={'civic-filter' + (filter === f.value ? ' is-active' : '')}
                        aria-pressed={filter === f.value}
                    >
                        {f.label}
                    </button>
                ))}
            </div>

            {loading ? (
                <div className="civic-loading">
                    <span className="civic-spinner" />
                    Cargando propuestas…
                </div>
            ) : proposals.length === 0 ? (
                <div className="civic-empty">
                    <Vote className="w-10 h-10" />
                    <p className="civic-empty-title">Todavía no hay propuestas</p>
                    <p className="civic-empty-desc">
                        {filter
                            ? 'Ninguna propuesta coincide con este filtro.'
                            : 'Cuando alguien presente la primera, aparecerá aquí.'}
                    </p>
                    {walletAddress && (
                        <button
                            onClick={() => setShowCreateModal(true)}
                            className="civic-btn civic-btn-primary civic-btn-sm"
                            style={{ marginTop: 18 }}
                        >
                            Crear la primera propuesta
                        </button>
                    )}
                </div>
            ) : (
                <div className="space-y-4">
                    {proposals.map(proposal => (
                        <ProposalCard
                            key={proposal.id}
                            proposal={proposal}
                            walletAddress={walletAddress}
                            chainId={chainId}
                            eip1193Provider={eip1193Provider}
                            onVoteSuccess={loadProposals}
                        />
                    ))}
                </div>
            )}

            <CreateProposalModal
                isOpen={showCreateModal}
                onClose={() => setShowCreateModal(false)}
                walletAddress={walletAddress}
                onSuccess={loadProposals}
            />
        </section>
    );
};

export default ProposalsList;
