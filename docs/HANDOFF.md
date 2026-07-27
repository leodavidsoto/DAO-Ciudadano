# Handoff — DAO Ciudadana

**Para:** Codex (o cualquier agente/desarrollador que retome el proyecto)
**Actualizado:** 27 de julio de 2026 · commit `09567b4`
**Documentos hermanos:** [`AUDIT.md`](./AUDIT.md) · [`ROADMAP.md`](./ROADMAP.md) · [`../AGENTS.md`](../AGENTS.md)

---

## Lee esto primero

Este proyecto **parece** más terminado de lo que está. La UI es pulida, hay 82 tests de backend, 29 de contrato, CI en verde y despliegue funcionando en producción. Eso puede llevarte a asumir que solo faltan detalles. No es así.

Los tres hechos que tienes que interiorizar antes de tocar una línea:

1. **`totalSupply()` del contrato en Sepolia sigue devolviendo 0.** Ningún SBT se ha minteado jamás on-chain. Lo que la app llama "membresía" son documentos de MongoDB. Verifícalo tú mismo antes de planificar (comando abajo).
2. **Ningún endpoint exige autenticación.** Hay control de *membresía* en gobernanza, pero no hay identidad: el backend cree cualquier dirección que le manden en el cuerpo de la petición. Un `curl` sigue pudiendo crear membresías.
3. **La verificación de identidad es simulada.** ClaveÚnica y la lectura NFC devuelven datos inventados; el liveness devuelve `0.85` fijo si no hay API key.

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

Plataforma de membresía ciudadana chilena. Una persona verifica su identidad (ClaveÚnica, chip NFC de la cédula o biometría) y recibe un **Soulbound Token** no transferible que acredita su pertenencia a una DAO. Con esa membresía participa en gobernanza: propone, vota, delega su voto y elige representantes.

---

## Estado por área

| Área | Estado | Detalle |
|---|---|---|
| **Contrato SBT** | ✅ Sólido | Soulbound, one-per-wallet, revocación con cooldown, pausable. 29 tests, 100 % statements. Desplegado en Sepolia. **0 tokens minteados.** |
| **Gobernanza** | ✅ Funcional | Propuestas, votos con peso por delegación, elecciones de representantes. Membresía obligatoria en todos los endpoints mutantes. |
| **Dashboard** | ✅ Montado | `/dashboard` con 5 secciones. Router funcionando. |
| **Despliegue** | ✅ Operativo | Backend en Render + MongoDB Atlas, frontend en Netlify, CI en GitHub Actions (4 jobs). |
| **Autenticación** | ❌ No existe | Ningún endpoint la exige. El `voter_address` viene del cuerpo de la petición. |
| **Minteo on-chain** | ❌ Simulado | El backend registra en Mongo. No firma transacciones. |
| **Identidad real** | ❌ Simulada | ClaveÚnica, NFC y liveness devuelven datos fabricados. |
| **PII** | ❌ Sin cifrar | RUT, email y nombre en texto plano. Hash de RUT reversible por fuerza bruta. |
| **App móvil** | ⚠️ Parcial | Contratos de API alineados y pantalla Wallet creada, pero la lectura PACE del chip no está implementada. |

---

## Hallazgos abiertos (de `AUDIT.md`)

Estos cuatro críticos siguen vivos. **Todos dependen de la Fase 1.**

- **C-1 · Sin autenticación.** Ningún endpoint la pide. Existen `python-jose`/`PyJWT` en el historial pero se retiraron: no había código que emitiera un token. Vuelven en la tarea 1.1.
- **C-2 · Minteo ficticio.** El usuario ve "MINTEANDO SBT" y un token que solo existe en MongoDB.
- **C-4 · PII en claro.** `users` guarda RUT, email y nombre sin cifrar. `generate_short_hash` es `sha256(x)[:16]` sin sal: el espacio de RUT chilenos (~30 M) se revierte en segundos. **No uses esa función para nada que vaya on-chain o a un log.**
- **C-6 · Login sin credencial.** `/api/auth/login` autentica con RUT + email, ambos datos públicos o adivinables.

