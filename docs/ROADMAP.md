# Plan de implementación — DAO Ciudadana

**Base vigente:** `main@73f2985` + endurecimiento local en
`codex/produccion-ci`. `f2902ca` se conserva en [`AUDIT.md`](./AUDIT.md) como
referencia histórica.
**Principio rector:** cada fase deja el sistema en un estado más honesto que la anterior. Nada que se muestre al usuario debe afirmar algo que el sistema no puede probar.

---

## Decisiones de arquitectura que hay que tomar antes de escribir código

Existen implementaciones provisionales para estas tres decisiones, pero deben
ratificarse mediante ADR antes de desplegar producción. No son detalles que deba
decidir implícitamente una implementación.

### D-1 · ¿Quién mintea el SBT?

| Opción | Cómo funciona | A favor | En contra |
|---|---|---|---|
| **A. Server-side (custodial)** | El backend firma con una wallet que tenga `MINTER_ROLE` y llama `mintMembership`. El código actual lo soporta, pero aún no está desplegado. | Cero fricción para el usuario, no necesita gas ni entender Web3. | El backend custodia una llave con poder de acuñar. Exige HSM/KMS, monitoreo y reconciliación. |
| **B. Client-side con firma** | El backend emite un voucher firmado (EIP-712); el usuario llama `mintWithVoucher` y paga su gas. Requiere modificar el contrato. | El backend nunca custodia llaves con fondos. El usuario controla su transacción. | Fricción alta: el ciudadano necesita ETH de gas. Barrera de adopción real en un proyecto cívico. |
| **C. Híbrido con meta-transacciones** | El usuario firma un mensaje sin gas; un relayer lo ejecuta y paga. | Combina lo mejor de A y B. | Más piezas: relayer, protección contra abuso del relayer, ERC-2771. |

**Resolución (ADR-001):** Opción **C (Híbrido con meta-transacciones y Account Abstraction)**. Se usará un Paymaster (ERC-4337) o Relayer para que la barrera de adopción y el gas sea cero, sin requerir custodia server-side.

### D-2 · ¿Qué se escribe on-chain como `identityHash`?

El esquema histórico (`sha256(RUT)[:16]`) es reversible por fuerza bruta y no
puede ir a un registro público. La rama `codex/produccion-ci` ya usa
HMAC-SHA256 completo para altas nuevas, pero la decisión sigue pendiente hasta
ratificar el diseño, custodiar/rotar el pepper en KMS y migrar o purgar datos
legacy. Alternativas:

**Resolución (ADR-001):** Se utilizará **Prueba de conocimiento cero (zk-SNARKs)** usando un nullifier on-chain como `identityHash`. Esto permite anonimato total y evita la coerción. El cliente generará la prueba ZK y el contrato la validará.

### D-3 · ¿La gobernanza es on-chain u off-chain?

Hoy la gobernanza sigue siendo off-chain en MongoDB. Las papeletas de propuestas
ya llevan firma EIP-712 y pueden reverificarse, pero los votos de elecciones aún
no; producción los bloquea. Además, los totales persisten separados de las
papeletas, por lo que todavía falta reconciliación/atomicidad antes de llamarlo
un sistema electoral verificable.

**Resolución (ADR-001):** Off-chain firmado con **MACI (Minimal Anti-Collusion Infrastructure)** para privacidad y anti-coerción, sumado a un **Safe multisig con oráculo Reality.eth** para ejecución trustless sin gas.

---

## Fase 0 — Higiene y verdad (1 semana)

> ✅ **Completada** en la rama `fase-0-higiene-y-verdad` (julio 2026). Resumen de lo hecho:
> cifras infladas del dashboard eliminadas · tesorería mock y `ensure_sample_transactions`
> retiradas · `participation_rate`/`runway_months` ahora reales o `null` · `server.py`,
> `.gitconfig` y `.emergent/` borrados · `artifacts/` y `cache/` fuera del control de versiones ·
> `DEBUG`/`CORS_ORIGINS` con defaults seguros · handler global sin fuga de `str(exc)` ·
> `.env.example` en los tres módulos · pasos simulados marcados con badge "MODO DEMO" · README honesto.


