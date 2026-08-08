/**
 * Registration Step - RUT + Email registration
 * Simple registration while waiting for ClaveÚnica sandbox access
 */
import React, { useState } from 'react';
import { UserPlus, Mail, CreditCard, User } from 'lucide-react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { CyberPanel, CyberLoader, SuccessDisplay } from './CyberUI';
import { useOnboarding } from '@/context';
import { authAPI } from '@/lib/api';

const RegistrationStep = () => {
    const { setLoading, loading, setClave, setStep } = useOnboarding();
    const [formData, setFormData] = useState({
        rut: '',
        email: '',
        nombre: '',
        apellido: ''
    });
    const [error, setError] = useState('');
    const [isLogin, setIsLogin] = useState(false);
    const [processingAccepted, setProcessingAccepted] = useState(false);

    const formatRut = (value) => {
        // Remove all non-alphanumeric characters
        let clean = value.replace(/[^0-9kK]/gi, '');

        if (clean.length > 9) {
            clean = clean.slice(0, 9);
        }

        if (clean.length > 1) {
            // Insert dots and dash
            const body = clean.slice(0, -1);
            const check = clean.slice(-1);

            let formatted = '';
            for (let i = body.length - 1, count = 0; i >= 0; i--, count++) {
                if (count > 0 && count % 3 === 0) {
                    formatted = '.' + formatted;
                }
                formatted = body[i] + formatted;
            }
            return `${formatted}-${check.toUpperCase()}`;
        }

        return clean;
    };

    const handleRutChange = (e) => {
        const formatted = formatRut(e.target.value);
        setFormData(prev => ({ ...prev, rut: formatted }));
        setError('');
    };

    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));
        setError('');
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        if (!processingAccepted) {
            setError('Confirma la advertencia de tratamiento antes de enviar tus datos al backend.');
            return;
        }
        setLoading(true);

        try {
            let response;
            if (isLogin) {
                response = await authAPI.login(formData.rut, formData.email);
            } else {
                response = await authAPI.register(
                    formData.rut,
                    formData.email,
                    formData.nombre,
                    formData.apellido
                );
            }

            if (response.data.ok) {
                // Set clave state for compatibility with existing flow
                setClave({
                    subject_id: response.data.subject_id,
                    assurance_level: response.data.assurance_level,
                    user_id: response.data.user_id,
                    rut: response.data.rut,
                    email: response.data.email,
                    nombre: response.data.nombre
                });
                // Proceed to next step (consent)
                setStep('consent');
            } else {
                setError(response.data.error || 'Error en el proceso');
            }
        } catch (err) {
            const backendError = err.response?.data?.detail || err.response?.data?.error;
            setError(
                typeof backendError === 'string'
                    ? backendError
                    : backendError
                        ? JSON.stringify(backendError)
                        : err.response
                            ? `El servidor rechazó la solicitud (${err.response.status})`
                            : 'No fue posible conectar con el servidor'
            );
        } finally {
            setLoading(false);
        }
    };

    return (
        <CyberPanel
            title={isLogin ? "INICIAR SESIÓN DEL PILOTO" : "CREAR CUENTA PILOTO"}
            description={isLogin
                ? "Ingresa a tu cuenta piloto; esto no acredita tu identidad"
                : "RUT y correo son datos declarados y no se contrastan con una fuente oficial"}
            icon={isLogin ? <CreditCard className="h-8 w-8" /> : <UserPlus className="h-8 w-8" />}
        >
            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                {/* RUT Input */}
                <div className="cyber-input-group">
                    <label className="cyber-label">
                        <CreditCard className="w-4 h-4 inline mr-2" />
                        RUT
                    </label>
                    <input
                        type="text"
                        name="rut"
                        value={formData.rut}
                        onChange={handleRutChange}
                        placeholder="12.345.678-9"
                        className="cyber-input"
                        required
                    />
                </div>

                {/* Email Input */}
                <div className="cyber-input-group">
                    <label className="cyber-label">
                        <Mail className="w-4 h-4 inline mr-2" />
                        Correo Electrónico
                    </label>
                    <input
                        type="email"
                        name="email"
                        value={formData.email}
                        onChange={handleChange}
                        placeholder="tu@email.com"
                        className="cyber-input"
                        required
                    />
                </div>

                {/* Name fields (only for registration) */}
                {!isLogin && (
                    <>
                        <div className="cyber-input-group">
                            <label className="cyber-label">
                                <User className="w-4 h-4 inline mr-2" />
                                Nombre
                            </label>
                            <input
                                type="text"
                                name="nombre"
                                value={formData.nombre}
                                onChange={handleChange}
                                placeholder="Tu nombre"
                                className="cyber-input"
                                required
                            />
                        </div>

                        <div className="cyber-input-group">
                            <label className="cyber-label">
                                <User className="w-4 h-4 inline mr-2" />
                                Apellido
                            </label>
                            <input
                                type="text"
                                name="apellido"
                                value={formData.apellido}
                                onChange={handleChange}
                                placeholder="Tu apellido"
                                className="cyber-input"
                                required
                            />
                        </div>
                    </>
                )}

                <label className="flex items-start gap-3 rounded-lg border border-yellow-500/40 bg-yellow-500/10 p-4 text-left">
                    <input
                        type="checkbox"
                        checked={processingAccepted}
                        onChange={(event) => setProcessingAccepted(event.target.checked)}
                        className="mt-1"
                    />
                    <span className="text-sm text-gray-300">
                        {isLogin
                            ? 'Confirmo que deseo enviar mi RUT y correo al backend para buscar una cuenta piloto existente.'
                            : 'Confirmo que deseo enviar RUT, correo, nombre y apellido al backend para crear una cuenta piloto cifrada.'}
                        {' '}Estos datos son declarados, no acreditan identidad y el proyecto aún no tiene una
                        política legal y de retención definitiva.
                    </span>
                </label>

                {/* Error display */}
                {error && (
                    <div className="cyber-error">
                        {error}
                    </div>
                )}

                {/* Loading */}
                {loading && <CyberLoader text={isLogin ? "VERIFICANDO..." : "REGISTRANDO..."} />}

                {/* Submit button */}
                {!loading && (
                    <Button
                        type="submit"
                        className="cyber-button-premium mt-4"
                        disabled={!processingAccepted}
                    >
                        {isLogin ? (
                            <>
                                <CreditCard className="w-4 h-4 mr-2" />
                                INICIAR SESIÓN
                            </>
                        ) : (
                            <>
                                <UserPlus className="w-4 h-4 mr-2" />
                                CREAR CUENTA PILOTO
                            </>
                        )}
                    </Button>
                )}

                {/* Toggle between login/register */}
                <div className="text-center mt-4">
                    <button
                        type="button"
                        onClick={() => {
                            setIsLogin(!isLogin);
                            setError('');
                            setProcessingAccepted(false);
                        }}
                        className="text-cyan-400 hover:text-cyan-300 text-sm font-mono underline"
                    >
                        {isLogin ? '¿No tienes cuenta? Regístrate' : '¿Ya tienes cuenta? Inicia sesión'}
                    </button>
                </div>

                {/* Info badge */}
                <div className="text-center mt-2">
                    <Badge className="cyber-badge text-xs">
                        Registro de cuenta • No acredita identidad
                    </Badge>
                </div>
            </form>
        </CyberPanel>
    );
};

export default RegistrationStep;
