# Auditoría técnica — DAO Ciudadana

> **Estado vigente:** lee primero “Hallazgos nuevos (cuarta pasada,
> 01-08-2026)” al final. El resumen y las secciones anteriores se conservan
> como registro histórico del commit `f2902ca` y no describen el HEAD actual.

**Fecha:** 26 de julio de 2026
**Commit auditado:** `f2902ca` (`main`) — *Add React Native mobile app with NFC chip reading support*
**Alcance:** backend FastAPI, contrato `DAOCiudadanaSBT.sol`, frontend React, app móvil React Native, despliegue.
**Método:** lectura completa del código, verificación on-chain contra Sepolia vía RPC público, sondeo del backend en producción.

> 📌 **Nota:** este informe describe el commit `f2902ca`. Varios hallazgos de higiene
> (M-5, M-6, M-7, M-8, M-12, M-13, B-1, B-2, B-3, B-4) y de datos inventados (A-9 parcial:
> las cifras fabricadas se eliminaron — incluida la siembra de 1432/32 en el estado inicial de
> `frontend/src/context/OnboardingContext.jsx` —; las fuentes reales de tesorería llegan en
> Fase 3.6) fueron abordados en la **Fase 0** (rama `fase-0-higiene-y-verdad`). C-5 (tests del
> contrato) se cerró con la suite de `contracts/test/`. El estado vigente de
> C-1…C-4/C-6 se actualiza en los hallazgos P-* al final.
>
> 📌 **Nota (tercera pasada, 26-07-2026) — gobernanza:** cerrados **C-3**, **A-4**, **A-5**
> y **M-10**.
>
> - **C-3**: todos los endpoints mutantes de gobernanza (crear propuesta, votar, delegar,
>   convocar elección, postularse, votar en elección) exigen membresía activa vía
>   `MembershipVerifier` (`backend/app/services/membership_verifier.py`). La implementación
>   Mongo es la fuente de verdad hasta que exista el minteo on-chain;
>   `OnChainMembershipVerifier` está deliberadamente **sin implementar** y lanza
>   `NotImplementedError` en vez de simular. Se elige con `MEMBERSHIP_SOURCE`.
> - **A-5**: `voting_power` = 1 + delegadores que sean miembros activos. Las delegaciones no
>   son transitivas y quien delegó no puede votar directamente mientras la delegación siga
>   vigente. El peso se persiste en el voto y se suma a los contadores.
> - **A-4**: `fraud_detector` estaba importado y nunca se llamaba; ahora `check_rapid_voting`
>   se ejecuta al votar y `check_delegation_chain` al delegar.
> - **M-10**: la UI de gobernanza dejó de ser código muerto. `App.js` tiene router y
>   `/dashboard` monta propuestas, elecciones, delegación y tesorería.
> - **Nuevo módulo**: elecciones de representantes (candidaturas, escaños, mandatos,
>   resultados), con los mismos controles de membresía y peso de voto.
> - **A-9 (resto)**: `TreasuryDashboard` ya no muestra `$0` con badge "Activo" cuando el
>   backend responde `configured: false`; distingue *sin configurar* de *vacía*.
>
> Siguen abiertos los críticos **C-1**, **C-2**, **C-4** y **C-6** (autenticación, minteo real
> on-chain y tratamiento de PII), todos dependientes de la Fase 1.

> 📌 **Nota (segunda pasada, 26-07-2026):** la Fase 2 quedó completa — tests de backend con
> `pytest` + `mongomock` (2.2), `backend_test.py` y `test_result.md` eliminados (2.3 / M-14),
> CI en GitHub Actions con backend, contratos, slither y build del frontend (2.4, 2.5), y
> `requirements.txt` con versiones fijadas (2.6). Además: M-1 corregido (`asyncio.sleep`),
> M-4 corregido (el router de membership delega en `BlockchainService`, con validación de
> duplicados e índice único en `members.wallet_address` — cierra también la carrera de M-3),
> A-6 y A-7 corregidos (contratos de `apiService.ts` alineados y pantalla `Wallet` creada),
> y el mint dejó de fabricar `tx_hash`: devuelve `null` hasta que exista minteo real (1.5).
> Ver «Hallazgos nuevos» al final.

---

## Resumen ejecutivo

El proyecto tiene una arquitectura correcta y bien organizada: separación limpia por capas en el backend, un contrato soulbound razonablemente diseñado, una UI cuidada y una app móvil con andamiaje completo. El problema no es la estructura, es que **la funcionalidad central está simulada de punta a punta y el sistema no tiene autenticación**.

Los tres hechos que definen el estado real:

1. **`totalSupply()` del contrato en Sepolia devuelve 0.** Nunca se ha minteado un SBT on-chain. Todas las "membresías" existen solo como documentos en MongoDB, con hashes de transacción inventados.
2. **Ningún endpoint de la API exige autenticación.** Cualquiera puede crear membresías, votar y crear propuestas con un `curl`.
3. **El backend de producción está suspendido** (Render devuelve 503) y el frontend en Netlify apunta a esa URL.

Se identificaron **6 hallazgos críticos, 9 altos, 15 medios y 8 bajos**.

**Recomendación:** no exponer este sistema a usuarios reales hasta cerrar los hallazgos críticos. El riesgo mayor no es técnico sino reputacional y legal: el producto declara verificación de identidad estatal y membresía blockchain, y hoy no entrega ninguna de las dos.

---

## Verificación on-chain (evidencia)

Consultas a `0x813fd379F715107b2451553d97f29408d8185f0e` en Sepolia:

| Consulta | Resultado | Lectura |
|---|---|---|
| `eth_getCode` | bytecode presente | El contrato sí está desplegado |
| `totalSupply()` | `0` | **Cero SBT minteados en toda la vida del contrato** |
| `owner()` | `0x154484aff9f6864db17141c6eec62568b8f5ac9b` | EOA única con control total |
| `paused()` | `false` | Operativo |

Sondeo a `https://dao-ciudadana-api.onrender.com`: HTTP 503, *"This service has been suspended by its owner."*

---

## CRÍTICOS

### C-1 · La API no tiene autenticación en ningún endpoint

`backend/app/routers/membership.py:19-20` — `POST /api/membership/mint` acepta `wallet_address`, `assurance_level` y `doc_hash` sin verificar que el solicitante haya completado verificación alguna. No comprueba duplicados, no valida el formato de la dirección, no exige token.

No existe emisión de JWT en ninguna parte del código, pese a que `requirements.txt` incluye `python-jose`, `PyJWT` y `passlib`. El interceptor de axios (`frontend/src/lib/api.js:23`) lee `localStorage.auth_token`, valor que nunca se escribe.

**Explotación:** un solo `curl` crea membresías ilimitadas. El mismo patrón aplica a `/api/governance/proposals`, `/api/governance/vote` y `/api/governance/delegate`.

**Impacto:** el padrón ciudadano completo es escribible por cualquier persona en internet.

---

### C-2 · El minteo es ficticio y se presenta al usuario como real

`backend/app/routers/membership.py:32-35` asigna `token_id = count_documents() + 1` y genera el hash de transacción con `generate_mock_tx_hash()` (`backend/app/core/security.py:71`), que devuelve `0xM1NT` + 8 hex aleatorios — ni siquiera tiene la longitud de un hash real.

`frontend/src/components/onboarding/MintStep.jsx:12-18` muestra las etapas *"FIRMANDO CONTRATO"*, *"MINTEANDO SBT"*, *"CONFIRMANDO EN BLOCKCHAIN"* y luego un badge `TX: 0xM1NT…` con confeti.

**Confirmado on-chain:** `totalSupply() == 0`. Nada de esto ha tocado la blockchain nunca.

**Impacto:** el usuario recibe una afirmación falsa y verificable sobre un registro público. Para un proyecto de identidad civil esto es el riesgo más serio del inventario.

---

### C-3 · Se puede votar sin ser miembro

`backend/app/routers/governance.py:237` — `cast_vote` valida que `voter_address` tenga formato de dirección Ethereum y que no haya votado antes en esa propuesta. **No consulta el contrato (`hasMembership`) ni la colección `members`.**

**Explotación:** generar N direcciones aleatorias válidas y emitir N votos. El costo de un ataque Sybil es cero.

Lo mismo aplica a `create_proposal` (`governance.py:146`) y `delegate_vote` (`governance.py:331`).

---

### C-4 · PII en texto plano y hash de RUT reversible por fuerza bruta

- `backend/app/routers/auth.py:310` — la colección `users` almacena RUT, email, nombre y apellido sin cifrar.
- `backend/app/routers/auth.py:51` — `IdentityEvent.user_id` guarda el RUT en claro.
- `backend/app/core/security.py:56` — `generate_short_hash()` es `sha256(dato)[:16]`, **sin sal ni pepper**.

El espacio de RUT chilenos válidos es de unos 30 millones de valores. Precomputar `sha256` de todos toma segundos en hardware común. Un hash de RUT sin sal **no es anonimización**.

Si ese hash se escribe on-chain como `identityHash`, queda público, permanente e inmutable — y cualquiera puede revertirlo a un RUT.

**Contradicción documental:** `README.md` afirma *"Solo hashes criptográficos on-chain"* y *"Datos PII nunca expuestos"*.

**Riesgo regulatorio:** tratamiento de datos personales bajo Ley 19.628 y la Ley 21.719 de Protección de Datos Personales, sin cifrado en reposo, sin política de retención y sin base de licitud documentada.

---

### C-5 · El contrato no tiene ni un solo test

`contracts/test/` no existe. `hardhat.config.js:38` apunta a `./test`; `contracts/package.json` declara `test` y `test:coverage`, que hoy no ejecutan nada.

Sin cobertura: la lógica soulbound (`_update`), la unicidad por wallet, la reutilización de `identityHash`, el cooldown de revocación y el pausado. Son exactamente las invariantes que sostienen el valor del token.

---

### C-6 · El login no requiere ninguna credencial secreta

`backend/app/routers/auth.py:339` — `POST /api/auth/login` autentica con **RUT + email**. Ambos son datos conocidos o adivinables; el RUT circula en facturas, contratos y padrones públicos.

No hay contraseña, ni OTP, ni firma de wallet, ni verificación de correo. Conocer el RUT y el email de una persona basta para suplantarla.

---

## ALTOS

### A-1 · Contradicción arquitectónica en el minteo
`DAOCiudadanaSBT.sol:97` — `mintMembership` es `onlyOwner`. `frontend/src/hooks/useSBTContract.js:76` lo invoca con el signer del usuario. Toda llamada revertiría con `OwnableUnauthorizedAccount`. Además `useSBTContract` **no se importa en ningún componente** — es código muerto. No hay una decisión tomada sobre si el minteo es client-side o server-side.

### A-2 · ABI del frontend desincronizada con el contrato desplegado
Evento real (`contracts/artifacts/.../DAOCiudadanaSBT.json`):
`MembershipMinted(address indexed member, uint256 indexed tokenId, string assuranceLevel, uint256 timestamp)`

Declarado en `frontend/src/contracts/SBTContract.js:78`:
`MembershipMinted(address indexed member, uint256 tokenId, string assuranceLevel)`

Firmas distintas → `topic0` distinto → `parseLog` nunca hace match → `tokenId` siempre `null`. Bug real que aparecería en cuanto el minteo on-chain se active.

### A-3 · La detección de vida no bloquea nada
`backend/app/routers/auth.py:202-203` devuelve `ok=True` con cualquier score, incluso 0.1. `frontend/src/context/OnboardingContext.jsx:98` avanza de paso sin comparar contra un umbral. Sin `EMERGENT_LLM_KEY` el backend devuelve **0.85 fijo** (`auth.py:135`, `auth.py:186`). Además `emergentintegrations` no figura en `requirements.txt`, así que en producción siempre cae al valor simulado.

### A-4 · El módulo antifraude está importado y nunca se ejecuta
`governance.py:22-25` importa `fraud_detector`, `generate_nonce` y `hash_vote_data`. Ninguno se llama. El campo `nonce` de `VoteRequest` (`governance.py:118`) se recibe y se descarta — el comentario dice *"For replay protection"* pero no hay protección de replay.

### A-5 · La delegación de voto no tiene efecto
`governance.py:399` calcula `voting_power` y lo devuelve por API, pero `cast_vote` siempre incrementa en 1. Delegar es una operación puramente cosmética.

### A-6 · La app móvil es incompatible con la API en todos sus llamados

| Llamada móvil | Envía | Backend espera | Resultado |
|---|---|---|---|
| `register` | `firstName`, `lastName` | `nombre`, `apellido` | 422 |
| `login` | `rut`, `password` | `rut`, `email` | 422 |
| `verifyNFC` | body con `serialNumber` | sin parámetros | body ignorado |
| `mintSBT` | `address`, `identityHash` | `wallet_address`, `doc_hash` | 422 |
| `getMembershipStatus` | `/membership/status/{addr}` | `/membership/member/{addr}` | 404 |

`mobile/src/services/apiService.ts:48` además espera `response.data.token`, que el backend nunca emite. **La app móvil no funciona contra la API actual en ningún flujo.**

### A-7 · Pantalla `Wallet` inexistente pero navegable
`mobile/src/screens/HomeScreen.tsx:71` y `SuccessScreen.tsx:30` hacen `navigation.navigate('Wallet')`. El Stack solo registra `Home`, `Scan` y `Success` (`mobile/App.tsx:55-69`) → error en tiempo de ejecución.

### A-8 · La lectura NFC de la cédula no está implementada
`mobile/src/services/nfcService.ts:150` deriva claves BAC y a continuación tiene `// TODO: Implement full PACE/BAC protocol`; devuelve todos los campos de identidad vacíos. `ScanScreen.tsx:93` llama `readSimpleTag()`, que usa **NDEF** — la cédula chilena es ISO-DEP con PACE, nunca responderá a NDEF. Lo único que se obtiene es el UID de la etiqueta, que en documentos electrónicos es aleatorio por sesión y no sirve como identificador.

Adicional: el módulo importa `createHash`/`createCipheriv` de `crypto` de Node sin polyfill; `metro.config.js` no define ningún `resolver.extraNodeModules` pese a que `react-native-quick-crypto` está en dependencias → fallo de bundling.

El commit más reciente se titula *"NFC chip reading support"*, pero la funcionalidad es un esqueleto.

### A-9 · Datos inventados presentados como métricas reales
- `dashboard.py:34` — `max(total_members, 1432)` y `max(recent_joins, 32)`: si hay 3 miembros reales, la UI muestra 1432.
- `governance.py:420` — `TREASURY_BALANCE` hardcodeado: 12.5 ETH, 25 000 USDC, 15 000 DAI.
- `governance.py:427-462` — `ensure_sample_transactions()` **inserta automáticamente** transacciones ficticias en la base, incluida *"Grant Ethereum Foundation — 10 000 USDC"*.
- `governance.py:302` — `participation_rate: 0.75` fijo. `governance.py:545` — `runway_months: 18` fijo.
- `governance.py:474` — precio del ETH hardcodeado en 2000 USD.

Una tesorería inventada en un proyecto que pide confianza cívica es un problema de integridad, no de UX.

---

## MEDIOS

| ID | Hallazgo | Ubicación |
|---|---|---|
| M-1 | `time.sleep()` bloqueante dentro de middleware async: congela el event loop para **todas** las peticiones concurrentes | `security_middleware.py:65` |
| M-2 | Rate limiter y antifraude en memoria de proceso: se pierden al reiniciar y no funcionan con múltiples workers ni instancias | `security_middleware.py:27`, `security.py:77` |
| M-3 | `token_id = count + 1`: colisiona tras revocaciones y sufre condición de carrera bajo concurrencia. Sin índice único en `wallet_address` | `membership.py:32` |
| M-4 | `BlockchainService.mint_sbt` sí valida duplicados, pero el router no lo usa: lógica duplicada y divergente | `membership.py` vs `blockchain_service.py:49` |
| M-5 | El handler global de excepciones devuelve `str(exc)` al cliente: fuga de detalles internos | `main.py:100` |
| M-6 | `CORS_ORIGINS` por defecto `*` junto a `allow_credentials=True`: combinación inválida e insegura si falta la variable | `config.py:24`, `main.py:88` |
| M-7 | `DEBUG: bool = True` por defecto → `/docs` y `/redoc` expuestos si no se define la variable de entorno | `config.py:17` |
| M-8 | `backend/server.py` (366 líneas) es una app legacy duplicada, no usada, que lee `os.environ['MONGO_URL']` en tiempo de import | `backend/server.py` |
| M-9 | `totalSupply()` devuelve `_nextTokenId` y no decrece al quemar: sobrecuenta miembros tras revocaciones | `DAOCiudadanaSBT.sol:261` |
| M-10 | UI de gobernanza huérfana: `ProposalsList`, `TreasuryDashboard`, `VoteDelegation` y `CreateProposalModal` no se renderizan en ninguna parte; `App.js` no tiene router pese a incluir `react-router-dom` | `frontend/src/App.js` |
| M-11 | Centralización: el owner del contrato es una EOA que puede revocar cualquier membresía y pausar el sistema. Una DAO cuyo padrón depende de una llave privada | `DAOCiudadanaSBT.sol:86` |
| M-12 | No existe `.env.example` en ningún módulo: el proyecto no se puede levantar sin adivinar variables | raíz, `backend/`, `frontend/` |
| M-13 | 46 archivos de build de Hardhat commiteados (`artifacts/` y `cache/`), incluido un `build-info` de 2,2 MB | `contracts/artifacts/`, `contracts/cache/` |
| M-14 | `test_result.md` contiene solo la plantilla del protocolo, sin un solo resultado. `backend_test.py` apunta a un host de preview de Emergent que ya no existe | `test_result.md`, `backend_test.py:11` |
| M-15 | Backend de producción suspendido (503) mientras `netlify.toml` y la app móvil siguen apuntando a esa URL | Render / `frontend/netlify.toml:8` |

---

## BAJOS

