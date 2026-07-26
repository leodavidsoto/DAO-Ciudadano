/**
 * NFC Authentication Step - Real Web NFC Integration
 * Uses Web NFC API on Chrome Android, fallback for unsupported browsers
 */
import React, { useEffect, useState } from 'react';
import { Radio, Activity, AlertTriangle, Smartphone, CheckCircle, XCircle } from 'lucide-react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { CyberPanel, CyberLoader, SuccessDisplay, DemoBadge } from './CyberUI';
import { useOnboarding } from '@/context';
import useNFC from '@/hooks/useNFC';

const NFCStep = () => {
    const { loading, setLoading, nfc, setNFC, setStep } = useOnboarding();
    const {
        isSupported,
        isReading,
        error: nfcError,
        tagData,
        startReading,
        permission
    } = useNFC();

    const [showInstructions, setShowInstructions] = useState(true);

    // When tag is successfully read
    useEffect(() => {
        if (tagData && tagData.serialNumber) {
            // Create hash from serial number
            const encoder = new TextEncoder();
            const data = encoder.encode(tagData.serialNumber + tagData.timestamp);
            crypto.subtle.digest('SHA-256', data).then(hashBuffer => {
                const hashArray = Array.from(new Uint8Array(hashBuffer));
                const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');

                setNFC({
                    chip_serial: tagData.serialNumber,
                    doc_hash: hashHex,
                    records: tagData.records,
                    timestamp: tagData.timestamp,
                    verified: true,
                });

                // Auto advance after 2 seconds
                setTimeout(() => setStep('wallet'), 2000);
            });
        }
    }, [tagData, setNFC, setStep]);

    const handleStartScan = async () => {
        setShowInstructions(false);
        setLoading(true);
        await startReading();
        setLoading(false);
    };

    // Check if on mobile
    const isMobile = /Android|iPhone|iPad/i.test(navigator.userAgent);
    const isAndroid = /Android/i.test(navigator.userAgent);

    return (
        <CyberPanel
            title="LECTURA CRIPTOGRÁFICA NFC"
            description="Validando autenticidad del chip de identificación"
            icon={<Radio className="h-8 w-8" />}
        >
            <DemoBadge label="MODO DEMO — la lectura del chip aún no está integrada en backend" />
            <div className="flex flex-col items-center gap-6">

                {/* Not supported warning */}
                {!isSupported && (
                    <div className="text-center p-6 border border-yellow-500/30 rounded-lg bg-yellow-500/5">
                        <AlertTriangle className="w-12 h-12 mx-auto text-yellow-400 mb-3" />
                        <h3 className="text-yellow-400 font-bold mb-2">NFC No Disponible</h3>
                        <p className="text-sm text-gray-400 font-mono mb-4">
                            {!isMobile ? (
                                "La lectura NFC requiere un dispositivo móvil Android con Chrome"
                            ) : !isAndroid ? (
                                "iOS Safari no soporta Web NFC. Usa Chrome en Android."
                            ) : (
                                "Tu navegador no soporta Web NFC. Actualiza Chrome."
                            )}
                        </p>
                        <div className="flex flex-col gap-2">
                            <Button
                                onClick={() => setStep('method')}
                                variant="outline"
                                className="text-cyan-400 border-cyan-500/30"
                            >
                                Usar otro método
                            </Button>
                        </div>
                    </div>
                )}

                {/* Instructions */}
                {isSupported && showInstructions && !nfc.chip_serial && (
                    <div className="text-center">
                        <div className="w-40 h-40 mx-auto mb-4 border-2 border-dashed border-cyan-400/50 rounded-2xl flex flex-col items-center justify-center bg-cyan-500/5">
                            <Smartphone className="w-16 h-16 text-cyan-400 mb-2" />
                            <Radio className="w-8 h-8 text-cyan-400 animate-pulse" />
                        </div>
                        <p className="text-sm text-gray-400 font-mono mb-4 max-w-xs">
                            Coloca la parte trasera del teléfono sobre el chip de tu cédula
                        </p>
                        <Button
                            onClick={handleStartScan}
                            className="cyber-button-premium"
                            disabled={loading || isReading}
                        >
                            <Radio className="w-4 h-4 mr-2" />
                            INICIAR ESCANEO NFC
                        </Button>
                    </div>
                )}

                {/* Reading state */}
                {(loading || isReading) && (
                    <div className="text-center">
                        <div className="w-40 h-40 mx-auto mb-4 border-2 border-cyan-400 rounded-2xl flex flex-col items-center justify-center bg-cyan-500/10 animate-pulse">
                            <Activity className="w-16 h-16 text-cyan-400 animate-bounce" />
                        </div>
                        <CyberLoader text="BUSCANDO CHIP NFC..." />
                        <p className="text-xs text-gray-500 font-mono mt-2">
                            Mantén el teléfono quieto sobre la cédula
                        </p>
                    </div>
                )}

                {/* Error state */}
                {nfcError && !isReading && (
                    <div className="text-center p-4 border border-red-500/30 rounded-lg bg-red-500/5">
                        <XCircle className="w-10 h-10 mx-auto text-red-400 mb-2" />
                        <p className="text-red-400 font-mono text-sm mb-3">{nfcError}</p>
                        <div className="flex gap-2 justify-center">
                            <Button
                                onClick={handleStartScan}
                                className="cyber-button"
                            >
                                Reintentar
                            </Button>
                            <Button
                                onClick={() => setStep('method')}
                                variant="outline"
                                className="text-gray-400"
                            >
                                Otro método
                            </Button>
                        </div>
                    </div>
                )}

                {/* Success state */}
                {nfc.chip_serial && (
                    <SuccessDisplay>
                        <CheckCircle className="w-12 h-12 mx-auto text-green-400 mb-2" />
                        <p className="font-mono mb-2">CHIP VALIDADO EXITOSAMENTE</p>
                        <div className="flex flex-wrap justify-center gap-2">
                            <Badge className="cyber-badge">
                                SERIAL: {nfc.chip_serial}
                            </Badge>
                            <Badge className="cyber-badge success">
                                HASH: {nfc.doc_hash?.slice(0, 12)}...
                            </Badge>
                        </div>
                        <p className="text-xs text-gray-500 mt-2 font-mono">
                            Avanzando a conexión de wallet...
                        </p>
                    </SuccessDisplay>
                )}

                {/* Permission denied */}
                {permission === 'denied' && (
                    <div className="text-center p-4 border border-orange-500/30 rounded-lg bg-orange-500/5 mt-4">
                        <p className="text-orange-400 text-sm font-mono">
                            Permiso NFC denegado. Ve a Configuración → Sitios → NFC y permite el acceso.
                        </p>
                    </div>
                )}
            </div>
        </CyberPanel>
    );
};

export default NFCStep;