Objetivo: que el repositorio sea levantable y que la UI deje de afirmar cosas falsas. Sin esta fase, cualquier otro trabajo se construye sobre una base engañosa.

| # | Tarea | Archivos | Criterio de aceptación |
|---|---|---|---|
| 0.1 | Crear `.env.example` en `backend/`, `frontend/` y `contracts/` con todas las variables documentadas y sin valores reales | nuevos | Un desarrollador nuevo levanta el proyecto siguiendo solo el README |
| 0.2 | Eliminar los datos inflados del dashboard: quitar `max(total_members, 1432)` y `max(recent_joins, 32)` | `dashboard.py:34` | La API devuelve los conteos reales, aunque sean 0 |
| 0.3 | Eliminar `ensure_sample_transactions()` y `TREASURY_BALANCE` hardcodeado; devolver `null` o un estado explícito `not_configured` mientras no haya tesorería real | `governance.py:420-462` | Ningún endpoint devuelve cifras inventadas |
| 0.4 | Sustituir `participation_rate: 0.75` y `runway_months: 18` por cálculo real o por `null` | `governance.py:302,545` | Sin constantes mágicas en respuestas de la API |
| 0.5 | Marcar visiblemente los flujos simulados en la UI (badge "MODO DEMO" en pasos con mock) hasta que la Fase 1 los reemplace | `MintStep.jsx`, `ClaveUnicaStep.jsx`, `NFCStep.jsx` | Ningún paso simulado se presenta como real |
| 0.6 | Borrar `backend/server.py` (app legacy duplicada) | `backend/server.py` | El backend arranca igual; no queda código muerto |
| 0.7 | Sacar `contracts/artifacts/` y `contracts/cache/` del control de versiones y añadirlos a `.gitignore` | `.gitignore` | `git status` limpio tras `npx hardhat compile` |
| 0.8 | Eliminar `.gitconfig` y `.emergent/` del repositorio | raíz | Sin residuos del andamiaje de generación |
| 0.9 | `DEBUG` por defecto a `False`; `CORS_ORIGINS` sin default `*` (fallar si no está definida en producción) | `config.py:17,24` | Arrancar sin variables en modo producción falla de forma explícita |
| 0.10 | El handler global de excepciones deja de devolver `str(exc)`; loguea con `request_id` y devuelve un mensaje genérico | `main.py:100` | Ningún 500 filtra rutas, drivers ni consultas |
| 0.11 | Actualizar el README para reflejar el estado real (Sepolia, no Polygon; qué funciona y qué no) | `README.md` | Sin afirmaciones contradichas por el código |

---

## Fase 1 — Autenticación y minteo real (2–3 semanas) · **BLOQUEANTE**

Objetivo: cerrar C-1, C-2 y C-6. Al terminar, un SBT existe de verdad y solo lo obtiene quien se verificó.

> **Estado 01-08-2026:** SIWE, autorización self y el camino técnico de minteo
> on-chain están implementados detrás de guardrails fail-closed. Las altas nuevas
> usan Fernet + HMAC. Siguen bloqueando producción: proveedor civil y grant de un
> solo uso, migración de PII legacy, ADR/KMS, y reconciliación
> idempotente cadena↔Mongo. El contrato base se encuentra desplegado y verificado en Sepolia en `0x6C6C7D0ceC1b7267cB2fa146519FBF9ef6319d56`.

