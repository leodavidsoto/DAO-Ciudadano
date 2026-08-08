# Handoff — DAO Ciudadana

**Para:** Codex (o cualquier agente/desarrollador que retome el proyecto)
**Actualizado:** 8 de agosto de 2026 · base `bbe06d6`, rama local `codex/produccion-ci`
**Documentos hermanos:** [`AUDIT.md`](./AUDIT.md) · [`ROADMAP.md`](./ROADMAP.md) · [`SECURITY_RUNBOOK.md`](./SECURITY_RUNBOOK.md) · [`../AGENTS.md`](../AGENTS.md)

---

## Lee esto primero

Este proyecto **parece** más terminado de lo que está. La UI es pulida y las
suites pasan, pero el servicio público sigue siendo un piloto y aún ejecuta la
versión anterior a los guardrails de esta rama.

Los cinco hechos que tienes que interiorizar antes de tocar una línea:

1. **Ya existe un despliegue compatible, y `totalSupply()` sigue en 0.** El
   `DAOCiudadanaSBT` del modelo ZK vive en
   `0x6C6C7D0ceC1b7267cB2fa146519FBF9ef6319d56` (Sepolia), verificado en
   Sourcify y con el relayer ya en `ROOT_MANAGER_ROLE`. Nadie ha minteado
   todavía. La dirección **histórica** `0x813fd3…` usa Ownable/`string`, es
   incompatible y no debe configurarse.
2. **Minteo y acciones mutantes de gobernanza exigen una sesión EIP-4361 y actuar
   como la misma wallet.** Producción también rechaza miembros demo/legacy.
3. **La identidad civil por cédula NFC ya funciona contra un documento físico**
   (07-08-2026, ver P-101 en `AUDIT.md`): Autenticación Pasiva contra ancla CSCA
   real, `identity_grant` + `membership_grant` emitidos. Lo que sigue pendiente
   es ClaveÚnica (sin credenciales), la Master List oficial, CRL/OCSP y el
   anti-replay. Web NFC nunca se acepta como cédula verificada.
4. **Un minteo con una cédula es irreversible para esa cédula.** El contrato
   nunca limpia `_usedNullifiers`, ni siquiera al revocar
   (`DAOCiudadanaSBT.sol:280`). Ver la trampa 16.
5. **Hay una llave de proveedor expuesta en el historial Git público.** Debe
   revocarse/rotarse de inmediato y revisarse su uso/facturación; no copies su valor
   desde commits antiguos.

Nada de esto es un descuido reciente: está documentado, medido y priorizado en `AUDIT.md` y `ROADMAP.md`. El proyecto avanza deliberadamente de "simulado" a "real", y va a mitad de camino.

