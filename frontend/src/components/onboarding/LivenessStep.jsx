/**
 * Liveness Detection Step
 */
import React from 'react';
import { ScanFace, Upload, Database, Code } from 'lucide-react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Badge } from '../ui/badge';
import { CyberPanel, CyberLoader, DemoBadge } from './CyberUI';
import { useOnboarding } from '@/context';

const LivenessStep = () => {
    const { loading, selectedFile, handleFileSelect, selfie, analyzeLiveness } = useOnboarding();

    return (
        <CyberPanel
            title="ANÁLISIS BIOMÉTRICO CON IA"
            description="Sistema de detección de vida avanzado. Procesamiento local seguro."
            icon={<ScanFace className="h-8 w-8" />}
        >
            <DemoBadge label="MODO DEMO — detección de vida simulada sin proveedor real" />
            <div className="space-y-6">
                <div>
                    <Label className="cyber-label">SUBIR IMAGEN BIOMÉTRICA</Label>
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
                        <Button onClick={analyzeLiveness} className="cyber-button">
                            <Upload className="w-4 h-4 mr-2" />
                            PROCESAR CON IA
                        </Button>
                    )}

                    {loading && <CyberLoader text="ANALIZANDO BIOMETRÍA..." />}

                    {selfie.score && (
                        <div className="cyber-success p-4 rounded-lg w-full">
                            <div className="flex items-center justify-between mb-3">
                                <span className="font-mono">ANÁLISIS COMPLETADO</span>
                                <Badge className={`cyber-badge ${selfie.score >= 0.7 ? 'success' : 'warning'}`}>
                                    SCORE: {Math.round(selfie.score * 100)}%
                                </Badge>
                            </div>
                            {selfie.analysis && (
                                <div className="bg-black/50 p-3 rounded border border-cyan-500/30">
                                    <p className="text-xs font-mono text-gray-300">
                                        <Code className="inline w-3 h-3 mr-1" />
                                        {selfie.analysis}
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
