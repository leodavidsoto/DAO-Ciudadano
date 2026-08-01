import React from 'react';
import { useOnboarding } from '@/context';

const CivicMethodSelector = () => {
    const { rut, setRut, setStep } = useOnboarding();

    return (
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
            <h2 style={{ fontFamily: 'Poppins, sans-serif', fontSize: 22, fontWeight: 600, color: '#003897', marginBottom: 24, textAlign: 'center', letterSpacing: '-0.01em' }}>
                Selecciona tu método de verificación
            </h2>
            
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 20 }}>
                {/* Registro Simplificado */}
                <div className="civic-card">
                    <div className="civic-card-header">
                        <i className="ph-bold ph-user-plus" style={{ fontSize: 24, color: '#003897' }} />
                        <h3>Registro Básico</h3>
                    </div>
                    <p className="civic-card-desc">Regístrate con tu RUT y correo electrónico para comenzar a participar en la DAO.</p>
                    <button onClick={() => setStep('registro')} className="civic-button">
                        CREAR CUENTA
                    </button>
                    <div className="civic-demo-info">
                        <span className="demo-badge">Demostración</span>
                        <small>Nivel de seguridad básico. En producción se conectará al backend real.</small>
                    </div>
                </div>

                {/* ClaveÚnica */}
                <div className="civic-card">
                    <div className="civic-card-header">
                        <i className="ph-bold ph-qr-code" style={{ fontSize: 24, color: '#003897' }} />
                        <h3>ClaveÚnica</h3>
                    </div>
                    <p className="civic-card-desc">Usa tu identidad gubernamental para validar tu acceso de forma segura.</p>
                    <div style={{ margin: '15px 0' }}>
                        <label style={{ fontSize: 11, fontWeight: 600, color: '#5C7099', display: 'block', marginBottom: 6 }}>RUT DE CIUDADANO</label>
                        <input 
                            type="text"
                            placeholder="12345678-9" 
                            value={rut} 
                            onChange={(e) => setRut(e.target.value)}
                            className="civic-input"
                        />
                    </div>
                    <button onClick={() => setStep('clave')} className="civic-button">
                        INICIAR CLAVE ÚNICA
                    </button>
                    <div className="civic-demo-info">
                        <span className="demo-badge">Demostración</span>
                        <small>No almacenamos tu RUT. Esto redirige a un entorno simulado gubernamental.</small>
                    </div>
                </div>

                {/* Cédula NFC */}
                <div className="civic-card">
                    <div className="civic-card-header">
                        <i className="ph-bold ph-wifi-high" style={{ fontSize: 24, color: '#003897' }} />
                        <h3>Cédula con NFC</h3>
                    </div>
                    <p className="civic-card-desc">Validación criptográfica mediante el chip integrado en tu cédula de identidad.</p>
                    <button onClick={() => setStep('nfc')} className="civic-button" style={{ marginTop: 'auto' }}>
                        ACTIVAR LECTURA NFC
                    </button>
                    <div className="civic-demo-info">
                        <span className="demo-badge">Demostración</span>
                        <small>Simulación del protocolo NFC, requiere aplicación móvil nativa en un entorno real.</small>
                    </div>
                </div>

                {/* Biometría */}
                <div className="civic-card">
                    <div className="civic-card-header">
                        <i className="ph-bold ph-scan" style={{ fontSize: 24, color: '#003897' }} />
                        <h3>Verificación Facial</h3>
                    </div>
                    <p className="civic-card-desc">Análisis biométrico avanzado con inteligencia artificial para detección de vida.</p>
                    <button onClick={() => setStep('selfie')} className="civic-button" style={{ marginTop: 'auto' }}>
                        INICIAR ANÁLISIS
                    </button>
                    <div className="civic-demo-info">
                        <span className="demo-badge">Demostración</span>
                        <small>Sistema simulado de captura facial. No utiliza biometría de usuarios reales.</small>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default CivicMethodSelector;
