# Auditoría técnica — DAO Ciudadana

**Fecha:** 26 de julio de 2026
**Commit auditado:** `f2902ca` (`main`) — *Add React Native mobile app with NFC chip reading support*
**Alcance:** backend FastAPI, contrato `DAOCiudadanaSBT.sol`, frontend React, app móvil React Native, despliegue.
**Método:** lectura completa del código, verificación on-chain contra Sepolia vía RPC público, sondeo del backend en producción.

> 📌 **Nota:** este informe describe el commit `f2902ca`. Varios hallazgos de higiene
> (M-5, M-6, M-7, M-8, M-12, M-13, B-1, B-2, B-3, B-4) y de datos inventados (A-9 parcial:
> las cifras fabricadas se eliminaron — incluida la siembra de 1432/32 en el estado inicial de
> `frontend/src/context/OnboardingContext.jsx` —; las fuentes reales de tesorería llegan en
> Fase 3.6) fueron abordados en la **Fase 0** (rama `fase-0-higiene-y-verdad`). C-5 (tests del
> contrato) se cerró con la suite de `contracts/test/`. Los críticos C-1…C-4 y C-6 siguen abiertos.
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
| N-3 | `FraudDetector.check_delegation_chain` recorre el mapa `delegate → [delegators]` en la dirección equivocada: un ciclo real `a→b` + `b→a` no se detecta (solo funciona el límite de delegadores). El módulo sigue sin cablearse a los endpoints (A-4) | `backend/app/core/security_middleware.py:241-253` | Media | Abierto — corregir junto con la activación del antifraude (tarea 3.4) |
