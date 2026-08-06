# Handoff — DAO Ciudadana

**Para:** Codex (o cualquier agente/desarrollador que retome el proyecto)
**Actualizado:** 6 de agosto de 2026 · base `0db034b`, rama local `codex/produccion-ci`
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
| **Minteo on-chain** | 🔒 Bloqueado por despliegue | El camino ZK (`/membership/mint-zk`) ya no tiene defectos conocidos: se corrigió una precondición que exigía un `MINTER_ROLE` inexistente y hacía imposible todo minteo (P-87), y la reconciliación cadena↔Mongo está implementada (P-89). Falta un despliegue compatible del contrato. `/membership/mint` **no puede mintear on-chain** y lo dice. |
| **Identidad real** | ❌ Pendiente | Demos bloqueadas en producción; Web NFC nunca se acepta como cédula verificada. |
| **PII** | 🟡 Código nuevo cifrado | Altas nuevas usan Fernet + índices HMAC. Datos legacy no fueron migrados/auditados; snapshot y migración son bloqueantes. |
| **Identidad ZK (D-2)** | 🟡 Implementada, sin proveedor | Circuito `MembershipEligibility(25)` con `recipient` ligado en la hoja; emisor con árbol Merkle de 25 niveles y firma EIP-191. Bloqueado: no existe proveedor civil que emita `identity_grant`, y la ceremonia de confianza es de una sola parte. |
| **Gobernanza MACI (D-3)** | 🟡 Circuitos listos, pipeline no | `MACICoordinator.sol` (24 tests), `maci_tally.circom` y `processMessages.circom` compilados y probados con testigo. Falta desplegar coordinador, ceremonia real y cerrar P-54. `/maci/status` mantiene `private_voting: false`. |
| **ERC-4337 (D-1)** | 🟡 No custodial, sin verificar | El backend prepara y retransmite; firma el ciudadano. Sin credenciales de Pimlico ni Safe desplegada: nunca se ejecutó un envío. Apagado por configuración; el minteo va por el relayer EOA. |
| **App móvil** | ⚠️ Experimental | TypeScript, 15 tests, lint y auditoría npm pasan localmente y tienen un job CI. Release falla cerrado sin keystore externo; faltan PACE real y build/publicación nativos reproducibles. |

---

## Sesión de orquestación 06-08-2026

Cuatro agentes trabajaron en paralelo (2 instancias de Claude en terminal +
2 subagentes headless de Antigravity). Resumen de lo logrado:

### Terminal 1 — Destrabar el minteo real (Claude, rama `fix-minter-role-and-tx-hash`)

Commit `58242c7`. Hallazgos P-87 a P-93 documentados en `AUDIT.md`:

- **(P-87 crítica)** `chain_service.py` exigía `MINTER_ROLE` que no existe en el
  contrato; toda llamada de minteo revertía en la precondición. Corregido.
- **(P-88 alta)** `MINT_MODE=onchain` llamaba a firma `mintMembership` borrada al
  migrar a ZK. Eliminado; responde 503 apuntando a `/membership/mint-zk`.
- **(P-89 alta)** Timeout de recibo provocaba doble gasto de gas. Nuevo módulo
  `mint_operations.py` persiste `tx_hash` al difundir y distingue
  `pending`/`submitted`/`confirmed`/`needs_review`.
- **(P-90)** Hashes de tx sin prefijo `0x`. Normalizado con `tx_hash_hex()`.
- **(P-91/P-92)** Rol `ROOT_MANAGER_ROLE` y estado del relayer ZK ahora visibles
  en `/health/ready` bajo `minting.zk_relayer`.
- **(P-93 alta)** Job de `gitleaks` en CI (SHA fijado, historial completo).
  Verificado: verde con el historial actual, rompe al plantar un secreto.

Suite final: **524 tests verdes** (los fallos son de la pasada paralela NFC).

### Terminal 2 — Autenticación pasiva ICAO (Claude, `/goal` activo ~35 min)

- Implementó `passive_auth.py`, `csca_trust_store.py`, router `cedula`,
  `extract_csca_from_ldif.py` y fixtures eMRTD.
- Extrajo e inyectó 5 certificados CSCA chilenos (`.pem`) en backend y mobile.
- Actualizó `.gitignore` para versionar certificados CSCA públicos del PKD.
- Actualizó `readiness.py` para exponer `passive_authentication` en `/health/ready`.

### Subagente Claude (headless) — Llave MACI en Sepolia

