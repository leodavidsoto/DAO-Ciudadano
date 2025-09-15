import React, { useState, useMemo } from "react";
import { Card, CardContent } from "./components/ui/card";
import { Button } from "./components/ui/button";
import { Input } from "./components/ui/input";
import { Label } from "./components/ui/label";
import { Badge } from "./components/ui/badge";
import { Progress } from "./components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import { CheckCircle2, ShieldCheck, ScanFace, Wallet, Cpu, FileCheck, Vote, Leaf, Radio, Loader2, QrCode, Fingerprint, Upload } from "lucide-react";
import axios from "axios";
import "./App.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Step indicator component
const Step = ({ n, title, active = false, done = false }) => (
  <div className="flex items-center gap-3">
    <div className={`flex h-8 w-8 items-center justify-center rounded-full border text-sm font-semibold ${
      done ? 'bg-emerald-600 text-white border-emerald-600' : 
      active ? 'bg-blue-600 text-white border-blue-600' : 
      'bg-white text-slate-700'
    }`}>
      {done ? <CheckCircle2 className="h-4 w-4"/> : n}
    </div>
    <span className={`text-sm ${active ? 'font-semibold' : 'text-slate-600'}`}>{title}</span>
  </div>
);

// Panel component
const Panel = ({ title, icon, description, children }) => (
  <Card className="rounded-2xl shadow-lg border-slate-200 bg-white/80 backdrop-blur-sm">
    <CardContent className="p-6">
      <div className="flex items-start gap-3 mb-4">
        <div className="mt-1 text-blue-600">{icon}</div>
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-800">{title}</h2>
          {description && <p className="text-slate-600 text-sm mt-1">{description}</p>}
        </div>
      </div>
      {children}
    </CardContent>
  </Card>
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
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-emerald-50 py-10">
      <div className="mx-auto max-w-5xl px-4">
        <header className="mb-8 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ShieldCheck className="h-7 w-7 text-blue-600"/>
            <h1 className="text-2xl font-bold tracking-tight text-slate-800">DAO Ciudadana · Membresía Digital</h1>
            <Badge variant="secondary" className="rounded-full bg-blue-100 text-blue-700">Beta</Badge>
          </div>
          <div className="hidden md:flex items-center gap-6">
            <Step n={1} title="Método" active={step==='method'} done={['clave','nfc','selfie','consent','wallet','mint','success','dashboard'].includes(step)} />
            <Step n={2} title="Identidad" active={['clave','nfc','selfie'].includes(step)} done={['consent','wallet','mint','success','dashboard'].includes(step)} />
            <Step n={3} title="Consentimiento" active={step==='consent'} done={['wallet','mint','success','dashboard'].includes(step)} />
            <Step n={4} title="Wallet" active={step==='wallet'} done={['mint','success','dashboard'].includes(step)} />
            <Step n={5} title="Mint SBT" active={step==='mint'} done={['success','dashboard'].includes(step)} />
          </div>
        </header>

        <div className="mb-6">
          <Progress value={progress} className="h-3 bg-slate-200" />
        </div>

        {error && (
          <div className="mb-4 p-4 rounded-lg bg-red-50 border border-red-200">
            <p className="text-red-700 text-sm">{error}</p>
          </div>
        )}

        {/* Method Selection */}
        {step === 'method' && (
          <Panel 
            title="Elige cómo verificar tu identidad" 
            description="No publicamos tus datos personales en blockchain. Solo guardamos huellas criptográficas."
            icon={<Fingerprint className="h-6 w-6"/>}
          >
            <Tabs defaultValue="clave" className="w-full">
              <TabsList className="grid grid-cols-3 w-full">
                <TabsTrigger value="clave">ClaveÚnica</TabsTrigger>
                <TabsTrigger value="nfc">Cédula NFC</TabsTrigger>
                <TabsTrigger value="selfie">Selfie + IA</TabsTrigger>
              </TabsList>
              
              <TabsContent value="clave" className="pt-4">
                <div className="grid md:grid-cols-[1fr_auto] gap-4 items-end">
                  <div>
                    <Label htmlFor="rut" className="text-slate-700">RUT (formato 11111111-1)</Label>
                    <Input 
                      id="rut" 
                      placeholder="Ingresa tu RUT" 
                      value={rut} 
                      onChange={e => setRut(e.target.value)}
                      className="mt-2"
                    />
                    <p className="text-xs text-slate-500 mt-2">Se usa solo para redirigir al flujo oficial de ClaveÚnica. La DAO no guarda tu RUT.</p>
                  </div>
                  <Button onClick={() => setStep('clave')} className="bg-blue-600 hover:bg-blue-700">
                    Continuar
                  </Button>
                </div>
              </TabsContent>
              
              <TabsContent value="nfc" className="pt-4">
                <p className="text-sm text-slate-600 mb-3">Acerca tu cédula al celular. Validaremos el chip sin guardar datos personales.</p>
                <Button variant="secondary" onClick={() => setStep('nfc')} className="gap-2">
                  <Radio className="h-4 w-4"/> Iniciar lectura NFC
                </Button>
              </TabsContent>
              
              <TabsContent value="selfie" className="pt-4">
                <p className="text-sm text-slate-600 mb-3">Usamos IA avanzada para validar que eres una persona real (no una foto o video).</p>
                <Button variant="secondary" onClick={() => setStep('selfie')} className="gap-2">
                  <ScanFace className="h-4 w-4"/> Iniciar detección de vida
                </Button>
              </TabsContent>
            </Tabs>
          </Panel>
        )}

        {/* ClaveÚnica Step */}
        {step === 'clave' && (
          <Panel 
            title="Verificar con ClaveÚnica" 
            description="Serás validado con el proveedor estatal. Volverás aquí automáticamente."
            icon={<QrCode className="h-6 w-6"/>}
          >
            <div className="flex flex-col md:flex-row items-center gap-4">
              <Button disabled={loading} onClick={doClave} className="gap-2 bg-blue-600 hover:bg-blue-700">
                {loading ? <Loader2 className="h-4 w-4 animate-spin"/> : <ShieldCheck className="h-4 w-4"/>}
                {loading ? 'Validando...' : 'Iniciar validación'}
              </Button>
              {clave.subject_id && (
                <Badge variant="outline" className="bg-emerald-50 text-emerald-700">
                  ✓ Verificado: {clave.subject_id}
                </Badge>
              )}
            </div>
          </Panel>
        )}

        {/* NFC Step */}
        {step === 'nfc' && (
          <Panel 
            title="Leer cédula por NFC" 
            description="Acerca tu cédula al teléfono. Validamos autenticidad criptográfica del chip."
            icon={<Radio className="h-6 w-6"/>}
          >
            <div className="flex flex-wrap items-center gap-3">
              <Button disabled={loading} onClick={doNFC} className="gap-2 bg-orange-600 hover:bg-orange-700">
                {loading ? <Loader2 className="h-4 w-4 animate-spin"/> : <Radio className="h-4 w-4"/>}
                {loading ? 'Leyendo...' : 'Leer ahora'}
              </Button>
              {nfc.chip_serial && <Badge variant="outline">Chip: {nfc.chip_serial}</Badge>}
              {nfc.doc_hash && <Badge variant="secondary">Hash: {nfc.doc_hash.slice(0,10)}…</Badge>}
            </div>
          </Panel>
        )}

        {/* Selfie Step */}
        {step === 'selfie' && (
          <Panel 
            title="Selfie: detección de vida con IA" 
            description="Subir una foto tuya para verificar que eres una persona real ahora mismo."
            icon={<ScanFace className="h-6 w-6"/>}
          >
            <div className="space-y-4">
              <div>
                <Label htmlFor="selfie" className="text-slate-700">Selecciona tu selfie</Label>
                <Input 
                  id="selfie"
                  type="file" 
                  accept="image/*" 
                  onChange={handleFileSelect}
                  className="mt-2"
                />
                {selectedFile && (
                  <p className="text-xs text-slate-600 mt-1">
                    Archivo seleccionado: {selectedFile.name} ({Math.round(selectedFile.size/1024)}KB)
                  </p>
                )}
              </div>
              
              <div className="flex flex-wrap items-center gap-3">
                <Button 
                  disabled={loading || !selectedFile} 
                  onClick={doSelfie} 
                  className="gap-2 bg-purple-600 hover:bg-purple-700"
                >
                  {loading ? <Loader2 className="h-4 w-4 animate-spin"/> : <Upload className="h-4 w-4"/>}
                  {loading ? 'Analizando...' : 'Analizar selfie'}
                </Button>
                
                {selfie.score && (
                  <Badge variant="outline" className={`${
                    selfie.score >= 0.7 ? 'bg-emerald-50 text-emerald-700' : 'bg-yellow-50 text-yellow-700'
                  }`}>
                    Score: {Math.round(selfie.score * 100)}%
                  </Badge>
                )}
              </div>
              
              {selfie.analysis && (
                <div className="p-3 rounded-lg bg-slate-50 border">
                  <p className="text-xs text-slate-600">Análisis IA:</p>
                  <p className="text-sm text-slate-700 mt-1">{selfie.analysis}</p>
                </div>
              )}
            </div>
          </Panel>
        )}

        {/* Consent Step */}
        {step === 'consent' && (
          <Panel 
            title="Consentimiento informado" 
            description="Transparencia total: nunca publicamos tu RUT ni tu foto."
            icon={<FileCheck className="h-6 w-6"/>}
          >
            <div className="space-y-4">
              <div className="p-4 rounded-lg border bg-slate-50">
                <h3 className="font-semibold text-slate-800 mb-2">¿Qué datos guardamos?</h3>
                <ul className="text-sm text-slate-700 space-y-1 list-disc ml-5">
                  <li>Solo huellas criptográficas (hashes) de la verificación</li>
                  <li>NFT ciudadano (soulbound) no transferible en tu wallet</li>
                  <li>Conteos agregados para el padrón público</li>
                </ul>
              </div>
              
              <div className="p-4 rounded-lg border bg-emerald-50">
                <h3 className="font-semibold text-emerald-800 mb-2">¿Qué NO hacemos?</h3>
                <ul className="text-sm text-emerald-700 space-y-1 list-disc ml-5">
                  <li>No guardamos tu RUT ni nombre en blockchain</li>
                  <li>No guardamos tu selfie ni foto</li>
                  <li>No vendemos ni compartimos datos personales</li>
                </ul>
              </div>
              
              <div className="flex gap-3">
                <Button onClick={() => setStep('wallet')} className="gap-2 bg-emerald-600 hover:bg-emerald-700">
                  <Wallet className="h-4 w-4"/> Acepto y continuar
                </Button>
                <Button variant="ghost" onClick={() => setStep('method')}>
                  Volver
                </Button>
              </div>
            </div>
          </Panel>
        )}

        {/* Wallet Step */}
        {step === 'wallet' && (
          <Panel 
            title="Conectar billetera digital" 
            description="Tu NFT ciudadano se guardará en tu wallet personal."
            icon={<Wallet className="h-6 w-6"/>}
          >
            <div className="flex flex-wrap items-center gap-3">
              <Button disabled={loading} onClick={doWallet} className="gap-2 bg-indigo-600 hover:bg-indigo-700">
                {loading ? <Loader2 className="h-4 w-4 animate-spin"/> : <Wallet className="h-4 w-4"/>}
                {loading ? 'Conectando...' : 'Conectar wallet'}
              </Button>
              {wallet.address && (
                <Badge variant="outline" className="bg-indigo-50 text-indigo-700">
                  ✓ {wallet.address}
                </Badge>
              )}
            </div>
          </Panel>
        )}

        {/* Mint Step */}
        {step === 'mint' && (
          <Panel 
            title="Emitir NFT ciudadano (Soulbound)" 
            description="Tu carnet digital para participar en la DAO. No es transferible."
            icon={<Cpu className="h-6 w-6"/>}
          >
            <div className="flex flex-wrap items-center gap-3">
              <Button disabled={loading} onClick={doMint} className="gap-2 bg-violet-600 hover:bg-violet-700">
                {loading ? <Loader2 className="h-4 w-4 animate-spin"/> : <Cpu className="h-4 w-4"/>}
                {loading ? 'Minteando...' : 'Mint SBT'}
              </Button>
              {mint.token_id && <Badge variant="secondary">Token #{mint.token_id}</Badge>}
              {mint.tx_hash && <Badge variant="outline">Tx: {mint.tx_hash.slice(0,10)}…</Badge>}
            </div>
          </Panel>
        )}

        {/* Success Step */}
        {step === 'success' && (
          <Panel 
            title="¡Éxito! Ya eres miembro de la DAO" 
            description="Tu NFT ciudadano está listo y registrado en blockchain."
            icon={<CheckCircle2 className="h-6 w-6"/>}
          >
            <div className="grid md:grid-cols-3 gap-6">
              <div className="p-6 rounded-xl border border-emerald-200 bg-emerald-50">
                <p className="text-sm text-emerald-600 font-medium">Tu Carnet Digital</p>
                <div className="mt-3 p-4 rounded-xl border-2 border-emerald-300 bg-white text-center">
                  <Leaf className="h-8 w-8 mx-auto text-emerald-600"/>
                  <p className="font-semibold mt-2 text-slate-800">NFT SBT · Token #{mint.token_id || '—'}</p>
                  <p className="text-xs text-slate-500 mt-1">{wallet.address}</p>
                </div>
              </div>
              
              <div className="p-6 rounded-xl border border-blue-200 bg-blue-50">
                <p className="text-sm text-blue-600 font-medium">Próximos Pasos</p>
                <ul className="list-disc ml-5 text-sm mt-3 space-y-2 text-slate-700">
                  <li>Explora el dashboard ciudadano</li>
                  <li>Crea tu primera propuesta</li>
                  <li>Participa en votaciones</li>
                  <li>Conecta con otros miembros</li>
                </ul>
              </div>
              
              <div className="p-6 rounded-xl border border-slate-200 bg-slate-50">
                <p className="text-sm text-slate-600 font-medium">Transparencia</p>
                <ul className="list-disc ml-5 text-sm mt-3 space-y-2 text-slate-700">
                  <li>Alta registrada: hash público</li>
                  <li>Datos personales: jamás expuestos</li>
                  <li>Audita el bloque en explorer</li>
                  <li>Código fuente abierto</li>
                </ul>
              </div>
            </div>
            
            <div className="mt-6">
              <Button onClick={() => { setStep('dashboard'); loadDashboardStats(); }} className="gap-2 bg-blue-600 hover:bg-blue-700">
                <Vote className="h-4 w-4"/> Ir al dashboard
              </Button>
            </div>
          </Panel>
        )}

        {/* Dashboard */}
        {step === 'dashboard' && (
          <Panel 
            title="Dashboard Ciudadano" 
            description="Estadísticas agregadas y enlaces para auditar blockchain."
            icon={<Vote className="h-6 w-6"/>}
          >
            <div className="grid md:grid-cols-3 gap-6 mb-6">
              <div className="p-6 rounded-xl border-2 border-blue-200 bg-blue-50 text-center">
                <p className="text-sm text-blue-600 font-medium">Miembros Activos</p>
                <p className="text-4xl font-bold mt-2 text-blue-800">{stats.total_members.toLocaleString()}</p>
              </div>
              
              <div className="p-6 rounded-xl border-2 border-emerald-200 bg-emerald-50 text-center">
                <p className="text-sm text-emerald-600 font-medium">Altas (30 días)</p>
                <p className="text-4xl font-bold mt-2 text-emerald-800">+{stats.recent_joins}</p>
              </div>
              
              <div className="p-6 rounded-xl border-2 border-violet-200 bg-violet-50 text-center">
                <p className="text-sm text-violet-600 font-medium">Tu NFT</p>
                <p className="text-lg font-bold mt-2 text-violet-800">#{mint.token_id || '—'}</p>
                <p className="text-xs text-violet-600 mt-1 break-all">{wallet.address || '—'}</p>
              </div>
            </div>
            
            <div className="grid md:grid-cols-2 gap-4">
              <Button variant="outline" className="gap-2">
                <FileCheck className="h-4 w-4"/> Ver en blockchain explorer
              </Button>
              <Button variant="outline" className="gap-2">
                <Vote className="h-4 w-4"/> Participar en propuestas
              </Button>
            </div>
            
            <p className="text-sm text-slate-500 mt-6 text-center">
              *Dashboard en vivo. Conecta tu subgraph/indexer para datos reales de blockchain.
            </p>
          </Panel>
        )}

        <footer className="text-center mt-12 text-xs text-slate-500">
          Hecho con ❤️ para la ciudadanía digital · Transparencia por diseño · Código abierto
        </footer>
      </div>
    </div>
  );
};

export default DAOOnboardingApp;