/**
 * ClaveÚnica Authentication Step
 */
import React from 'react';
import { Shield, QrCode } from 'lucide-react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { CyberPanel, CyberLoader, SuccessDisplay } from './CyberUI';
import { useOnboarding } from '@/context';

const ClaveUnicaStep = () => {
    const { loading, clave, authenticateClaveUnica } = useOnboarding();

    return (
        <CyberPanel
            title="PROTOCOLO CLAVE ÚNICA ACTIVADO"
            description="Estableciendo conexión segura con servidor gubernamental..."
            icon={<QrCode className="h-8 w-8" />}
        >
            <div className="flex flex-col items-center gap-6">
                {!loading && !clave.subject_id && (
                    <Button onClick={authenticateClaveUnica} className="cyber-button">
                        <Shield className="w-4 h-4 mr-2" />
                        AUTENTICAR CON GOBIERNO
                    </Button>
                )}

                {loading && <CyberLoader text="VALIDANDO IDENTIDAD..." />}

                {clave.subject_id && (
                    <SuccessDisplay>
                        <p className="font-mono">IDENTIDAD VERIFICADA</p>
                        <Badge className="cyber-badge success mt-2">
                            {clave.subject_id} • NIVEL {clave.assurance_level}
                        </Badge>
                    </SuccessDisplay>
                )}
            </div>
        </CyberPanel>
    );
};

export default ClaveUnicaStep;