- Ejecutó `backend/scripts/generate_maci_key.py` generando el par de llaves.
- Llamó a `setCoordinatorPubKey` en Sepolia (contrato `0x1CC2...36a6`).
  Tx: `0x7b847d6d56c05794e151510e228ebf76f228697e507954b2adb2636bb8e98363`.
- Verificó que `tallyIsVerifiable()` sigue en `true` tras la actualización.

### Subagente Codex (headless) — Auditoría criptográfica Mobile

- Commit de 85 archivos de CI/CD móvil en `codex/produccion-ci`.
- Confirmó que la Tarea 1.13 (sesión HttpOnly/CSRF) ya estaba implementada.
- **Parche crítico en `bacCrypto.ts`:** `retailMac` instanciaba el cifrador JNI
  por cada bloque de 8 bytes; con datos DG2 (~20 KB) eran miles de objetos/segundo.
  Reescrito para delegar CBC completo a la capa nativa (1 sola instancia JNI).
  Eliminada variable global `ZERO_IV` susceptible a mutación.
- **Parche en `PassportReaderModule.kt`:** fuga de hilo por `Timer` sin `.cancel()`
  cuando expiraba el timeout de lectura NFC. Corregido.

### Commit consolidado

`0db034b` — `feat(core): completar autenticación pasiva ICAO, parche de memoria
JNI en Mobile y setup MACI` (30 archivos, +2377 −167).


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
│   ├── tests/                  247 tests con mongomock-motor
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

6. **`OnChainMembershipVerifier` ya consulta la cadena (ROADMAP 3.1), pero el despliegue sigue en `MEMBERSHIP_SOURCE=mongo`.** Cambiarlo a `onchain` solo tiene sentido cuando el contrato tenga membresías reales: hoy `totalSupply()` sigue en 0 y todo el mundo recibiría 403. Cuando la cadena no responde, la respuesta es **503, nunca 403** — `chain_service.has_membership` lanza `ChainReadError` en vez de devolver `False`. No lo "simplifiques" a un `except: return False`: convertiría una caída del RPC en la afirmación "esta persona no es miembro".

7. **La tesorería no le pone precio en dólares al ETH de testnet.** Si `chain_id != 1`, `total_usd_value` es `null` aunque haya proveedor de precio (`treasury_service.py`). No lo "arregles" quitando la comprobación: el ETH de Sepolia no vale nada y el panel estaría mostrando dinero inventado. Por la misma razón la respuesta declara `assets_covered: ["ETH"]` — los ERC-20 aún no se leen y el total no debe parecer completo.

8. **La delegación no es transitiva y es una decisión, no un olvido.** Está razonada en `governance_service.py`. Si la cambias, cambia también el razonamiento. Lo mismo vale para el campo `delegators` de cada papeleta: no es metadata decorativa, es lo que permite recomputar el `weight` y lo único que queda cuando alguien revoca una delegación cuyo peso su delegado ya emitió (P-61). Si lo quitas, el doble conteo vuelve en silencio.

9. **`CORS_ORIGINS` y `REACT_APP_BACKEND_URL` deben cambiarse juntas.** Si no coinciden, el navegador bloquea todo y la app aparece rota sin error visible en pantalla. `CORS_ORIGIN_REGEX` sirve solo fuera de producción; producción exige orígenes HTTPS exactos y las aliases deben redirigir al dominio canónico.

10. **Arranque en frío:** Render free suspende el servicio tras ~15 min sin tráfico; la primera petición tarda 30–60 s. Además, si `MONGO_URL` está mal, el arranque bloquea 30 s creando índices antes de continuar con un warning.

11. **Los procesos en segundo plano no sobreviven** entre comandos en entornos de sandbox. Si un `npm install` parece colgado, comprueba que el proceso siga vivo antes de esperarlo.

12. **El lock de nonce del minter es local al proceso.** Antes de escalar a varias
    instancias debe existir un coordinador distribuido. También hay que alinear el
    timeout del cliente (30 s) con la espera de recibo del backend (hasta 120 s).
    *Salida prevista:* el transporte ERC-4337 usa los nonces bidimensionales del
    EntryPoint, así que cada worker puede tomar su propia `key` sin coordinación.
    Está escrito pero sin verificar contra un bundler real.

12. **Papeleta y tally no son una escritura atómica.** El índice único evita votos
    duplicados concurrentes en propuestas, pero una caída entre insertar el voto y
    sumar el contador exige transacción o reconciliación derivada de papeletas.

