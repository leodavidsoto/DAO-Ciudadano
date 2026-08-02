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
| P-19 | El código cifra altas nuevas, pero no existe migración/backfill validado para PII legacy; múltiples documentos sin `rut_key`/`email_key` pueden impedir crear índices únicos y dejar readiness en 503 | colección Atlas `users`; `backend/app/core/database.py` | **Crítica (release/datos)** | 🔴 Abierto: snapshot, inventario/duplicados, migración ensayada y rollback antes de promover la base. Readiness falla cerrado; no se ejecutó ninguna mutación remota |
| P-20 | Configuración on-chain no vacía pero inválida podía declarar readiness; no se comprobaban chainId, bytecode, ABI, `MINTER_ROLE` ni saldo | `backend/app/services/chain_service.py`; `backend/app/core/readiness.py` | Alta | ✅ Corregido: readiness y el endpoint de minteo ejecutan la misma validación estática/runtime contra Sepolia, bytecode, ABI, rol y gas; producción exige RPC HTTPS. El envío usa chain ID fijo, reserva local de nonce, errores sanitizados y obtiene el token desde evento o lectura del contrato, sin inventarlo |
| P-21 | El frontend mantenía la dirección Sepolia histórica y una ABI manual `string` incompatible con el contrato actual `bytes32`; cualquier `tx_hash` abría el contrato equivocado | `frontend/netlify.toml`; `src/contracts/SBTContract.js`; `useSBTContract.js`; `DashboardStep.jsx` | Alta (integridad) | ✅ Corregido: dirección, ABI y hook huérfano eliminados; la UI enlaza únicamente el `tx_hash` real devuelto por la API |
| P-22 | El challenge de wallet se anunciaba como SIWE pero omitía Chain ID y usaba dominio/URI fijos no públicos | `backend/app/services/siwe_service.py` | Alta (autenticación) | ✅ Corregido: mensaje EIP-4361 completo con primera línea canónica, dominio/URI/red/expiración; nonce atómico de un solo uso que no se quema ante una firma inválida; JWT valida `iss`/`aud` + `jti`. Challenge, verify y consumo de sesión aplican el gate en runtime, no solo en readiness |
| P-23 | El camino on-chain envía la transacción antes de persistir Mongo; una caída o colisión deja cadena y base divergentes | `backend/app/services/blockchain_service.py`; `frontend/src/lib/api.js` | Alta (futuro release) | 🔴 Abierto: diseñar idempotency key, operación `pending`, reconciliador por eventos/recibos y retry seguro. El lock de nonce solo cubre un proceso y debe ser distribuido; además, el cliente corta a 30 s mientras el backend puede esperar 120 s. La espera RPC ya está fuera del event loop |
| P-24 | Readiness no bloqueaba `DEBUG=true`, CORS abierto, papeletas sin firma o una fuente de membresía on-chain aún no implementada | `backend/app/core/readiness.py`; `render.yaml`; `DEPLOY.md` | Alta | ✅ Corregido: invariantes cruzadas forman parte de `/health/ready`, el blueprint declara decisiones demo y el despliegue manual enumera toda la configuración obligatoria |
| P-25 | Los votos de propuestas aceptaban un `nonce` sin firma ni persistencia verificable; elecciones seguía el mismo patrón | `backend/app/routers/governance.py`; `backend/app/routers/elections.py`; `frontend/src/components/governance/ProposalsList.jsx` | **Crítica (integridad electoral)** | 🟡 Propuestas corregidas end-to-end: EIP-712 firmado en wallet, nonce único persistido, firma/hash reverificables y endpoint público de papeletas. Los votos de elecciones aún no tienen papeleta firmada y por eso producción los rechaza explícitamente |
| P-26 | Insertar una papeleta y actualizar el total de la propuesta son dos escrituras Mongo separadas; una caída entre ambas puede desalinear papeletas y resultado | `backend/app/routers/governance.py`; `backend/app/routers/elections.py` | Alta (integridad) | 🔴 Abierto: transacción Mongo o tally derivado/reconciliable para propuestas y elecciones. El índice único evita doble voto concurrente, pero no resuelve una caída entre escrituras |
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
| P-45 | `requirements-dev.txt` instala `black`, `flake8` y `mypy`, pero **ningún job de CI los ejecuta**. Con los defaults hay 176 avisos de flake8, 26 archivos que `black` reformatearía y 15 errores de `mypy`. Tampoco hay job de tests de frontend | `.github/workflows/ci.yml`; `backend/requirements-dev.txt` | Media (proceso) | 🔴 **Abierto**: activarlos hoy dejaría CI en rojo. Requiere decidir configuración (`setup.cfg`/`pyproject`) y una pasada de formateo separada, que no se mezcla con esta revisión funcional |
| P-46 | `fraud_detector.check_rapid_voting` registra el intento **antes** de validar que la propuesta exista o que el votante no haya votado ya. Diez intentos fallidos (propuesta inexistente, ya votada) consumen la cuota y bloquean al miembro con 429 sin que haya emitido un solo voto | `backend/app/routers/governance.py`; `elections.py` | Baja | 🔴 **Abierto**: separar "comprobar" de "registrar" cambia la firma que usa `test_security_utils.py`; se deja explícito en vez de tocarlo de paso |
| P-47 | En `DEBUG`, `crypto.py` genera la llave Fernet de desarrollo **una vez por proceso**. Con `--reload` o varios workers, lo que un proceso cifra otro no puede descifrarlo: el nombre vuelve `None` sin explicación | `backend/app/core/crypto.py` | Baja (solo desarrollo) | 🔴 **Abierto**: derivar la llave de desarrollo de un valor fijo y documentado |

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
| P-53 | El router ERC-4337 añadido en `a49883e` no implementa todavía el contrato del cliente: `PrepareMintRequest` exige `proof`, mientras el frontend envía `account + mint`; además intenta decodificar el `callData` exterior de `Safe4337Module.executeUserOpWithErrorString` directamente con la ABI del SBT. El camino integrado devolvería 422 antes de patrocinar una operación válida | `backend/app/routers/erc4337.py:65`; `backend/app/routers/erc4337.py:112`; `REQUEST_TO_CLAUDE.md:177` | **Alta (integración bloqueada)** | 🟡 Parcialmente mitigado, integración bloqueada: falta recalcular la Safe ciudadana, decodificar primero el envoltorio Safe4337, alinear el modelo con el payload documentado y validar la prueba completa. `d9f40d0` ya eliminó correctamente la dependencia de una `ERC4337_ACCOUNT_ADDRESS` global y añadió una sonda real del bundler, pero no modificó este router. La suite E2E usa un fixture contractual y no afirma haber probado el flujo integrado con Pimlico |

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