| ID | Hallazgo | Ubicación |
|---|---|---|
| B-1 | `.gitconfig` commiteado con la identidad del agente generador (`github@emergent.sh`) | `.gitconfig` |
| B-2 | `.emergent/emergent.yml` con `job_id`: residuo del andamiaje de generación | `.emergent/` |
| B-3 | README desactualizado: describe `contracts/` como *"(Future) Smart contracts"* y Polygon como red, cuando ya hay despliegue en Sepolia | `README.md:63` |
| B-4 | README afirma capacidades que la auditoría no respalda (*"Rate limiting implementado"*, *"Datos PII nunca expuestos"*) | `README.md:108-109` |
| B-5 | CSP con `unsafe-inline` y `unsafe-eval`, lo que anula buena parte de su valor | `security_middleware.py:105` |
| B-6 | `isChecksumAddress()` no valida EIP-55: solo comprueba si hay alguna mayúscula | `frontend/src/lib/security.js:19` |
| B-7 | `generate_mock_address()` produce direcciones de longitud inválida (`0x…C1TY`) que el propio validador del backend rechazaría | `security.py:66` |
| B-8 | Dependencias sin fijar en el backend (`>=`) en un proyecto con requisitos de reproducibilidad | `backend/requirements.txt` |

---

## Contradicciones entre documentación y código

| El README afirma | La realidad |
|---|---|
| "Solo hashes criptográficos on-chain" | Nada se ha escrito on-chain; los hashes off-chain son SHA-256 sin sal, reversibles |
| "Datos PII nunca expuestos" | RUT, email y nombre en texto plano en MongoDB |
| "Rate limiting implementado" | Existe, pero en memoria de proceso y con `sleep` bloqueante |
| "SBT no transferible" | Correcto — es la única afirmación de seguridad que el código respalda |
| "contracts/ — (Future) Smart contracts" | Ya desplegado en Sepolia |

---

## Lo que sí está bien

Vale la pena registrarlo, porque define qué conservar:

- **El contrato está bien diseñado.** Soulbound aplicado en `_update` (no en hooks obsoletos), errores personalizados en vez de strings, `ReentrancyGuard`, `Pausable`, revocación con cooldown de 3 días y `_usedIdentityHashes` que no se limpia al quemar para impedir re-registro. Es trabajo sólido.
- **La estructura del backend es limpia:** `core` / `models` / `routers` / `services` correctamente separados, Pydantic v2, validadores en los modelos de gobernanza con límites de longitud y normalización de direcciones.
- **La validación de RUT con dígito verificador** (`auth.py:220`) está correctamente implementada, módulo 11 incluido.
- **La integración real de MetaMask** (`useWallet` + `WalletStep`) funciona y maneja los casos de MetaMask ausente, cambio de red y reconexión.
- **La UI tiene un nivel de acabado alto** y una identidad visual coherente.

El proyecto no necesita reescribirse. Necesita que lo simulado se vuelva real y que se le ponga una capa de autenticación.

---

## Hallazgos nuevos (segunda pasada, 26-07-2026)

| ID | Hallazgo | Ubicación | Severidad | Estado |
|---|---|---|---|---|
| N-1 | `Platform.OS` usado sin importar `Platform` → crash en runtime al renderizar la pantalla de éxito | `mobile/src/screens/SuccessScreen.tsx:187` | Alta (móvil) | ✅ Corregido |
| N-2 | Violación de checks-effects-interactions en `mintMembership`: `_memberTokens`, `_identityHashes` y `_usedIdentityHashes` se escribían **después** de `_safeMint`, cuyo callback `onERC721Received` permite a un receptor contrato observar estado de membresía a medio actualizar (slither `reentrancy-no-eth`) | `contracts/contracts/DAOCiudadanaSBT.sol:116-122` | Media | ✅ Corregido (efectos antes de la interacción + test con `ReceiverProbe`). Nota: el contrato **desplegado** en Sepolia aún tiene el orden antiguo; se corrige con el redeploy ya previsto en 1.6 |
| N-3 | `FraudDetector.check_delegation_chain` recorría el mapa `delegate → [delegators]` en la dirección equivocada y no detectaba un ciclo real `a→b` + `b→a` | `backend/app/core/security_middleware.py`; `backend/app/routers/governance.py` | Media | ✅ Corregido: recorre delegaciones salientes, valida el ciclo autoritativo contra MongoDB y los controles están cableados con regresiones |

---

## Hallazgos nuevos (cuarta pasada, 01-08-2026)

**Base verificada:** `main` en `73f2985`. Esta sección prevalece cuando el
estado histórico descrito arriba contradice el código actual.

| ID | Hallazgo | Ubicación | Severidad | Estado |
|---|---|---|---|---|
| P-1 | La CI de `main` no compilaba: `OnboardingPage` importaba `onboarding-estamosdao.css`, archivo que nunca existió | `frontend/src/pages/OnboardingPage.jsx:35` en `73f2985` | Alta (release) | ✅ Corregido en `codex/produccion-ci`: se usa la redefinición ya existente en `App.css`; build de producción ejecutado correctamente |
| P-2 | Los tres endpoints mutantes de elecciones aceptaban una dirección miembro sin exigir sesión SIWE: se podía convocar, postular y votar como otra wallet | `backend/app/routers/elections.py:227-408` en `73f2985` | **Crítica** | ✅ Corregido en `codex/produccion-ci`: `current_address` + `ensure_acts_as_self`; pruebas de 401, 403 y camino válido |
| P-3 | El paso NFC web fallaba al leer un tag: el contexto exporta `setNfc`, pero el componente llamaba `setNFC` | `frontend/src/components/onboarding/NFCStep.jsx:14,36` en `73f2985` | Alta (frontend) | ✅ Corregido en `codex/produccion-ci` |
| P-3b | El frontend enviaba el dato sintético `0xDOC` al minteo cuando no existía hash de documento | `frontend/src/context/OnboardingContext.jsx:156` en `73f2985` | Alta (integridad) | ✅ Corregido en `codex/produccion-ci`: el flujo se detiene con un error explícito si falta la verificación |
| P-4 | Una sesión SIWE solo prueba control de wallet; `POST /membership/mint` aceptaba `assurance_level` y `doc_hash` autoafirmados, sin consumir una verificación de identidad emitida por el servidor | `backend/app/routers/membership.py:23-35`; `backend/app/services/blockchain_service.py:41-82` | **Crítica** | 🟡 Mitigado en `codex/produccion-ci`: producción rechaza todo minteo; sigue abierto implementar y consumir el *verification grant* de un solo uso |
| P-5 | Producción respondía `HTTP 200 / healthy` aunque el propio diagnóstico declaraba `onchain_minting.configured=false`; el contrato Sepolia continúa con `totalSupply() == 0` | `backend/main.py:151-166`; `backend/app/core/readiness.py:63-88` | **Crítica (release)** | ✅ Guardrail corregido en `codex/produccion-ci`: `/health/live` separado de `/health/ready`, índices/config/modo forman parte de readiness y producción incompleta devuelve 503 |
| P-6 | Liveness seguía abierto por defecto: sin proveedor o dependencia retornaba `0.85`, no aplicaba umbral y no se enlazaba con el permiso de minteo | `backend/app/routers/auth.py` | Alta | 🟡 Mitigado en `codex/produccion-ci`: todos los flujos de identidad simulados devuelven 503 en producción, no persisten evidencia y se rotulan como demo; sigue abierto integrar un proveedor especializado y un grant de un solo uso |
| P-7 | La app móvil no participaba en CI, tenía errores reales de TypeScript/Jest/lint y el release Android usaba la clave debug | `.github/workflows/ci.yml`; `mobile/App.tsx`; `mobile/src/services/nfcService.ts`; `mobile/android/app/build.gradle` | Alta | 🟡 Mitigado: TypeScript, 15 tests, lint y SCA pasan localmente y tienen job CI; release falla cerrado sin keystore externo. Sigue abierta una compilación/publicación nativa reproducible |
| P-8 | La UI anunciaba “NFT registrado” y “datos sincronizados con blockchain” incluso cuando `tx_hash` era `null`; el QR contenía JSON autoafirmado y apuntaba a una ruta inexistente | `frontend/src/components/onboarding/MintStep.jsx:12-18,138-160`; `SuccessStep.jsx:49-106`; `DashboardStep.jsx:18-20,102-108`; `frontend/src/components/membership/MembershipQR.jsx:19-29` en `73f2985` | **Crítica (integridad)** | ✅ Corregido en `codex/produccion-ci`: estados y credencial dependen de una transacción real; el modo off-chain se identifica como piloto y el QR consulta un endpoint existente |
| P-9 | La cadena de suministro JavaScript acumulaba 60 avisos en frontend y 78 en contratos, incluidos 2 críticos por árbol | `frontend/package-lock.json`; `contracts/package-lock.json`; `mobile/package-lock.json`; `.github/workflows/ci.yml` | Alta | 🟡 Mitigado sin `--force`: frontend queda en 33 (11 bajos, 6 medios, 16 altos, **0 críticos**), contratos en 47 (20 bajos, 20 medios, 7 altos, **0 críticos**) y mobile en **0**. En dependencias de runtime (`--omit=dev`): frontend 2 altos y contratos 0. CI bloquea nuevos críticos en los tres árboles; eliminar los altos restantes requiere migrar/reemplazar los toolchains legacy CRA/Hardhat y revisar la aplicabilidad de React Router |
| P-10 | Aunque readiness fallaba, `current_address()` seguía decodificando JWT con la clave pública por defecto `dev-secret-key`; un atacante podía firmar su propio token y ejecutar acciones de un miembro activo | `backend/app/routers/deps.py`; `backend/app/core/readiness.py` | **Crítica** | ✅ Corregido: toda sesión valida primero la clave; placeholders y claves débiles fallan cerrado incluso si `DEBUG=true` en producción; regresión con JWT forjado |
| P-11 | El rate limiter también contaba `/health/live` y `/health/ready`; la petición 101 devolvía 429 y podía inducir falsos reinicios o sacar una instancia del balanceador | `backend/app/core/security_middleware.py` | Alta (operación) | ✅ Corregido: probes excluidos del limiter y regresión de 110 llamadas; challenge/verify SIWE pasan al límite sensible |
| P-12 | Readiness comprobaba solo presencia: aceptaba `SECRET_KEY=x`, pepper de un carácter y una clave Fernet malformada, aunque el primer uso fallaba o era inseguro | `backend/app/core/readiness.py` | Alta | ✅ Corregido: longitud mínima, placeholders prohibidos y construcción Fernet validados por una única función usada por health y endpoints |
| P-13 | Web NFC marcaba cualquier etiqueta NDEF como `verified: true`, generaba un hash y avanzaba el onboarding como si hubiera autenticado el chip protegido de una cédula | `frontend/src/components/onboarding/NFCStep.jsx`; `OnboardingContext.jsx` | **Crítica (integridad)** | ✅ Corregido: una lectura solo registra “etiqueta detectada”, nunca verifica ni avanza; el minteo exige verificación explícita + hash y producción permanece bloqueada |
| P-14 | ClaveÚnica, NFC, liveness y RUT/email simulados seguían expuestos bajo `APP_ENV=production` y algunos persistían eventos con nombres de verificadores gubernamentales/biométricos ficticios | `backend/app/routers/auth.py`; `backend/app/services/auth_service.py` en `73f2985` | **Crítica (integridad)** | ✅ Corregido: las cinco rutas devuelven 503 en producción, usan identificadores `DEMO_UNVERIFIED` fuera de producción, no guardan evidencia falsa y se eliminó el servicio mock duplicado |
| P-15 | Permanecían rutas muertas que inventaban wallet/balance y un POST público capaz de llenar `status_checks`; además `GET /membership/member` exponía el `doc_hash` interno | `backend/app/routers/wallet.py`; `dashboard.py`; `membership.py` | Alta | ✅ Corregido: superficie mock eliminada, cliente huérfano borrado y respuesta pública de membresía reducida a campos operativos |
| P-16 | La landing, onboarding y README seguían presentando capacidades no disponibles como identidad civil verificada, votos/fondos on-chain y biometría | `frontend/src/pages/LandingPage.jsx`; componentes de onboarding; `README.md` | Alta (reputación) | ✅ Corregido: producto rotulado como piloto, demos y límites visibles; lenguaje on-chain condicionado a transacciones reales |
| P-17 | Promover la misma base de datos de demo a producción conservaba como miembros activos a altas autoafirmadas: `members` no registraba procedencia y el verificador Mongo solo comprobaba `status=active` | `backend/app/models/schemas.py`; `backend/app/services/blockchain_service.py`; `membership_verifier.py` | **Crítica (autorización)** | ✅ Corregido: cada alta declara `issuance_mode`, todo camino actual mantiene `identity_verified=false`, legacy queda como `legacy_unverified` y producción solo autoriza `active + onchain + tx_hash + identity_verified=true`; regresión demo→producción incluida |
| P-18 | El historial público contiene una `EMERGENT_LLM_KEY` con formato real dentro de `backend/.env` | historial Git: `6202a9f` (confirmado 02-08-2026); `8d66b97` y `9977a2f` ya no contienen el archivo | **P0 crítica** | 🔴 **Sigue abierto.** Verificado el 02-08-2026: el valor continúa accesible en el repositorio público. Revocar/rotar en el proveedor es acción externa que ningún agente puede ejecutar. Runbook: `docs/SECURITY_RUNBOOK.md` |
| P-19 | El código cifra altas nuevas, pero no existe migración/backfill validado para PII legacy; múltiples documentos sin `rut_key`/`email_key` pueden impedir crear índices únicos y dejar readiness en 503 | colección Atlas `users`; `backend/app/core/database.py` | **Crítica (release/datos)** | ✅ Corregido: Migración ejecutada con el script de mantenimiento. La PII legacy se cifró en reposo y se generaron los índices ciegos correspondientes. |
| P-20 | Configuración on-chain no vacía pero inválida podía declarar readiness; no se comprobaban chainId, bytecode, ABI, `MINTER_ROLE` ni saldo | `backend/app/services/chain_service.py`; `backend/app/core/readiness.py` | Alta | ✅ Corregido: readiness y el endpoint de minteo ejecutan la misma validación estática/runtime contra Sepolia, bytecode, ABI, rol y gas; producción exige RPC HTTPS. El envío usa chain ID fijo, reserva local de nonce, errores sanitizados y obtiene el token desde evento o lectura del contrato, sin inventarlo |
| P-21 | El frontend mantenía la dirección Sepolia histórica y una ABI manual `string` incompatible con el contrato actual `bytes32`; cualquier `tx_hash` abría el contrato equivocado | `frontend/netlify.toml`; `src/contracts/SBTContract.js`; `useSBTContract.js`; `DashboardStep.jsx` | Alta (integridad) | ✅ Corregido: dirección, ABI y hook huérfano eliminados; la UI enlaza únicamente el `tx_hash` real devuelto por la API |
| P-22 | El challenge de wallet se anunciaba como SIWE pero omitía Chain ID y usaba dominio/URI fijos no públicos | `backend/app/services/siwe_service.py` | Alta (autenticación) | ✅ Corregido: mensaje EIP-4361 completo con primera línea canónica, dominio/URI/red/expiración; nonce atómico de un solo uso que no se quema ante una firma inválida; JWT valida `iss`/`aud` + `jti`. Challenge, verify y consumo de sesión aplican el gate en runtime, no solo en readiness |
| P-23 | El camino on-chain envía la transacción antes de persistir Mongo; una caída o colisión deja cadena y base divergentes | `backend/app/services/blockchain_service.py`; `frontend/src/lib/api.js` | Alta (futuro release) | ✅ Corregido: Se implementó un estado `pending` en MongoDB antes del llamado on-chain, con resolución a `active` o `failed` y limpieza en reintentos |
| P-24 | Readiness no bloqueaba `DEBUG=true`, CORS abierto, papeletas sin firma o una fuente de membresía on-chain aún no implementada | `backend/app/core/readiness.py`; `render.yaml`; `DEPLOY.md` | Alta | ✅ Corregido: invariantes cruzadas forman parte de `/health/ready`, el blueprint declara decisiones demo y el despliegue manual enumera toda la configuración obligatoria |
| P-25 | Los votos de propuestas aceptaban un `nonce` sin firma ni persistencia verificable; elecciones seguía el mismo patrón | `backend/app/routers/governance.py`; `backend/app/routers/elections.py`; `frontend/src/components/governance/ProposalsList.jsx` | **Crítica (integridad electoral)** | 🟡 Propuestas corregidas end-to-end: EIP-712 firmado en wallet, nonce único persistido, firma/hash reverificables y endpoint público de papeletas. Los votos de elecciones aún no tienen papeleta firmada y por eso producción los rechaza explícitamente |
| P-26 | Insertar una papeleta y actualizar el total de la propuesta son dos escrituras Mongo separadas; una caída entre ambas puede desalinear papeletas y resultado | `backend/app/routers/governance.py`; `backend/app/routers/elections.py` | Alta (integridad) | ✅ Corregido: Se eliminó la persistencia de totales. Los resultados de propuestas y elecciones ahora se derivan (`tally_service`/`compute_results`) dinámicamente de las papeletas firmadas (un solo write) |
| P-27 | Las dependencias Python fijadas acumulaban 48 avisos conocidos en `python-dotenv`, `python-multipart`, Pillow, cryptography y PyJWT; CI no ejecutaba SCA para backend | `backend/requirements.txt`; `requirements-dev.txt`; `.github/workflows/ci.yml` | **Crítica (cadena de suministro)** | ✅ Corregido: versiones seguras verificadas con la suite completa, `pip-audit --strict` no encuentra vulnerabilidades conocidas y el gate se ejecuta en CI |
| P-28 | El rate limiter confiaba en el primer `X-Forwarded-For`, no clasificaba el voto de elecciones como sensible y el límite de 10 MB dependía de `Content-Length`; además producción podía aceptar el fallback Mongo local | `backend/app/core/security_middleware.py`; `backend/app/core/readiness.py` | Alta (abuso/release) | ✅ Corregido: peer TCP por defecto, proxies explícitos por IP/CIDR, buckets global+sensible, límite de bytes ASGI incluso chunked y `MONGO_URL` remoto obligatorio en producción |
| P-29 | La app móvil afirmaba identidad/blockchain/voto verificados y firmaba el build Android `release` con el keystore debug público | `mobile/src/screens/HomeScreen.tsx`; `mobile/App.tsx`; `mobile/android/app/build.gradle` | Alta (integridad/release) | ✅ Mitigado: lenguaje explícito de piloto no verificado y release falla cerrado sin keystore/credenciales externos. Mobile sigue experimental hasta PACE, gates CI y un proceso de publicación real |
| P-30 | El frontend no declaraba CSP/HSTS y conserva el JWT SIWE en `localStorage`, donde un XSS podría extraerlo | `frontend/netlify.toml`; `frontend/src/lib/api.js`; `frontend/README.md` | Media | 🟡 Mitigado: CSP sin `unsafe-eval`, HSTS, Permissions-Policy y redirección del alias Netlify al host SIWE canónico. Migrar a cookie `Secure`/`HttpOnly`/`SameSite` requiere un cambio coordinado con CORS, CSRF, logout y revocación |
| P-31 | CI usaba tags mutables de Actions y permisos implícitos; no existía actualización automática de dependencias ni branch protection | `.github/workflows/ci.yml`; `.github/dependabot.yml`; configuración de GitHub | Alta (supply chain/proceso) | 🟡 Mitigado en código: Actions fijadas por SHA, `contents: read`, timeouts, auditorías npm/Python, gate mobile y Dependabot semanal. 🔴 Acción externa pendiente: habilitar ruleset de `main`, exigir los checks y activar secret scanning/protección de push |

