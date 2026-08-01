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
            title="RESUMEN Y LIMITACIONES DEL PILOTO"
            description="La confirmación de RUT o imagen se solicitó antes de enviarlos al backend"
            icon={<FileCheck className="h-8 w-8" />}
        >
            <div className="space-y-6">
                <div className="grid md:grid-cols-2 gap-6">
                    <div className="bg-green-500/10 border border-green-500/30 p-4 rounded-lg">
                        <h3 className="cyber-label text-green-400 mb-3">
                            <Lock className="inline w-4 h-4 mr-2" />
                            IMPLEMENTADO HOY
                        </h3>
                        <ul className="text-sm text-gray-300 space-y-2 font-mono">
                            <li>• RUT, email, nombre y apellido cifrados en la colección de usuarios</li>
                            <li>• Sesión de wallet validada mediante firma</li>
                            <li>• La imagen de selfie no se conserva como archivo</li>
                            <li>• El resultado indica si hubo transacción on-chain real</li>
                        </ul>
                    </div>

                    <div className="bg-red-500/10 border border-red-500/30 p-4 rounded-lg">
                        <h3 className="cyber-label text-red-400 mb-3">
                            <Shield className="inline w-4 h-4 mr-2" />
                            LIMITACIONES ABIERTAS
                        </h3>
                        <ul className="text-sm text-gray-300 space-y-2 font-mono">
                            <li>• ClaveÚnica, NFC y liveness siguen en modo demo</li>
                            <li>• El piloto puede guardar membresías solo en el backend</li>
                            <li>• Aún falta evaluación legal y política de retención</li>
                            <li>• No uses este registro como credencial oficial</li>
                        </ul>
                    </div>
                </div>

                <div className="flex justify-center gap-4">
                    <Button onClick={() => setStep('wallet')} className="cyber-button">
                        <Wallet className="w-4 h-4 mr-2" />
                        CONTINUAR A LA WALLET
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
