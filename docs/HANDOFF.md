# Handoff — DAO Ciudadana

**Para:** Codex (o cualquier agente/desarrollador que retome el proyecto)
**Actualizado:** 1 de agosto de 2026 · base `73f2985`, rama local `codex/produccion-ci`
**Documentos hermanos:** [`AUDIT.md`](./AUDIT.md) · [`ROADMAP.md`](./ROADMAP.md) · [`SECURITY_RUNBOOK.md`](./SECURITY_RUNBOOK.md) · [`../AGENTS.md`](../AGENTS.md)

---

## Lee esto primero

Este proyecto **parece** más terminado de lo que está. La UI es pulida y las
suites pasan, pero el servicio público sigue siendo un piloto y aún ejecuta la
versión anterior a los guardrails de esta rama.

Los cuatro hechos que tienes que interiorizar antes de tocar una línea:

1. **`totalSupply()` del contrato histórico de Sepolia sigue devolviendo 0.**
   Esa dirección usa Ownable/`string` y es incompatible con el contrato actual
   AccessControl/`bytes32`; sirve solo como evidencia histórica y no debe configurarse.
2. **Minteo y acciones mutantes de gobernanza exigen una sesión EIP-4361 y actuar
   como la misma wallet.** Producción también rechaza miembros demo/legacy, pero falta integrar
   la verificación civil de un solo uso antes de habilitar nuevas membresías.
3. **La identidad real sigue pendiente.** ClaveÚnica, NFC, liveness y RUT/email
   son demos rotuladas y devuelven 503 con `APP_ENV=production`.
4. **Hay una llave de proveedor expuesta en el historial Git público.** Debe
   revocarse/rotarse de inmediato y revisarse su uso/facturación; no copies su valor
   desde commits antiguos.

Nada de esto es un descuido reciente: está documentado, medido y priorizado en `AUDIT.md` y `ROADMAP.md`. El proyecto avanza deliberadamente de "simulado" a "real", y va a mitad de camino.

```bash
# Compruébalo tú mismo — 5 segundos
curl -s -X POST https://ethereum-sepolia-rpc.publicnode.com \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"eth_call","params":[{"to":"0x813fd379F715107b2451553d97f29408d8185f0e","data":"0x18160ddd"},"latest"],"id":1}'
# result: 0x0...0  → cero SBT minteados
```

---

## Qué es el proyecto

Piloto de una futura plataforma de membresía y gobernanza ciudadana. La meta es
emitir un SBT tras verificar identidad, pero hoy ninguna identidad civil ni
credencial on-chain de producción está habilitada.

---

## Estado por área

| Área | Estado | Detalle |
|---|---|---|
| **Contrato SBT** | 🟡 Código probado | AccessControl, soulbound y revocación; 31 tests. **No existe despliegue compatible.** La dirección histórica tiene supply 0 y otra ABI. |
| **Gobernanza** | 🟡 Propuestas verificables | Propuestas con papeletas EIP-712, nonce único y endpoint público de reverificación. Elecciones existen, pero votar queda bloqueado en producción hasta firmar sus papeletas; falta tally transaccional. |
| **Dashboard** | ✅ Montado | `/dashboard` con 5 secciones. Router funcionando. |
| **Despliegue** | 🟡 Servicio histórico activo | La versión pública anterior responde; esta rama separa liveness/readiness y aún no fue publicada. |
| **Autenticación** | ✅ Wallet / 🟡 identidad | Challenge EIP-4361, JWT corto y gates self/active. No equivale a identidad civil. |
| **Minteo on-chain** | 🔒 Bloqueado | Sin fallback implícito; producción espera grant de identidad + contrato compatible + reconciliación. |
| **Identidad real** | ❌ Pendiente | Demos bloqueadas en producción; Web NFC nunca se acepta como cédula verificada. |
| **PII** | 🟡 Código nuevo cifrado | Altas nuevas usan Fernet + índices HMAC. Datos legacy no fueron migrados/auditados; snapshot y migración son bloqueantes. |
| **App móvil** | ⚠️ Experimental | TypeScript, 15 tests, lint y auditoría npm pasan localmente y tienen un job CI. Release falla cerrado sin keystore externo; faltan PACE real y build/publicación nativos reproducibles. |

---

## Hallazgos abiertos (de `AUDIT.md`)

El estado vigente y la evidencia están al final de `AUDIT.md` (hallazgos P-*).
Bloqueantes principales: rotar el secreto histórico; migrar/cuarentenar datos
legacy; integrar grant de identidad; desplegar/verificar el contrato compatible;
resolver idempotencia cadena↔Mongo; ratificar D-1/D-2/D-3; migrar toolchains con
avisos altos de dependencias; firmar elecciones; añadir tally transaccional e
completar el build/release nativo de mobile. `main` no tiene branch protection/ruleset: CI informa,
pero aún no impide técnicamente un merge con checks rojos.

---

## Mapa del repositorio