Cerrados desde la auditoría inicial: C-3, C-5, A-1, A-2, A-4, A-5, A-6, A-7, A-9, M-1, M-3…M-8, M-10, M-12…M-15, y toda la serie B. Detalle en `AUDIT.md`.

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
│   ├── tests/                  82 tests con mongomock-motor
│   └── app/
│       ├── core/               config · database · security · middleware
│       ├── models/schemas.py   modelos Pydantic
│       ├── routers/
│       │   ├── auth.py         ⚠️ identidad simulada (Fase 4)
│       │   ├── deps.py         ensure_active_member — gate de gobernanza
│       │   ├── elections.py    elecciones de representantes
│       │   ├── governance.py   propuestas, votos, delegación, tesorería
│       │   ├── membership.py   minteo (delega en BlockchainService)
│       │   └── wallet.py       ⚠️ mock, se elimina en 1.7
│       └── services/
│           ├── blockchain_service.py    ⚠️ mint_sbt no toca la cadena
│           ├── governance_service.py    voting_power, ciclo de elecciones
│           └── membership_verifier.py   Mongo | on-chain (sin implementar)
├── frontend/                   React 19 + craco + Tailwind + Radix
│   └── src/
│       ├── App.js              router: / (onboarding) y /dashboard
│       ├── pages/DashboardPage.jsx   layout + secciones
│       ├── components/governance/    6 componentes, todos montados
│       ├── components/onboarding/    flujo de alta
│       ├── context/            OnboardingContext
│       ├── hooks/              useWallet · useNFC · useSBTContract
│       └── contracts/          ⚠️ ABI a mano, regenerar desde artifacts
├── contracts/                  Hardhat + OpenZeppelin 5
│   ├── contracts/DAOCiudadanaSBT.sol
│   └── test/                   29 tests, 100 % statements
└── mobile/                     React Native 0.83 + NFC
```

---

## Datos operativos

| Elemento | Valor |
|---|---|
| Contrato SBT (Sepolia) | `0x813fd379F715107b2451553d97f29408d8185f0e` |
| Owner del contrato | `0x154484aff9f6864db17141c6eec62568b8f5ac9b` (EOA) |
| `totalSupply()` | **0** |
| Backend | `https://dao-ciudadana-api.onrender.com` (Render free) |
| Frontend | `https://regal-dieffenbachia-6e9194.netlify.app` (Netlify) |
| Base de datos | MongoDB Atlas, clúster `EstadosDaos`, DB `dao_ciudadana` |

**Advertencia sobre la llave del owner:** no está en el repositorio (correcto). Sin ella no se puede mintear on-chain ni transferir la propiedad. **Confirma con el dueño del proyecto que existe y está a resguardo antes de planificar la Fase 1.** Si se perdió, hay que redesplegar — y como `totalSupply()` es 0, eso no cuesta nada. De hecho conviene: el contrato desplegado aún tiene el orden checks-effects-interactions antiguo (hallazgo N-2) y le falta `AccessControl`.

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
npm install --legacy-peer-deps
npm start