| # | Tarea | Detalle | Criterio de aceptación |
|---|---|---|---|
| 1.1 | 🟡 **Sesión basada en firma de wallet (SIWE / EIP-4361)** | Challenge/verify canónico, nonce de un solo uso y JWT corto implementados. Falta decidir si se necesita refresh/rotación de sesión. | `/api/wallet/challenge` y `/verify` funcionando; el JWT contiene `sub = address` |
| 1.2 | ✅ **Dependencia `require_auth` en FastAPI** | Aplicada a mint, propuestas, voto, delegación y elecciones; cada acción debe corresponder al `sub` del token. | Ningún endpoint mutante acepta actuar como otra dirección |
| 1.3 | ✅ **Completada** (04-08-2026). HMAC-SHA256 con pepper + **rotación implementada**: `PII_ENCRYPTION_KEYS` (MultiFernet) e `IDENTITY_PEPPER_PREVIOUS`, con `scripts/pii_maintenance.py` migrando los datos exitosamente. Las credenciales seguras han sido inyectadas y la migración legacy (desde texto plano) se ejecutó contra la base de datos de producción (Atlas). | Ningún hash reversible por diccionario queda almacenado |
| 1.4 | ✅ **Completada** (04-08-2026). Fernet + índices HMAC, **inventario de campos cifrados, política de retención declarada (`app/core/retention.py`, con TTL derivados de ella) y migración de texto plano legacy ejecutada con éxito**. El script de mantenimiento aplicó la rotación y reindexado sin downtime. | Un volcado de la base no expone RUT en claro |
| 1.5 | 🟡 **Minteo real on-chain** | Construcción, firma, recibo, evento/lectura de `tokenId` y precondiciones de red/rol/gas implementados. Producción permanece cerrada hasta disponer de grant, contrato, custodia e idempotencia/reconciliación. | `totalSupply()` en el despliegue compatible aumenta y se reconcilia con Mongo |
| 1.6 | 🟡 **Añadir `MINTER_ROLE`** | El contrato actual usa AccessControl y tiene tests; falta desplegarlo, verificarlo y separar/custodiar los roles. | Admin y minter son direcciones distintas y están inventariadas |
| 1.7 | **Eliminar el mock de wallet** ✅ | Eliminados `POST /api/wallet/connect`, `generate_mock_address()` y el cliente huérfano. La conexión la hace MetaMask y la sesión usa challenge/verify SIWE. | No existe una ruta que invente una wallet; `useWallet` firma el desafío real |
| 1.8 | **Eliminar la ABI manual del frontend** ✅ | El minteo es responsabilidad del backend; se borraron la ABI manual incompatible y la dirección legacy. La UI enlaza la transacción real recibida de la API. | Sin ABI duplicada ni dirección histórica en el bundle |
| 1.9 | **Eliminar `useSBTContract` huérfano** ✅ | El hook no se usaba y permitía intentar minteo con el signer del usuario; fue eliminado. | Sin hooks que sugieran minteo client-side inexistente |
| 1.10 | **Proveedor real de identidad/liveness + grant** | Sustituir las demos por un proveedor adecuado, aplicar sus garantías y emitir un permiso de alta de un solo uso. La heurística visual demo no debe promoverse a acreditación. | Sin proveedor o evidencia válida, producción falla cerrado y no puede mintear |
| 1.11 | ✅ **Completada** (03-08-2026). Índice único en `members.wallet_address` y en `members.nullifier_hash` (parcial: solo cuando es string, para que las filas demo/legacy con `null` convivan). El nullifier es el identificador de PERSONA que fijó D-2, así que cierra el hueco de una misma persona con dos wallets. | migración MongoDB | Imposible crear dos membresías para la misma wallet |
| 1.12 | ✅ Reemplazar `token_id = count + 1` por el `tokenId` del evento o la lectura del contrato | `blockchain_service.py` | El camino on-chain nunca inventa un ID local |
| 1.13 | ✅ **Completada** (06-08-2026). Backend revoca JWTs en Mongo (`revoked_tokens` con TTL). Frontend usa `HttpOnly` cookie para el transporte de sesión y borra sesión en logout. | Un XSS del frontend no puede extraer el JWT SIWE |

---

## Fase 2 — Tests y CI (1–2 semanas)