12b. **El estado de un minteo lo decide la cadena, nunca un temporizador.**
    `mint_operations.py` distingue `pending` (nada difundido, reintentable) de
    `submitted` (la transacción salió; su suerte la decide la cadena). Si
    "simplificas" marcando `failed` al expirar la espera del recibo, vuelve el
    bug que costaba gas: el reintento envía una segunda transacción que revierte
    por `NullifierAlreadyUsed`. Por lo mismo, `nullifier_is_used()` y
    `transaction_outcome()` devuelven `None`/`unknown` cuando el RPC falla —
    **`None` no es `False`**: leer un corte de red como "no pasó nada" es lo que
    autoriza ese segundo envío. Las operaciones olvidadas se cierran con
    `python scripts/reconcile_mints.py sweep`; no hay barrido automático porque
    con varias instancias cada una correría el suyo contra el RPC.

13. **El backend NO firma UserOperations, y no debe hacerlo.** La Safe es del
    ciudadano y firma él con MetaMask; el servidor solo prepara, valida y
    retransmite. `SAFE_OWNER_PRIVATE_KEY` no se usa en ningún camino: tenerla
    configurada se reporta como ERROR, porque su presencia sugiere que alguien
    pretende que el servidor custodie Safes ajenas. El camino custodial que
    existió brevemente se eliminó a propósito.

14. **El coordinador MACI puede excluir mensajes mal firmados** (hallazgo P-54,
    aceptado a sabiendas para el piloto). `processMessages.circom` exige firma
    válida, así que un mensaje inválido no se puede probar y queda fuera. No
    apto para una elección vinculante hasta tener un verificador EdDSA con
    salida booleana.

15. **El JWT SIWE sigue en `localStorage`.** La CSP reduce la superficie XSS,
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

**Ruta crítica (sin cambio):** proveedor de identidad + grant → desplegar contrato
compatible → minteo idempotente → verificador on-chain → desplegar esta rama.

**Trabajo desbloqueado tras esta sesión, en orden de impacto:**

1. **Desplegar el contrato compatible en Sepolia** — `contracts/scripts/deploy.js`.
   Conceder `ROOT_MANAGER_ROLE` al relayer. `/health/ready` confirma en
   `minting.zk_relayer`. Es el paso que convierte `totalSupply()` de 0 a >0.
2. **Validar antifraude contra Redis real** — los tests usan `fakeredis[lua]`.
   Levantar Redis y repetirlos antes de producción.
3. **Anclaje poll↔propuesta on-chain (MACI D-3)** — vincular el ID de una
   encuesta MACI con el de una propuesta de la DAO. Falta para habilitar
   `private_voting: true`.
4. **Build nativo iOS** — Android está cubierto; iOS necesita CocoaPods,
   autolinking de `react-native-quick-crypto` y el bridge PACE.
5. **Ceremonia multi-parte** — los 3 circuitos ZK tienen una sola contribución
   Phase 2. Necesitan participantes independientes y beacon final.
6. **Identidad civil** — ClaveÚnica (sandbox DGD), Master List CSCA (Registro
   Civil/ICAO), CRLs y AA/CA. Bloqueado por terceros.
7. **Branch protection/ruleset en `main`** — CI informa pero no impide merges
   con checks rojos.

**Lo que ya NO bloquea (cerrado en esta sesión):**
- Minteo con `MINTER_ROLE` inexistente (P-87).
- Doble gasto de gas por timeout de recibo (P-89).
- Hashes de tx malformados (P-90).
- Secret scanning en CI (P-93).
- Llave MACI del coordinador en Sepolia.
- Fuga de memoria JNI en `bacCrypto.ts`.
- Thread leak en `PassportReaderModule.kt`.
- Autenticación pasiva ICAO (backend + mobile, sin Master List oficial).
- Sesión HttpOnly/CSRF en el frontend (Tarea 1.13).

---

## Cómo trabajar aquí

Las reglas completas están en [`AGENTS.md`](../AGENTS.md). Las tres que más importan:

1. **Nunca inventes datos para rellenar una interfaz.** Este repositorio ya tuvo un dashboard con 1432 miembros falsos y una tesorería con un "Grant Ethereum Foundation" ficticio sembrado en la base de datos. Si un dato no existe, devuelve `null` y muestra un estado vacío honesto.

2. **No marques nada como completo si no ejecutaste el camino real.** El precedente aquí es un `test_result.md` que documentaba un protocolo de testing elaborado sin un solo resultado registrado.

3. **Verifica contra la fuente, no contra la documentación.** El README de este repositorio llegó a afirmar cosas que el código contradecía. Si algo es on-chain, consúltalo por RPC antes de darlo por cierto.
· [`CLAUDE_REPORT.md`](./CLAUDE_REPORT.md) — Últimas tareas y refactorizaciones realizadas por Claude