# Contratos
cd contracts
npm install
npx hardhat test              # 29 tests
```

Despliegue completo (Atlas + Render + Netlify) en [`backend/DEPLOY.md`](../backend/DEPLOY.md).

---

## Trampas concretas del código

Cosas que te van a costar tiempo si no las sabes de antemano:

1. **`generate_short_hash()` es `sha256(x)[:16]` sin sal.** Con RUT chilenos es reversible en segundos. No la uses para nada público. Rehacerla es la tarea 1.3.

2. **La ABI del frontend está escrita a mano** en `src/contracts/SBTContract.js`. Ya causó un bug de firma de evento (A-2, corregido). Genérala desde `contracts/artifacts/` en el build en vez de mantenerla; sigue pendiente.

3. **`mintMembership` es `onlyOwner`**, pero `useSBTContract.js` lo llamaría con el signer del usuario. Ese camino revertiría siempre. Es la decisión D-1: resuélvela antes de escribir código de minteo.

4. **`requirements.txt` está deliberadamente mínimo.** `python-multipart` y `pymongo` **no aparecen en ningún `import`** pero son obligatorias: la primera la exige FastAPI para `UploadFile` en `/api/auth/liveness`, la segunda la arrastra `motor` con un rango estrecho. Están documentadas en el propio archivo. No las quites por parecer huérfanas.

5. **El CI instala `requirements-dev.txt`**, no `requirements.txt`. Si mueves `pytest` de sitio, actualiza `.github/workflows/ci.yml`.

6. **`OnChainMembershipVerifier` lanza `NotImplementedError` a propósito.** No lo "arregles" devolviendo `True`: eso reintroduce exactamente el tipo de capacidad fingida que este proyecto está eliminando.

7. **La delegación no es transitiva y es una decisión, no un olvido.** Está razonada en `governance_service.py`. Si la cambias, cambia también el razonamiento.

8. **`CORS_ORIGINS` y `REACT_APP_BACKEND_URL` deben cambiarse juntas.** Si no coinciden, el navegador bloquea todo y la app aparece rota sin error visible en pantalla. Para previews de Netlify existe `CORS_ORIGIN_REGEX`.

9. **Arranque en frío:** Render free suspende el servicio tras ~15 min sin tráfico; la primera petición tarda 30–60 s. Además, si `MONGO_URL` está mal, el arranque bloquea 30 s creando índices antes de continuar con un warning.

10. **Los procesos en segundo plano no sobreviven** entre comandos en entornos de sandbox. Si un `npm install` parece colgado, comprueba que el proceso siga vivo antes de esperarlo.

---

## Decisiones pendientes — bloquean la Fase 1

No son decisiones técnicas que un agente deba tomar solo: definen custodia de llaves privadas, qué se publica de forma permanente e irreversible sobre cada ciudadano, y qué garantías reales ofrece la DAO. **Hay recomendaciones concretas con su riesgo residual en [`adr/0001-decisiones-fase-1.md`](./adr/0001-decisiones-fase-1.md)**, pendientes de aprobación.

- **D-1 · ¿Quién mintea el SBT?** Backend custodial (lo que el contrato ya permite), usuario con voucher firmado EIP-712, o relayer con meta-transacciones. Las dos últimas exigen redesplegar el contrato.
- **D-2 · ¿Qué se escribe on-chain como `identityHash`?** El esquema actual es reversible por fuerza bruta y no puede ir a un registro público inmutable.
- **D-3 · ¿La gobernanza es on-chain u off-chain?** Hoy es 100 % off-chain en MongoDB: el operador puede editar los votos. Eso no es una DAO todavía.

Cuando se tomen, déjalas escritas como ADR en `docs/`.

---

## Por dónde seguir

**Ruta crítica:** D-1 → 1.1 (autenticación) → 1.5 (minteo real). Hasta que 1.5 esté hecho, el producto no hace lo que dice hacer.

**Empezar hoy en paralelo:** el trámite de acceso al sandbox de ClaveÚnica. Es el único elemento cuyo plazo no controla el equipo, y bloquea toda la Fase 4.

**Trabajo desbloqueado que puedes tomar ya:**

- **1.8** — generar la ABI desde `artifacts/` en el build.
- **3.2 / 3.3** — votos firmados EIP-712 y nonce anti-replay. El campo `nonce` ya viaja en la petición y se ignora.
- **3.6** — tesorería real desde un Safe multisig. El backend ya responde `configured: false` honestamente.
- **3.8** — mover rate limiter y antifraude a Redis: hoy viven en memoria de proceso y se pierden al reiniciar.
- **4.2 / 4.3** — lectura PACE del chip de la cédula y polyfill de `crypto` en Metro.

---

## Cómo trabajar aquí

Las reglas completas están en [`AGENTS.md`](../AGENTS.md). Las tres que más importan:

1. **Nunca inventes datos para rellenar una interfaz.** Este repositorio ya tuvo un dashboard con 1432 miembros falsos y una tesorería con un "Grant Ethereum Foundation" ficticio sembrado en la base de datos. Si un dato no existe, devuelve `null` y muestra un estado vacío honesto.

2. **No marques nada como completo si no ejecutaste el camino real.** El precedente aquí es un `test_result.md` que documentaba un protocolo de testing elaborado sin un solo resultado registrado.

3. **Verifica contra la fuente, no contra la documentación.** El README de este repositorio llegó a afirmar cosas que el código contradecía. Si algo es on-chain, consúltalo por RPC antes de darlo por cierto.