### Evidencia ejecutada en esta pasada

- Backend: suite completa después de los guardrails: `151 passed`; incluye
  401/403 en elecciones, JWT forjado, secretos malformados, probes sin límite,
  cuerpos chunked sobredimensionados, proxies no confiables, papeletas EIP-712
  y readiness fail-closed.
- Contrato: `31 passing` con Hardhat.
- Frontend: `CI=true npm run build` terminó correctamente después de los
  cambios de P-1/P-3/P-8/P-13/P-16/P-25. El comando de tests termina sin casos:
  todavía no existe una suite unitaria de frontend.
- Mobile: `tsc --noEmit`, 2 suites/15 tests de Jest y ESLint pasan (0 errores,
  21 advertencias preexistentes); `npm audit` informa 0 vulnerabilidades. No se
  completó una compilación nativa release firmada.
- Dependencias: `npm audit --audit-level=critical` pasa en frontend y contratos;
  `pip-audit --strict` no encuentra vulnerabilidades Python conocidas. No quedan
  vulnerabilidades críticas conocidas en los árboles auditados.
- Servicio público anterior (consulta de solo lectura): `/health` devolvió `200`
  con minteo on-chain no configurado y `/health/ready` devolvió `404`; el RPC de
  Sepolia devolvió supply cero. Esta rama todavía no está desplegada.

---

## Hallazgos nuevos (quinta pasada — revisión de `codex/produccion-ci`, 01-08-2026)

**Alcance:** revisión del árbol de trabajo sin commitear sobre `73f2985`.
Suites ejecutadas de verdad antes y después de cada cambio (ver evidencia al
final). Los `✅` de esta tabla están corregidos **en el árbol de trabajo**,
todavía sin commit ni despliegue.

| ID | Hallazgo | Ubicación | Severidad | Estado |
|---|---|---|---|---|
| P-32 | `ballot_service.verify` envolvía el `insert_one` del nonce en `except Exception`, así que **cualquier** fallo de Mongo (red, autenticación, réplica caída) se le devolvía al votante como `409 "Esta papeleta ya fue usada"`. El votante firmaba una papeleta nueva que fallaba igual, y un voto legítimo quedaba sin registrar bajo una explicación falsa | `backend/app/services/ballot_service.py:119` | **Alta (integridad electoral)** | ✅ Corregido: solo `DuplicateKeyError` significa replay; cualquier otro `PyMongoError` devuelve `503` diciendo explícitamente que el voto **no** quedó emitido. Regresión: `test_replayed_ballot_nonce_is_rejected_as_conflict` |
| P-33 | `GET /governance/treasury/transactions` devolvía documentos Mongo crudos. El `_id` (`ObjectId`) no es serializable por FastAPI, así que la primera transacción real almacenada convertía el endpoint en un `500`. Solo pasaba desapercibido porque la colección nunca se escribe | `backend/app/routers/governance.py:759` | Media (latente) | ✅ Corregido: proyección `{"_id": 0}` y `response_model=List[TreasuryTransaction]` — el modelo ya existía y estaba muerto. Regresión: `test_treasury_transactions_serialize_stored_records` |
| P-34 | Cuatro endpoints públicos sin autenticar aceptaban `limit` sin cota (`?limit=10000000`), obligando al servidor a materializar la colección entera. `ballots` sí validaba; los demás no | `backend/app/routers/governance.py`; `elections.py`; `dashboard.py` | Media (abuso) | ✅ Corregido: `Query(ge=1, le=MAX_PAGE_SIZE)` en propuestas, tesorería, elecciones y actividad. Regresión: `test_public_list_limits_are_bounded` |
| P-35 | El rate limiter acumulaba una entrada permanente por dirección IP distinta en `requests`, `failed_attempts` y (por ser `defaultdict`) también para IPs que solo pasaron una vez. Nada se liberaba nunca: en una API pública la contabilidad del propio limitador se vuelve el vector de agotamiento de memoria que debía prevenir | `backend/app/core/security_middleware.py:140` | Media (disponibilidad) | ✅ Corregido: barrido amortizado a una vez por ventana que olvida clientes silenciosos tras 10 ventanas, conservando la penalización progresiva. Regresiones: `test_rate_limiter_forgets_silent_clients`, `test_rate_limiter_sweep_is_amortized_to_one_per_window` |
| P-36 | `revoke_membership` decidía "Token no encontrado" con `modified_count`. Revocar una membresía **ya revocada** no modifica nada, así que el operador recibía "no existe" sobre un token que sí está en la colección — indistinguible de un id inexistente | `backend/app/services/blockchain_service.py:213` | Media (operación) | ✅ Corregido: se usa `matched_count`; además el `except` dejó de reflejar `str(e)` del driver. Regresión: `test_revoking_twice_reports_the_membership_as_found` |
| P-37 | `POST /governance/delegate` validaba al **delegado** con un `find_one({status: "active"})` crudo, más débil que el gate de producción que se aplica al delegante (`issuance_mode=onchain` + `identity_verified` + `tx_hash`). Una fila legacy/demo en cuarentena podía recibir delegaciones que nunca podría ejercer | `backend/app/routers/governance.py:602` | Media (autorización) | ✅ Corregido: el delegado pasa por el mismo `MembershipVerifier` que el delegante |
| P-38 | Reapertura parcial de **P-6**: sin `EMERGENT_LLM_KEY` (o sin la biblioteca) el liveness seguía devolviendo `score = 0.85`, y ante un error del proveedor `0.5`. La UI lo mostraba como "PUNTAJE DEMO: 85%". El rótulo cambió, el número inventado no — exactamente lo que prohíbe la regla 2 de `AGENTS.md` | `backend/app/routers/auth.py`; `frontend/src/components/onboarding/LivenessStep.jsx` | Alta (integridad) | ✅ Corregido: sin proveedor no hay puntaje (`score = null`) y la UI muestra "SIN PUNTAJE — PROVEEDOR NO CONFIGURADO" en vez de un porcentaje fabricado |
| P-39 | Cuatro rutas de identidad devolvían `str(e)` al cliente (`error=str(e)`, `analysis=f"...{str(e)}"`), filtrando texto interno de excepciones y del proveedor LLM — justo lo que el manejador global de `main.py` evita con cuidado | `backend/app/routers/auth.py` | Media (fuga de información) | ✅ Corregido: mensajes genéricos al cliente, detalle completo al log |
| P-40 | `useWallet` reutilizaba el JWT de `localStorage` sin mirar `exp`. Pasada la hora de sesión, `connect()` reportaba éxito y la UI mostraba la wallet conectada, mientras cada request devolvía 401 y el interceptor borraba el token en silencio: el usuario quedaba "conectado" sin poder mintear, votar ni delegar | `frontend/src/hooks/useWallet.js` | Media (UX/autenticación) | ✅ Corregido: se lee `exp` (con margen de 30 s) antes de reutilizar; un token vencido se descarta y se pide un desafío nuevo |
| P-41 | `GET /governance/elections` ejecutaba dos `count_documents` por elección (hasta ~200 round-trips por request público) y `GET /representatives` una consulta por representante | `backend/app/routers/elections.py` | Baja (rendimiento) | ✅ Corregido: conteos agregados en dos `$group` sobre la página seleccionada y títulos resueltos con un `$in` |
| P-42 | El `MintingUnavailable` lanzado dentro del `try` de `mint_sbt` (tokenId on-chain no verificable) lo capturaba el `except Exception` de más abajo y se aplanaba a un genérico "No se pudo crear la membresía", perdiendo el motivo específico que el router traduce a 503 | `backend/app/services/blockchain_service.py:143` | Baja | ✅ Corregido: `except MintingUnavailable: raise` antes del genérico |
| P-43 | `GET /` anunciaba `"docs": "/docs"` con `DEBUG=true`, pero `docs_url` además exige no estar en producción: un despliegue con `DEBUG=true` publicitaba una ruta que devuelve 404 | `backend/main.py` | Baja (documentación vs código) | ✅ Corregido: ambas decisiones derivan de una única constante `DOCS_ENABLED` |
| P-44 | `AsyncIOMotorClient` se construía sin `serverSelectionTimeoutMS`, dejando el default de 30 s: con `MONGO_URL` mal configurada el arranque se bloquea 30 s creando índices (trampa 9 de `HANDOFF.md`) antes de que el servicio responda | `backend/app/core/database.py` | Baja (operación) | ✅ Corregido: 5 s, suficiente para un arranque en frío de Atlas y visible de inmediato en los logs |
| P-45 | `requirements-dev.txt` instala `black`, `flake8` y `mypy`, pero **ningún job de CI los ejecuta**. Con los defaults hay 176 avisos de flake8, 26 archivos que `black` reformatearía y 15 errores de `mypy`. Tampoco hay job de tests de frontend | `.github/workflows/ci.yml`; `backend/requirements-dev.txt` | Media (proceso) | ✅ **Cerrado para backend** (04-08-2026): configuración en `pyproject.toml` (black, mypy) y `setup.cfg` (flake8), formateo aplicado en un commit aparte, 59 avisos y 41 errores de tipos corregidos, y job `backend-quality` en CI. El job de tests de **frontend** sigue siendo de Codex |
| P-46 | `fraud_detector.check_rapid_voting` registra el intento **antes** de validar que la propuesta exista o que el votante no haya votado ya. Diez intentos fallidos (propuesta inexistente, ya votada) consumen la cuota y bloquean al miembro con 429 sin que haya emitido un solo voto | `backend/app/routers/governance.py`; `elections.py` | Baja | ✅ **Cerrado** (04-08-2026): `check_rapid_voting(voter)` solo LEE (nuevo `RateLimitStore.count()`, con su Lua en Redis) y `record_vote(voter)` apunta después de persistir la papeleta. `proposal_id` sale de la firma: nunca formó parte de la clave. Cubierto por `test_checking_does_not_consume_quota` |
| P-47 | En `DEBUG`, `crypto.py` genera la llave Fernet de desarrollo **una vez por proceso**. Con `--reload` o varios workers, lo que un proceso cifra otro no puede descifrarlo: el nombre vuelve `None` sin explicación | `backend/app/core/crypto.py` | Baja (solo desarrollo) | ✅ **Cerrado** (04-08-2026): se deriva de una constante fija y visible en el repositorio (`sha256` del sembrado, en base64 urlsafe). No es un secreto y solo se usa sin llaves configuradas Y con `DEBUG`; `key_status()` no la cuenta, así que readiness sigue bloqueando producción |

### Evidencia ejecutada en esta pasada

Todo lo siguiente se ejecutó de verdad en el árbol de trabajo, no se dedujo:

- **Backend:** `pytest -q` → **157 passed** (151 previos + 6 regresiones nuevas).
  Baseline de 151 confirmado antes de tocar código.
- **Contratos:** `npx hardhat test` → **31 passing**. Sin cambios en `contracts/`.
- **Mobile:** `npx jest` → **15 passed**, 2 suites. Sin cambios en `mobile/`.
- **Frontend:** `CI=true npm run build` → `Compiled successfully.` antes y
  después de los cambios (avisos tratados como error).
- **P-33 y P-36 se reprodujeron empíricamente** antes de corregirlos:
  `jsonable_encoder` sobre un documento con `ObjectId` lanza `ValueError`, y
  `revoke_membership(7)` sobre un token ya revocado devolvía
  `(False, 'Token no encontrado')` con el token presente en la colección.
- **No ejecutado:** compilación nativa de mobile, despliegue, ninguna mutación
  contra Atlas o Sepolia, y ningún `git commit`/`push`.

---

## Hallazgos del rediseño cívico del interior (01-08-2026)

El dashboard seguía en el tema cyberpunk mientras la portada ya era cívica. Al
convertirlo aparecieron dos defectos funcionales que el tema oscuro escondía:

| ID | Hallazgo | Ubicación | Severidad | Estado |
|---|---|---|---|---|
| P-48 | El modal de nueva propuesta marcaba la categoría y la duración elegidas con clases Tailwind armadas por interpolación (`bg-${cat.color}-500/20`). Tailwind purga lo que no aparece literal en el código, así que esas clases **nunca se generaron**: la opción seleccionada se veía igual que las demás y el usuario no tenía forma de saber qué había elegido | `frontend/src/components/governance/CreateProposalModal.jsx` | Media (usabilidad) | ✅ Corregido: el estado activo usa clases reales del sistema cívico y `aria-pressed` |
| P-49 | `VoteDelegation` calculaba el poder de voto como `delegators.length + 1`, contando **todos** los delegantes. El backend solo suma los que siguen siendo miembros activos (`voting_power`), así que la interfaz mostraba un poder mayor al que realmente se aplica al votar | `frontend/src/components/governance/VoteDelegation.jsx` | Media (dato inflado) | ✅ Corregido: se usa `voting_power` de la API y los delegantes sin membresía activa se marcan como tales |
| P-50 | El diálogo de nueva propuesta no se podía cerrar con teclado (sin `Escape`, sin `role="dialog"`), y los botones de icono del QR de membresía no tenían nombre accesible | `CreateProposalModal.jsx`; `frontend/src/components/membership/MembershipQR.jsx` | Baja (accesibilidad) | ✅ Corregido: cierre con `Escape`, `role="dialog"` + `aria-modal` y `aria-label` en los botones de icono |

**Sobre el tema visual:** `styles/civic.css` es ahora la única fuente de verdad
del interior. `.civic-onboarding` (en `App.css`) solo redefinía cuatro clases
`cyber-*`, así que botones, insignias, campos y avisos seguían saliendo oscuros
a mitad del flujo de `/unete` pese al rediseño anterior; la capa nueva cubre el
vocabulario completo. El marcado de los once pasos del onboarding no se tocó, a
propósito: ahí vive la lógica de NFC, liveness, wallet y minteo.

**Verificación ejecutada:** `CI=true npm run build` correcto; las seis rutas
(`/`, `/dashboard`, `/dashboard/{elecciones,delegacion,tesoreria}`, `/unete`)
renderizadas en Chromium headless contra el build de producción, con capturas y
comprobación del color computado — todas devuelven fondo claro `rgb(247,249,252)`
y tinta `rgb(51,69,107)`. Un barrido de contraste texto/fondo sobre el flujo de
alta no encontró combinaciones ilegibles (el único positivo es el `<noscript>`,
que nunca se muestra con JS activo).

---

## Hallazgos de la Tarea 6 — E2E y firma no custodial (01-08-2026)

| ID | Hallazgo | Ubicación | Severidad | Estado |
|---|---|---|---|---|
| P-51 | La suite Playwright arrancaba CRA con `craco start` directamente, saltándose `prestart/zk:sync`. En un checkout limpio podía ejecutar sin los tres artefactos ZK de `public/zk` o reutilizar residuos locales; además no existía un job E2E en CI | `e2e/playwright.config.js`; `.github/workflows/ci.yml` | Alta (integridad de pruebas) | ✅ Corregido: usa `npm start`, reconstruye los artefactos desde el manifiesto verificado y la CI instala Chromium y ejecuta Playwright en cada PR |
| P-52 | El flujo guardaba solo dirección/red y, al mintear, `erc4337.js` caía a `globalThis.ethereum`. La instancia que estableció SIWE no quedaba fijada hasta la firma de la UserOperation | `frontend/src/hooks/useWallet.js`; `WalletStep.jsx`; `OnboardingContext.jsx`; `lib/api.js`; `lib/erc4337.js` | Alta (autorización) | ✅ Corregido: la instancia MetaMask EIP-1193 viaja explícitamente en memoria, sin fallback global; cuenta y red se revalidan antes de construir y firmar, y la firma Safe v0.7 debe medir 77 bytes. El E2E sustituye el provider global tras SIWE y prueba que ninguna solicitud de firma se desvía |
| P-53 | El router ERC-4337 no implementaba el contrato del cliente: `PrepareMintRequest` exigía `proof` mientras el frontend envía `account + mint`, y decodificaba el `callData` exterior de `Safe4337Module.executeUserOpWithErrorString` con la ABI del SBT | `backend/app/routers/erc4337.py` | **Alta (integración bloqueada)** | ✅ **Cerrado** (02-08-2026): modelos alineados, decodificación en dos capas, y **derivación CREATE2 de la Safe implementada y verificada** contra direcciones generadas por el mismo `permissionless.js` del navegador |

### Evidencia ejecutada

- Frontend: `CI=true npm test -- --watchAll=false --runInBand` → **7 suites,
  41 tests**; incluye un test con `permissionless` real que observa una única
  llamada `eth_signTypedData_v4` con `SafeOp`. `CI=true npm run build` compiló
  correctamente.
- E2E desde configuración limpia: los tres artefactos ZK fueron resincronizados
  desde `circuits/build`; la primera corrida limpia pasó en **4.0m**. La corrida
  final reforzada, sustituyendo el provider global después de SIWE, dio
  `CI=true E2E_FRONTEND_PORT=3015 npm test` → **1 passed (52.9s)** en Chromium.
  Se verificó la prueba Groth16, se recuperó el owner de la firma EIP-712 y se
  descifró/validó la papeleta MACI capturada.
