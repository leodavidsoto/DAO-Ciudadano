/**
 * Simulated ClaveÚnica journey
 */
import React, { useState } from 'react';
import { Shield, QrCode } from 'lucide-react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { CyberPanel, CyberLoader, SuccessDisplay, DemoBadge } from './CyberUI';
import { useOnboarding } from '@/context';

const ClaveUnicaStep = () => {
    const { loading, clave, authenticateClaveUnica } = useOnboarding();
    const [processingAccepted, setProcessingAccepted] = useState(false);

    return (
        <CyberPanel
            title="SIMULACIÓN DE CLAVEÚNICA"
            description="Demostración visual sin conexión a ClaveÚnica ni a servidores gubernamentales."
            icon={<QrCode className="h-8 w-8" />}
        >
            <DemoBadge label="MODO DEMO — ClaveÚnica aún no integra el OAuth gubernamental real" />
            <div className="flex flex-col items-center gap-6">
                {!clave.subject_id && (
                    <label className="flex max-w-xl items-start gap-3 rounded-lg border border-yellow-500/40 bg-yellow-500/10 p-4 text-left">
                        <input
                            type="checkbox"
                            checked={processingAccepted}
                            onChange={(event) => setProcessingAccepted(event.target.checked)}
                            className="mt-1"
                        />
                        <span className="text-sm text-gray-300">
                            Confirmo que deseo enviar el RUT ingresado al backend para ejecutar esta simulación.
                            No se consulta ClaveÚnica, no se acredita identidad y no debo usar este resultado como
                            credencial oficial.
                        </span>
                    </label>
                )}

                {!loading && !clave.subject_id && (
                    <Button
                        onClick={() => authenticateClaveUnica(processingAccepted)}
                        className="cyber-button"
                        disabled={!processingAccepted}
                    >
                        <Shield className="w-4 h-4 mr-2" />
                        EJECUTAR SIMULACIÓN
                    </Button>
                )}

                {loading && <CyberLoader text="EJECUTANDO DEMOSTRACIÓN..." />}

                {clave.subject_id && (
                    <SuccessDisplay>
                        <p className="font-mono">DEMOSTRACIÓN COMPLETADA</p>
                        <Badge className="cyber-badge success mt-2">
                            SIN CONEXIÓN A CLAVEÚNICA
                        </Badge>
                    </SuccessDisplay>
                )}
            </div>
        </CyberPanel>
    );
};

export default ClaveUnicaStep;