> 🟡 **Parcial** (agosto 2026). 2.1: suite de `contracts/test/` (31 tests, incluye la
> regresión del orden checks-effects-interactions en `mintMembership`). 2.2: suite de
> `backend/tests/` con 548 tests, sin red ni Mongo real. 2.3:
> `backend_test.py` y `test_result.md` eliminados. 2.4: `.github/workflows/ci.yml` corre
> backend, contratos, slither, auditoría crítica de npm, `pip-audit` estricto,
> 90 tests unitarios web, build del frontend y un flujo E2E Playwright ZK/AA/MACI
> en cada PR; las Actions están fijadas por SHA. 2.5: `slither --fail-medium
> --exclude-dependencies` en verde. 2.6: `requirements.txt` con versiones exactas.
> Dependabot quedó configurado para los cinco directorios/ecosistemas. Mobile pasa
> TypeScript, 43 tests, lint y auditoría npm localmente; el workflow incorpora esos
> mismos gates en un nuevo job estático. `testDebugUnitTest` pasa al invocar
> explícitamente el binario cacheado Gradle 9.0.0, y el wrapper local se reparó a 9.0.0.
> Pendientes: build/release nativo de iOS, branch protection y migración de los
> toolchains legacy que concentran los avisos altos de dependencias. (Lint backend,
> cobertura formal web/backend, Android wrapper y secret scanning recurrente están completados).

Objetivo: cerrar C-5 y hacer que las fases siguientes no rompan lo anterior.

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 2.1 | Suite de tests del contrato en `contracts/test/`: minteo, unicidad por wallet, rechazo de `identityHash` repetido, intento de transferencia (debe revertir), pausado, ciclo completo de revocación con cooldown, permisos | Cobertura ≥ 90 % en `DAOCiudadanaSBT.sol` |
| 2.2 | Tests de integración del backend con `pytest` + `mongomock` o contenedor efímero: autenticación, mint, voto, límites de tasa | Cobertura ≥ 70 % en `routers/` y `services/` |
| 2.3 | Reescribir `backend_test.py`, que hoy apunta a un host de preview inexistente, o eliminarlo | Sin tests que apunten a infraestructura muerta |
| 2.4 | GitHub Actions: tests de contrato + tests de backend + slither + auditoría crítica npm + build estricto del frontend en cada PR; lint backend pendiente | Los checks informan cualquier regresión antes del merge |
| 2.5 | `slither` sobre el contrato en CI | Sin hallazgos de severidad alta |
| 2.6 | Fijar versiones exactas en `requirements.txt` | Builds reproducibles |
| 2.7 | Configurar branch protection/ruleset en `main` y exigir los checks de CI | Un PR con checks rojos no se puede mergear |
| 2.8 | ✅ SCA y mantenimiento: `pip-audit --strict`, npm sin críticos, Actions fijadas por SHA y Dependabot semanal | Una dependencia Python vulnerable o un crítico npm rompe CI |
| 2.9 | ✅ Gate estático mobile: instalación reproducible, auditoría crítica, TypeScript, presupuesto de warnings ESLint y Jest | Una regresión móvil bloquea el PR antes del build nativo |
| 2.10 | **Secret scanning recurrente y protección de push** | GitHub Secret Scanning/ruleset o scanner fijado por SHA, con procedimiento de triage | Una credencial nueva se bloquea antes de llegar a `main` |
| 2.11 | ✅ Gate web E2E: Playwright sincroniza artefactos ZK desde el manifiesto, genera/verifica Groth16, recupera la firma SafeOp de un fixture EIP-1193 tipo MetaMask y valida una papeleta MACI cifrada | El flujo completo de navegador falla ante una regresión de ZK, ERC-4337, privacidad MACI o del contrato de fixture |

---

## Fase 3 — Gobernanza verificable (2–3 semanas)

Objetivo: cerrar C-3, A-4, A-5, A-9 y M-10.