- El nuevo job `E2E · Playwright` y la suite unitaria de frontend quedaron como
  gates de `.github/workflows/ci.yml`.
- Trusted setup real: `trusted_setup.sh` autenticó el Powers of Tau oficial,
  compiló el circuito y publicó atómicamente la contribución #1 en
  `circuits/build/trusted-setup/production-20260801-participant-1/` tras
  **4 h 21 min 18,05 s** de ejecución.
  `trusted_setup.test.sh` pasó y una segunda ejecución de `snarkjs zkey verify`
  terminó en **`ZKey Ok!`**. SHA-256 de `verify_identity_phase2.zkey`:
  `040f52b9fe5d4eb40525db9f3ce905213f900869db03ff9fb340a7b874719795`.
  El recibo declara honestamente `participant_independence=not-attested-by-script`,
  `beacon=not-applied` y `promotion_status=not-promoted`: es una contribución
  Phase 2 verificada, no una ceremonia de producción final.

---

## Hallazgo de la Tarea 6 — margen de censura del coordinador MACI (02-08-2026)

| ID | Hallazgo | Ubicación | Severidad | Estado |
|---|---|---|---|---|
| P-54 | `processMessages.circom` **exige** que la firma EdDSA del comando sea válida (`EdDSAPoseidonVerifier.enabled === 1`). Un mensaje mal firmado no puede probarse, así que el coordinador debe excluirlo del procesamiento. Eso le deja margen de censura: puede declarar "inválido" un mensaje legítimo y nadie puede distinguir esa exclusión de una legítima, porque el contenido está cifrado. El acumulador on-chain prueba **qué mensajes se publicaron**, pero no que todos los válidos se hayan procesado | `circuits/processMessages.circom` (componente `signature`, `enabled <== 1`) | **Alta (integridad electoral)** | 🔴 **Aceptado a sabiendas para el alcance del piloto** (decisión del orquestador, 02-08-2026). No apto para una elección vinculante |

**Por qué no se cerró ahora.** Procesar mensajes inválidos como *no-op* —sin
revelar cuáles lo son— requiere que la verificación de firma produzca un
**booleano** que alimente un selector de estado, en vez de una restricción dura.
`EdDSAPoseidonVerifier` de circomlib solo restringe: no expone salida. Hacen
falta dos cosas:

1. un verificador EdDSA-Poseidon con salida (`valid`), reimplementado o
   adaptado desde circomlib, y
2. multiplexar la transición: `newLeaf = valid ? leafActualizada : leafPrevia`,
   de modo que la prueba avance el estado igual haya sido válido o no y el
   observador no pueda inferir cuál fue.

Con eso, el coordinador quedaría obligado a procesar **todos** los mensajes
publicados en orden, y omitir uno rompería la cadena de raíces de estado.

**Mitigación disponible mientras tanto:** el acumulador de
`MACICoordinator.publishMessage` fija contenido y orden de todo lo publicado,
así que un observador puede contar cuántos mensajes hubo y compararlos con
cuántos declara el coordinador haber procesado. Detecta una omisión masiva; no
detecta la exclusión selectiva de un mensaje concreto.

**Contexto de decisión:** aceptado explícitamente para el piloto por el
orquestador el 02-08-2026, con el compromiso de abordarlo antes de cualquier
uso vinculante. Se registra aquí para que la deuda no se pierda entre
iteraciones.

### Frontera de protocolo aprobada — cifrado de mensajes MACI

El esquema de cifrado de `processMessages.circom` quedó **aprobado** el
02-08-2026 y es contrato con el cliente:

```
shared        = coordinatorPrivKey · ephemeralPubKey     (ECDH Baby Jubjub)
ciphertext[i] = plaintext[i] + Poseidon(shared.x, shared.y, i)   (mod p)
```

El cliente deriva la MISMA clave como `ephemeralPrivKey · coordinatorPubKey`.

**No es el `poseidonDecrypt` de la implementación de referencia de MACI.** Es
equivalente en garantías y más barato en restricciones, pero exige que el
cliente cifre exactamente así: cualquier otra construcción produce texto que el
circuito descifra como basura y cuya firma no verifica — y el fallo aparece
como "firma inválida", no como "cifrado incompatible", que es difícil de
diagnosticar.

Disposición del texto plano (10 elementos, los que acepta el contrato):

| Índice | Campo |
|---|---|
| 0 | `stateIndex` |
| 1 | `voteOption` |
| 2 | `voteWeight` |
| 3 | `nonce` |
| 4 | `newPubKeyX` |
| 5 | `newPubKeyY` |
| 6 | `sigR8x` |
| 7 | `sigR8y` |
| 8 | `sigS` |
| 9 | relleno (0) |

La firma EdDSA-Poseidon se calcula sobre `Poseidon(plaintext[0..5])`.


---

## Endurecimiento del repositorio (02-08-2026)

Cierra la parte de **P-31** que dependía de configuración de GitHub y que hasta
ahora estaba marcada como "acción externa pendiente".

| Control | Antes | Ahora |
|---|---|---|
| Ruleset sobre `main` | ninguno | **activo** (id 20222928): exige PR, checks en verde, y bloquea force-push y borrado |
| Checks obligatorios | ninguno | `Backend · pytest`, `Contracts · hardhat test`, `Contracts · slither`, `Frontend · build` |
| Secret scanning | deshabilitado | **habilitado** |
| Push protection | deshabilitado | **habilitado** |
| Dependabot security updates | deshabilitado | **habilitado** |

**Decisión sobre las revisiones:** el ruleset exige PR pero con
`required_approving_review_count: 0`. Exigir una aprobación dejaría al
mantenedor en solitario sin poder mergear nada —GitHub no permite aprobar el
propio PR— y el efecto práctico sería desactivar la protección para poder
trabajar. Con cero aprobaciones se conserva lo que pedía la auditoría: **no se
puede mergear con CI en rojo**.

**`Mobile · static gates` NO se incluyó** entre los checks obligatorios: el job
existe en `ci.yml` pero todavía no ha reportado sobre `main`, y exigir un check
que nunca llega deja los PR colgados para siempre. Añadirlo en cuanto la rama
actual se integre.

**Sin cobertura (requieren GitHub Advanced Security, de pago):**
`secret_scanning_non_provider_patterns` y `secret_scanning_validity_checks`
siguen deshabilitados. Importa para P-18: `EMERGENT_LLM_KEY` es un nombre
propio, no un patrón de proveedor reconocido, así que el escaneo estándar
**puede no detectarlo**. No confiar en la alerta automática para darlo por
cerrado.

**Controles preventivos verificados hoy:** `*.env` está en `.gitignore`
(`backend/.env` confirmado ignorado) y no hay ningún `.env` rastreado. Con push
protection activo, un intento de reintroducir una clave reconocible quedaría
bloqueado en el push.


### Cierre de P-53 (02-08-2026) — derivación CREATE2 verificada

Lo que quedaba pendiente ya está implementado. El enfoque final resultó **mejor
que replicar las constantes de despliegue de Safe**: se deriva la dirección
desde el propio `factoryData` del cliente, decodificando
`createProxyWithNonce(address,bytes,uint256)` y leyendo el `proxyCreationCode`
**de la propia factory on-chain**. Cero constantes adivinadas.

Verificado contra vectores reales generados con el mismo `permissionless.js`
que usa el navegador (Safe v1.4.1, módulo canónico, saltNonce 0):

| owner | Safe derivada |
|---|---|
| `0x118d2C9e…` | `0x9875C9C1cE9C23ff2240197276B9cf740b2c3989` |
| `0x1111…1111` | `0x4315A87ca896aCfd7c8Ce0Fcf10eEc8fe3053816` |

Ambas coinciden. El vector y el `proxyCreationCode` quedaron como fixtures en
`backend/tests/fixtures/`, así que si la derivación se rompe falla un test en
vez de rechazar peticiones legítimas en producción.

Se conservan **dos comprobaciones complementarias**, porque ninguna sustituye a
la otra: la derivación prueba que la dirección declarada es la que ese
`factoryData` despliega; el binding de owner prueba que esa cuenta pertenece a
quien firmó. Sin la primera, el cliente podía declarar una dirección y desplegar
otra; sin la segunda, el paymaster pagaría el despliegue de una Safe ajena.

### Nota histórica — por qué no se hizo antes

La corrección cubre el bloqueo real (modelos y decodificación). Sobre
"recalcular la Safe ciudadana" conviene ser preciso, porque se implementó de
forma parcial y deliberada:

**Sí se valida**, y basta para proteger lo que importa:
- el perfil de cuenta declarado (`type`, `version`, `salt_nonce`, módulo,
  `use_multi_send_for_setup`) debe coincidir exactamente con el que sirve
  `/config`; con otros parámetros la Safe tendría otra dirección y la firma no
  validaría;
- `user_operation.sender` debe ser la `safe_address` declarada;
- si la operación **despliega** la Safe, su `factoryData` debe nombrar a la
  wallet autenticada. Esto es lo que impide que el paymaster de la DAO pague
  el despliegue de una cuenta ajena, que era el riesgo económico concreto;
- la llamada interna va al SBT configurado, con `operation=CALL`, valor cero,
  destinatario igual a la wallet autenticada, y **coordenadas Groth16, nullifier
  y raíz idénticas a las declaradas** — sin esto último el campo `mint` sería
  decorativo: se validaría una prueba y se ejecutaría otra.

**No se implementó** la derivación CREATE2 completa de la dirección Safe
(factory + singleton + hash del inicializador + saltNonce). Requiere replicar
exactamente las constantes de despliegue de Safe v1.4.1 que usa
`permissionless.js`, y **no hay en el repositorio ningún vector conocido
(owner → dirección) contra el que verificarlo**: los tests del cliente usan
direcciones de relleno. Implementarla a ciegas y equivocar una constante
rechazaría *todas* las peticiones legítimas, que es peor que el hueco que
cierra. Queda pendiente de un vector real —lo aporta el primer despliegue en
Sepolia— y hasta entonces la protección efectiva es el resto de comprobaciones.


---

## Despliegue de integración en Sepolia — verificación independiente (02-08-2026)

Comprobado contra la cadena, no contra el reporte:

| Contrato | Dirección | Verificado |
|---|---|---|
| `DAOCiudadanaSBT` | `0x41491B6976A3796bEf8660625Dc9eA51e72a587a` | 9.877 bytes de bytecode |
| `Verifier` | `0x26b18c29E8EF613958EFE0123a24A70E9ff52413` | 1.658 bytes; **coincide** con `membershipVerifier()` del SBT |
| `MACICoordinator` | `0x1CC218883dBeFf6aB8b4933723DF23B8F69336a6` | 5.349 bytes; su `membership()` apunta al SBT |

- `membershipScope()` = `16916500747997676645551243185131135892121977094615858609009617732596527423811`
- `totalSupply()` = **0** — todavía no se ha minteado ninguna membresía.
- El admin `0x118d2C9e…` tiene `ROOT_MANAGER_ROLE`: puede aprobar raíces.
- `tallyIsVerifiable()` = **false**, `tallyVerifier()` = `address(0)`, tal como
  se reportó. Ningún resultado de MACI puede publicarse.
- **`coordinatorPubKeyX` = 0**: la llave del coordinador MACI **no está
  publicada**. `GET /maci/proposals/{id}/poll` devuelve 503 correctamente, y
  seguirá haciéndolo hasta que se publique: anunciar una llave sin anclaje
  produciría votos que nadie puede descifrar.

### Bug encontrado al leer el despliegue real

`chain_service.membership_scope()` devolvía `None` pese a que el contrato
respondía: `is_configured()` exigía también `MINTER_PRIVATE_KEY`, y **las
lecturas no necesitan llave privada**. El efecto era que la emisión de
credenciales fallaba con "no se pudo leer membershipScope()" cuando el único
problema era que el relayer no estaba configurado — dos cosas sin relación.
Corregido con `can_read_chain()`, separado de `is_configured()`.


---

## Llave del coordinador MACI — por qué no la publicó un agente (02-08-2026)

Se pidió ejecutar `setCoordinatorPubKey` para habilitar la recepción de votos.
No se hizo, por dos razones que conviene dejar escritas.

**1. Custodia.** La llave pública del coordinador se deriva de una privada que
**descifra todos los votos**. Generarla en un agente automatizado deja esa
capacidad en un entorno efímero y en un archivo temporal: es precisamente el
poder que MACI existe para acotar. Debe generarla quien vaya a custodiarla, en
su máquina. Para eso está `backend/scripts/generate_maci_key.py`, que genera y
**valida** el par con la misma comprobación de curva y subgrupo primo que se
aplica a las llaves de los votantes.

**2. Oportunidad.** `tallyIsVerifiable()` es `false` y `tallyVerifier` sigue en
`address(0)`; no existe ni el `zkey` del circuito de tally. Publicar la llave
del coordinador es lo que permite abrir consultas (`createPoll` la exige), así
que hacerlo ahora habilitaría **recoger papeletas reales que nadie podría
contar de forma verificable**. Sería la apariencia de una votación funcionando
sin la garantía que la justifica — exactamente el tipo de capacidad aparente
que este repositorio viene eliminando.

**Orden correcto:** ceremonia multiparte del circuito de tally → desplegar el
verificador → `setTallyVerifier` → comprobar `tallyIsVerifiable()` → recién
entonces `setCoordinatorPubKey`.

Nota operativa: el par que el script imprimió durante la verificación de esta
tarea quedó en el registro de la sesión y **no debe usarse**.


---

## TallyVerifier de MACI desplegado en Sepolia (03-08-2026)

`tallyIsVerifiable()` pasó a **`true`**. Ya se puede publicar un recuento, pero
solo contra una prueba válida del circuito de esta ceremonia.

| Elemento | Valor |
|---|---|
| `TallyVerifier` | `0x3817516c4fa354c9F24f6deCE0eA636048c54D87` (1.560 bytes) |
| `MACICoordinator` | `0x1CC218883dBeFf6aB8b4933723DF23B8F69336a6` |
| tx de enlace | `0x5851dc7d8295e2f89956b441b56d27c6625137afd511b71b43af42f59eb8d7fa` |
| Circuito | `maci_tally.circom`, 34.900 restricciones, 3 señales públicas |
| Powers of Tau | Hermez potencia 17, digest oficial verificado |
| `zkey` sha256 | `cc1dc57b63e45eb4345e73319c0bf8101f50b2f42aa104758a57a80cd0575162` |

Verificado leyendo la cadena de forma independiente, no fiándose del recibo de
la transacción.

### Esta ceremonia NO es apta para una elección vinculante

Una sola contribución, hecha localmente, sin beacon final. El propio manifiesto
lo registra: `participant_independence=not-attested-by-script`,
`beacon=not-applied`, `promotion_status=not-promoted`. **Quien ejecutó esta
ceremonia conoce el toxic waste y podría fabricar recuentos falsos.** Sirve para
integración. Antes de un uso vinculante hace falta pasar el `zkey` por
participantes independientes (`--input-zkey`) y cerrar con un beacon público
documentado.

### Correcciones a `trusted_setup.sh`

Tres, encontradas al usarlo sobre un circuito distinto de aquel para el que se
escribió:

1. **Circuito y potencia de ptau parametrizables** (`--circuit`,
   `--ptau-power`), con los digests oficiales de snarkjs fijados por potencia.
   Duplicar el script habría dejado dos copias divergiendo en los controles.
2. **Compilar antes de descargar el ptau.** El orden anterior verificaba
   criptográficamente cientos de MB *antes* de compilar, así que un circuito
   que no cabía en la potencia elegida se descubría una hora después. Ahora se
   comprueba `2^power >= 2 x restricciones` justo tras compilar: falla en
   **2,8 segundos** indicando la potencia correcta. Es exactamente lo que costó
   descubrir que `maci_tally` necesitaba potencia 17 y no 15.
3. **Cachear la verificación del transcript por digest.** Es determinista sobre
   un archivo ya fijado por hash; el marcador se indexa por ese digest y solo
   se usa tras revalidar el hash en la misma ejecución, así que no rebaja la
   garantía.

### Nota de método

La primera ejecución se dio por buena por error: se canalizó la salida a `tail`
y el `exit code 0` observado era el de `tail`, no el del script — que **había
fallado**. Las ejecuciones posteriores capturan el estado real sin tubería de
por medio.

---

## Quinta pasada (02-08-2026) — membresía on-chain y sesión web

### C-3 (cierre real): `hasMembership()` on-chain con caché corta

`backend/app/services/membership_verifier.py` — `OnChainMembershipVerifier` dejó
de lanzar `NotImplementedError`: consulta `hasMembership(address)` del SBT vía
`chain_service.has_membership()` (`backend/app/services/chain_service.py:552`),
con caché en memoria de proceso (`MEMBERSHIP_CACHE_TTL_SECONDS`, 30 s por
defecto) e invalidación explícita al mintear.

Tres decisiones que conviene no revertir por accidente:

- **Un RPC caído responde 503, no 403.** `has_membership()` lanza
  `ChainReadError` en vez de devolver `False`; `deps.is_active_member` lo
  traduce a 503. Un 403 afirmaría "esta persona no es miembro" cuando lo único
  cierto es que no se pudo consultar.
- **También se cachean las respuestas negativas.** Una dirección sin SBT que
  reintenta es justo el tráfico que no debe llegar al RPC. Por eso el minteo
  invalida la entrada: si no, quien acaba de recibir su credencial vería 403
  durante el resto del TTL.
- **La caché es por proceso.** Con varias instancias no hay coherencia entre
  ellas más allá del TTL; por eso el TTL es corto y configurable. Compartirla en
  Redis sería posible, pero añade una dependencia para ahorrar una lectura
  `view` barata.

`MEMBERSHIP_SOURCE` sigue en `mongo` en el despliegue: el contrato aún no tiene
membresías (`totalSupply()` = 0) y cambiarlo hoy dejaría a todo el mundo fuera.
`/health/ready` bloquea `onchain` si faltan `SEPOLIA_RPC_URL` o
`SBT_CONTRACT_ADDRESS`.

### P-60 (media, corregida): el peso por delegación usaba un filtro más débil que el gate

