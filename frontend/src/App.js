import React, { useState, useMemo } from "react";
import { Card, CardContent } from "./components/ui/card";
import { Button } from "./components/ui/button";
import { Input } from "./components/ui/input";
import { Label } from "./components/ui/label";
import { Badge } from "./components/ui/badge";
import { Progress } from "./components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import { 
  CheckCircle2, ShieldCheck, ScanFace, Wallet, Cpu, FileCheck, Vote, 
  Leaf, Radio, Loader2, QrCode, Fingerprint, Upload, Zap, Terminal,
  Eye, Shield, Database, Globe, Lock, Code, Wifi, Activity
} from "lucide-react";
import axios from "axios";
import "./App.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Cyberpunk Step indicator component
const CyberStep = ({ n, title, active = false, done = false }) => (
  <div className="cyber-step">
    <div className={`cyber-step-number ${done ? 'completed' : active ? 'active' : 'pending'}`}>
      {done ? <CheckCircle2 className="h-4 w-4"/> : n}
    </div>
    <span className={`cyber-step-title ${done ? 'completed' : active ? 'active' : ''}`}>
      {title}
    </span>
  </div>
);

// Cyberpunk Panel component
const CyberPanel = ({ title, icon, description, children, className = "" }) => (
  <Card className={`cyber-card ${className}`}>
    <CardContent className="p-6">
      <div className="flex items-start gap-4 mb-6">
        <div className="text-cyan-400 cyber-icon">
          {icon}
        </div>
        <div className="flex-1">
          <h2 className="cyber-title text-xl font-bold tracking-wider mb-2" data-text={title}>
            {title}
          </h2>
          {description && (
            <p className="text-gray-400 text-sm font-mono">
              <Terminal className="inline w-3 h-3 mr-2"/>
              {description}
            </p>
          )}
        </div>
      </div>
      {children}
    </CardContent>
  </Card>
);

// Cyberpunk Loading Component
const CyberLoader = ({ text = "PROCESANDO..." }) => (
  <div className="flex items-center gap-3">
    <div className="cyber-spinner"></div>
    <span className="font-mono text-cyan-400 text-sm animate-pulse">
      {text}
    </span>
  </div>
);