> **Estado 03-08-2026:** 3.1–3.5 y 3.7–3.9 implementados, ya no solo para propuestas:
> las elecciones comparten papeleta EIP-712, nonce, antifraude y peso delegado.
> El verificador on-chain existe y se elige con `MEMBERSHIP_SOURCE=onchain`; el
> despliegue sigue en `mongo` hasta que el contrato tenga membresías reales
> (`totalSupply()` = 0), con cuarentena demo/legacy en producción. Votar en
> producción exige `SIGNED_BALLOTS_REQUIRED=true` en ambos módulos; si no, 503.
> **Fase 3 completa** salvo lo que depende de terceros. Balance nativo y ERC-20,
> precios reales, recuento dinámico (3.10) y antifraude verificado.

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 3.1 | ✅ **Completada** (02-08-2026). `OnChainMembershipVerifier` consulta `hasMembership(address)` con caché en memoria (`MEMBERSHIP_CACHE_TTL_SECONDS`, 30 s) e invalidación al mintear. Un RPC caído responde 503, nunca 403. El peso por delegación usa el mismo verificador. | Una dirección sin SBT recibe 403 |
| 3.2 | ✅ **Completada** (02-08-2026). Propuestas y elecciones firman EIP-712, persisten firma/nonce/chainId y exponen papeletas públicas | Cualquier tercero puede recomputar el resultado sin confiar en el servidor |
| 3.3 | ✅ **Completada** (02-08-2026). Nonce único compartido por propuestas y elecciones sobre el mismo índice | Reenviar un voto firmado da 409 |
| 3.4 | ✅ **Completada** (03-08-2026). `check_rapid_voting` se llama desde propuestas y elecciones y falla cerrado sin almacén. `check_delegation_chain` **ya no existe**: se eliminó en 3.8 porque duplicaba el grafo de MongoDB, y su única heurística propia (profundidad máxima) vive en `delegation_block_reason`, que ahora distingue ciclo de cadena profunda en vez de llamar "circular" a ambos. Cubierto por `tests/test_antifraud.py` (9 tests por HTTP). | Los tests de patrones sospechosos pasan |
| 3.5 | ✅ **Completada** (03-08-2026). El peso aplicado sale de `contest_vote_weight`, que descuenta a los delegantes que ya votaron por su cuenta en esa consulta, y la papeleta persiste `delegators` para que el peso sea recomputable. Cierra el doble conteo P-61 en sus dos órdenes. | Delegar cambia el resultado de forma medible |
| 3.6 | ✅ **Completada** (04-08-2026). `treasury_service.py` lee el balance nativo del Safe y los ERC-20 declarados en `TREASURY_TOKENS` (decimales y símbolo leídos de la cadena, nunca supuestos), con precios de CoinGecko por contrato. Verificado contra mainnet: ETH + USDC + DAI consolidados en un total real. Fuera de mainnet el USD es `null`; un activo con saldo y sin precio anula el total en vez de sumar parcial; un token ilegible deja `balances: null` en vez de publicar cero. | Ningún número de tesorería es una constante en el código |
| 3.7 | ✅ **Enrutado y montaje de la UI de gobernanza**: `/` (landing), `/unete` (onboarding) y `/dashboard/{propuestas,elecciones,delegacion,tesoreria}` | Las secciones de gobernanza son alcanzables |
| 3.8 | ✅ **Completada** (02-08-2026). Rate limiter y antifraude sobre Redis | Ventana deslizante atómica en Lua, historial de votos y penalización progresiva compartidos. Ya no queda estado en memoria de proceso. Degradación a memoria **visible** en `/health/ready`. Verificado con `fakeredis[lua]`, **no** contra un Redis real |
| 3.9 | ✅ **Hecho (julio 2026)** — el middleware usa `asyncio.sleep`; el event loop ya no se bloquea | Sin bloqueo del event loop bajo carga |
| 3.10 | ✅ **Completada** (04-08-2026). Los totales se derivan de las papeletas al leerlos, así que votar es UNA escritura de UN documento y no queda contador que pueda divergir. La finalización de elecciones se reconcilia por `upsert` hasta escribir su marca `finalized_at`, que es la última escritura: una caída antes de ella se repara en la siguiente lectura. `GET /governance/proposals/{id}/audit` y `/elections/{id}/audit` recomputan el resultado verificando cada firma EIP-712 y el peso contra sus delegantes, y declaran si coincide con lo publicado. | El resultado siempre puede reconstruirse desde papeletas válidas |

---

## Fase 4 — Identidad real (4–8 semanas, dependiente de terceros)

Objetivo: cerrar C-4 en su raíz, A-3 y A-8. Los tiempos dependen de organismos externos, no del equipo.