`backend/app/services/governance_service.py:81` — `get_active_delegators()`
consultaba `members` con `{"status": "active"}` a secas, mientras el gate de
votar exigía además, en producción, `issuance_mode="onchain"`,
`identity_verified=True` y `tx_hash` no vacío. Consecuencia: una fila demo o
legacy no podía votar por sí misma, pero **sí sumaba peso** al delegado que la
recibiera. Con `MEMBERSHIP_SOURCE=onchain` la divergencia habría sido mayor:
peso de direcciones sin SBT.

Corregido moviendo la consulta al propio verificador (`filter_members()`), que
es ahora el único lugar donde se define qué cuenta como membresía activa.

### Tarea 1.13 (backend): la sesión ya no obliga a `localStorage`

`backend/app/core/session.py` (nuevo) — `/wallet/verify` fija el JWT en la
cookie `dao_session` (`HttpOnly`, `Secure` fuera de local, `SameSite`
explícito) y publica un token CSRF de doble envío en `dao_csrf`, derivado como
`HMAC-SHA256(SECRET_KEY, "dao-csrf-v1:" + jwt)`. Los métodos con efectos exigen
repetirlo en `X-CSRF-Token` **solo** cuando la sesión llegó por cookie: el
header `Authorization: Bearer` no lo adjunta el navegador por su cuenta y la
app móvil no debe romperse.

Límites reconocidos, no disimulados:

- `/wallet/logout` borra las cookies pero **no revoca el JWT**, que sigue siendo
  válido hasta expirar. Una lista de revocación necesita almacenamiento
  compartido (el mismo Redis de 3.8) y no existe todavía.
- Mientras el frontend siga leyendo `token` del body, el JWT sigue pasando por
  JavaScript. El body ya se puede omitir con `session_transport: "cookie"`; el
  cierre efectivo de 1.13 depende de que el cliente lo use.
- `main.py` ya no permite `allow_credentials=True` junto a `CORS_ORIGINS=*`:
  Starlette reflejaría cualquier origen y le entregaría la cookie de sesión.

### P-61 (alta, corregida): el peso delegado se contaba dos veces

`backend/app/routers/governance.py` y `.../elections.py` — el peso aplicado se
calculaba con `voting_power()`, que suma *todos* los delegantes activos sin
mirar si ya habían votado. Dos secuencias producían más votos que miembros:

1. **A vota, luego delega en B, luego B vota.** El peso de A se contaba en su
   propia papeleta y otra vez dentro del peso de B. Comprobado antes de
   corregir: dos miembros, `votes_for = 3`.
2. **A delega en B, B vota, A revoca y vota.** La comprobación existente
   (`get_delegate_of`) solo mira la delegación *vigente*, y al revocar ya no
   había ninguna. Mismo resultado: `votes_for = 3`.

La segunda no se puede detectar mirando el grafo de delegaciones, porque la
revocación borra la única evidencia. Por eso la papeleta pasa a persistir
`delegators`: la lista exacta de direcciones cuyo peso incorporó. Con eso:

- `contest_vote_weight()` excluye a los delegantes que ya votaron en esa misma
  consulta (cubre la secuencia 1),
- `weight_already_delegated_away()` encuentra la papeleta que ya gastó el peso
  de quien intenta votar y responde **409** (cubre la secuencia 2),
- y el `weight` deja de ser un número que solo el servidor puede justificar:
  cualquiera puede recomputarlo desde las papeletas públicas, que es el
  criterio de aceptación de 3.2.

El bloqueo es **por consulta**, no global: el peso gastado en una propuesta no
impide votar en otra. Cubierto en `tests/test_governance.py` (tres casos) y en
elecciones.

### P-62 (baja, corregida): "delegación circular" para cadenas que no lo son

`backend/app/services/governance_service.py:167` — `find_delegation_cycle()`
devolvía un booleano para dos rechazos distintos (ciclo real y cadena de más de
`MAX_DELEGATION_DEPTH` saltos), y el router respondía "Delegación circular
detectada" en ambos casos. A quien eligió a alguien con una cadena larga por
detrás se le afirmaba algo falso sobre lo que había hecho, y el mensaje no
permitía corregirlo.

Ahora `delegation_block_reason()` devuelve `"cycle"` o `"depth"` y el router
redacta cada uno por separado. `find_delegation_cycle()` queda como envoltorio.

### 3.4: el antifraude estaba conectado, pero nada lo verificaba

`check_rapid_voting` sí se llamaba desde propuestas y elecciones (A-4 se cerró
en la tercera pasada), y falla cerrado cuando no hay almacén. Lo que no existía
era una prueba de que se siguiera llamando: `tests/test_antifraud.py` cubre
ahora el umbral documentado, que la ventana es por votante y no por propuesta,
que las elecciones comparten la misma ventana, el fallo cerrado sin almacén, y
las dos heurísticas del grafo de delegaciones.

La tarea 3.4 del ROADMAP pedía llamar también a `check_delegation_chain`. Esa
función **ya no existe**: se eliminó en 3.8 porque duplicaba en memoria el grafo
que MongoDB ya tenía. No se reintrodujo; la redacción del ROADMAP era lo
desactualizado.

---

## Sexta pasada (03-08-2026) — tesorería real (3.6)

`backend/app/services/treasury_service.py` (nuevo). `/governance/treasury`
devolvía `configured: false` con balances `null`: honesto, pero no era un dato.
Ahora el balance sale de `eth_getBalance` sobre `TREASURY_SAFE_ADDRESS` y el
precio de CoinGecko o Binance (`ETH_PRICE_PROVIDER`). Ningún número vive en el
código.

Verificado contra fuentes reales, no solo con dobles de test:

| Comprobación | Resultado |
|---|---|
| Sepolia, `MACICoordinator` | `chain_id` 11155111 leído de la cadena, balance 0.0, USD `null` |
| Mainnet, dirección pública | 6,632 ETH × 1866,75 USD = 12 380,91 USD |
| CoinGecko / Binance | 1866,75 y 1868,97 USD/ETH — los dos parsers contra la API real |

### El ETH de testnet no se convierte a USD

Es la decisión de diseño principal. Si `chain_id != 1`, `total_usd_value` es
`null` con motivo explícito, aunque haya proveedor de precio configurado. Un
Safe en Sepolia tiene ETH sin valor de mercado: mostrar "$X" en el panel del
ciudadano sería el mismo fraude que la tesorería ficticia que se borró en la
Fase 0, esta vez con un decimal creíble. El balance en ETH **sí** se publica,
porque ese sí se leyó de la cadena.

### Tres estados distinguibles

`sin configurar` (`configured: false`), `configurada pero el RPC no responde`
(`configured: true`, `balances: null`, `error`) y `leída` (`balances` con su
valor, que puede ser `0.0`). Un fallo de lectura nunca se degrada a un balance
de cero, que es la forma más fácil de anunciar una tesorería vacía que no lo
está.

### Alcance declarado: solo ETH nativo

La respuesta incluye `assets_covered: ["ETH"]`. Los ERC-20 que pueda tener el
Safe **no se leen todavía**, y sumarlos al total en USD exigiría un precio por
token. Antes que publicar un total que ignora en silencio la mitad del
patrimonio, la respuesta dice qué cubre. Queda como pendiente explícito de 3.6.

### Defensas del feed de precio

- Rango de cordura (1 – 1 000 000 USD): un proveedor que cambie de formato o
  devuelva basura no multiplica el balance por un número cualquiera.
- Degradación marcada: si el proveedor falla se sirve el último precio conocido
  con `stale: true` hasta `ETH_PRICE_STALE_MAX_SECONDS`; pasado ese margen, se
  reporta ausente. Un precio viejo sin etiqueta sería una afirmación falsa.
- Caché del snapshot: `/governance/treasury` es público y sin autenticar; sin
  caché, refrescar el panel en bucle convertiría a cualquier visitante en un
  amplificador contra el RPC y contra la API de precios.

### `runway_months` deja de ser `null` por definición

Se calcula contra el balance real dividido por el gasto mensual observado, con
un suelo de un mes (sin él, tres gastos del mismo día darían un runway de casi
cero). Si hay gastos en otra moneda se devuelve `null` con
`runway_unavailable_reason`, en vez de inventar la conversión.

---

## Séptima pasada (03-08-2026) — lectura eMRTD de la cédula (4.2)

Implementación del módulo nativo Android (`PassportReaderModule.kt` +
`PassiveAuthenticator.kt`) y del ciclo de sesión NFC en iOS. Al construir sobre
el andamiaje existente aparecieron cinco problemas; los tres primeros impedían
que la funcionalidad existiera siquiera.

### P-63 (crítica, corregida): el puente JS fijaba `identityVerified: true`

`mobile/src/services/nfcService.ts:185` — el resultado nativo se descartaba:

```js
const result = await PassportReader.startPACESession(can);
return { success: true, identityVerified: true, /* ... */ };  // constante
```

Con esa línea, **toda la criptografía del módulo nativo era decorativa**:
cualquier respuesta que no lanzara excepción se reportaba como identidad
verificada, incluida una cédula cuya cadena de confianza NO valida y —hoy
siempre— un build sin certificado CSCA instalado. Es el mismo patrón que el
propio archivo documenta haber eliminado antes en `readChileanID`. Ahora
propaga el veredicto del nativo y el detalle por paso.

### P-64 (alta, corregida): JMRTD 0.7.18 es incompatible con BouncyCastle ≥ 1.75

`mobile/android/app/build.gradle` declaraba `bcprov-jdk15to18:1.77` mientras
JMRTD arrastra `bcprov-jdk15on:1.64`. Dos consecuencias, ambas verificadas
ejecutando:

1. Con los dos artefactos, `checkDebugDuplicateClasses` **aborta el APK**: son
   las mismas clases con distinto nombre de módulo.
2. Excluyendo el viejo y quedándose con 1.77, el APK compila **pero el EF.SOD
   revienta en runtime** con
   `NoSuchMethodError: ASN1TaggedObject.getObject()`. BouncyCastle eliminó ese
   método en 1.75 y JMRTD lo llama al parsear el SOD.

El segundo caso es el peligroso: sin un test que ejecute la criptografía, el
fallo solo habría aparecido con una cédula real en la mano. Comprobado con
`javap` sobre 1.68/1.70/1.71/1.72/1.73/**1.74**/1.75/1.76/1.77: **1.74 es la
última versión con esa API**. Se fija ahí — diez años menos de CVEs que la 1.64
de JMRTD e incluye el arreglo de CVE-2023-33201. Subir de 1.74 exige actualizar
JMRTD primero.

### P-65 (media, corregida): las dependencias eMRTD no estaban en la verificación

El proyecto usa dependency verification de Gradle
(`mobile/android/gradle/verification-metadata.xml`, 1068 componentes fijados),
pero los 8 artefactos nuevos de JMRTD/scuba/BouncyCastle no tenían checksum, así
que **cualquier tarea que resolviera el classpath fallaba**. Añadidos con
`--write-verification-metadata sha256`; el `jmrtd-0.7.18.jar` se contrastó
además contra el `.sha1` publicado en Maven Central (coinciden). Es fijado
TOFU sobre HTTPS: detecta manipulación futura, no certifica el artefacto
original.

### Sin certificado CSCA no hay identidad verificada

`android/app/src/main/assets/csca/` está **vacío a propósito** y su README
explica por qué. Mientras no contenga el certificado del Registro Civil, la
autenticación pasiva falla en el paso 3 e `identityVerified` es `false`, aunque
los hashes y la firma del SOD sean correctos. Es el comportamiento correcto: un
documento falsificado trae su propia cadena y verifica consigo mismo — hay un
test que lo demuestra. El endpoint `/api/csca-masterlist` que ADR-004 propone
como mitigación de rotación **tampoco existe todavía** en el backend.

### Qué está verificado y qué no

| Comprobación | Estado |
|---|---|
| Autenticación pasiva (hashes, firma, cadena, falsificación) | ✅ 6 tests JVM con documentos sintéticos |
| Compilación del módulo y APK debug | ✅ `assembleDebug` |
| Swift contra el SDK de iOS 18.5 | ✅ `swiftc -typecheck` |
| Suite JS y TypeScript | ✅ 15 tests, `tsc --noEmit` limpio |
| **PACE, secure messaging y parseo de un DG1 real** | ❌ **requiere cédula física** |
| **iOS: PACE** | ❌ no implementado; falta la librería eMRTD |

Nada de esto acredita todavía una identidad civil: 4.2 sigue 🟡.

---

## Octava pasada (03-08-2026) — ciclo de vida de la PII (1.3, 1.4, 1.11)

### 1.11 — unicidad por PERSONA, no solo por wallet

`backend/app/core/database.py` — el índice único de `members.wallet_address`
impedía dos membresías para la misma wallet, pero nada impedía que **la misma
persona minteara con dos wallets distintas**. Desde D-2 el valor que identifica
a una persona es el nullifier del circuito (se deriva de su secreto de
identidad y del scope del contrato), así que se añade un índice único sobre
`members.nullifier_hash`.

Es **parcial** (`{"nullifier_hash": {"$type": "string"}}`), no `sparse`: las
filas demo/legacy tienen `null` y varios `null` colisionarían en un índice
único normal, impidiendo incluso crearlo. Comprobado quitando el índice: el
test correspondiente falla.

### 1.3 — la llave que no se podía rotar

`backend/app/core/crypto.py` — había **una** `PII_ENCRYPTION_KEY`. Si se
filtraba, la única salida era descifrar y volver a cifrar todo a mano con la
aplicación parada; en la práctica, eso significa no rotarla nunca.

Ahora `PII_ENCRYPTION_KEYS` acepta varias llaves (MultiFernet): se cifra con la
primera y se descifra con cualquiera, así que publicar una llave nueva no
invalida ni un registro. `scripts/pii_maintenance.py rotate-pii` los reescribe
en caliente y `status` dice cuántos faltan antes de poder retirar la vieja.

El pepper es peor que la llave y merece mención aparte: los índices ciegos
(`rut_key`, `email_key`) son derivaciones determinísticas suyas, así que
cambiarlo **deja a todo el mundo fuera de sesión al instante**.
`IDENTITY_PEPPER_PREVIOUS` abre una ventana en la que las consultas prueban con
ambos (`lookup_key_candidates`), cubierta por un test extremo a extremo que
registra con un pepper y entra con el siguiente.

**Lo que NO se hizo: KMS.** Las llaves siguen en variables de entorno; quien
pueda leer el entorno del proceso puede leerlas. Lo resuelto es la *mecánica*
de rotación, que era el bloqueo real para adoptar un KMS. `crypto._load_keys()`
es el único punto que materializa llaves y es donde entraría. `/health/ready`
lo declara con `"key_custody": "environment"` en vez de dejar creer que la
custodia está resuelta.

### 1.4 — política de retención declarada, y qué NO se borra

`backend/app/core/retention.py` — cifrar responde a "si roban el volcado, ¿qué
ven?", no a "¿por qué seguimos guardando esto?". La política vive ahora en un
solo módulo, como datos auditables, y los índices TTL se derivan de ella en vez
de estar repartidos a mano por `ensure_indexes`.

Dos reglas que no conviene revertir sin pensarlo:

- **Los registros de ciudadanos no se borran automáticamente.**
  `INACTIVE_USER_RETENTION_DAYS` viene en 0. Eliminar el registro civil de una
  persona es una decisión de gobernanza, no el efecto secundario de un TTL que
  alguien configuró un martes. La regla existe y el script la ejecuta, pero hay
  que activarla explícitamente.
- **`ballot_nonces` y `mint_operations` no caducan.** Son justamente la memoria
  de "esto ya pasó": purgarlos por antigüedad reabre la ventana de repetición
  que cierran. Hay un test que lo fija.

### La herramienta de migración está probada, no solo escrita

La lógica vive en `app/services/pii_maintenance.py` y no dentro del script,
para poder ejecutarla en los tests. Una herramienta que reescribe PII de
ciudadanos y que nadie ejecutó nunca es exactamente lo que este repositorio no
permite; el momento de descubrir que rota mal es antes de tocar producción.

Todos los subcomandos van **en seco por defecto** y solo escriben con
`--apply`. Cubierto por tests: que el modo seco no escribe, que la rotación
alcanza los cuatro campos cifrados sin alterar el contenido, que la PII legacy
en texto plano se cifra, que un documento ilegible **se reporta en vez de
saltarse en silencio** (perder eso pierde datos para siempre) y que reindexar
cierra una rotación de pepper.

385 tests (362 antes).

---

## Novena pasada (03-08-2026) — observabilidad y regresión en iOS

### P-66 (alta, corregida y rectificada): cadena documental iOS

`mobile/ios/DAOCiudadanaApp/PassportReader.swift` — la primera descripción de
este hallazgo invirtió dos nombres contraintuitivos de `NFCPassportReader`.
Leyendo las implementaciones, no sus etiquetas:

- `passportDataNotTampered` compara hashes DG↔EF.SOD;
- `documentSigningCertificateVerified` valida la firma CMS/RFC 5652 del SOD
  con el Document Signer;
- `passportCorrectlySigned` construye la cadena Document Signer→CSCA contra el
  `CAFile` recibido.

Por tanto, con `masterListURL: nil`, `passportCorrectlySigned` queda falso: esa
versión concreta no habría aprobado la cadena por sí sola. La conclusión
histórica de que ese flag sólo era "coherencia interna" era incorrecta y se
rectifica aquí. La brecha real era distinta y más básica: los archivos
`PassportReader.swift`/`.m` no estaban en Sources del target Xcode, por lo que
el bridge auditado no existía en el binario; además, una revisión intermedia
abría una sesión CoreNFC y luego pedía a la librería abrir una segunda.

Corregido: ambos archivos pertenecen al target, una sola instancia
`NFCPassportReader.PassportReader(masterListURL:)` posee la sesión, y el
veredicto exige PACE, DG1/DG2/SOD, perfil/emisor chileno, hashes, firma SOD y
cadena CSCA. La ausencia del PEM aborta antes de abrir NFC.

La corrección todavía no equivale a acreditar una cédula: falta el trust store
autorizado y un test físico iOS. Ambos permanecen bloqueantes explícitos.

### P-67 (media, corregida): `/metrics` público

`backend/main.py` — `Instrumentator().instrument(app).expose(app)` publica
`/metrics` **sin autenticación**. Comprobado con una petición real: 200 y el
volcado completo. No contiene PII, pero sí el inventario de rutas (incluidas
las no documentadas), el volumen de tráfico por endpoint, las latencias y el
recuento de errores.