```
DAO-Ciudadano/
├── AGENTS.md · CLAUDE.md       reglas de trabajo para agentes
├── docs/                       AUDIT.md · ROADMAP.md · HANDOFF.md
├── backend/                    FastAPI + MongoDB (Motor)
│   ├── main.py                 punto de entrada
│   ├── Dockerfile              imagen portable, respeta $PORT
│   ├── render.yaml             blueprint (plan free, rootDir backend)
│   ├── requirements.txt        SOLO producción — mínimo a propósito
│   ├── requirements-dev.txt    producción + pytest/mongomock/linters
│   ├── tests/                  157 tests con mongomock-motor
│   └── app/
│       ├── core/               config · database · security · middleware
│       ├── models/schemas.py   modelos Pydantic
│       ├── routers/
│       │   ├── auth.py         demos de identidad, 503 en producción
│       │   ├── deps.py         sesión wallet + gate de membresía
│       │   ├── elections.py    elecciones de representantes
│       │   ├── governance.py   propuestas, votos, delegación, tesorería
│       │   ├── membership.py   minteo (delega en BlockchainService)
│       │   └── wallet.py       challenge/verify EIP-4361
│       └── services/
│           ├── blockchain_service.py    modos disabled/demo/onchain explícitos
│           ├── governance_service.py    voting_power, ciclo de elecciones
│           └── membership_verifier.py   Mongo | on-chain (sin implementar)
├── frontend/                   React 19 + craco + Tailwind + Radix
│   └── src/
│       ├── App.js              router: /, /unete y /dashboard/*
│       ├── pages/DashboardPage.jsx   layout + secciones
│       ├── components/governance/    6 componentes, todos montados
│       ├── components/onboarding/    flujo de alta
│       ├── context/            OnboardingContext
│       └── hooks/              useWallet · useNFC (hook on-chain huérfano eliminado)
├── contracts/                  Hardhat + OpenZeppelin 5
│   ├── contracts/DAOCiudadanaSBT.sol
│   └── test/                   31 tests
└── mobile/                     React Native 0.83 + NFC
```

---

## Datos operativos

| Elemento | Valor |
|---|---|
| Contrato histórico incompatible (solo evidencia) | `0x813fd379F715107b2451553d97f29408d8185f0e` — **no configurar** |
| Owner del contrato | `0x154484aff9f6864db17141c6eec62568b8f5ac9b` (EOA) |
| `totalSupply()` | **0** |
| Frontend canónico / dominio SIWE | `https://estamosdao.cl` |
| API configurada por el frontend | `https://api.estamosdao.cl` |
| Backend histórico sondeado | `https://dao-ciudadana-api.onrender.com` — versión anterior en Render free |
| Base de datos | MongoDB Atlas, clúster `EstadosDaos`, DB `dao_ciudadana` |

La dirección histórica no se reutiliza. El próximo despliegue debe verificar el
código actual, separar `DEFAULT_ADMIN_ROLE`/`MINTER_ROLE`, custodiar las llaves y
registrar direcciones/red en un ADR e inventario operativo.

---

## Cómo levantarlo

```bash
# Backend
cd backend
cp .env.example .env          # completar MONGO_URL
pip install -r requirements-dev.txt
uvicorn main:app --reload --port 8000

# Frontend
cd frontend
cp .env.example .env
npm ci
npm start

# Contratos
cd contracts
npm ci
npx hardhat test              # 31 tests
```

Despliegue completo (Atlas + Render + Netlify) en [`backend/DEPLOY.md`](../backend/DEPLOY.md).

---

## Trampas concretas del código

Cosas que te van a costar tiempo si no las sabes de antemano:

1. **Los usuarios legacy no están migrados.** No promociones Atlas sin snapshot,
   inventario de duplicados, backfill cifrado validado y plan de rollback.

2. **La dirección Sepolia histórica es incompatible.** La ABI/hook manuales del
   frontend se eliminaron; el nuevo despliegue sale de artifacts del contrato actual.

3. **El minteo actual es server-side con `MINTER_ROLE`, provisional.** Falta
   ratificar D-1 y resolver reconciliación/idempotencia entre recibo y Mongo.

4. **`requirements.txt` está deliberadamente mínimo.** `python-multipart` y `pymongo` **no aparecen en ningún `import`** pero son obligatorias: la primera la exige FastAPI para `UploadFile` en `/api/auth/liveness`, la segunda la arrastra `motor` con un rango estrecho. Están documentadas en el propio archivo. No las quites por parecer huérfanas.

5. **El CI instala `requirements-dev.txt`**, no `requirements.txt`. Si mueves `pytest` de sitio, actualiza `.github/workflows/ci.yml`.

6. **`OnChainMembershipVerifier` lanza `NotImplementedError` a propósito.** No lo "arregles" devolviendo `True`: eso reintroduce exactamente el tipo de capacidad fingida que este proyecto está eliminando.

7. **La delegación no es transitiva y es una decisión, no un olvido.** Está razonada en `governance_service.py`. Si la cambias, cambia también el razonamiento.

