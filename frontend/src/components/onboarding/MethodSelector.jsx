/**
 * Method Selection Step
 * Choose a pilot journey: RUT+Email, simulated ClaveÚnica, Web NFC, or image demo
 */
import React from 'react';
import { QrCode, Wifi, Eye, Shield, Lock, Radio, ScanFace, UserPlus } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { CyberPanel } from './CyberUI';
import { Fingerprint } from 'lucide-react';
import { useOnboarding } from '@/context';

const MethodSelector = () => {
    const { rut, setRut, setStep } = useOnboarding();

    return (
        <CyberPanel
            title="SELECCIONAR RECORRIDO DEL PILOTO"
            description="Demostraciones técnicas: ninguno de estos métodos acredita identidad en esta versión."
            icon={<Fingerprint className="h-8 w-8" />}
        >
            <div className="cyber-tabs">
                <Tabs defaultValue="registro" className="w-full">
                    <TabsList className="grid grid-cols-2 md:grid-cols-4 w-full bg-transparent gap-2">
                        <TabsTrigger value="registro" className="cyber-tab">
                            <UserPlus className="w-4 h-4 mr-2" />
                            Registro
                        </TabsTrigger>
                        <TabsTrigger value="clave" className="cyber-tab">
                            <QrCode className="w-4 h-4 mr-2" />
                            ClaveÚnica
                        </TabsTrigger>
                        <TabsTrigger value="nfc" className="cyber-tab">
                            <Wifi className="w-4 h-4 mr-2" />
                            Cédula NFC
                        </TabsTrigger>
                        <TabsTrigger value="selfie" className="cyber-tab">
                            <Eye className="w-4 h-4 mr-2" />
                            Imagen demo
                        </TabsTrigger>
                    </TabsList>

                    {/* RUT + Email Simple Registration */}
                    <TabsContent value="registro" className="pt-6">
                        <div className="space-y-4">
                            <div className="text-center p-6 border border-green-500/30 rounded-lg bg-green-500/5">
                                <UserPlus className="w-12 h-12 mx-auto text-green-400 mb-3" />
                                <h3 className="text-lg font-bold text-green-400 mb-2">Registro Simplificado</h3>
                                <p className="text-sm text-gray-400 font-mono mb-4">
                                    Crea una cuenta piloto con RUT y correo declarados por ti. No se contrastan con una fuente oficial.
                                </p>
                                <Button onClick={() => setStep('registro')} className="cyber-button-premium">
                                    <UserPlus className="w-4 h-4 mr-2" />
                                    CREAR CUENTA / INICIAR SESIÓN
                                </Button>
                                <p className="text-xs text-gray-500 mt-3 font-mono">
                                    <Lock className="inline w-3 h-3 mr-1" />
                                    Registro de cuenta • No acredita identidad
                                </p>
                            </div>
                        </div>
                    </TabsContent>

                    <TabsContent value="clave" className="pt-6">
                        <div className="space-y-4">
                            <div>
                                <Label className="cyber-label">RUT DE CIUDADANO</Label>
                                <Input
                                    placeholder="12345678-9"
                                    value={rut}
                                    onChange={e => setRut(e.target.value)}
                                    className="cyber-input mt-2"
                                />
                                <p className="text-xs text-gray-500 mt-2 font-mono">
                                    <Lock className="inline w-3 h-3 mr-1" />
                                    Simulación visual: no conecta con ClaveÚnica ni con el Gobierno de Chile.
                                </p>
                            </div>
                            <Button onClick={() => setStep('clave')} className="cyber-button w-full">
                                <Shield className="w-4 h-4 mr-2" />
                                PROBAR FLUJO SIMULADO
                            </Button>
                        </div>
                    </TabsContent>

                    <TabsContent value="nfc" className="pt-6">
                        <div className="space-y-4">
                            <div className="text-center p-6 border border-cyan-500/30 rounded-lg bg-cyan-500/5">
                                <Radio className="w-12 h-12 mx-auto text-cyan-400 mb-3" />
                                <p className="text-sm text-gray-400 font-mono mb-4">
                                    Web NFC puede detectar etiquetas compatibles, pero no verifica una cédula chilena.
                                </p>
                                <Button onClick={() => setStep('nfc')} className="cyber-button">
                                    <Wifi className="w-4 h-4 mr-2" />
                                    DETECTAR ETIQUETA NFC
                                </Button>
                            </div>
                        </div>
                    </TabsContent>

                    <TabsContent value="selfie" className="pt-6">
                        <div className="space-y-4">
                            <div className="text-center p-6 border border-purple-500/30 rounded-lg bg-purple-500/5">
                                <ScanFace className="w-12 h-12 mx-auto text-purple-400 mb-3" />
                                <p className="text-sm text-gray-400 font-mono mb-4">
                                    Resultado simulado sobre una imagen; no es biometría certificada ni prueba de vida.
                                </p>
                                <Button onClick={() => setStep('selfie')} className="cyber-button">
                                    <Eye className="w-4 h-4 mr-2" />
                                    PROBAR DEMOSTRACIÓN
                                </Button>
                            </div>
                        </div>
                    </TabsContent>
                </Tabs>
            </div>
        </CyberPanel>
    );
};

export default MethodSelector;
