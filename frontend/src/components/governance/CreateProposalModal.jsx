/**
 * Create Proposal Modal Component
 * Modal form for creating new governance proposals
 */
import React, { useState } from 'react';
import { X, FileText, Clock, Tag, Send, AlertCircle } from 'lucide-react';
import { Button } from '../ui/button';
import { governanceAPI } from '@/lib/api';

const CATEGORIES = [
    { value: 'general', label: 'General', color: 'cyan' },
    { value: 'treasury', label: 'Tesorería', color: 'green' },
    { value: 'membership', label: 'Membresía', color: 'purple' },
    { value: 'technical', label: 'Técnico', color: 'orange' },
];

const DURATIONS = [
    { days: 3, label: '3 días' },
    { days: 7, label: '1 semana' },
    { days: 14, label: '2 semanas' },
    { days: 30, label: '1 mes' },
];

const CreateProposalModal = ({ isOpen, onClose, walletAddress, onSuccess }) => {
    const [title, setTitle] = useState('');
    const [description, setDescription] = useState('');
    const [category, setCategory] = useState('general');
    const [durationDays, setDurationDays] = useState(7);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!title.trim()) {
            setError('El título es requerido');
            return;
        }
        if (!description.trim()) {
            setError('La descripción es requerida');
            return;
        }
        if (description.length < 20) {
            setError('La descripción debe tener al menos 20 caracteres');
            return;
        }

        setLoading(true);
        setError('');

        try {
            const response = await governanceAPI.createProposal(
                title,
                description,
                category,
                walletAddress,
                durationDays
            );

            if (response.data) {
                // Reset form
                setTitle('');
                setDescription('');
                setCategory('general');
                setDurationDays(7);

                // Callback
                if (onSuccess) {
                    onSuccess(response.data);
                }
                onClose();
            }
        } catch (err) {
            console.error('Error creating proposal:', err);
            setError(err.response?.data?.detail || 'Error al crear la propuesta');
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            {/* Backdrop */}
            <div
                className="absolute inset-0 bg-black/80 backdrop-blur-sm"
                onClick={onClose}
            />

            {/* Modal */}
            <div className="relative w-full max-w-lg glass-dark rounded-xl border border-cyan-500/30 p-6 animate-in fade-in zoom-in-95 duration-200">
                {/* Header */}
                <div className="flex items-center justify-between mb-6">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-cyan-500/20 flex items-center justify-center">
                            <FileText className="w-5 h-5 text-cyan-400" />
                        </div>
                        <h2 className="text-xl font-bold text-white">Nueva Propuesta</h2>
                    </div>
                    <button
                        onClick={onClose}
                        className="w-8 h-8 rounded-full hover:bg-white/10 flex items-center justify-center transition-colors"
                    >
                        <X className="w-5 h-5 text-gray-400" />
                    </button>
                </div>

                <form onSubmit={handleSubmit} className="space-y-4">
                    {/* Title */}
                    <div>
                        <label className="block text-sm text-gray-400 mb-2">
                            Título de la propuesta
                        </label>
                        <input
                            type="text"
                            value={title}
                            onChange={(e) => setTitle(e.target.value)}
                            placeholder="Ej: Implementar sistema de recompensas"
                            className="cyber-input w-full"
                            maxLength={100}
                        />
                        <div className="text-xs text-gray-500 mt-1 text-right">
                            {title.length}/100
                        </div>
                    </div>

                    {/* Description */}
                    <div>
                        <label className="block text-sm text-gray-400 mb-2">
                            Descripción detallada
                        </label>
                        <textarea
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            placeholder="Describe tu propuesta en detalle. Incluye objetivos, beneficios y plan de implementación..."
                            className="cyber-input w-full h-32 resize-none"
                            maxLength={2000}
                        />
                        <div className="text-xs text-gray-500 mt-1 text-right">
                            {description.length}/2000
                        </div>
                    </div>

                    {/* Category */}
                    <div>
                        <label className="block text-sm text-gray-400 mb-2">
                            <Tag className="w-4 h-4 inline mr-1" />
                            Categoría
                        </label>
                        <div className="grid grid-cols-2 gap-2">
                            {CATEGORIES.map((cat) => (
                                <button
                                    key={cat.value}
                                    type="button"
                                    onClick={() => setCategory(cat.value)}
                                    className={`p-3 rounded-lg border transition-all ${category === cat.value
                                            ? `bg-${cat.color}-500/20 border-${cat.color}-500/50 text-${cat.color}-400`
                                            : 'bg-black/30 border-gray-700 text-gray-400 hover:border-gray-500'
                                        }`}
                                >
                                    {cat.label}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Duration */}
                    <div>
                        <label className="block text-sm text-gray-400 mb-2">
                            <Clock className="w-4 h-4 inline mr-1" />
                            Duración de la votación
                        </label>
                        <div className="grid grid-cols-4 gap-2">
                            {DURATIONS.map((d) => (
                                <button
                                    key={d.days}
                                    type="button"
                                    onClick={() => setDurationDays(d.days)}
                                    className={`p-2 rounded-lg border text-sm transition-all ${durationDays === d.days
                                            ? 'bg-purple-500/20 border-purple-500/50 text-purple-400'
                                            : 'bg-black/30 border-gray-700 text-gray-400 hover:border-gray-500'
                                        }`}
                                >
                                    {d.label}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Error */}
                    {error && (
                        <div className="flex items-center gap-2 text-red-400 text-sm p-3 bg-red-500/10 rounded-lg border border-red-500/30">
                            <AlertCircle className="w-4 h-4 flex-shrink-0" />
                            {error}
                        </div>
                    )}

                    {/* Submit */}
                    <div className="flex gap-3 pt-4">
                        <Button
                            type="button"
                            onClick={onClose}
                            variant="outline"
                            className="flex-1 border-gray-600 text-gray-400"
                        >
                            Cancelar
                        </Button>
                        <Button
                            type="submit"
                            disabled={loading || !title || !description}
                            className="flex-1 cyber-button-premium"
                        >
                            {loading ? (
                                <div className="animate-spin w-5 h-5 border-2 border-white border-t-transparent rounded-full" />
                            ) : (
                                <>
                                    <Send className="w-4 h-4 mr-2" />
                                    Crear Propuesta
                                </>
                            )}
                        </Button>
                    </div>
                </form>

                {/* Info */}
                <div className="mt-4 p-3 bg-black/30 rounded-lg text-xs text-gray-500">
                    <p>💡 Una vez creada, la propuesta estará activa inmediatamente.</p>
                    <p className="mt-1">Los miembros podrán votar durante el período establecido.</p>
                </div>
            </div>
        </div>
    );
};

export default CreateProposalModal;
