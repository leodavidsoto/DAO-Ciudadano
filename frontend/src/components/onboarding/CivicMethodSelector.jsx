import React from 'react';
import { useOnboarding } from '@/context';

const DemoNotice = ({ children }) => (
    <div className="civic-note civic-note-warn civic-method-note">
        <i className="ph-bold ph-flask" aria-hidden="true" />
        <span>{children}</span>
    </div>
);

const CivicMethodSelector = () => {
    const { selectIdentityMethod } = useOnboarding();

    return (
        <section className="civic-methods" aria-labelledby="identity-method-title">
            <div className="civic-methods-heading">
                <span className="civic-eyebrow">Acreditación ciudadana</span>
                <h2 id="identity-method-title" className="civic-section-title">
                    Elige cómo continuar
                </h2>
                <p className="civic-muted">
                    Sólo ClaveÚnica puede entregar un grant civil para emitir la credencial.
                    Los demás recorridos se conservan como pruebas técnicas explícitas.
                </p>
            </div>

            <div className="civic-method-grid">
                <article className="civic-card civic-card-pad civic-method-card civic-method-card-primary">
                    <div className="civic-method-icon" aria-hidden="true">
                        <i className="ph-bold ph-shield-check" />
                    </div>
                    <div>
                        <span className="civic-tag civic-tag-blue">IDENTIDAD OFICIAL</span>
                        <h3>ClaveÚnica</h3>
                        <p>
                            Autentícate en el proveedor estatal mediante OIDC Authorization Code
                            con PKCE. EstamosDAO no solicita ni recibe tu contraseña.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={() => selectIdentityMethod('clave')}
                        className="civic-btn civic-btn-primary civic-method-action"
                    >
                        <i className="ph-bold ph-sign-in" aria-hidden="true" />
                        INGRESAR CON CLAVEÚNICA
                    </button>
                    <div className="civic-note civic-note-info civic-method-note">
                        <i className="ph-bold ph-lock-key" aria-hidden="true" />
                        <span>El código de retorno se limpia de la URL y el grant vive sólo en memoria.</span>
                    </div>
                </article>

                <article className="civic-card civic-card-pad civic-method-card">
                    <div className="civic-method-icon" aria-hidden="true">
                        <i className="ph-bold ph-user-plus" />
                    </div>
                    <div>
                        <h3>Registro básico</h3>
                        <p>Crea una cuenta piloto con datos declarados, sin contrastarlos con una fuente oficial.</p>
                    </div>
                    <button
                        type="button"
                        onClick={() => selectIdentityMethod('registro')}
                        className="civic-btn civic-btn-ghost civic-method-action"
                    >
                        CREAR CUENTA PILOTO
                    </button>
                    <DemoNotice>No acredita identidad ni habilita emisión.</DemoNotice>
                </article>

                <article className="civic-card civic-card-pad civic-method-card">
                    <div className="civic-method-icon" aria-hidden="true">
                        <i className="ph-bold ph-wifi-high" />
                    </div>
                    <div>
                        <h3>Lectura NFC web</h3>
                        <p>Detecta etiquetas compatibles; el navegador no verifica la cadena documental de una cédula.</p>
                    </div>
                    <button
                        type="button"
                        onClick={() => selectIdentityMethod('nfc')}
                        className="civic-btn civic-btn-ghost civic-method-action"
                    >
                        PROBAR LECTURA
                    </button>
                    <DemoNotice>No ejecuta PACE ni acredita identidad.</DemoNotice>
                </article>

                <article className="civic-card civic-card-pad civic-method-card">
                    <div className="civic-method-icon" aria-hidden="true">
                        <i className="ph-bold ph-scan" />
                    </div>
                    <div>
                        <h3>Prueba de imagen</h3>
                        <p>Ejercita la carga de una imagen, pero no constituye biometría ni prueba de vida certificada.</p>
                    </div>
                    <button
                        type="button"
                        onClick={() => selectIdentityMethod('selfie')}
                        className="civic-btn civic-btn-ghost civic-method-action"
                    >
                        PROBAR IMAGEN
                    </button>
                    <DemoNotice>No entrega un grant de identidad.</DemoNotice>
                </article>
            </div>
        </section>
    );
};

export default CivicMethodSelector;
