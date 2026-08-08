/**
 * Simulated image-analysis step
 */
import React, { useState } from 'react';
import { ScanFace, Upload, Database, Code } from 'lucide-react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Badge } from '../ui/badge';
import { CyberPanel, CyberLoader, DemoBadge } from './CyberUI';
import { useOnboarding } from '@/context';

const LivenessStep = () => {
    const { loading, selectedFile, handleFileSelect, selfie, analyzeLiveness } = useOnboarding();
    const [processingAccepted, setProcessingAccepted] = useState(false);

    return (
        <CyberPanel
            title="DEMOSTRACIÓN CON IMAGEN"
            description="Resultado simulado: no es biometría certificada, prueba de vida ni verificación de identidad."
            icon={<ScanFace className="h-8 w-8" />}
        >
            <DemoBadge label="MODO DEMO — sin proveedor de liveness certificado" />
            <div className="space-y-6">
                <label className="flex items-start gap-3 rounded-lg border border-yellow-500/40 bg-yellow-500/10 p-4 text-left">
                    <input
                        type="checkbox"
                        checked={processingAccepted}
                        onChange={(event) => setProcessingAccepted(event.target.checked)}
                        className="mt-1"
                    />
                    <span className="text-sm text-gray-300">
                        Confirmo que deseo enviar la imagen al backend para una demostración no biométrica.
                        Si el entorno tiene una integración configurada, la imagen puede ser procesada por ese
                        proveedor. No constituye prueba de vida ni verificación de identidad.
                    </span>
                </label>

                <div>
                    <Label className="cyber-label">SUBIR IMAGEN PARA LA DEMOSTRACIÓN</Label>
                    <Input
                        type="file"
                        accept="image/*"
                        onChange={handleFileSelect}
                        className="cyber-file-input mt-2"
                    />
                    {selectedFile && (
                        <p className="text-xs text-cyan-400 mt-2 font-mono">
                            <Database className="inline w-3 h-3 mr-1" />
                            {selectedFile.name} • {Math.round(selectedFile.size / 1024)}KB
                        </p>
                    )}
                </div>

                <div className="flex flex-col items-center gap-4">
                    {!loading && selectedFile && (
                        <Button
                            onClick={() => analyzeLiveness(processingAccepted)}
                            className="cyber-button"
                            disabled={!processingAccepted}
                        >
                            <Upload className="w-4 h-4 mr-2" />
                            EJECUTAR SIMULACIÓN
                        </Button>
                    )}

                    {loading && <CyberLoader text="GENERANDO RESULTADO DE DEMO..." />}

                    {/* El backend devuelve score=null cuando no hay proveedor
                        configurado: en ese caso no se inventa un puntaje, pero
                        el análisis textual sí debe verse. Comparar contra null
                        además evita ocultar un puntaje legítimo de 0. */}
                    {(selfie.score != null || selfie.analysis) && (
                        <div className="cyber-success p-4 rounded-lg w-full">
                            <div className="flex items-center justify-between mb-3">
                                <span className="font-mono">RESULTADO SIMULADO</span>
                                <Badge className={`cyber-badge ${selfie.score != null && selfie.score >= 0.7 ? 'success' : 'warning'}`}>
                                    {selfie.score != null
                                        ? `PUNTAJE DEMO: ${Math.round(selfie.score * 100)}%`
                                        : 'SIN PUNTAJE — PROVEEDOR NO CONFIGURADO'}
                                </Badge>
                            </div>
                            {selfie.analysis && (
                                <div className="bg-black/50 p-3 rounded border border-cyan-500/30">
                                    <p className="text-xs font-mono text-gray-300">
                                        <Code className="inline w-3 h-3 mr-1" />
                                        Salida demostrativa, no dictamen biométrico: {selfie.analysis}
                                    </p>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </CyberPanel>
    );
};

export default LivenessStep;