Ahora la ruta la sirve `app/routers/metrics.py` detrás de `METRICS_TOKEN`
(comparación con `compare_digest`). En producción, habilitar métricas sin token
responde 503 **y** aparece como bloqueante en `/health/ready`; fuera de
producción se sirve sin token con un aviso en los logs.

### Sentry: dos ajustes

- `send_default_pii=False` explícito. Es el valor por defecto del SDK, pero
  esta API procesa RUT, email y nombres: que esté escrito obliga a que
  activarlo sea una decisión revisable y no un descuido.
- `traces_sample_rate` configurable, por defecto 0.1 en vez de 1.0. Enviar el
  100% de las transacciones es caro y ruidoso.

391 tests (385 antes).

---

## Décima pasada (04-08-2026) — balances ERC-20 de la tesorería (3.6b)

Cierra el hueco declarado en la sexta pasada: `assets_covered` ya no dice
`["ETH"]` mientras el Safe puede tener la mitad del patrimonio en tokens.

### Lo que se lee y lo que no

Se consultan el ETH nativo y **solo** los ERC-20 declarados en
`TREASURY_TOKENS`. `assets_covered` enumera exactamente eso: si el Safe tiene
otro token que nadie configuró, no aparece y el total no lo incluye. No se
descubren tokens automáticamente — hacerlo exigiría indexar transferencias y
abriría la puerta a que cualquiera "regale" un token de humo al Safe para
inflar la cifra que ve el ciudadano.

`decimals()` y `symbol()` se leen de la cadena, nunca se suponen: USDC tiene 6
decimales y asumir 18 mostraría el saldo un billón de veces menor. Si un token
antiguo devuelve `symbol()` como bytes32 y la llamada falla, el saldo se
conserva y la etiqueta pasa a derivarse de la dirección con
`symbol_source: "address"`, para que quede claro que es una etiqueta nuestra y
no lo que declara el contrato.

### Un activo sin precio no vale cero

Es la decisión de diseño de esta entrega. Si algún activo **con saldo** no
tiene precio conocido, `total_usd_value` es `null` con
`total_usd_unavailable_reason`, en vez de sumar solo lo que sí tiene precio y
llamarlo total. Un total parcial presentado como total hace parecer la
tesorería más pequeña de lo que es, que es la misma clase de mentira que
inflarla. Un saldo cero sin precio no anula nada: aporta cero valga lo que
valga.

### P-68 (media, corregida antes de commitear): CoinGecko admite un contrato por petición

La primera implementación agrupaba las direcciones en una sola llamada
(`contract_addresses=a,b`). Contra mainnet devuelve **400 con
`error_code 10012`**: el plan gratuito permite una única dirección por
petición. Se descubrió ejecutando contra la red real, no leyendo la
documentación; con dobles de test habría pasado inadvertido y el panel habría
mostrado el total en `null` para siempre sin motivo aparente.

Ahora se consulta un token por petición, un fallo individual no arrastra a los
demás y solo se recurre a la caché obsoleta si fallan todos.

### Verificación contra la cadena real

Sobre una dirección pública de mainnet, con USDC y DAI reales:

| Activo | Saldo leído | Decimales | Precio | Valor |
|---|---|---|---|---|
| ETH | 6,632333 | 18 | 1862,36 | 12 351,79 |
| USDC | 37,192124 | 6 | 0,99953 | 37,17 |
| DAI | 4,572078 | 18 | 0,999878 | 4,57 |
| **Total** | | | | **12 393,54 USD** |

Los decimales distintos (6 y 18) confirman que se leen de cada contrato.

Cubierto además por 11 tests nuevos: total consolidado, activo sin precio que
anula el total, saldo cero que no lo anula, token ilegible que deja
`balances: null` en vez de cero, decimales absurdos rechazados, token sin
símbolo, tokens de testnet sin precio, dirección inválida y exceso de tokens
como error de configuración visible en `/health/ready`.

402 tests (391 antes).

---

## Undécima pasada (04-08-2026) — recuento reconstruible (3.10)

### P-69 (alta, corregida): la finalización de una elección no se reintentaba nunca

`backend/app/services/governance_service.py` — la causa raíz era más profunda
que el `insert_many` no atómico. `sync_election_status` llamaba a
`finalize_election` **solo en la transición de estado**:

```python
if derived != election.get("status"):
    ...
    if derived == "closed":
        await cls.finalize_election(election)
```

Una vez persistido `status: "closed"`, esa rama no volvía a entrar jamás. Y
`finalize_election` empezaba con "si ya existe cualquier representante, salir".
Combinados: si el proceso moría a mitad del `insert_many` —que no es atómico
entre documentos— quedaba un parlamento con tres escaños de cinco, **para
siempre**, y sin ninguna señal visible: la lista de representantes se ve
perfectamente normal, solo que le faltan personas.

Corregido con el patrón de marca de commit, sin transacciones (exigirían
replica set, que el despliegue actual no tiene):

- `finalize_election` reconcilia en vez de insertar: `upsert` por
  (election_id, address) con índice único, y borra a quien ya no salga
  elegido. Reejecutarla no cambia nada.
- `finalized_at` se escribe **al final**, después de reconciliar. Su ausencia
  significa exactamente "esto no terminó", así que la siguiente lectura lo
  reintenta.

Verificado con una caída simulada fiel (escaños parciales + marca ausente) y
con mutación: revertir la condición hace fallar el test.

### Reconstrucción desde firmas válidas

`backend/app/services/tally_service.py` (nuevo) y los endpoints públicos
`/governance/proposals/{id}/audit` y `/governance/elections/{id}/audit`.

Derivar los totales de las papeletas elimina la divergencia, pero por sí solo
solo significa "confiamos en otra colección del mismo servidor". La auditoría
recomputa el resultado desde cero comprobando, papeleta a papeleta:

1. que la firma EIP-712 recupera exactamente la dirección del votante,
2. que el peso declarado cuadra con su composición (`1 + len(delegators)`,
   persistida desde P-61) — un peso inflado a mano en la base se detecta,
3. que no hay dos papeletas del mismo votante.

Lo que no pasa esas tres no se cuenta y aparece en `rejected` con su motivo.
`matches` dice si el recuento verificado coincide con el publicado.

Las papeletas sin firma se cuentan solo mientras `SIGNED_BALLOTS_REQUIRED`
esté apagado (piloto) y **siempre** se reportan en `ballots_unsigned`: nadie
debe leer "auditado" como "criptográficamente probado" cuando parte del censo
no lleva firma.

Los endpoints son públicos y sin autenticación a propósito — un resultado que
solo puede comprobar quien tiene sesión no es verificable, es una promesa. La
recuperación de firmantes se ejecuta en un hilo (es CPU y bloquearía el event
loop) y hay un tope de 5000 papeletas por auditoría, declarado en `truncated`.

### Dos cosas que quedaron mintiendo, corregidas

- **Contadores muertos.** Las propuestas seguían guardando `votes_for: 0` y
  compañía al crearse, aunque los totales ya se derivaban. Un `0` con pinta de
  dato autoritativo que nadie actualiza es la divergencia que esta fase
  elimina, solo que en diferido. Se dejaron de persistir.
- **Bloqueante obsoleto de readiness.** `deployment_blockers()` afirmaba
  incondicionalmente que "el recuento de elecciones aún no es transaccional ni
  reconstruible desde las papeletas". Ya no es cierto; lo que sigue bloqueando
  es publicar resultados sin exigir firmas, y de eso ya se encarga el
  bloqueante de `SIGNED_BALLOTS_REQUIRED`.

414 tests (402 antes).

---

## Duodécima pasada (04-08-2026) — ERC-4337: lo que faltaba de verdad (D-1)

Se reportó que el backend "no soporta la recepción ni retransmisión al
Bundler". **Es inexacto**: `app/routers/erc4337.py` ya implementaba el flujo
completo —`/config`, `/prepare-mint`, `/submit-mint`, `/operations/{hash}`—
con validación de derivación CREATE2 de la Safe, binding del owner, decodifi-
cación de las dos capas del callData, comprobación de que la prueba declarada
es la ejecutada, rechazo si el Paymaster altera campos inmutables, idempotencia
por nullifier y reconciliación del estado. El EntryPoint canónico v0.7
(`0x0000000071727De22E5E9d8BAf0edAc6f37da032`) ya estaba fijado.

Lo que realmente bloquea el flujo es **configuración**: `ERC4337_ENABLED=false`
y sin `BUNDLER_RPC_URL`, todo falla cerrado con 503. Esa credencial la tiene
que inyectar el operador; inventarla no es una opción.

Auditando el camino aparecieron dos defectos reales.

### P-70 (alta, corregida): el minteo patrocinado no creaba la membresía

`app/routers/erc4337.py` — al confirmarse la operación se actualizaba el
registro de `erc4337_operations` con el `token_id`, pero **`members` no se
tocaba nunca**. El camino del relayer (`/membership/mint-zk`) sí llamaba a
`_reconcile_member_record`; el de ERC-4337 se había quedado atrás.

Consecuencia: el ciudadano recibía su SBT on-chain —el objetivo entero de D-1,
onboarding sin gas— y **quedaba fuera de la gobernanza**, porque el gate de
membresía consulta MongoDB (`MEMBERSHIP_SOURCE=mongo`). Credencial válida,
imposible votar, y sin ningún error que lo explicara.

La reconciliación se movió a `app/services/membership_records.py` para que los
dos caminos compartan exactamente el mismo registro; tenerla duplicada en cada
router fue precisamente lo que permitió que uno se quedara atrás.

### P-71 (media, corregida): se retransmitía sin verificar la firma SafeOp

`/submit-mint` comprobaba que solo el campo `signature` hubiera cambiado
respecto a lo preparado, pero **no verificaba la firma**. El EntryPoint la
habría rechazado on-chain, así que no era un agujero de autorización, pero:

* el ciudadano recibía un error opaco del bundler tras un viaje de ida y vuelta,
* y el backend retransmitía una operación cuya autorización nadie había mirado.

El propio docstring de `paymaster_service.sign_user_operation` decía que
`safe_op_digest` se conservaba "para VALIDAR que la firma recibida corresponde
al owner declarado". La intención estaba escrita; el cableado no existía.

Ahora `safe_4337.recover_owner()` recupera el firmante del digest EIP-712 y
`/submit-mint` responde 422 sin retransmitir si no es el propietario. Se
admiten las dos convenciones reales: `v` 27/28 (firma EIP-712 directa) y `v`
31/32 (variante de Safe en que el digest va envuelto en el prefijo de
`personal_sign`). Verificar no es firmar: el backend sigue sin ser propietario
ni custodio de ninguna Safe.

### Sobre Biconomy

`PAYMASTER_SPONSOR_METHOD` es configurable y el parseo acepta la forma de
respuesta de Pimlico/Alchemy. **No se ha probado contra Biconomy** y no se
declara compatible: su API v2 usa parámetros propios (`mode`,
`sponsorshipInfo`) que no se pueden implementar a ciegas. Añadir código
específico sin credenciales para ejecutarlo sería exactamente la capacidad
fingida que este repositorio no admite.

420 tests (414 antes).

---

## Decimotercera pasada (03-08-2026) — MACI: cliente compatible, protocolo aún cerrado

Al ejecutar el cifrado web contra el WASM real de `processMessages` apareció
una diferencia que los tests anteriores ocultaban: el cliente usaba el
`PCommand.encrypt` de MACI 2.5 de referencia, pero el circuito de este
repositorio aprobó otro wire format. La revisión cruzada descubrió además tres
fallos críticos independientes. Por eso `/maci/status` y
`accepting_messages` deben seguir en `false`.

| ID | Hallazgo | Ubicación | Severidad | Estado |
|---|---|---|---|---|
| P-72 | El navegador cifraba el `PCommand` empaquetado de referencia; `processMessages` espera diez campos explícitos, firma Poseidon de seis campos y stream aditivo Poseidon. Los tests sólo descifraban con la misma librería JS y no ejecutaban el circuito | `frontend/src/lib/maci.js:339`; `circuits/processMessages.circom:30` | **Crítica (disponibilidad/integridad electoral)** | 🟢 Corregida en frontend: `frontend/src/lib/maci.js:349-405` implementa la frontera aprobada. Se generó un testigo válido con `circuits/build/process/processMessages_js/processMessages.wasm`; el test unitario conserva descifrado y verificación cruzada de firma |
| P-73 | `pollId` no forma parte del comando firmado ni de `messageHash`; `stateIndex` se firma pero nunca se ata a `pathIndices`. Además, el nonce no está en `StateLeaf`: `currentNonce` es una entrada privada que el coordinador puede escoger en cada prueba | `circuits/processMessages.circom:45-49`; `circuits/processMessages.circom:80-98`; `circuits/processMessages.circom:135-148`; `circuits/processMessages.circom:183-201`; `circuits/processMessages.circom:266-275` | **Crítica (replay y sustitución de estado)** | 🔴 Abierta. El frontend exige `poll_bound_messages=true` y `stateful_nonces=true` antes de habilitar el envío (`frontend/src/components/governance/VotingBallot.jsx:58-69`) |
| P-74 | El circuito de tally acepta la misma hoja y ruta en las cinco posiciones del batch y suma las cinco. Se reprodujo con el WASM: una sola hoja válida produjo `[5,0,0]` | `circuits/maci_tally.circom:129-170`; `circuits/maci_tally.circom:199-207` | **Crítica (multiplicación de votos)** | 🔴 Abierta. Falta demostrar índices distintos/cobertura; el frontend exige `unique_tally_leaves=true` |
| P-75 | El pipeline no enlaza las raíces de `processMessages` con el tally y contrato/circuito discrepan en sus tres señales públicas: el circuito declara raíces/compromisos; `publishTally` entrega message chain, censo y compromiso. Mongo tampoco publica on-chain y su SHA-256 de strings difiere del `keccak256(abi.encode(...))` del contrato | `circuits/processMessages.circom:285`; `circuits/maci_tally.circom:233-237`; `contracts/contracts/MACICoordinator.sol:284-292`; `contracts/contracts/MACICoordinator.sol:325-331`; `backend/app/services/maci_service.py:465-490` | **Crítica (tally no verificable/pipeline inoperante)** | 🔴 Abierta. Los tests Solidity usan un verifier mock. El frontend exige `process_tally_linked=true` y mantiene fail-closed |
| P-76 | Elecciones web enviaba `voter_address`, `candidate_address`, nonce y firma EIP-712 al endpoint en claro; la firma autentica, pero no oculta la preferencia | `frontend/src/components/governance/ElectionsList.jsx` (flujo retirado); `backend/app/routers/elections.py:423`; `frontend/src/lib/api.js:428-430` | **Alta (privacidad electoral)** | 🟡 Cerrada en frontend: se eliminó el método de transporte y el CTA queda bloqueado con estado explícito (`frontend/src/components/governance/ElectionsList.jsx:271-335`). Backend/contrato MACI para elecciones sigue pendiente |
| P-77 | El backend devuelve `{ok,index,message_chain,duplicate}`, pero la UI exigía `message_id`, `message_hash` o `tx_hash`; una recepción 200 real se presentaba como error y podía reintentarse indefinidamente | `backend/app/services/maci_service.py:455-490`; `frontend/src/lib/api.js:363-381` | **Alta (idempotencia/disponibilidad)** | 🟢 Corregida: el cliente valida índice y acumulador canónicos y muestra la referencia completa |

La UI tampoco presenta ya los conteos parciales de propuestas activas como si
fueran compatibles con una urna cifrada. Las fases visuales se mueven sólo por
eventos reales —llave, registro público, poll, anclaje, cifrado y publicación—,
sin porcentajes ni progreso simulado.

Los requisitos de contrato/circuito y el endpoint MACI pendiente para
elecciones quedaron detallados en `REQUEST_TO_CLAUDE.md`, sin modificar
`backend/`, `contracts/` ni `circuits/`.

---

## Decimocuarta pasada (04-08-2026) — ClaveÚnica OIDC real (4.1)

`backend/app/services/clave_unica.py` y `backend/app/routers/clave_unica.py`.

### El simulador se eliminó, no se dejó al lado

`POST /api/auth/clave-unica` aceptaba **cualquier RUT con formato válido** y
devolvía `demo:clave-unica:<uuid>` con un `assurance_level` inventado. No
autenticaba a nadie. Mantenerlo junto al flujo real dejaría dos puertas donde
una finge identidad civil (AGENTS.md, regla 2). Ahora responde **410** con la
ruta correcta, en vez de un 404 mudo, porque podía haber clientes desplegados
llamándolo. El frontend actual ya no expone ni consume ese método.

### Lo que NO se tocó, y por qué

El router `/auth` conserva su dependencia que responde 503 en producción.
Implementar ClaveÚnica no vuelve reales el NFC demo ni el liveness: el primero
no lee PACE (eso es 4.2, en el módulo nativo) y el segundo es una heurística
sobre una sola imagen. Por eso ClaveÚnica vive en un router APARTE, que sí
funciona en producción cuando está configurado. Hay un test que fija que los
demos siguen bloqueados.

### Decisiones de seguridad

* **El algoritmo de firma se fija por configuración** (`CLAVE_UNICA_ID_TOKEN_ALG`)
  y jamás se lee de la cabecera del token. Es la defensa contra la confusión
  de algoritmos: con un JWKS RS256 publicado, un atacante firma con HMAC
  usando la clave pública —que es pública— y el token pasaría. Hay un test que
  forja ese token **a mano**, porque PyJWT se niega a producirlo.
* **`state`, `nonce` y verificador PKCE viven en el servidor**, atados entre
  sí, con TTL y de un solo uso. El `state` se consume con un
  `find_one_and_update` atómico: dos callbacks con el mismo código no producen
  dos grants.
* **RS256 sin JWKS es error de configuración.** Sin clave pública no se puede
  verificar, y "no verificar" no es una opción.
* **El dígito verificador del RUN se recalcula.** Un RUN cuyo DV no cuadra no
  es un RUN, lo firme quien lo firme.
* **Si el RUN no aparece, se falla.** No se deriva un identificador del `sub`
  ni se inventa nada: sin RUN no hay identidad civil que acreditar.