| # | Tarea | Nota |
|---|---|---|
| 4.1 | 🟡 **Backend y cliente web conectados, aún cerrados** (04-08-2026). El backend implementa `authorization_code` + PKCE S256 y el frontend procesa `/unete/clave-unica/callback`, limpia código/state antes del canje y conserva el grant sólo en memoria. El simulador se eliminó. El callback backend ahora implementa idempotencia y está ligado a la sesión del navegador mediante cookie `HttpOnly; Secure` (P-78 resuelto). **Bloqueantes:** trámite/credenciales DGD y prueba contra sandbox. | El trámite administrativo es el camino crítico: iniciarlo en la Fase 0, no aquí |
| 4.2 | 🟡 **Android e iOS cableados, sin trust store ni prueba física** (04-08-2026). Ambos exigen PACE, DG1/DG2/SOD, perfil/emisor chileno, vigencia, hashes, firma SOD y cadena hasta una CSCA chilena aprobada; iOS incluye el bridge en Sources y el release provisiona el PEM por secreto/SHA-256. **Bloqueantes:** el proyecto no dispone de la Master List autorizada, CAN no está validado físicamente y faltan revocación, anti-cloning (AA/CA) y correspondencia DG2↔titular. Sin ello los clientes fallan cerrados para emisión. | No usar listas sample; obtener Registro Civil/ICAO por canal autorizado, validar fingerprints por segundo canal y ratificar revocación/AA/CA |
| 4.3 | 🟡 El código ya importa `react-native-quick-crypto` directamente; validar autolinking, 3DES y rendimiento en builds/dispositivos Android e iOS reales | Prerrequisito de 4.2 |
| 4.4 | 🟡 **Parcial** — contratos de API, wallet y release existen. La app ya no automintea con un booleano/UID NFC: falta un contrato backend de atestación que produzca grant one-shot ligado a SIWE. El build iOS y la lectura física siguen sin ejecutarse en esta máquina | Mantener la app como experimental hasta cerrar P-7/P-79/P-81 |
| 4.5 | Liveness con proveedor especializado (iProov, Onfido, FaceTec) en lugar de un LLM de visión general | Un LLM no es un sistema de detección de vida certificado; no resiste ataques de presentación |

---

## Fase 5 — Descentralización y producción (continuo)

| # | Tarea |
|---|---|
| 5.1 | ✅ **Completada** (04-08-2026). El script `5.1-transfer-roles.js` transfirió `DEFAULT_ADMIN_ROLE` al `TREASURY_SAFE_ADDRESS` base y asignó los roles `ROOT_MANAGER_ROLE`, `PAUSER_ROLE`, y `REVOKER_ROLE` a Safes distintos en Sepolia. La EOA renunció a los privilegios. | Ejecutado en cadena |
| 5.2 | ✅ **Completada** (04-08-2026). Definición del proceso de revocación redactada en `ADR-003-Revocation.md`. |
| 5.3 | ✅ **Completada** (04-08-2026). Guardrails y evaluación de Render free tier documentados en `ADR-004-Observability.md`. |
| 5.4 | ✅ **Completada** (04-08-2026). Arquitectura de observabilidad y Sentry/OTel definidas en `ADR-004-Observability.md`. |
| 5.5 | ✅ **Completada** (04-08-2026). Requisito ineludible de auditoría externa establecido en `ADR-005-Mainnet.md`. |
| 5.6 | ✅ **Completada** (04-08-2026). Política de privacidad, estatutos y consentimiento versionado para Ley 21.719 en `PRIVACY.md`. |
| 5.7 | ✅ **Completada** (04-08-2026). Proceso de selección de red L2 (Arbitrum/Polygon) establecido en `ADR-005-Mainnet.md`. |
| 5.8 | **Seguridad NFC (P-83 / P-84)**: Obtener e inyectar del Gobierno de Chile (Registro Civil) / ICAO los CRLs oficiales (Certificate Revocation Lists) para evitar lectura de cédulas robadas/revocadas (P-83), y habilitar verificación de Autenticación Activa (AA/CA) para impedir clonación del chip (P-84). Fase bloqueada hasta conseguir este material criptográfico oficial. |

---

## Orden de ejecución y dependencias

```
D-1, D-2, D-3  (decisiones — bloquean todo)
      │
   Fase 0 ──────────────────────────────► (paralelo: iniciar trámite ClaveÚnica)
      │
   Fase 1 (bloqueante: nada real hasta aquí)
      │
      ├── Fase 2 (tests — idealmente en paralelo desde 1.5)
      │
   Fase 3
      │
   Fase 4 (limitada por terceros)
      │
   Fase 5
```