8. **`CORS_ORIGINS` y `REACT_APP_BACKEND_URL` deben cambiarse juntas.** Si no coinciden, el navegador bloquea todo y la app aparece rota sin error visible en pantalla. `CORS_ORIGIN_REGEX` sirve solo fuera de producción; producción exige orígenes HTTPS exactos y las aliases deben redirigir al dominio canónico.

9. **Arranque en frío:** Render free suspende el servicio tras ~15 min sin tráfico; la primera petición tarda 30–60 s. Además, si `MONGO_URL` está mal, el arranque bloquea 30 s creando índices antes de continuar con un warning.

10. **Los procesos en segundo plano no sobreviven** entre comandos en entornos de sandbox. Si un `npm install` parece colgado, comprueba que el proceso siga vivo antes de esperarlo.

11. **El lock de nonce del minter es local al proceso.** Antes de escalar a varias
    instancias debe existir un coordinador distribuido. También hay que alinear el
    timeout del cliente (30 s) con la espera de recibo del backend (hasta 120 s).

12. **Papeleta y tally no son una escritura atómica.** El índice único evita votos
    duplicados concurrentes en propuestas, pero una caída entre insertar el voto y
    sumar el contador exige transacción o reconciliación derivada de papeletas.

13. **El JWT SIWE sigue en `localStorage`.** La CSP reduce la superficie XSS,
    pero pasar a cookie `HttpOnly` exige un cambio coordinado de emisión/logout,
    CORS con credenciales y defensa CSRF; no hagas una migración parcial.

---

## Decisiones pendientes — bloquean la Fase 1

No son decisiones técnicas que un agente deba tomar solo: definen custodia de llaves privadas, qué se publica de forma permanente e irreversible sobre cada ciudadano, y qué garantías reales ofrece la DAO. Detalle completo en `ROADMAP.md`.

- **D-1 · ¿Quién mintea el SBT?** Backend custodial (lo que el contrato ya permite), usuario con voucher firmado EIP-712, o relayer con meta-transacciones. Las dos últimas exigen redesplegar el contrato.
- **D-2 · ¿Qué se escribe on-chain como `identityHash`?** Las altas nuevas usan HMAC-SHA256 de 32 bytes, pero falta ratificar el diseño, llevar el pepper a KMS y migrar/purgar el esquema legacy reversible.
- **D-3 · ¿La gobernanza es on-chain u off-chain?** Las propuestas ya usan firmas EIP-712 off-chain; falta decidir el modelo definitivo, firmar elecciones y hacer el tally reconstruible/transaccional.

Cuando se tomen, déjalas escritas como ADR en `docs/`.

---

## Por dónde seguir

**Ruta crítica:** proveedor de identidad + grant de un solo uso → ratificar
D-1/D-2 y custodiar llaves/pepper → desplegar/verificar el contrato compatible →
minteo idempotente con reconciliación → verificador de membresía on-chain →
desplegar los guardrails de esta rama.

**Empezar hoy en paralelo:** el trámite de acceso al sandbox de ClaveÚnica. Es el único elemento cuyo plazo no controla el equipo, y bloquea toda la Fase 4.

**Trabajo desbloqueado que puedes tomar ya:**

- **Identidad** — integrar proveedor real (ClaveÚnica/liveness o alternativa) y emitir un grant de verificación de un solo uso; los demos ya están bloqueados en producción.
- **Minteo** — diseñar operación `pending`, idempotency key, reconciliador por recibos/eventos y coordinación distribuida de nonce.
- **Elecciones** — extender EIP-712/nonce a sus votos y hacer que resultados se deriven o actualicen transaccionalmente; propuestas ya tienen papeletas firmadas.
- **3.6** — tesorería real desde un Safe multisig. El backend ya responde `configured: false` honestamente.
- **3.8** — mover rate limiter y antifraude a Redis: hoy viven en memoria de proceso y se pierden al reiniciar.
- **4.2 / 4.3** — lectura PACE del chip y validación de `react-native-quick-crypto`
  en un build/dispositivo nativo real.
- **Legal/operación** — consentimientos versionados, privacidad/DPIA, observabilidad, backups y runbooks antes de admitir ciudadanía real.

---

## Cómo trabajar aquí

Las reglas completas están en [`AGENTS.md`](../AGENTS.md). Las tres que más importan:

1. **Nunca inventes datos para rellenar una interfaz.** Este repositorio ya tuvo un dashboard con 1432 miembros falsos y una tesorería con un "Grant Ethereum Foundation" ficticio sembrado en la base de datos. Si un dato no existe, devuelve `null` y muestra un estado vacío honesto.

2. **No marques nada como completo si no ejecutaste el camino real.** El precedente aquí es un `test_result.md` que documentaba un protocolo de testing elaborado sin un solo resultado registrado.

3. **Verifica contra la fuente, no contra la documentación.** El README de este repositorio llegó a afirmar cosas que el código contradecía. Si algo es on-chain, consúltalo por RPC antes de darlo por cierto.