* **UserInfo debe hablar del mismo sujeto** que el `id_token`. Mezclar dos
  acreditaría a la persona equivocada.

### Qué queda del ciudadano en la base

El RUN **no se persiste en ninguna parte**. Solo su índice ciego HMAC
(`subject_key`), con el mismo pepper y la misma separación de dominio que el
resto, así que rota con `pii_maintenance.py reindex-lookups`. El `id_token`
tampoco se guarda. Hay un test que serializa el documento del grant y
comprueba que el RUN no aparece.

El intento de login (verificador PKCE y nonce) caduca solo: se añadió a la
política de retención con TTL igual a `CLAVE_UNICA_LOGIN_TTL_SECONDS`.

### Lo que NO está verificado

**Nada se ha probado contra ClaveÚnica.** No hay credenciales ni acceso al
sandbox de la División de Gobierno Digital, y por eso tampoco hay endpoints
por defecto en `.env.example`: escribir una URL "de memoria" del proveedor del
Estado sería inventar su configuración. Los 27 tests usan un IdP falso con
claves generadas en el momento; cubren el protocolo y los ataques, no la
interoperabilidad real. El trámite administrativo sigue siendo el camino
crítico de 4.1.

446 tests (420 antes).

---

## Decimoquinta pasada (04-08-2026) — fronteras reales de identidad web/iOS

### P-78 (crítica, corregida en backend y web): PKCE sin binding de navegador

`backend/app/routers/clave_unica.py:61-107` — `/authorize` no fija un secreto
de navegador y `/callback` acepta públicamente `code + state`. El backend
conserva el `code_verifier`, por lo que otro cliente que obtenga esos dos
valores puede usar el endpoint como oráculo PKCE y recibir el grant civil. El
`state` one-shot evita replay, pero no demuestra qué navegador lo canjeó.

El cliente no pretende compensar una frontera backend con JavaScript:
`frontend/src/lib/claveUnica.js` exige un status versionado con
`browser_bound`, `credential_exchange_browser_bound`, `callback_idempotent` y
`grant_single_use` verdaderos antes de redirigir y antes del canje. El segundo
binding es necesario porque proteger sólo `/callback` deja el grant bearer
transferible al pedir `/identity-credential` desde otra sesión/wallet. Como el
endpoint status aún no existe, el flujo permanece bloqueado sin fallback demo.
El contrato y las pruebas negativas requeridas quedaron en
`REQUEST_TO_CLAUDE.md`.

### P-79 (crítica, código corregido; build/dispositivo pendientes): bridge NFC ausente del binario

`mobile/ios/DAOCiudadanaApp.xcodeproj/project.pbxproj:109-122` — el proyecto
compilaba sólo `AppDelegate.swift`: los dos archivos del módulo React Native no
pertenecían a Sources. La revisión anterior de P-66 auditó código muerto.
Además, ese bridge abría CoreNFC y luego llamaba a una librería que abre su
propia sesión, una combinación que no puede completar una lectura.

Ahora ambos archivos están incluidos en Sources y una sola
`NFCPassportReader.PassportReader` posee la sesión. El AND de
`mobile/ios/DAOCiudadanaApp/PassportReader.swift` exige explícitamente
`documentSigningCertificateVerified == true`, cadena DS→CSCA, hashes,
PACE-CAN sin fallback BAC, DG1/DG2/SOD, emisor `CHL`, perfil de cédula,
vigencia, una CSCA chilena usada realmente por la cadena y al menos una ancla.
El fork pudo emitir un módulo Swift arm64/iOS 15 y el bridge pasó `typecheck`
contra ese módulo, OpenSSL, React Core y Yoga. Falta enlazar la aplicación con
un build Xcode integral y ejecutarla sobre hardware; por esa razón no se marca
4.2 completa.

### P-80 (alta, abierta): el proyecto no dispone de una Master List chilena con procedencia aprobada

Los dos PEM encontrados bajo los ejemplos de `NFCPassportReader` no son
aceptables: uno es un certificado autofirmado de prueba y el otro es una lista
grande sin manifiesto que permita reconstruir origen ICAO, fecha, firma,
licencia y fingerprints validados por segundo canal. Promover cualquiera a
trust store cambiaría un `nil` honesto por confianza no demostrada.

`mobile/scripts/install-csca-master-list.sh` y
`.github/workflows/mobile-release.yml` implementan el aprovisionamiento desde
environment protegido: el release falla si falta el PEM/SHA-256, valida su
estructura, rechaza cualquier ancla cuyo país no sea Chile, lo instala en el
bundle y vuelve a comparar la huella extraída del IPA. El bridge además exige
que la CSCA elegida por OpenSSL sea chilena y del Registro Civil. **No se
incorporó ningún certificado al repositorio.**
Sigue faltando que el dueño entregue/autorice el artefacto oficial y su huella
obtenida por un canal independiente.

El instalador se ejercitó además con certificados OpenSSL sintéticos en
`/private/tmp`: instaló byte a byte una CA chilena con SHA-256 correcto y
rechazó una huella incorrecta, una CA sólo extranjera, un bundle mixto
chileno/extranjero y un certificado chileno con `CA:FALSE`. Sin fuente, el
modo distribución falló y el modo no distribución avisó sin inventar una
ancla. Son siete regresiones del mecanismo de aprovisionamiento; no acreditan
la procedencia de una CSCA real.

### P-81 (crítica, cliente corregido; contrato backend abierto): booleano NFC autorizaba alta

`mobile/src/screens/WalletScreen.tsx:70-99` — después de una lectura local, la
app usaba un serial/UID como `docHash` de placeholder y pedía minteo con
assurance alto. Un booleano de React Native, aun derivado de criptografía local,
no es una atestación que el servidor pueda confiar: un cliente modificado lo
puede fabricar.

Se retiró el autominteo. La wallet puede abrir una sesión y consultar una
membresía existente, pero una alta nueva muestra el bloqueo explícito y no
llama al backend. Falta ratificar una atestación verificable o decidir que NFC
no emite; `REQUEST_TO_CLAUDE.md` exige que cualquier solución termine en el
mismo grant corto, one-shot y ligado a SIWE, nunca en un UID/hash declarado por
el cliente.

### P-82 (alta, parcialmente corregida): fork PACE-CAN no validado y material secreto en logs

`mobile/ios/NFCPassportReader/Sources/NFCPassportReader/` — el fork imprimía a
OSLog CAN/MRZ, claves derivadas y de sesión, nonces, shared secrets, tokens y
APDU con contenido documental. Esos logs se retiraron. También se corrigió el
alcance de `paceKeyReference`, que impedía compilar el fork, se prohibió el
fallback BAC para CAN y se añadió cancelación de la sesión CoreNFC propietaria.

El soporte CAN sigue sin validación upstream ni prueba física chilena; la
propia base 2.3.3 lo describe como no soportado. El bridge exige
`PACEStatus.success` y rechaza el fallback BAC, de modo que esta incertidumbre
produce indisponibilidad explícita, no identidad falsa. Procedencia y cambios
locales están registrados en
`mobile/ios/NFCPassportReader/DAO-PROVENANCE.md`; cerrar el hallazgo requiere
vectores o cédula física, CAN correcto/erróneo y evidencia reproducible.

En web pasaron las 90 pruebas y un E2E de navegador contra el fixture del
contrato OIDC seguro → emisión ZK subsidiada, manteniendo MACI cerrado. No es
una prueba contra el backend/IdP real. En mobile pasaron 43 pruebas y
`tsc --noEmit`. `testDebugUnitTest` pasó al invocar explícitamente el binario
cacheado Gradle 9.0.0 (`BUILD SUCCESSFUL`, 221 tareas), pero eso no demuestra
el gate normal: el wrapper del árbol de trabajo apunta a Gradle 9.6.1 y falla
en `:gradle-plugin:settings-plugin:compileKotlin` por metadata Kotlin 2.3.0
incompatible con el compilador 2.1.0. El fork iOS sí emitió un módulo Swift
arm64 y el bridge pasó comprobación semántica contra OpenSSL/React, pero el
build integral terminó antes de compilar la app (exit 70): Xcode informó que la
plataforma iOS 18.5 no estaba instalada. Esa comprobación no demuestra que el
módulo haya quedado enlazado en un binario de aplicación.

### P-83 (alta, abierta): no se consulta revocación documental

`mobile/ios/NFCPassportReader/Sources/NFCPassportReader/NFCPassportModel.swift`
declara `hasCertBeenRevoked`, pero la propia librería lo marca como no usado;
Android configura `PKIXParameters.isRevocationEnabled = false` en
`mobile/android/app/src/main/java/com/daociudadanaapp/PassiveAuthenticator.kt`.
La Master List autentica raíces, no sustituye CRL/defect lists. Un DS revocado
podría seguir aceptándose. Falta una política de actualización y revocación
autorizada, con comportamiento offline definido; la UI ya no presenta este
resultado como identidad civil completa y la emisión móvil permanece bloqueada.

### P-84 (alta, abierta): autenticación pasiva no prueba chip genuino ni titular

`mobile/ios/DAOCiudadanaApp/PassportReader.swift` lee DG1/DG2/SOD, pero no
ejecuta Active Authentication o Chip Authentication ni compara el rostro DG2
con liveness. Una copia de datos legítimamente firmados no queda descartada por
PACE + autenticación pasiva. La pantalla ahora dice “DOCUMENTO VERIFICADO” y
expone esta limitación; cerrarla requiere ratificar el perfil real de la cédula
chilena, prueba física y un proveedor/protocolo biométrico autorizado.

### P-85 (alta, abierta): el wrapper Android vigente no es compatible ni conserva la huella

`mobile/android/gradle/wrapper/gradle-wrapper.properties:1-6` — el árbol de
trabajo apunta a Gradle 9.6.1 y ya no contiene `distributionSha256Sum`,
`networkTimeout` ni `validateDistributionUrl`. Con ese wrapper,
`testDebugUnitTest` falla antes de las pruebas porque el plugin de React Native
espera metadata Kotlin 2.1 y Gradle aporta 2.3. La misma tarea sí terminó con
éxito usando directamente el binario cacheado Gradle 9.0.0, pero esa ejecución
no valida el camino que usarán CI y otros clones. Hasta fijar una versión
compatible con su SHA-256 y ejecutar el wrapper normal, el gate Android nativo
permanece rojo.

---

## Decimocuarta pasada (04-08-2026) — binding de navegador en ClaveÚnica (4.1)

### P-72 (alta, corregida): `/callback` era un oráculo PKCE

Reportado por Codex en `REQUEST_TO_CLAUDE.md` (TAREA 6) y **confirmado**: el
callback aceptaba `code + state` de cualquier cliente HTTP.

Que el flujo use PKCE no lo impide. PKCE protege el canje contra quien
intercepte el código *camino del proveedor*, pero aquí el **backend** guarda el
`code_verifier` y actúa como cliente confidencial: quien consiguiera `code` y
`state` —de la barra de direcciones, del historial, de un `Referer`, de otra
app en el mismo dispositivo— podía llamar a `/callback` desde su propia
máquina y recibir el `identity_grant`. Comparar el `state` en `sessionStorage`
no cubre esa frontera, porque esa comprobación vive en el navegador honesto.

Corregido con **binding de navegador**: `/authorize` genera un secreto
aleatorio, lo fija en una cookie `HttpOnly` (`Path=/api`, `SameSite=None` +
`Secure` en producción, `Lax` en local porque los navegadores descartan
`None` sin `Secure` sobre http) y persiste **solo su hash**. `/callback` exige
esa cookie **antes** de hablar con el proveedor, así que un tercero ni siquiera
llega a gastar el código de autorización. Verificado con dos clientes HTTP
distintos sobre la misma app.

Dos detalles que no son accesorios:

* El intento del atacante **no quema el `state`** del ciudadano legítimo, que
  puede completar su flujo después. Comprobar el binding antes de consumir
  evita convertir el ataque en una denegación de servicio.
* El mensaje es el mismo falte la cookie o no coincida: no hay nada que ganar
  diciéndole a quien roba un código cuál de las dos cosas le falta.

### Idempotencia del callback

Requisito 3 del contrato: si la respuesta HTTP se pierde, repetir el callback
desde el mismo navegador devuelve **el mismo grant vigente**. Emitir uno nuevo
duplicaría identidades; responder 401 dejaría a la persona sin credencial y sin
forma de obtener otra. El grant se recuerda **cifrado** en el intento de login
(con la llave de PII), por la misma razón por la que los grants solo se
persisten como digest: quien lea la base no debe poder canjear el de nadie. Si
el grant ya se canjeó o caducó, se responde 401 en vez de resucitarlo.

### El canje de la credencial también está ligado

`/identity-credential` exige ahora la misma cookie **además** de SIWE y CSRF, y
el binding entra en el filtro atómico de `identity_grant.consume`: copiar el
grant —o el bearer de sesión— a otro navegador falla antes de emitir nada. Los
grants antiguos sin binding se siguen canjeando: exigirlo retroactivamente
dejaría sin credencial a quien ya lo tenía.

### P-73 (media, corregida): un timeout del proveedor salía como 500

Un fallo de red hablando con ClaveÚnica escapaba al manejador global. Ahora hay
`ClaveUnicaProviderError` → **502**: un timeout del Estado no es "tu inicio de
sesión no es válido", y mandar al ciudadano a repetir un flujo que no falló por
su culpa es una respuesta falsa.

### P-74 (media, corregida): comparación de fechas con y sin zona

`_load_login_session` comparaba el `expires_at` leído de Mongo —que llega **sin
tzinfo**— contra `datetime.now(timezone.utc)`, lo que lanza `TypeError`. Lo
detectaron los tests, pero habría ocurrido igual en producción en el primer
callback. Se normaliza a UTC antes de comparar.

### Telemetría

`GET /api/auth/clave-unica/status` devuelve el contrato exacto que la web exige
antes de habilitar el botón. Cada bandera describe una garantía que este
backend cumple de verdad: si alguna dejara de cumplirse habría que bajarla, no
maquillarla. Es público y no expone `client_id` ni secretos.

### Readiness

Producción bloquea si `IDENTITY_PROVIDER` no es exactamente `clave-unica` —un
nombre de sandbox olvidado emitiría grants sin verificación— o si ClaveÚnica
está declarada con configuración incompleta. Los endpoints del Estado deben ser
HTTPS en cualquier entorno: en claro viajarían el código de autorización y el
`client_secret`.

Sigue sin probarse contra ClaveÚnica: no hay credenciales de la DGD.

463 tests (446 antes).
| P-85 | ~~React Native 0.83 fuerza AGP 9.3.1, incompatible con Gradle 9.0.0~~ **Premisa falsa, ver Decimoséptima pasada.** El catálogo de RN fija `agp = "8.12.0"` y la app usa 8.9.1; el único `9.3.1` del repo es `androidx.databinding`. Con el wrapper actual (Gradle 9.0.0) el comando exacto de CI **compila**: 27m49s, APK+AAB para 4 ABIs, verificación estricta. Subir a 9.5.0 **rompe** el build (Kotlin 2.3.20 vs 2.2.0). | `mobile/android/gradle/wrapper/gradle-wrapper.properties` | Crítica (CI/Infraestructura) | ✅ **Cerrado** (04-08-2026): verificado ejecutando, no razonando. Wrapper en 9.0.0 con su SHA-256 oficial, `validateDistributionUrl` y `networkTimeout` restaurado |

---

## Decimoquinta pasada (04-08-2026) — frontera anónima MACI (TAREA 5)

De la TAREA 5 solo era implementable la parte del backend. Los cuatro fallos
de protocolo (replay entre polls, nonces sin estado, hojas duplicadas en el
tally y falta de enlace verificable entre `processMessages` y el recuento)
viven en `circuits/` y exigen ratificar D-3 más pruebas negativas contra el
circuito, el verifier y el contrato reales. **No se tocaron**, y ahora se
declaran explícitamente.

### P-75 (alta, corregida): el acumulador no era recomputable contra la cadena

`backend/app/services/maci_service.py` — el backend calculaba

```python
sha256(":".join([prev, x, y, *ciphertext]))   # representaciones decimales
```

mientras `MACICoordinator.publishMessage` calcula

```solidity
keccak256(abi.encode(poll.messageChain, x, y, ciphertext))
```

El "recibo canónico" que el cliente valida no correspondía a lo que la cadena
calcularía al publicar ese mismo mensaje. Un acumulador que solo coincide
consigo mismo no acredita nada: cualquiera podría reordenar o sustituir
mensajes y el recibo seguiría cuadrando con la base de datos.

Corregido con `keccak256(abi.encode(...))` reproducido en Python y
**contrastado contra `ethers.AbiCoder`** con un vector fijo — mismo digest,
`0x7ec175c5…`. El vector queda como test: si alguien cambia el formato, deja
de coincidir y se entera.

Nota de migración: los `message_chain` guardados con el formato anterior no son
comparables con los nuevos. No hay datos reales en juego —el voto privado
nunca se habilitó— pero conviene vaciar `maci_messages`/`maci_polls` de
cualquier entorno de prueba antes de comparar recibos.

### P-76 (alta, corregida): la frontera anónima ignoraba campos en silencio

`AnonymousMessageRequest` no declaraba `extra="forbid"`. Un cliente que
enviara `wallet_address`, `choice` o la firma del comando recibía **200**:
Pydantic descartaba el campo sin decir nada. El docstring prometía no aceptar
esos campos; el modelo no lo cumplía, y nadie se habría enterado de que el
frontend estaba filtrando identidad en cada voto. Ahora es 422 con el nombre
del campo, y también dentro de `message`.

### P-77 (media, corregida): `proposal_id` llegaba y no se miraba

El endpoint aceptaba mensajes sin comprobar que el poll existiera, que
correspondiera a esa propuesta ni que la propuesta siguiera vigente. Se podía
encolar un voto contra un poll inexistente, creando un acumulador nuevo desde
cero que nadie podría reconciliar, o contra una propuesta ya cerrada — un voto
que nadie contaría.

"Abierto" se mide contra estado real (la propuesta existe y no ha pasado su
`ends_at`), no contra un plazo propio del poll: ese anclaje verificable es
justo lo que falta y lo que mantiene `accepting_messages` en `false`.

### P-78 (media, corregida): la idempotencia no era atómica

