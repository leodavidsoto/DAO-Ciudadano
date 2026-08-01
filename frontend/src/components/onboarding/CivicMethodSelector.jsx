import React from 'react';
import { useOnboarding } from '@/context';

const CivicMethodSelector = () => {
    const { rut, setRut, setStep } = useOnboarding();

    return (
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
            <h2 style={{ fontFamily: 'Poppins, sans-serif', fontSize: 22, fontWeight: 600, color: '#003897', marginBottom: 24, textAlign: 'center', letterSpacing: '-0.01em' }}>
                Selecciona un recorrido del piloto
            </h2>
            
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 20 }}>
                {/* Registro Simplificado */}
                <div className="civic-card">
                    <div className="civic-card-header">
                        <i className="ph-bold ph-user-plus" style={{ fontSize: 24, color: '#003897' }} />
                        <h3>Registro Básico</h3>
                    </div>
                    <p className="civic-card-desc">Crea una cuenta piloto con los datos que declaras. Este registro no acredita tu identidad.</p>
                    <button onClick={() => setStep('registro')} className="civic-button">
                        CREAR CUENTA
                    </button>
                    <div className="civic-demo-info">
                        <span className="demo-badge">Demostración</span>
                        <small>RUT y correo son datos declarados por la persona; no se contrastan con una fuente oficial.</small>
                    </div>
                </div>

                {/* ClaveÚnica */}
                <div className="civic-card">
                    <div className="civic-card-header">
                        <i className="ph-bold ph-qr-code" style={{ fontSize: 24, color: '#003897' }} />
                        <h3>ClaveÚnica</h3>
                    </div>
                    <p className="civic-card-desc">Prueba una simulación visual del recorrido. No existe conexión con ClaveÚnica ni con el Gobierno de Chile.</p>
                    <div style={{ margin: '15px 0' }}>
                        <label style={{ fontSize: 11, fontWeight: 600, color: '#5C7099', display: 'block', marginBottom: 6 }}>RUT PARA LA DEMOSTRACIÓN</label>
                        <input 
                            type="text"
                            placeholder="12345678-9" 
                            value={rut} 
                            onChange={(e) => setRut(e.target.value)}
                            className="civic-input"
                        />
                    </div>
                    <button onClick={() => setStep('clave')} className="civic-button">
                        PROBAR FLUJO SIMULADO
                    </button>
                    <div className="civic-demo-info">
                        <span className="demo-badge">Demostración</span>
                        <small>No autentica con ClaveÚnica ni redirige a un sistema gubernamental.</small>
                    </div>
                </div>

                {/* Cédula NFC */}
                <div className="civic-card">
                    <div className="civic-card-header">
                        <i className="ph-bold ph-wifi-high" style={{ fontSize: 24, color: '#003897' }} />
                        <h3>Lectura NFC</h3>
                    </div>
                    <p className="civic-card-desc">La Web NFC del navegador puede detectar etiquetas compatibles, pero no verifica una cédula chilena.</p>
                    <button onClick={() => setStep('nfc')} className="civic-button" style={{ marginTop: 'auto' }}>
                        DETECTAR ETIQUETA NFC
                    </button>
                    <div className="civic-demo-info">
                        <span className="demo-badge">Demostración</span>
                        <small>No ejecuta el protocolo seguro de la cédula ni acredita identidad.</small>
                    </div>
                </div>

                {/* Biometría */}
                <div className="civic-card">
                    <div className="civic-card-header">
                        <i className="ph-bold ph-scan" style={{ fontSize: 24, color: '#003897' }} />
                        <h3>Prueba de imagen</h3>
                    </div>
                    <p className="civic-card-desc">Carga una imagen y observa un resultado simulado. No es biometría certificada ni acredita identidad.</p>
                    <button onClick={() => setStep('selfie')} className="civic-button" style={{ marginTop: 'auto' }}>
                        PROBAR DEMOSTRACIÓN
                    </button>
                    <div className="civic-demo-info">
                        <span className="demo-badge">Demostración</span>
                        <small>La puntuación es demostrativa y no constituye una prueba de vida.</small>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default CivicMethodSelector;
