/**
 * NFC Authentication Step
 */
import React from 'react';
import { Radio, Activity } from 'lucide-react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { CyberPanel, CyberLoader, SuccessDisplay } from './CyberUI';
import { useOnboarding } from '@/context';

const NFCStep = () => {
    const { loading, nfc, authenticateNFC } = useOnboarding();

    return (
        <CyberPanel
            title="LECTURA CRIPTOGRÁFICA NFC"
            description="Validando autenticidad del chip de cédula..."
            icon={<Radio className="h-8 w-8" />}
        >
            <div className="flex flex-col items-center gap-6">
                {!loading && !nfc.chip_serial && (
                    <div className="text-center">
                        <div className="w-32 h-32 mx-auto mb-4 border-2 border-dashed border-cyan-400 rounded-lg flex items-center justify-center">
                            <Activity className="w-12 h-12 text-cyan-400 animate-pulse" />
                        </div>
                        <Button onClick={authenticateNFC} className="cyber-button">
                            <Radio className="w-4 h-4 mr-2" />
                            ESCANEAR CHIP
                        </Button>
                    </div>
                )}

                {loading && <CyberLoader text="LEYENDO CHIP NFC..." />}

                {nfc.chip_serial && (
                    <SuccessDisplay>
                        <p className="font-mono mb-2">CHIP VALIDADO</p>
                        <div className="flex flex-wrap justify-center gap-2">
                            <Badge className="cyber-badge">SERIAL: {nfc.chip_serial}</Badge>
                            <Badge className="cyber-badge success">HASH: {nfc.doc_hash?.slice(0, 10)}...</Badge>
                        </div>
                    </SuccessDisplay>
                )}
            </div>
        </CyberPanel>
    );
};

export default NFCStep;