// Main DAO App Component
const DAOOnboardingApp = () => {
  // State management
  const [step, setStep] = useState('method');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  
  // Form data
  const [rut, setRut] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  
  // API responses
  const [clave, setClave] = useState({});
  const [nfc, setNfc] = useState({});
  const [selfie, setSelfie] = useState({});
  const [wallet, setWallet] = useState({});
  const [mint, setMint] = useState({});
  const [stats, setStats] = useState({ total_members: 1432, recent_joins: 32 });

  // Progress calculation
  const progress = useMemo(() => {
    const order = ['method','clave','nfc','selfie','consent','wallet','mint','success'];
    const idx = Math.max(0, order.indexOf(step));
    return Math.round(((idx+1)/order.length)*100);
  }, [step]);

  // API calls
  const doClave = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await axios.post(`${API}/auth/clave-unica`, { rut });
      if (response.data.ok) {
        setClave(response.data);
        setStep('nfc');
      } else {
        setError(response.data.error || 'Error en ClaveÚnica');
      }
    } catch (err) {
      setError('Error de conexión con ClaveÚnica');
    } finally {
      setLoading(false);
    }
  };

  const doNFC = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await axios.post(`${API}/auth/nfc`);
      if (response.data.ok) {
        setNfc(response.data);
        setStep('selfie');
      } else {
        setError(response.data.error || 'Error en lectura NFC');
      }
    } catch (err) {
      setError('Error de conexión con NFC');
    } finally {
      setLoading(false);
    }
  };

  const doSelfie = async () => {
    if (!selectedFile) {
      setError('Por favor selecciona una imagen');
      return;
    }

    setLoading(true);
    setError('');
    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      
      const response = await axios.post(`${API}/auth/liveness`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      
      if (response.data.ok) {
        setSelfie(response.data);
        setStep('consent');
      } else {
        setError(response.data.error || 'Error en detección de vida');
      }
    } catch (err) {
      setError('Error de conexión en análisis de selfie');
    } finally {
      setLoading(false);
    }
  };

  const doWallet = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await axios.post(`${API}/wallet/connect`);
      if (response.data.ok) {
        setWallet(response.data);
        setStep('mint');
      } else {
        setError(response.data.error || 'Error conectando wallet');
      }
    } catch (err) {
      setError('Error de conexión con wallet');
    } finally {
      setLoading(false);
    }
  };

  const doMint = async () => {
    if (!wallet.address) return;
    
    setLoading(true);
    setError('');
    try {
      const response = await axios.post(`${API}/membership/mint`, {
        wallet_address: wallet.address,
        assurance_level: clave.assurance_level || 'AL1',
        doc_hash: nfc.doc_hash || '0xDOC',
      });
      
      if (response.data.ok) {
        setMint(response.data);
        await loadDashboardStats();
        setStep('success');
      } else {
        setError(response.data.error || 'Error minteando SBT');
      }
    } catch (err) {
      setError('Error de conexión en mint');
    } finally {
      setLoading(false);
    }
  };

  const loadDashboardStats = async () => {
    try {
      const response = await axios.get(`${API}/dashboard/stats`);
      setStats(response.data);
    } catch (err) {
      console.error('Error loading stats:', err);
    }
  };

  const handleFileSelect = (event) => {
    const file = event.target.files[0];
    if (file) {
      if (file.size > 10 * 1024 * 1024) {
        setError('Archivo muy grande (máximo 10MB)');
        return;
      }
      if (!file.type.startsWith('image/')) {
        setError('El archivo debe ser una imagen');
        return;
      }
      setSelectedFile(file);
      setError('');
    }
  };

  return (
    <div className="min-h-screen relative">
      {/* Matrix Rain Background Effect */}
      <div className="matrix-rain"></div>
      
      <div className="mx-auto max-w-6xl px-4 py-8 relative z-10">
        {/* Cyberpunk Header */}
        <header className="mb-10 text-center">
          <div className="flex items-center justify-center gap-4 mb-4">
            <div className="w-12 h-12 rounded-full bg-gradient-to-r from-cyan-400 to-purple-600 flex items-center justify-center">
              <Shield className="h-6 w-6 text-black"/>
            </div>
            <div>
              <h1 className="cyber-title text-3xl font-black" data-text="DAO CIUDADANA">
                DAO CIUDADANA
              </h1>
              <p className="text-cyan-400 font-mono text-sm tracking-wider">
                SISTEMA DE MEMBRESÍA DIGITAL • BLOCKCHAIN GOVERNANCE
              </p>
            </div>
            <div className="cyber-badge">
              BETA v0.1
            </div>
          </div>
          
          {/* Step Indicators - Hidden on mobile */}
          <div className="hidden lg:flex items-center justify-center gap-8 mt-6">
            <CyberStep n={1} title="Método" active={step==='method'} done={['clave','nfc','selfie','consent','wallet','mint','success','dashboard'].includes(step)} />
            <CyberStep n={2} title="Identidad" active={['clave','nfc','selfie'].includes(step)} done={['consent','wallet','mint','success','dashboard'].includes(step)} />
            <CyberStep n={3} title="Consentimiento" active={step==='consent'} done={['wallet','mint','success','dashboard'].includes(step)} />
            <CyberStep n={4} title="Wallet" active={step==='wallet'} done={['mint','success','dashboard'].includes(step)} />
            <CyberStep n={5} title="NFT" active={step==='mint'} done={['success','dashboard'].includes(step)} />
          </div>
        </header>

        {/* Progress Bar */}
        <div className="mb-8">
          <div className="cyber-progress">
            <div className="cyber-progress-fill" style={{ width: `${progress}%` }}></div>
          </div>
          <p className="text-center text-cyan-400 font-mono text-xs mt-2">
            PROGRESO: {progress}% COMPLETADO
          </p>
        </div>

        {/* Error Display */}
        {error && (
          <div className="cyber-error mb-6">
            <Zap className="inline w-4 h-4 mr-2"/>
            <strong>ERROR:</strong> {error}
          </div>
        )}

        {/* Method Selection */}
        {step === 'method' && (
          <CyberPanel 
            title="SELECCIONAR MÉTODO DE VERIFICACIÓN" 
            description="Protocolos de autenticación disponibles. Datos personales protegidos por criptografía."
            icon={<Fingerprint className="h-8 w-8"/>}
          >
            <div className="cyber-tabs">
              <Tabs defaultValue="clave" className="w-full">
                <TabsList className="grid grid-cols-3 w-full bg-transparent gap-2">
                  <TabsTrigger value="clave" className="cyber-tab">
                    <QrCode className="w-4 h-4 mr-2"/>
                    ClaveÚnica
                  </TabsTrigger>
                  <TabsTrigger value="nfc" className="cyber-tab">
                    <Wifi className="w-4 h-4 mr-2"/>
                    Cédula NFC
                  </TabsTrigger>
                  <TabsTrigger value="selfie" className="cyber-tab">
                    <Eye className="w-4 h-4 mr-2"/>
                    Biometría IA
                  </TabsTrigger>
                </TabsList>
                
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
                        <Lock className="inline w-3 h-3 mr-1"/>
                        Redirige a sistema gubernamental oficial. No almacenamos RUT.
                      </p>
                    </div>
                    <Button onClick={() => setStep('clave')} className="cyber-button w-full">
                      <Shield className="w-4 h-4 mr-2"/>
                      INICIAR PROTOCOLO CLAVE ÚNICA
                    </Button>
                  </div>
                </TabsContent>
                
                <TabsContent value="nfc" className="pt-6">
                  <div className="space-y-4">
                    <div className="text-center p-6 border border-cyan-500/30 rounded-lg bg-cyan-500/5">
                      <Radio className="w-12 h-12 mx-auto text-cyan-400 mb-3"/>
                      <p className="text-sm text-gray-400 font-mono mb-4">
                        Validación criptográfica del chip de cédula de identidad
                      </p>
                      <Button onClick={() => setStep('nfc')} className="cyber-button">
                        <Wifi className="w-4 h-4 mr-2"/>
                        ACTIVAR LECTURA NFC
                      </Button>
                    </div>
                  </div>
                </TabsContent>
                
                <TabsContent value="selfie" className="pt-6">
                  <div className="space-y-4">
                    <div className="text-center p-6 border border-purple-500/30 rounded-lg bg-purple-500/5">
                      <ScanFace className="w-12 h-12 mx-auto text-purple-400 mb-3"/>
                      <p className="text-sm text-gray-400 font-mono mb-4">
                        Análisis biométrico avanzado con IA para detección de vida
                      </p>
                      <Button onClick={() => setStep('selfie')} className="cyber-button">
                        <Eye className="w-4 h-4 mr-2"/>
                        INICIAR ANÁLISIS BIOMÉTRICO
                      </Button>
                    </div>
                  </div>
                </TabsContent>
              </Tabs>
            </div>
          </CyberPanel>
        )}

        {/* ClaveÚnica Step */}
        {step === 'clave' && (
          <CyberPanel 
            title="PROTOCOLO CLAVE ÚNICA ACTIVADO" 
            description="Estableciendo conexión segura con servidor gubernamental..."
            icon={<QrCode className="h-8 w-8"/>}
          >
            <div className="flex flex-col items-center gap-6">
              {!loading && !clave.subject_id && (
                <Button onClick={doClave} className="cyber-button">
                  <Shield className="w-4 h-4 mr-2"/>
                  AUTENTICAR CON GOBIERNO
                </Button>
              )}
              
              {loading && <CyberLoader text="VALIDANDO IDENTIDAD..." />}
              
              {clave.subject_id && (
                <div className="cyber-success text-center p-4 rounded-lg">
                  <CheckCircle2 className="w-8 h-8 mx-auto mb-2"/>
                  <p className="font-mono">IDENTIDAD VERIFICADA</p>
                  <Badge className="cyber-badge success mt-2">
                    {clave.subject_id} • NIVEL {clave.assurance_level}
                  </Badge>
                </div>
              )}
            </div>
          </CyberPanel>
        )}

        {/* NFC Step */}
        {step === 'nfc' && (
          <CyberPanel 
            title="LECTURA CRIPTOGRÁFICA NFC" 
            description="Validando autenticidad del chip de cédula..."
            icon={<Radio className="h-8 w-8"/>}
          >
            <div className="flex flex-col items-center gap-6">
              {!loading && !nfc.chip_serial && (
                <div className="text-center">
                  <div className="w-32 h-32 mx-auto mb-4 border-2 border-dashed border-cyan-400 rounded-lg flex items-center justify-center">
                    <Activity className="w-12 h-12 text-cyan-400 animate-pulse"/>
                  </div>
                  <Button onClick={doNFC} className="cyber-button">
                    <Radio className="w-4 h-4 mr-2"/>
                    ESCANEAR CHIP
                  </Button>
                </div>
              )}
              
              {loading && <CyberLoader text="LEYENDO CHIP NFC..." />}
              
              {nfc.chip_serial && (
                <div className="cyber-success text-center p-4 rounded-lg w-full">
                  <CheckCircle2 className="w-8 h-8 mx-auto mb-2"/>
                  <p className="font-mono mb-2">CHIP VALIDADO</p>
                  <div className="flex flex-wrap justify-center gap-2">
                    <Badge className="cyber-badge">SERIAL: {nfc.chip_serial}</Badge>
                    <Badge className="cyber-badge success">HASH: {nfc.doc_hash?.slice(0,10)}...</Badge>
                  </div>
                </div>
              )}
            </div>
          </CyberPanel>
        )}

        {/* Selfie Step */}
        {step === 'selfie' && (
          <CyberPanel 
            title="ANÁLISIS BIOMÉTRICO CON IA" 
            description="Sistema de detección de vida avanzado. Procesamiento local seguro."
            icon={<ScanFace className="h-8 w-8"/>}
          >
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
                    <Database className="inline w-3 h-3 mr-1"/>
                    {selectedFile.name} • {Math.round(selectedFile.size/1024)}KB
                  </p>
                )}
              </div>
              
              <div className="flex flex-col items-center gap-4">
                {!loading && selectedFile && (
                  <Button onClick={doSelfie} className="cyber-button">
                    <Upload className="w-4 h-4 mr-2"/>
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
                          <Code className="inline w-3 h-3 mr-1"/>
                          {selfie.analysis}
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </CyberPanel>
        )}

        {/* Consent Step */}
        {step === 'consent' && (
          <CyberPanel 
            title="PROTOCOLO DE PRIVACIDAD" 
            description="Consentimiento informado para procesamiento de datos biométricos"
            icon={<FileCheck className="h-8 w-8"/>}
          >
            <div className="space-y-6">
              <div className="grid md:grid-cols-2 gap-6">
                <div className="bg-green-500/10 border border-green-500/30 p-4 rounded-lg">
                  <h3 className="cyber-label text-green-400 mb-3">
                    <Lock className="inline w-4 h-4 mr-2"/>
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
                    <Shield className="inline w-4 h-4 mr-2"/>
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
                  <Wallet className="w-4 h-4 mr-2"/>
                  ACEPTO TÉRMINOS • CONTINUAR
                </Button>
                <Button onClick={() => setStep('method')} variant="outline" className="border-gray-600 text-gray-400 hover:text-white">
                  REVISAR MÉTODOS
                </Button>
              </div>
            </div>
          </CyberPanel>
        )}

        {/* Wallet Step */}
        {step === 'wallet' && (
          <CyberPanel 
            title="CONEXIÓN DE WALLET BLOCKCHAIN" 
            description="Estableciendo enlace con billetera digital descentralizada"
            icon={<Wallet className="h-8 w-8"/>}
          >
            <div className="flex flex-col items-center gap-6">
              {!loading && !wallet.address && (
                <div className="text-center">
                  <div className="w-32 h-32 mx-auto mb-4 border-2 border-purple-500 rounded-lg flex items-center justify-center bg-purple-500/5">
                    <Globe className="w-12 h-12 text-purple-400"/>
                  </div>
                  <Button onClick={doWallet} className="cyber-button">
                    <Wallet className="w-4 h-4 mr-2"/>
                    CONECTAR WALLET
                  </Button>
                </div>
              )}
              
              {loading && <CyberLoader text="ESTABLECIENDO CONEXIÓN..." />}
              
              {wallet.address && (
                <div className="cyber-success text-center p-4 rounded-lg w-full">
                  <CheckCircle2 className="w-8 h-8 mx-auto mb-2"/>
                  <p className="font-mono mb-2">WALLET CONECTADA</p>
                  <Badge className="cyber-badge success font-mono">
                    {wallet.address}
                  </Badge>
                </div>
              )}
            </div>
          </CyberPanel>
        )}

        {/* Mint Step */}
        {step === 'mint' && (
          <CyberPanel 
            title="GENERACIÓN DE NFT CIUDADANO" 
            description="Minteando Soulbound Token • Contrato inteligente ejecutándose"
            icon={<Cpu className="h-8 w-8"/>}
          >
            <div className="flex flex-col items-center gap-6">
              {!loading && !mint.token_id && (
                <div className="text-center">
                  <div className="w-32 h-32 mx-auto mb-4 border-2 border-yellow-500 rounded-lg flex items-center justify-center bg-yellow-500/5">
                    <Zap className="w-12 h-12 text-yellow-400 animate-pulse"/>
                  </div>
                  <Button onClick={doMint} className="cyber-button">
                    <Cpu className="w-4 h-4 mr-2"/>
                    MINTEAR SBT
                  </Button>
                </div>
              )}
              
              {loading && <CyberLoader text="EJECUTANDO SMART CONTRACT..." />}
              
              {mint.token_id && (
                <div className="cyber-success text-center p-4 rounded-lg w-full">
                  <CheckCircle2 className="w-8 h-8 mx-auto mb-2"/>
                  <p className="font-mono mb-2">NFT GENERADO</p>
                  <div className="flex flex-wrap justify-center gap-2">
                    <Badge className="cyber-badge">TOKEN #{mint.token_id}</Badge>
                    <Badge className="cyber-badge success">TX: {mint.tx_hash?.slice(0,10)}...</Badge>
                  </div>
                </div>
              )}
            </div>
          </CyberPanel>
        )}

        {/* Success Step */}
        {step === 'success' && (
          <CyberPanel 
            title="MEMBRESÍA DAO ACTIVADA" 
            description="Ciudadanía digital verificada • NFT registrado en blockchain"
            icon={<CheckCircle2 className="h-8 w-8"/>}
          >
            <div className="grid md:grid-cols-3 gap-6 mb-6">
              <div className="cyber-stat-card bg-gradient-to-br from-cyan-500/10 to-blue-500/10 border-cyan-500/30">
                <div className="text-center">
                  <Leaf className="w-8 h-8 mx-auto text-cyan-400 mb-3"/>
                  <div className="cyber-stat-number text-2xl">#{mint.token_id || '—'}</div>
                  <div className="cyber-stat-label">NFT CIUDADANO</div>
                  <p className="text-xs text-gray-500 mt-2 font-mono break-all">
                    {wallet.address?.slice(0,16)}...
                  </p>
                </div>
              </div>
              
              <div className="cyber-stat-card bg-gradient-to-br from-purple-500/10 to-pink-500/10 border-purple-500/30">
                <div className="text-center">
                  <Vote className="w-8 h-8 mx-auto text-purple-400 mb-3"/>
                  <div className="cyber-stat-number text-lg">ACTIVO</div>
                  <div className="cyber-stat-label">ESTADO</div>
                  <div className="mt-3 space-y-1">
                    <p className="text-xs text-gray-400 font-mono">• Propuestas</p>
                    <p className="text-xs text-gray-400 font-mono">• Votaciones</p>
                    <p className="text-xs text-gray-400 font-mono">• Tesorería</p>
                  </div>
                </div>
              </div>
              
              <div className="cyber-stat-card bg-gradient-to-br from-green-500/10 to-teal-500/10 border-green-500/30">
                <div className="text-center">
                  <Shield className="w-8 h-8 mx-auto text-green-400 mb-3"/>
                  <div className="cyber-stat-number text-lg">100%</div>
                  <div className="cyber-stat-label">PRIVACIDAD</div>
                  <div className="mt-3 space-y-1">
                    <p className="text-xs text-gray-400 font-mono">• Hash público</p>
                    <p className="text-xs text-gray-400 font-mono">• PII protegida</p>
                    <p className="text-xs text-gray-400 font-mono">• Auditable</p>
                  </div>
                </div>
              </div>
            </div>
            
            <div className="text-center">
              <Button onClick={() => { setStep('dashboard'); loadDashboardStats(); }} className="cyber-button">
                <Terminal className="w-4 h-4 mr-2"/>
                ACCEDER AL DASHBOARD
              </Button>
            </div>
          </CyberPanel>
        )}

        {/* Dashboard */}
        {step === 'dashboard' && (
          <CyberPanel 
            title="DASHBOARD CIUDADANO ACTIVO" 
            description="Métricas en tiempo real • Datos agregados de blockchain"
            icon={<Activity className="h-8 w-8"/>}
          >
            <div className="grid md:grid-cols-3 gap-6 mb-8">
              <div className="cyber-stat-card">
                <div className="cyber-stat-number">{stats.total_members.toLocaleString()}</div>
                <div className="cyber-stat-label">MIEMBROS ACTIVOS</div>
              </div>
              
              <div className="cyber-stat-card">
                <div className="cyber-stat-number">+{stats.recent_joins}</div>
                <div className="cyber-stat-label">NUEVOS (30D)</div>
              </div>
              
              <div className="cyber-stat-card">
                <div className="cyber-stat-number">#{mint.token_id || '—'}</div>
                <div className="cyber-stat-label">TU NFT ID</div>
              </div>
            </div>
            
            <div className="grid md:grid-cols-2 gap-4">
              <Button variant="outline" className="cyber-button bg-transparent">
                <Globe className="w-4 h-4 mr-2"/>
                EXPLORAR BLOCKCHAIN
              </Button>
              <Button variant="outline" className="cyber-button bg-transparent">
                <Vote className="w-4 h-4 mr-2"/>
                VER PROPUESTAS
              </Button>
            </div>
            
            <div className="mt-8 p-4 bg-black/50 border border-cyan-500/30 rounded-lg">
              <p className="text-xs text-cyan-400 font-mono text-center">
                <Terminal className="inline w-3 h-3 mr-2"/>
                Sistema operativo • Datos sincronizados con red blockchain
              </p>
            </div>
          </CyberPanel>
        )}

        {/* Cyberpunk Footer */}
        <footer className="cyber-footer">
          Sistema DAO Ciudadana • Blockchain Governance • Código Abierto • v0.1.0
        </footer>
      </div>
    </div>
  );
};

export default DAOOnboardingApp;