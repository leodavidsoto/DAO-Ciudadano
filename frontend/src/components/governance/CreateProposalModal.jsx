/**
 * Create Proposal Modal Component
 * Modal form for creating new governance proposals
 *
 * Las opciones de categoría/duración se marcaban con clases Tailwind armadas
 * por interpolación (`bg-${cat.color}-500/20`). Tailwind purga lo que no
 * aparece literal en el código, así que esas clases nunca se generaban y la
 * opción elegida no se distinguía de las demás. Ahora el estado activo usa
 * clases reales del sistema cívico.
 */
import React, { useState, useEffect } from 'react';
import { X, FileText, Clock, Tag, Send, AlertCircle, Info } from 'lucide-react';
import { governanceAPI } from '@/lib/api';

const CATEGORIES = [
    { value: 'general', label: 'General' },
    { value: 'treasury', label: 'Tesorería' },
    { value: 'membership', label: 'Membresía' },
    { value: 'technical', label: 'Técnico' },
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

    // Cerrar con Escape: el diálogo se abría sin ninguna salida de teclado.
    useEffect(() => {
        if (!isOpen) return;
        const onKey = (e) => { if (e.key === 'Escape') onClose(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [isOpen, onClose]);

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
        <div className="civic-app fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'transparent', minHeight: 0 }}>
            <div
                className="absolute inset-0"
                style={{ background: 'rgba(11, 37, 69, 0.45)', backdropFilter: 'blur(2px)' }}
                onClick={onClose}
            />

            <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="nueva-propuesta-titulo"
                className="civic-dialog relative w-full max-w-lg p-6 overflow-y-auto"
                style={{ maxHeight: '90vh' }}
            >
                <div className="flex items-center justify-between gap-4 mb-5">
                    <div className="flex items-center gap-3">
                        <span
                            className="w-10 h-10 rounded-full flex items-center justify-center shrink-0"
                            style={{ background: '#EAF0FB' }}
                        >
                            <FileText className="w-5 h-5" style={{ color: '#003897' }} />
                        </span>
                        <h2 id="nueva-propuesta-titulo" className="civic-ink text-lg font-bold" style={{ fontFamily: 'Poppins, sans-serif' }}>
                            Nueva propuesta
                        </h2>
                    </div>
                    <button
                        onClick={onClose}
                        aria-label="Cerrar"
                        className="w-8 h-8 rounded-full flex items-center justify-center civic-muted"
                        style={{ border: '1px solid #E5EBF5', background: '#fff' }}
                    >
                        <X className="w-4 h-4" />
                    </button>
                </div>

                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label htmlFor="propuesta-titulo" className="civic-label">
                            Título de la propuesta
                        </label>
                        <input
                            id="propuesta-titulo"
                            type="text"
                            value={title}
                            onChange={(e) => setTitle(e.target.value)}
                            placeholder="Ej: Implementar sistema de recompensas"
                            className="civic-field"
                            maxLength={100}
                        />
                        <div className="civic-help text-right">{title.length}/100</div>
                    </div>

                    <div>
                        <label htmlFor="propuesta-desc" className="civic-label">
                            Descripción detallada
                        </label>
                        <textarea
                            id="propuesta-desc"
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            placeholder="Describe tu propuesta en detalle: objetivos, beneficios y plan de implementación."
                            className="civic-field resize-none"
                            style={{ height: 128 }}
                            maxLength={2000}
                        />
                        <div className="civic-help text-right">{description.length}/2000</div>
                    </div>

                    <fieldset>
                        <legend className="civic-label">
                            <Tag className="w-4 h-4 inline mr-1" />
                            Categoría
                        </legend>
                        <div className="grid grid-cols-2 gap-2">
                            {CATEGORIES.map((cat) => (
                                <button
                                    key={cat.value}
                                    type="button"
                                    onClick={() => setCategory(cat.value)}
                                    aria-pressed={category === cat.value}
                                    className={
                                        'civic-btn ' +
                                        (category === cat.value ? 'civic-btn-ghost' : 'civic-btn-quiet')
                                    }
                                >
                                    {cat.label}
                                </button>
                            ))}
                        </div>
                    </fieldset>

                    <fieldset>
                        <legend className="civic-label">
                            <Clock className="w-4 h-4 inline mr-1" />
                            Duración de la votación
                        </legend>
                        <div className="grid grid-cols-4 gap-2">
                            {DURATIONS.map((d) => (
                                <button
                                    key={d.days}
                                    type="button"
                                    onClick={() => setDurationDays(d.days)}
                                    aria-pressed={durationDays === d.days}
                                    className={
                                        'civic-btn civic-btn-sm ' +
                                        (durationDays === d.days ? 'civic-btn-ghost' : 'civic-btn-quiet')
                                    }
                                >
                                    {d.label}
                                </button>
                            ))}
                        </div>
                    </fieldset>

                    {error && (
                        <div className="civic-note civic-note-error">
                            <AlertCircle className="w-4 h-4" />
                            {error}
                        </div>
                    )}

                    <div className="flex gap-3 pt-2">
                        <button
                            type="button"
                            onClick={onClose}
                            className="civic-btn civic-btn-quiet flex-1"
                        >
                            Cancelar
                        </button>
                        <button
                            type="submit"
                            disabled={loading || !title || !description}
                            className="civic-btn civic-btn-primary flex-1"
                        >
                            {loading ? (
                                <span className="civic-spinner" style={{ borderTopColor: '#fff', borderColor: 'rgba(255,255,255,.4)' }} />
                            ) : (
                                <>
                                    <Send className="w-4 h-4" />
                                    Crear propuesta
                                </>
                            )}
                        </button>
                    </div>
                </form>

                <div className="civic-note civic-note-info mt-4">
                    <Info className="w-4 h-4" />
                    <span>
                        La propuesta queda activa de inmediato y los miembros podrán votar
                        durante el período que elijas.
                    </span>
                </div>
            </div>
        </div>
    );
};

export default CreateProposalModal;