```bash
# Compruébalo tú mismo — 5 segundos (contrato VIGENTE, no el histórico)
curl -s -X POST https://ethereum-sepolia-rpc.publicnode.com \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"eth_call","params":[{"to":"0x6C6C7D0ceC1b7267cB2fa146519FBF9ef6319d56","data":"0x18160ddd"},"latest"],"id":1}'
# result: 0x0...0  → cero SBT minteados (comprobado el 08-08-2026)
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
| **Contrato SBT** | ✅ Desplegado y verificado | AccessControl, soulbound y revocación; 31 tests. Despliegue compatible en `0x6C6C7D0c…` (Sepolia), Sourcify `exact_match`, relayer con `ROOT_MANAGER_ROLE`. `totalSupply()` = 0. La dirección histórica `0x813fd3…` es otra ABI y no debe configurarse. |
| **Gobernanza** | 🟡 Propuestas verificables | Propuestas con papeletas EIP-712, nonce único y endpoint público de reverificación. Elecciones existen, pero votar queda bloqueado en producción hasta firmar sus papeletas; falta tally transaccional. |
| **Dashboard** | ✅ Montado | `/dashboard` con 5 secciones. Router funcionando. |
| **Despliegue** | 🟡 Servicio histórico activo | La versión pública anterior responde; esta rama separa liveness/readiness y aún no fue publicada. |
| **Autenticación** | ✅ Wallet / 🟡 identidad | Challenge EIP-4361, JWT corto y gates self/active. No equivale a identidad civil. |
| **Minteo on-chain** | 🟡 Camino listo, nunca ejecutado | `/membership/mint-zk` no tiene defectos conocidos (P-87 y P-89 cerrados) y el contrato ya está desplegado. Nadie ha minteado todavía. `/membership/mint` **no puede mintear on-chain** y lo dice: sus tres modos están bloqueados en producción. |
| **Identidad real** | 🟡 Cédula NFC sí, el resto no | Cédula chilena por NFC probada contra documento físico (P-97, P-101). ClaveÚnica, liveness y RUT/email siguen siendo demos y devuelven 503 en producción. Web NFC nunca se acepta como cédula verificada. Falta anti-replay, Master List oficial y CRL/OCSP. |
| **Frontend web** | 🟡 Sano, sin identidad civil | 90 tests verdes (`craco test`, 07-08-2026). Mintea por ERC-4337 + Safe. Su única vía de identidad es ClaveÚnica, que no está configurada: **hoy el onboarding web no puede completarse en producción.** |
| **PII** | 🟡 Código nuevo cifrado | Altas nuevas usan Fernet + índices HMAC. Datos legacy no fueron migrados/auditados; snapshot y migración son bloqueantes. |
| **Identidad ZK (D-2)** | 🟡 Implementada, sin proveedor | Circuito `MembershipEligibility(25)` con `recipient` ligado en la hoja; emisor con árbol Merkle de 25 niveles y firma EIP-191. Bloqueado: no existe proveedor civil que emita `identity_grant`, y la ceremonia de confianza es de una sola parte. |
| **Gobernanza MACI (D-3)** | 🔴 Tally roto | `MACICoordinator.sol` (24 tests), `maci_tally.circom` y `processMessages.circom` compilados. **Las señales públicas del contrato y las del circuito no coinciden**, así que una prueba auténtica es rechazada por `publishTally` (`contracts/test/MACI.test.js:264`). Falta además desplegar coordinador, ceremonia real y cerrar P-54. `/maci/status` mantiene `private_voting: false`, y eso es un hecho, no un ajuste. |
| **ERC-4337 (D-1)** | 🟡 No custodial, sin verificar | El backend prepara y retransmite; firma el ciudadano. Sin credenciales de Pimlico ni Safe desplegada: nunca se ejecutó un envío. Apagado por configuración; el minteo va por el relayer EOA. |
| **App móvil** | ⚠️ Lee cédulas, no mintea | 76 tests verdes (07-08-2026). Lectura NFC probada contra cédula real en Android; iOS sin probar físicamente. **No puede mintear en producción** (P-102): `apiService.mintSBT` llama a `/membership/mint`, que está bloqueado. Release falla cerrado sin keystore externo. P-98 (BouncyCastle 1.64 → CVE-2023-33201) sigue abierto: no publicar APK así. |

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


## Sesión 07/08-08-2026 — primera alta civil y tres frentes en paralelo

### Lo que se cerró

- **P-101 (crítica).** El RUN se leía del campo opcional equivocado de la MRZ.
  Corregido con `MRZ.national_number`. Con eso, el camino de identidad civil
  funcionó de extremo a extremo contra una cédula chilena física.
- **`production_ready` era inalcanzable por construcción** (`046b570`). `ready`
  exigía que `/membership/mint` estuviera disponible, pero ese endpoint tiene
  sus tres modos bloqueados en producción a propósito. Ningún despliegue podía
  dar verde. Ahora en producción se exige el relayer ZK, que es el camino real.
- **Documentación de despliegue:** [`PRODUCCION_SEPOLIA.md`](./PRODUCCION_SEPOLIA.md)
  enumera cada variable que falta con la línea de `readiness.py` que la exige.

### Tres encargos en curso, uno por terminal

Cada uno tiene su prompt de arranque autocontenido y toca directorios distintos
para no pisarse:

| Encargo | Prompt | Ficheros | Estado |
|---|---|---|---|
| Minteo móvil | [`PROMPT_MINTEO_MOVIL.md`](./PROMPT_MINTEO_MOVIL.md) | `mobile/src/`, `backend/app/routers/membership.py` | En curso |
| Anti-replay de la cédula | [`PROMPT_ANTI_REPLAY.md`](./PROMPT_ANTI_REPLAY.md) | `backend/app/services/`, módulos nativos | En curso |
| D-3 · tally MACI | [`PROMPT_MACI_TALLY_D3.md`](./PROMPT_MACI_TALLY_D3.md) | `circuits/`, `contracts/` | En curso |

**Se rozan en `mobile/src/services/nfcService.ts` y en los lectores nativos.**
Ya pasó en la sesión anterior que dos agentes se pisaran esos archivos y
dejaran 16 tests rojos. Coordina ahí.

### Decisiones tomadas en esta sesión

- **El móvil mintea por el relayer** (`/membership/mint-zk`), no por ERC-4337.
  Es una enmienda a la letra del ADR-001 —ver
  [`ADR-001`](./adr/001-arquitectura-vanguardia.md), "Enmienda 1"—, forzada por
  que el camino ERC-4337 no tiene credenciales de Pimlico ni Safe desplegada y
  nunca ejecutó un envío.
- **La prueba Groth16 se genera en un WebView local con snarkjs.** Hermes no
  ejecuta WASM; `@iden3/react-native-rapidsnark` está en `0.0.1-beta.2` y ni
  siquiera calcula el testigo. El circuito es pequeño (6.658 restricciones no
  lineales, wasm 2,1 MB, zkey 5,9 MB), así que el WebView debería bastar —
  pero **es una medición pendiente, no una predicción**: hay que cronometrarlo
  en un teléfono real y publicar el número.

### Deuda que se pierde si nadie la rescata

El trabajo del **MACI relayer** sigue sin commitear en el worktree
`subagent-MACI-Relayer-Engineer-…` (`a8e5cb9`). Si alguien limpia ese worktree,
`maci_relayer.py`, sus tests y los cambios de `governance.py` desaparecen.
Urgente por frágil, no por difícil. Lo mismo, con menos riesgo, para
`5f2a315` (E2E Playwright).

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

### Inventario on-chain (Sepolia, comprobado el 06-08-2026)

| Elemento | Valor |
|---|---|
| **`DAOCiudadanaSBT` vigente** | `0x6C6C7D0ceC1b7267cB2fa146519FBF9ef6319d56` |
| **`Groth16Verifier`** | `0x179e2bbfBe6dCFA610a5a30B81d5A6C0eb19dDd7` |
| `membershipScope()` | `6514418762376236255077166818315585639416036470302962028908681129483188802648` |
| `totalSupply()` / `totalIssued()` | **0** / **0** — aún no se ha minteado ninguno |
| `paused()` | `false` |
| Admin / relayer / minter | `0x118d2C9eec35bdfc2C84B5A33299AcCc16Ed60d4` (EOA, **una sola** para los cuatro roles) |
| Emisor de credenciales | `0x178b15422116bCD1b9682FF311F7FA0389186Ba6` |
| Verificación del código | Sourcify `exact_match` en creación y runtime, ambos contratos |
| Contrato histórico incompatible (solo evidencia) | `0x813fd379F715107b2451553d97f29408d8185f0e` — **no configurar** |

El bytecode de ambas direcciones se comparó contra los artifacts compilados
—enmascarando los `immutable`, que se hornean al desplegar— y coincide con la
versión vigente del repositorio.

**Dos cosas que este despliegue todavía no cumple**, y que no son opcionales
antes de admitir ciudadanía real:

1. **Una sola EOA concentra `DEFAULT_ADMIN_ROLE`, `ROOT_MANAGER_ROLE`,
   `PAUSER_ROLE` y `REVOKER_ROLE`, y además es el relayer.** El contrato está
   escrito esperando un Safe/multisig como `admin` (lo dice su propio
   docstring). Comprometer esa llave es comprometer el padrón entero: permite
   aprobar raíces arbitrarias, pausar y revocar. Separar los roles exige mover
   la custodia, no redesplegar.
2. **La ceremonia del verificador es de una sola parte.**
   `circuits/artifact-manifest.json` declara `productionReady: false` y
   `trustedSetup: "single-host-development-integration"`. Quien tenga el
   *toxic waste* puede fabricar pruebas válidas. Sirve para el piloto en
   testnet; **no** para mainnet ni para membresías vinculantes.

`membershipScope` se deriva de `address(this)`: **redesplegar cambia el scope e
invalida toda credencial ya emitida.** No se redespliega sin migrar.

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

3. **`MINTER_ROLE` no existe en este contrato.** El rol que hay que mirar es
   `ROOT_MANAGER_ROLE`, y ya lo tiene el relayer. Exigir `MINTER_ROLE` fue el
   bug P-87, que hacía imposible todo minteo; no lo reintroduzcas guiándote por
   documentación vieja. La reconciliación recibo↔Mongo sí está implementada
   (P-89, `mint_operations.py`).

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

16. **Revocar un SBT no libera el nullifier, y eso es deliberado.**
    `executeRevocation` (`DAOCiudadanaSBT.sol:261`, requiere `REVOKER_ROLE`)
    quema el token, libera la wallet y decrementa el suministro activo, pero
    `_usedNullifiers` **nunca** se limpia — el propio contrato lo dice en la
    línea 280. Consecuencia práctica: **cada cédula sirve para exactamente un
    minteo por despliegue, y ni el admin puede deshacerlo.** No es un descuido:
    si se pudiera limpiar, quien tenga `REVOKER_ROLE` fabricaría membresías
    ilimitadas desde una sola cédula, que es justo el ataque que el nullifier
    cierra. Planifica las pruebas de alta en consecuencia: para repetirlas hace
    falta otra cédula o un despliegue nuevo. El flujo de revocación es en dos
    pasos con `REVOCATION_COOLDOWN = 3 days` entre `requestRevocation` y
    `executeRevocation`.

17. **La app móvil no comparte camino de minteo con la web.** La web usa
    ERC-4337 + Safe (`prepare-mint`/`submit-mint`); el móvil llamaba a
    `/membership/mint`, que está bloqueado en producción (P-102). Si tocas uno
    de los dos, no supongas que el otro hace lo mismo.

---

## Decisiones pendientes — bloquean la Fase 1

No son decisiones técnicas que un agente deba tomar solo: definen custodia de llaves privadas, qué se publica de forma permanente e irreversible sobre cada ciudadano, y qué garantías reales ofrece la DAO. Detalle completo en `ROADMAP.md`.

- **D-1 · ¿Quién mintea el SBT?** Resuelto en ADR-001 como ERC-4337, y
  enmendado el 08-08-2026: el móvil va por el relayer porque ERC-4337 está
  bloqueado por credenciales que no existen. El camino custodial se eliminó y
  no vuelve. Queda pendiente ratificar quién paga el gas a largo plazo y que el
  admin del contrato deje de ser la misma EOA que el relayer.
- **D-2 · ¿Qué se escribe on-chain como `identityHash`?** Las altas nuevas usan HMAC-SHA256 de 32 bytes, pero falta ratificar el diseño, llevar el pepper a KMS y migrar/purgar el esquema legacy reversible.
- **D-3 · ¿La gobernanza es on-chain u off-chain?** Las propuestas ya usan firmas EIP-712 off-chain; falta decidir el modelo definitivo, firmar elecciones y hacer el tally reconstruible/transaccional.

Cuando se tomen, déjalas escritas como ADR en `docs/`.

---

## Por dónde seguir

**Ruta crítica actualizada (08-08-2026):** la identidad civil por cédula y el
contrato desplegado ya no bloquean. Lo que queda entre el piloto y una demo son
**dos cosas**: que el móvil pueda mintear, y que la cédula resista un replay.
El resto es configuración, trámites con terceros o decisiones tuyas.

**En orden de impacto:**

1. **Minteo móvil** (P-102) — en curso, `PROMPT_MINTEO_MOVIL.md`.
2. **Anti-replay de la cédula** — en curso, `PROMPT_ANTI_REPLAY.md`. Hoy quien
   consiga los bytes del SOD y los DG puede reenviarlos y obtener un grant de
   ese titular: la Autenticación Pasiva prueba que Chile firmó los datos, no
   que el chip esté presente.
3. **D-3 · tally MACI** — en curso, `PROMPT_MACI_TALLY_D3.md`.
4. **Configuración de producción** — enumerada variable por variable en
   [`PRODUCCION_SEPOLIA.md`](./PRODUCCION_SEPOLIA.md), con la línea de
   `readiness.py` que exige cada una.
5. **P-98 · BouncyCastle 1.64** — mide si volver a 1.74 rompe de verdad
   `PACEKeySpec.createMRZKey` en un teléfono. Nadie lo midió; se bajó y con eso
   volvió CVE-2023-33201.
6. **Ceremonia multi-parte** — los 3 circuitos ZK tienen una sola contribución
   Phase 2. Necesitan participantes independientes y beacon final. Es el mismo
   problema que hace que el minteo móvil, aun funcionando, **no sea
   "producción"**.
7. **Rescatar el worktree del MACI relayer** (`a8e5cb9`) antes de que alguien lo
   limpie.
8. **Identidad civil de terceros** — ClaveÚnica (sandbox DGD), Master List CSCA
   (Registro Civil/ICAO), CRLs. Bloqueado por terceros.
9. **Onboarding web sin identidad civil** — la web solo tiene ClaveÚnica. O se
   configura, o se le da un camino de cédula, o el alta es solo por móvil.
10. **Branch protection/ruleset en `main`** — CI informa pero no impide merges
    con checks rojos.
11. **Separar roles del contrato** — una sola EOA es admin, root manager, pauser,
    revoker y relayer. El contrato espera un Safe como admin.

**Lo que ya NO bloquea:**
- Lectura de la cédula chilena por NFC: formato del CAN (P-97) y posición del
  RUN en la MRZ (P-101), ambos descubiertos contra un documento físico.
- `production_ready` inalcanzable por construcción (`046b570`).
- Anclaje poll↔propuesta on-chain en MACI (D-3, P-94). **Ojo: esto no habilitó
  `private_voting`, que sigue en `false` porque el tally está roto.**
- Despliegue real del SBT en Sepolia, verificado en Sourcify, con
  `ROOT_MANAGER_ROLE` asignado al relayer zk.
- Build nativo iOS con autolinking de `react-native-quick-crypto` y corrección de llave CAN en bridge PACE.
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