**Ruta crítica vigente:** proveedor de identidad + grant de un solo uso → ratificar
D-1/D-2 y custodiar llaves/pepper → desplegar/verificar contrato compatible →
minteo idempotente con reconciliación → verificador de membresía on-chain →
despliegue de los guardrails de esta rama.

**Empezar hoy en paralelo:** el trámite de acceso al sandbox de ClaveÚnica (4.1). Es el único elemento cuyo plazo no controla el equipo.

---

## Métricas de salida por fase

| Fase | Cómo se sabe que terminó |
|---|---|
| 0 | Un desarrollador nuevo levanta el proyecto en < 30 min siguiendo el README. Ningún endpoint devuelve cifras inventadas. |
| 1 | `totalSupply()` en Sepolia > 0 y coincide con `members.count()`. Ningún endpoint mutante acepta peticiones sin JWT. |
| 2 | CI en verde con ≥ 90 % de cobertura en el contrato y ≥ 70 % en el backend. |
| 3 | Un tercero puede reverificar todos los votos de una propuesta sin confiar en el servidor. |
| 4 | Un ciudadano completa el onboarding con ClaveÚnica real y cédula real, sin ningún mock en el camino. |
| 5 | El contrato está auditado externamente y el owner es un multisig. |

---

## Estado tras la Tarea 6 (02-08-2026) — arquitectura de vanguardia

Resumen del avance real sobre las tres decisiones del ADR-001, con lo que
sigue bloqueado dicho explícitamente.

### D-1 · Minteo — **no custodial**

El camino custodial se **eliminó**. La Safe es del ciudadano, firma él con
MetaMask y el backend solo prepara, valida y retransmite. `SAFE_OWNER_PRIVATE_KEY`
ya no se usa en ningún flujo: tenerla configurada se reporta como error.

`prepare-mint` decodifica el `callData` y exige que sea exactamente el
`mintMembership` declarado antes de gastar patrocinio — sin eso, el gas de la
DAO financiaría cualquier transacción que el cliente quisiera.

🔴 **Bloqueado:** sin credenciales de Pimlico ni Safe desplegada, nunca se
ejecutó un envío. El transporte está apagado y el minteo va por el relayer EOA,
que sí está probado.

### D-2 · Identidad — circuito y emisor listos

`MembershipEligibility(25)` con `recipient` ligado en la hoja (cierra el
front-running). Emisor con árbol Merkle de 25 niveles, Poseidon compatible con
circomlib verificado contra vectores publicados, y firma EIP-191.

🔴 **Bloqueado:** no existe proveedor civil que emita `identity_grant`. El
servicio está implementado y probado, pero solo lo ejercitan los tests, y los
simuladores no deben promoverse para resolverlo. Producción falla cerrado.

### D-3 · Gobernanza MACI — los dos circuitos existen

| Pieza | Estado |
|---|---|
| `MACICoordinator.sol` | ✅ 24 tests |
| `maci_tally.circom` | ✅ compilado (16.370 restricciones) y probado con testigo |
| `processMessages.circom` | ✅ compilado (19.860 restricciones) y probado con testigo |
| Registro de llaves | ✅ con validación de subgrupo primo |
| Transporte anónimo | 🟡 sin bearer SIWE, pero no resuelve correlación IP/tiempo |
| Coordinador desplegado | ❌ |
| Ceremonia de confianza | ❌ una sola parte |
| Anclaje poll↔propuesta on-chain | ❌ |

🔴 **`private_voting` se mantiene en `false`** hasta cerrar las cuatro últimas
filas. La existencia de los circuitos no habilita votación privada.

### Deuda registrada

- **P-54** (`AUDIT.md`): el coordinador puede excluir mensajes mal firmados.
  Aceptado a sabiendas para el piloto; exige un verificador EdDSA con salida
  booleana antes de cualquier uso vinculante.
