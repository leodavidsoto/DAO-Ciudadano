/**
 * Proposals List Component
 * Display and vote on governance proposals
 */
import React, { useState, useEffect } from 'react';
import {
    Vote, ThumbsUp, ThumbsDown, MinusCircle,
    Clock, Users, CheckCircle, XCircle, Timer,
    PlusCircle, ChevronRight
} from 'lucide-react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { governanceAPI } from '@/lib/api';
import CreateProposalModal from './CreateProposalModal';

const ProposalCard = ({ proposal, walletAddress, onVote }) => {
    const [voting, setVoting] = useState(false);

    const totalVotes = proposal.votes_for + proposal.votes_against + proposal.votes_abstain;
    const forPercent = totalVotes > 0 ? (proposal.votes_for / totalVotes) * 100 : 0;
    const againstPercent = totalVotes > 0 ? (proposal.votes_against / totalVotes) * 100 : 0;

    const statusColors = {
        active: 'bg-green-500/20 text-green-400 border-green-500/30',
        passed: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
        rejected: 'bg-red-500/20 text-red-400 border-red-500/30',
        expired: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
    };

    const statusIcons = {
        active: <Clock className="w-3 h-3" />,
        passed: <CheckCircle className="w-3 h-3" />,
        rejected: <XCircle className="w-3 h-3" />,
        expired: <Timer className="w-3 h-3" />,
    };

    const handleVote = async (voteType) => {
        if (!walletAddress || voting) return;
        setVoting(true);
        try {
            await onVote(proposal.id, voteType);
        } finally {
            setVoting(false);
        }
    };

    const endsAt = new Date(proposal.ends_at);
    const timeLeft = Math.max(0, Math.floor((endsAt - new Date()) / (1000 * 60 * 60 * 24)));

    return (
        <div className="proposal-card glass-dark p-4 rounded-lg border border-cyan-500/20 hover:border-cyan-500/40 transition-all">
            {/* Header */}
            <div className="flex items-start justify-between mb-3">
                <div className="flex-1">
                    <h3 className="font-bold text-white text-lg mb-1">{proposal.title}</h3>
                    <div className="flex items-center gap-2">
                        <Badge className={`text-xs ${statusColors[proposal.status]} border`}>
                            {statusIcons[proposal.status]}
                            <span className="ml-1">{proposal.status.toUpperCase()}</span>
                        </Badge>
                        <span className="text-xs text-gray-500 font-mono">
                            {proposal.category}
                        </span>
                    </div>
                </div>
                {proposal.status === 'active' && (
                    <div className="text-right">
                        <div className="text-xs text-gray-400">Cierra en</div>
                        <div className="text-cyan-400 font-mono font-bold">{timeLeft}d</div>
                    </div>
                )}
            </div>

            {/* Description */}
            <p className="text-gray-400 text-sm mb-4 line-clamp-2">
                {proposal.description}
            </p>

            {/* Vote Progress Bar */}
            <div className="mb-4">
                <div className="flex justify-between text-xs text-gray-400 mb-1">
                    <span className="text-green-400">A favor: {proposal.votes_for}</span>
                    <span className="text-red-400">En contra: {proposal.votes_against}</span>
                </div>
                <div className="h-2 bg-gray-800 rounded-full overflow-hidden flex">
                    <div
                        className="bg-green-500 transition-all"
                        style={{ width: `${forPercent}%` }}
                    />
                    <div
                        className="bg-red-500 transition-all"
                        style={{ width: `${againstPercent}%` }}
                    />
                </div>
                <div className="flex justify-between text-xs text-gray-500 mt-1">
                    <span><Users className="inline w-3 h-3 mr-1" />{totalVotes} votos</span>
                    <span>Quórum: {proposal.quorum_required}</span>
                </div>
            </div>

            {/* Vote Buttons */}
            {proposal.status === 'active' && walletAddress && (
                <div className="grid grid-cols-3 gap-2">
                    <Button
                        onClick={() => handleVote('for')}
                        disabled={voting}
                        className="bg-green-500/20 hover:bg-green-500/30 text-green-400 border border-green-500/30"
                        size="sm"
                    >
                        <ThumbsUp className="w-4 h-4 mr-1" />
                        A favor
                    </Button>
                    <Button
                        onClick={() => handleVote('against')}
                        disabled={voting}
                        className="bg-red-500/20 hover:bg-red-500/30 text-red-400 border border-red-500/30"
                        size="sm"
                    >
                        <ThumbsDown className="w-4 h-4 mr-1" />
                        En contra
                    </Button>
                    <Button
                        onClick={() => handleVote('abstain')}
                        disabled={voting}
                        className="bg-gray-500/20 hover:bg-gray-500/30 text-gray-400 border border-gray-500/30"
                        size="sm"
                    >
                        <MinusCircle className="w-4 h-4 mr-1" />
                        Abstener
                    </Button>
                </div>
            )}
        </div>
    );
};

