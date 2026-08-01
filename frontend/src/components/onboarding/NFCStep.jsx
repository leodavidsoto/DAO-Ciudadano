/**
 * NFC Authentication Step - Real Web NFC Integration
 * Uses Web NFC API on Chrome Android, fallback for unsupported browsers
 */
import React, { useEffect, useState } from 'react';
import { Radio, Activity, AlertTriangle, Smartphone, XCircle } from 'lucide-react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { CyberPanel, CyberLoader, DemoBadge } from './CyberUI';
import { useOnboarding } from '@/context';
import useNFC from '@/hooks/useNFC';

const NFCStep = () => {
    const { loading, setLoading, nfc, setNfc, setStep } = useOnboarding();
    const {
        isSupported,
        isReading,
        error: nfcError,
        tagData,
        startReading,
        permission
    } = useNFC();

    const [showInstructions, setShowInstructions] = useState(true);

    // Web NFC only proves that an NDEF tag was read. It does not authenticate
    // the protected chip of a Chilean identity card, so this result must never
    // unlock the identity flow by itself.
    useEffect(() => {
        if (tagData && tagData.serialNumber) {
            setNfc({
                chip_serial: tagData.serialNumber,
                records: tagData.records,
                timestamp: tagData.timestamp,
                verified: false,
                verification_error: 'Web NFC detectó una etiqueta NDEF, pero no verificó una identidad.',
            });
        }
    }, [tagData, setNfc]);

    const handleStartScan = async () => {
        setShowInstructions(false);
        setNfc({});
        setLoading(true);
        await startReading();
        setLoading(false);
    };

    // Check if on mobile
    const isMobile = /Android|iPhone|iPad/i.test(navigator.userAgent);
    const isAndroid = /Android/i.test(navigator.userAgent);

    return (
        <CyberPanel
            title="DETECCIÓN DE ETIQUETA NFC"
            description="Lectura técnica de una etiqueta NDEF; no verifica identidad"
            icon={<Radio className="h-8 w-8" />}
        >
            <DemoBadge label="MODO DEMO — Web NFC no autentica el chip protegido de una cédula chilena" />
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
                            Acerca la parte trasera del teléfono a una etiqueta NFC NDEF compatible
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
                        <CyberLoader text="BUSCANDO ETIQUETA NFC..." />
                        <p className="text-xs text-gray-500 font-mono mt-2">
                            Mantén el teléfono quieto cerca de la etiqueta
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

                {/* Detection is intentionally not treated as identity verification. */}
                {nfc.chip_serial && !loading && !isReading && (
                    <div className="w-full max-w-lg rounded-lg border border-yellow-500/40 bg-yellow-500/10 p-5 text-center">
                        <AlertTriangle className="w-12 h-12 mx-auto text-yellow-400 mb-2" />
                        <p className="font-mono text-yellow-300 mb-2">ETIQUETA DETECTADA • IDENTIDAD NO VERIFICADA</p>
                        <div className="flex flex-wrap justify-center gap-2">
                            <Badge className="cyber-badge">
                                ID ETIQUETA: {nfc.chip_serial}
                            </Badge>
                        </div>
                        <p className="text-xs text-gray-400 mt-3 font-mono">
                            Leer una etiqueta NDEF no demuestra que pertenezca a una cédula ni a una persona.
                            Este resultado no habilita la creación de membresía.
                        </p>
                        <div className="mt-4 flex flex-wrap justify-center gap-2">
                            <Button onClick={handleStartScan} className="cyber-button">
                                Leer otra etiqueta
                            </Button>
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
