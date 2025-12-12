/**
 * Consent Step
 */
import React from 'react';
import { FileCheck, Lock, Shield, Wallet } from 'lucide-react';
import { Button } from '../ui/button';
import { CyberPanel } from './CyberUI';
import { useOnboarding } from '@/context';

const ConsentStep = () => {
    const { setStep } = useOnboarding();

    return (
        <CyberPanel
            title="PROTOCOLO DE PRIVACIDAD"
            description="Consentimiento informado para procesamiento de datos biométricos"
            icon={<FileCheck className="h-8 w-8" />}
        >
            <div className="space-y-6">
                <div className="grid md:grid-cols-2 gap-6">
                    <div className="bg-green-500/10 border border-green-500/30 p-4 rounded-lg">
                        <h3 className="cyber-label text-green-400 mb-3">
                            <Lock className="inline w-4 h-4 mr-2" />
                            DATOS PROTEGIDOS
                        </h3>
                        <ul className="text-sm text-gray-300 space-y-2 font-mono">
                            <li>• Solo hashes criptográficos on-chain</li>
                            <li>• NFT ciudadano no transferible</li>
                            <li>• Métricas agregadas anónimas</li>
                            <li>• Cumplimiento GDPR/LOPD</li>
                        </ul>
                    </div>

                    <div className="bg-red-500/10 border border-red-500/30 p-4 rounded-lg">
                        <h3 className="cyber-label text-red-400 mb-3">
                            <Shield className="inline w-4 h-4 mr-2" />
                            NUNCA EXPUESTO
                        </h3>
                        <ul className="text-sm text-gray-300 space-y-2 font-mono">
                            <li>• RUT o datos de identidad</li>
                            <li>• Imágenes biométricas</li>
                            <li>• Información personal</li>
                            <li>• Historial de navegación</li>
                        </ul>
                    </div>
                </div>

                <div className="flex justify-center gap-4">
                    <Button onClick={() => setStep('wallet')} className="cyber-button">
                        <Wallet className="w-4 h-4 mr-2" />
                        ACEPTO TÉRMINOS • CONTINUAR
                    </Button>
                    <Button onClick={() => setStep('method')} variant="outline" className="border-gray-600 text-gray-400 hover:text-white">
                        REVISAR MÉTODOS
                    </Button>
                </div>
            </div>
        </CyberPanel>
    );
};

export default ConsentStep;