const ProposalsList = ({ walletAddress }) => {
    const [proposals, setProposals] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState(null);
    const [showCreateModal, setShowCreateModal] = useState(false);

    useEffect(() => {
        loadProposals();
    }, [filter]);

    const loadProposals = async () => {
        setLoading(true);
        try {
            const response = await governanceAPI.getProposals(filter);
            setProposals(response.data);
        } catch (err) {
            console.error('Error loading proposals:', err);
        } finally {
            setLoading(false);
        }
    };

    const handleVote = async (proposalId, vote) => {
        try {
            const response = await governanceAPI.vote(proposalId, walletAddress, vote);
            if (response.data.ok) {
                loadProposals(); // Reload to show updated counts
            } else {
                alert(response.data.error);
            }
        } catch (err) {
            console.error('Vote error:', err);
        }
    };

    const filters = [
        { value: null, label: 'Todas' },
        { value: 'active', label: 'Activas' },
        { value: 'passed', label: 'Aprobadas' },
        { value: 'rejected', label: 'Rechazadas' },
    ];

    return (
        <div className="proposals-list">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-2">
                    <Vote className="w-6 h-6 text-cyan-400" />
                    <h2 className="text-xl font-bold text-white">Propuestas</h2>
                </div>
                {walletAddress && (
                    <Button
                        onClick={() => setShowCreateModal(true)}
                        className="cyber-button-premium"
                        size="sm"
                    >
                        <PlusCircle className="w-4 h-4 mr-1" />
                        Nueva Propuesta
                    </Button>
                )}
            </div>

            {/* Filters */}
            <div className="flex gap-2 mb-6 overflow-x-auto pb-2">
                {filters.map(f => (
                    <Button
                        key={f.value || 'all'}
                        onClick={() => setFilter(f.value)}
                        variant={filter === f.value ? 'default' : 'outline'}
                        size="sm"
                        className={filter === f.value
                            ? 'bg-cyan-500/30 text-cyan-400 border-cyan-500'
                            : 'border-gray-600 text-gray-400'}
                    >
                        {f.label}
                    </Button>
                ))}
            </div>

            {/* Proposals Grid */}
            {loading ? (
                <div className="text-center py-8 text-gray-400">
                    <div className="animate-spin w-8 h-8 border-2 border-cyan-500 border-t-transparent rounded-full mx-auto mb-2" />
                    Cargando propuestas...
                </div>
            ) : proposals.length === 0 ? (
                <div className="text-center py-12 glass-dark rounded-lg">
                    <Vote className="w-12 h-12 mx-auto text-gray-500 mb-3" />
                    <p className="text-gray-400">No hay propuestas {filter ? `${filter}s` : ''}</p>
                    {walletAddress && (
                        <Button
                            onClick={() => setShowCreateModal(true)}
                            className="mt-4 cyber-button"
                        >
                            Crear la primera propuesta
                        </Button>
                    )}
                </div>
            ) : (
                <div className="space-y-4">
                    {proposals.map(proposal => (
                        <ProposalCard
                            key={proposal.id}
                            proposal={proposal}
                            walletAddress={walletAddress}
                            onVote={handleVote}
                        />
                    ))}
                </div>
            )}

            {/* Create Proposal Modal */}
            <CreateProposalModal
                isOpen={showCreateModal}
                onClose={() => setShowCreateModal(false)}
                walletAddress={walletAddress}
                onSuccess={loadProposals}
            />
        </div>
    );
};

export default ProposalsList;