Había comprobación previa e índice único, pero el `DuplicateKeyError` de dos
reintentos simultáneos salía como 500. Ahora el perdedor devuelve el recibo
del ganador: reintentar tras un timeout es lo normal en un transporte sin
sesión, y no puede castigarse con un error.

### Rate limiting propio

`/api/maci/polls/{id}/messages` es anónimo, sin bearer y escribe en la base:
exactamente el perfil que necesita el bucket sensible. Se añadió a
`_SENSITIVE_PATH_PATTERNS`.

### Cuatro banderas nuevas en `/api/maci/status`

`poll_bound_messages`, `stateful_nonces`, `unique_tally_leaves` y
`process_tally_linked`, todas en `false` con su motivo. La web las exige antes
de habilitar el voto privado. Solo pueden subir tras las pruebas negativas
contra los artefactos reales; publicarlas en `true` sin eso sería afirmar una
privacidad que no existe.

471 tests (463 antes).


---

## Decimosexta pasada (04-08-2026) — deuda técnica del backend (P-45, P-46, P-47)

### P-45 — black, flake8 y mypy en CI

Estaban instalados y nadie los ejecutaba. Al medirlo con los valores por
defecto: **1420 avisos de flake8, 76 archivos que black reformatearía y 41
errores de mypy** (el hallazgo original decía 176/26/15; el backend creció
desde entonces).

Configuración en dos archivos porque las herramientas son así: black y mypy en
`pyproject.toml`, flake8 en `setup.cfg` —todavía no lee `pyproject`—. El
`line-length` es 88 en ambos: si divergen, cada herramienta pide lo contrario
que la otra. flake8 ignora E203 y W503/W504, que son los conflictos conocidos
con black, y su `max-line-length` es 100: black formatea el CÓDIGO a 88, pero
no parte cadenas ni comentarios, y exigirles 88 obligaría a un `noqa` por cada
mensaje de error largo.

`per-file-ignores` cubre lo que es una decisión y no un descuido: `E402` en
`main.py`, `scripts/` y `conftest.py`, que cargan el entorno **antes** de
importar la aplicación —al revés el proceso arrancaría sin variables—, y
`F401` en los `__init__`, cuyo trabajo es reexportar.

El formateo va en un commit separado, como pedía el propio hallazgo: 76
archivos de cambio mecánico no deben mezclarse con cambios de comportamiento.

De los 59 avisos que quedaron tras formatear, 16 eran defectos reales
—imports muertos, una variable asignada y nunca usada— y se corrigieron; el
resto eran cadenas largas, partidas a mano. Al partir `STATEMENT` en
`siwe_service.py` se comprobó que el valor resultante es **idéntico**: cambiar
un carácter de ese texto invalidaría todas las firmas SIWE existentes.

De los 41 errores de mypy, ninguno era un defecto de ejecución: casi todos
venían de diccionarios heterogéneos (documentos de Mongo, respuestas JSON-RPC)
cuyo tipo mypy infiere como `dict[str, object]`. Se anotaron como
`dict[str, Any]`, que es lo que de verdad son. Dos sí mejoraron el código:
`session_cookie_samesite` ahora devuelve el `Literal["lax","strict","none"]`
que espera Starlette —un typo en esa variable era un error silencioso—, y
`RateLimitStore.backend` pasó a propiedad, porque el almacén con respaldo lo
calcula en vez de declararlo.

mypy queda deliberadamente pragmático (sin `strict`, sin
`disallow_untyped_defs`). El objetivo de esta tarea era que CI detecte errores
reales, no convertir la suite en una migración de anotaciones de semanas.
Endurecerlo es un paso posterior y consciente.

El job `backend-quality` va **separado** del de pytest: un fallo de formato no
debe esconder un test roto ni al revés, y el nombre del check dice qué
arreglar. Se ejecutaron los tres comandos exactos del job antes de commitear.

### P-46 — el antifraude contaba intentos, no votos

`check_rapid_voting` comprobaba y registraba en la misma llamada, así que diez
peticiones inválidas —propuesta inexistente, ya votada, plazo vencido—
agotaban la cuota y devolvían 429 a alguien que no había emitido ni un voto.

Ahora son dos operaciones. `check_rapid_voting(voter)` solo LEE, apoyándose en
un `RateLimitStore.count()` nuevo (con su Lua en Redis: limpia la ventana y
hace `ZCARD` sin `ZADD`), y `record_vote(voter)` apunta **después** de que la
papeleta se haya persistido. Lo que limita el antifraude son votos; de los
intentos fallidos ya se ocupa el limitador por IP con su penalización
progresiva.

`proposal_id` desaparece de la firma: nunca formó parte de la clave —incluirlo
permitiría gastar la cuota entera contra cada propuesta rotando el
identificador— y tenerlo como parámetro sugería lo contrario.

### P-47 — la llave de desarrollo cambiaba por proceso

Se generaba con `Fernet.generate_key()` al importar el módulo. Con `--reload`
o varios workers, lo que cifraba un proceso no lo descifraba otro: el nombre
del ciudadano volvía como `None` sin ningún error que lo explicara.

Ahora se deriva de una constante fija y visible en el repositorio. **No es un
secreto**: solo se usa cuando no hay ninguna llave configurada Y `DEBUG` está
activo, y `key_status()` no la cuenta, así que readiness sigue bloqueando
producción por falta de llave.

### P-18 no se toca desde aquí

El secreto expuesto en el historial de Git es una acción externa —rotación en
el proveedor y auditoría de uso— que ningún cambio de código resuelve. Sigue
el procedimiento de `docs/SECURITY_RUNBOOK.md`.

472 tests. black, flake8 y mypy en verde.


---

## Decimoséptima pasada (04-08-2026) — P-85: la premisa era falsa

Se instruyó subir Gradle a 9.5.0 porque «React Native 0.83 fuerza AGP 9.3.1 e
es incompatible con Gradle 9.0.0». **Ninguna de las dos afirmaciones se
sostiene**, y actuar sobre ellas habría roto el gate que se quería destrabar.

### De dónde salió el «AGP 9.3.1»

El único `9.3.1` de todo el repositorio es
`androidx.databinding:databinding-common:9.3.1` en `verification-metadata.xml`
—una biblioteca de *databinding*, no el plugin de Android—. El catálogo de
React Native declara `agp = "8.12.0"` (y ese catálogo compila el plugin de RN,
no la app), y `android/build.gradle:16` fija
`classpath("com.android.tools.build:gradle:8.9.1")`.

### El build no estaba roto

Se ejecutó el **comando exacto de CI** (`npm run android:ci`, que corre
`lintRelease`, `testReleaseUnitTest`, `assembleRelease`, `validateReleaseBundle`
con `--dependency-verification=strict` y cuatro ABIs) con el wrapper vigente:

    BUILD SUCCESSFUL in 27m 49s
    521 actionable tasks: 494 executed, 27 up-to-date

APK sin firmar (86 MB) y AAB generados, y el script completó todas sus
aserciones —zipalign, `aapt2 dump badging`, permiso NFC, no-debuggable y las
cuatro arquitecturas nativas—, que es lo que imprime los checksums finales.

### Subir Gradle es lo que rompe

Se probó la instrucción antes de descartarla. Con Gradle 9.5.0 (checksum
oficial `553c78f5…`):

    Gradle 9.5.0
    Kotlin:  2.3.20
    > Task :gradle-plugin:settings-plugin:compileKotlin FAILED
      Internal compiler error.

Es el mismo modo de fallo que ya describía la parte narrativa de P-85: el
plugin de React Native no compila con la metadata de Kotlin que trae el Gradle
más nuevo. Gradle 9.0.0 embebe **Kotlin 2.2.0** y funciona; 9.5.0 embebe
**2.3.20** y no. La dirección correcta es **no subir**, no subir más.

El wrapper queda en 9.0.0 con su SHA-256 oficial verificado contra
`services.gradle.org` (`8fad3d78…`), `validateDistributionUrl=true` y
`networkTimeout=10000`, que alguien había eliminado al reordenar el archivo.

### P-86 (baja, corregida): lintear después de compilar daba 6087 problemas

`npm run lint` es `eslint .`, así que arrastraba `android/build/reports` —los
informes HTML que genera Gradle—. Quien compilara Android en local y luego
linteara veía **6087 problemas** que escondían los 21 reales del código. En CI
no se notaba porque el job estático lintea antes de compilar nada.

Con `.eslintignore` el gate local pasa a coincidir con el de CI: 0 errores y 21
avisos, exactamente el presupuesto configurado (`--max-warnings=21`).

Nota para quien toque el móvil: ese presupuesto está **al límite**. Un aviso
más rompe CI, así que conviene arreglar los `no-bitwise` de `bacCrypto.ts`
—que son legítimos en criptografía y podrían llevar una excepción de regla en
vez de gastar cupo— antes de añadir código nuevo.

### Estado del móvil tras esta pasada

| Gate | Resultado |
|---|---|
| `npm run typecheck` | ✅ limpio |
| `npm test` | ✅ 43 tests, 5 suites |
| `npm run lint -- --max-warnings=21` | ✅ 0 errores, 21 avisos |
| `npm run android:ci` (comando de CI) | ✅ BUILD SUCCESSFUL, APK+AAB |

---

## Decimoctava pasada (06-08-2026) — el minteo real nunca pudo ejecutarse

Objetivo de la pasada: destrabar el primer minteo real en Sepolia. Se buscaba
trabajar la idempotencia (fase 1/3) y apareció antes un defecto que hacía
imposible cualquier minteo, estuviera todo lo demás bien configurado o no.

### P-87 (crítica, corregida): la precondición on-chain exigía un rol inexistente

`backend/app/services/chain_service.py:275` (antes de esta pasada) llamaba a
`contract.functions.MINTER_ROLE().call()` dentro de `runtime_status()`.

`MINTER_ROLE` **no existe en `DAOCiudadanaSBT.sol`**. El contrato declara
`ROOT_MANAGER_ROLE`, `PAUSER_ROLE` y `REVOKER_ROLE`, y nada más:

    $ grep -rn "MINTER_ROLE" contracts/contracts/
    (sin resultados)

Contra el contrato desplegado esa llamada revierte. La excepción se capturaba
en el `except Exception` de la función y se traducía a
`errors = ["no se pudo validar RPC, contrato, ABI y MINTER_ROLE"]` con
`ready: False`. Como `mint_with_proof()` aborta cuando el sondeo no está
`ready`, **todo minteo real fallaba en la precondición sin llegar a enviar
nada**, y el mensaje mandaba a revisar la red y los permisos en vez del código.

Por qué no lo vio nadie: `backend/tests/test_chain_service.py:75` definía un
contrato falso que **sí** exponía `MINTER_ROLE()`. El doble era más permisivo
que el original, así que el suite confirmaba un contrato que no existe. Es
exactamente el fallo contra el que existe la regla 4 de `AGENTS.md`.

Corregido: el sondeo comprueba lo que el contrato pide de verdad —red,
bytecode, `membershipScope()` (que además distingue el contrato ZK del
histórico), `paused()` y saldo del relayer—. `mintMembership` no exige rol
alguno: la prueba Groth16 es la autorización. El doble de test se reescribió
para imitar el contrato real, sin `MINTER_ROLE()`.

### P-88 (alta, corregida): `MINT_MODE=onchain` llamaba a una firma borrada

`blockchain_service.mint_sbt` invocaba `chain_service.mint_sbt_onchain`, que
construía `mintMembership(to, identityHash, assuranceLevel, uri)`. Esa firma
desapareció al migrar al modelo ZK —el propio comentario del ABI lo decía— y no
está ni en el ABI ni en el contrato. El resultado era siempre un
`"No se pudo confirmar el minteo on-chain. Intenta más tarde."`: un error que
parece de red y que ninguna revisión de infraestructura podía resolver.

Corregido: se eliminó `mint_sbt_onchain` y `MINT_MODE=onchain` responde 503
indicando `POST /api/membership/mint-zk`. `MINT_MODE` queda gobernando solo el
registro local (`disabled` / `demo`).

### P-89 (alta, corregida): un timeout de recibo provocaba un segundo gasto de gas

`mint_with_proof` esperaba el recibo hasta 120 s y el hash solo se guardaba al
terminar. Dos consecuencias:

1. Si el proceso moría dentro de esa ventana, la transacción quedaba **sin
   rastro en Mongo**. La operación seguía `pending` para siempre y el ciudadano
   recibía un 409 permanente, sin credencial y sin forma de pedir otra.
2. Si expiraba el timeout, el router marcaba `failed`. El reintento enviaba una
   SEGUNDA transacción que revertía por `NullifierAlreadyUsed`, quemando gas de
   la DAO sin emitir nada.

Corregido en `backend/app/services/mint_operations.py` (nuevo). El hash se
persiste desde el hilo del RPC en cuanto la transacción se difunde, mediante
el callback `on_submitted`, y aparece el estado `submitted`: una transacción
difundida ya no la declara fallida un temporizador de este proceso, solo la
cadena. Una operación abierta se resuelve consultando el recibo y, si no
alcanza, `isNullifierUsed()`.

Regla que atraviesa el módulo: un RPC que no responde nunca se lee como "no
pasó nada". Todas las lecturas devuelven `None`/`unknown` y mantienen la
operación en vuelo; traducir un corte de red a "puedes reintentar" es justo lo
que provoca el doble gasto.

Contradicciones (nullifier consumido sin SBT para esa wallet) quedan en
`needs_review` y las mira una persona: no se adivinan.

### P-90 (media, corregida): los hashes de transacción se guardaban malformados

`hexbytes` 1.x dejó de prefijar `.hex()` con `0x`, y el código guardaba el
valor tal cual. Los `tx_hash` de `members` y `mint_operations` no eran hashes
válidos para ningún explorador: el ciudadano no podía seguir su transacción.
Comprobado en el entorno real del proyecto:

    $ python -c "from hexbytes import HexBytes; print(HexBytes(b'\x01').hex())"
    01

Corregido con `chain_service.tx_hash_hex()`, que normaliza una sola vez.

### P-91 (media, corregida): sin ROOT_MANAGER_ROLE el fallo era opaco

`approveIdentityRoot` es `onlyRole(ROOT_MANAGER_ROLE)` y `scripts/deploy.js`
concede ese rol **solo al admin**. Si el relayer no lo tiene, la emisión de
credenciales fallaba como un revert durante la estimación de gas, sin decir que
lo que faltaba era una concesión de rol. Ahora se comprueba antes, con su
motivo, y `/health/ready` lo reporta en `minting.zk_relayer`.

### P-92 (media, corregida): el estado del relayer ZK era invisible

`main.py` solo sondeaba la cadena con `MINT_MODE=onchain`. Como
`/membership/mint-zk` no consulta esa variable, el despliegue que de verdad
mintea reportaba `ready` sin haber comprobado nunca su relayer. Ahora se sondea
siempre que la cadena esté configurada (el sondeo ya cachea 30 s) y readiness
publica `minting.zk_relayer`.

### P-93 (alta, mitigada — la rotación sigue pendiente): no había secret scanning

El paso 4 de `docs/SECURITY_RUNBOOK.md` pedía escanear HEAD, ramas, tags e
historial. No existía ningún job: el incidente P0 se encontró leyendo el
historial a mano.

Añadido el job `Seguridad · secret scanning` a `.github/workflows/ci.yml`
(gitleaks 8.30.1, fijado por versión y checksum SHA-256, sobre el historial
completo). Verificado en ambos sentidos sobre un clon limpio: sale en verde con
el historial actual y **rompe la build** al plantar un secreto de prueba.

`.gitleaks.toml` lista las excepciones una a una, ancladas a commit y ruta.
La del incidente P0 **no lo cierra**: borrar blobs no vuelve segura una llave
que ya fue pública. Revocarla en el proveedor sigue siendo obligatorio y sigue
pendiente; la excepción solo permite que el detector empiece a proteger de los
secretos futuros mientras esa rotación se coordina.

Cinco de los seis hallazgos del historial eran falsos positivos (fixtures de
test y un checksum de CocoaPods); el sexto es el `backend/.env` de `6202a9f`
que el runbook ya documenta.

### Estado tras esta pasada

Al terminar, el suite completo estaba en **524 tests verdes**. Después entró en
el árbol de trabajo la pasada paralela de NFC/autenticación pasiva
(`passive_auth.py`, `csca_trust_store.py`, `emrtd_fixtures.py`,
`extract_csca_from_ldif.py`, el router `cedula`), que a esta hora está a medias
y deja los gates del repositorio en rojo. Por eso la tabla separa ambos ámbitos
en vez de anunciar un verde que no es cierto:

| Gate | Archivos de esta pasada | Repositorio completo |
|---|---|---|
| `pytest -q` | ✅ 88 tests | ❌ 2 fallos en `test_auth.py::test_nfc_*` |
| `black --check` | ✅ 13 archivos limpios | ❌ 5 archivos sin formatear |
| `flake8` | ✅ limpio | ❌ 5 avisos (F401/E501/F541) |
| `mypy` | ✅ sin errores | ❌ 1 error en `passive_auth.py:217` |
| `gitleaks git .` sobre clon limpio | ✅ 0 hallazgos, y rompe con un secreto plantado | — |

Todos los fallos de la columna derecha están en archivos de la pasada paralela;
ninguno toca los de esta. No se corrigieron a propósito: son de trabajo en
curso de otro agente y arreglarlos sería pisar su edición.

`black` y `flake8` ya estaban **rojos antes de esta pasada**, por otro motivo:
`app/routers/analytics.py` y `main.py` (un router de analítica que entró sin
formatear, con un `List` sin usar). Eso sí se corrigió de paso; es solo formato.

### Lo que sigue bloqueado, y por quién

- **Minteo real:** ya no hay defecto conocido en el camino, pero sigue sin
  existir un despliegue compatible del contrato. `totalSupply()` de la
  dirección histórica sigue en 0 y esa dirección tiene otra ABI.
- **Identidad:** el camino ClaveÚnica está implementado de punta a punta
  (`clave_unica.py` → `identity_grant.issue` → `identity_issuer`). Lo que falta
  son las credenciales del sandbox que entrega la División de Gobierno Digital.
  No es trabajo de código.
- **Llave filtrada:** revocarla es una acción del dueño en el proveedor.