- Ninguno de los tres circuitos tiene ceremonia multi-parte. `verify_identity`
  cuenta con una primera contribución Phase 2 verificada y no promovida en
  `build/trusted-setup/production-20260801-participant-1`, pero todavía faltan
  participantes independientes y beacon final. Quien conozca el residuo de una
  ceremonia de una sola parte puede fabricar pruebas falsas.


---

## Cierre de 3.8 — rate limiter y antifraude compartidos (02-08-2026)

Qué se movió a Redis y qué **no**, que es la parte interesante:

| Estado | Antes | Ahora |
|---|---|---|
| Ventana de peticiones por IP | memoria de proceso | Redis (sorted set + Lua atómico) |
| Penalización progresiva por fallos | memoria de proceso | Redis (contador con TTL) |
| Historial de votos (antifraude) | memoria de proceso | Redis (misma ventana deslizante) |
| Grafo de delegaciones | memoria de proceso | **eliminado** — duplicaba MongoDB |

**Por qué el grafo de delegaciones no fue a Redis.** Era una copia de la
colección `delegations`, y el router ya comprobaba ciclos con
`find_delegation_cycle` y el máximo de delegados con un `count_documents`,
ambos contra la base y con el mismo límite. Llevarlo a Redis habría creado una
tercera copia divergiendo de la fuente autoritativa. Se eliminó, y la única
heurística que aportaba en exclusiva —profundidad máxima de cadena— vive ahora
en `find_delegation_cycle`, sobre el grafo real.

**Corrección de un umbral.** El detector comparaba `> 10` después de excluir el
voto actual, así que dejaba pasar 11 y marcaba el 12º pese a que su constante
decía 10. Ahora se permiten 10 y se marca el 11º.

**El límite de voto es por votante, no por propuesta.** Antes el `proposal_id`
entraba en la clave, así que rotarlo permitía emitir la cuota entera contra
cada propuesta. Hay un test que lo fija.

🔴 **Sin verificar contra un Redis real.** Los tests ejercitan el mismo script
Lua con `fakeredis[lua]`, lo que valida la lógica de la ventana, pero no
sustituye a una prueba contra un servidor. Antes de producción hay que
levantar Redis y repetirlas.


---

## Cierre de 3.2 y 3.3 — papeletas firmadas en elecciones (02-08-2026)

Las propuestas ya firmaban EIP-712; faltaba el mismo esquema en elecciones.

**Separación de dominio.** El tipo es `ElectionBallot(string electionId,
address voter, address candidate, string nonce)`, con `primaryType` distinto
del `Ballot` de propuestas. El nombre del tipo entra en el structHash de
EIP-712, así que una firma no vale en el otro contexto: sin eso, quien firmara
"a favor" en una propuesta estaría firmando también un voto en cualquier
elección con el mismo nonce. Hay un test que lo comprueba emitiendo una firma
de propuesta contra el endpoint de elecciones.

**Nonce compartido.** Propuestas y elecciones usan la misma colección
`ballot_nonces` y el mismo índice único por `(voter_address, nonce)`. Es más
estricto de lo necesario —un nonce gastado en una propuesta no sirve en una
elección— pero evita razonar sobre dos espacios de nonces, y el cliente los
genera al azar.

**Nuevos endpoints:**
- `GET /governance/elections/ballot-schema` — types y domain, para que
  frontend y móvil no mantengan una copia manual desincronizada.
- `GET /governance/elections/{id}/ballots` — papeletas públicas con
  `signature_valid` recomputado, que es lo que permite auditar el resultado
  sin confiar en el servidor.

**Bloqueo de producción actualizado.** El 503 incondicional del voto en
elecciones se sustituyó por el mismo gate que usan las propuestas
(`SIGNED_BALLOTS_REQUIRED`). El bloqueador de readiness pasó de "falta firma
EIP-712" a lo que realmente queda: **el recuento sigue sin ser transaccional
ni reconstruible desde las papeletas** (ROADMAP 3.5).

**Bug encontrado al probarlo.** `/elections/ballot-schema` quedaba eclipsada
por `/elections/{election_id}`: FastAPI resuelve por orden de registro, así
que "ballot-schema" se interpretaba como un id de elección y devolvía 404. Se
reordenó y quedó anotado en el código para que no se repita.
