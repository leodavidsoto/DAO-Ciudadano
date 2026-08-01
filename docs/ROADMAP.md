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
> solo uso, migración de PII legacy, ADR/KMS, despliegue compatible y reconciliación
> idempotente cadena↔Mongo.

| # | Tarea | Detalle | Criterio de aceptación |
|---|---|---|---|
| 1.1 | 🟡 **Sesión basada en firma de wallet (SIWE / EIP-4361)** | Challenge/verify canónico, nonce de un solo uso y JWT corto implementados. Falta decidir si se necesita refresh/rotación de sesión. | `/api/wallet/challenge` y `/verify` funcionando; el JWT contiene `sub = address` |
| 1.2 | ✅ **Dependencia `require_auth` en FastAPI** | Aplicada a mint, propuestas, voto, delegación y elecciones; cada acción debe corresponder al `sub` del token. | Ningún endpoint mutante acepta actuar como otra dirección |
| 1.3 | 🟡 **Rehacer el hash de identidad** | HMAC-SHA256 completo implementado para datos nuevos. Falta KMS/rotación, ADR y migrar/purgar hashes antiguos. | Ningún hash reversible por diccionario queda almacenado |
| 1.4 | 🟡 **Cifrar la PII en reposo** | Fernet + índices HMAC implementados para altas nuevas. Falta inventario, snapshot, migración y rollback de Atlas legacy, además de política de retención. | Un volcado de la base no expone RUT en claro |
| 1.5 | 🟡 **Minteo real on-chain** | Construcción, firma, recibo, evento/lectura de `tokenId` y precondiciones de red/rol/gas implementados. Producción permanece cerrada hasta disponer de grant, contrato, custodia e idempotencia/reconciliación. | `totalSupply()` en el despliegue compatible aumenta y se reconcilia con Mongo |
| 1.6 | 🟡 **Añadir `MINTER_ROLE`** | El contrato actual usa AccessControl y tiene tests; falta desplegarlo, verificarlo y separar/custodiar los roles. | Admin y minter son direcciones distintas y están inventariadas |
| 1.7 | **Eliminar el mock de wallet** ✅ | Eliminados `POST /api/wallet/connect`, `generate_mock_address()` y el cliente huérfano. La conexión la hace MetaMask y la sesión usa challenge/verify SIWE. | No existe una ruta que invente una wallet; `useWallet` firma el desafío real |
| 1.8 | **Eliminar la ABI manual del frontend** ✅ | El minteo es responsabilidad del backend; se borraron la ABI manual incompatible y la dirección legacy. La UI enlaza la transacción real recibida de la API. | Sin ABI duplicada ni dirección histórica en el bundle |
| 1.9 | **Eliminar `useSBTContract` huérfano** ✅ | El hook no se usaba y permitía intentar minteo con el signer del usuario; fue eliminado. | Sin hooks que sugieran minteo client-side inexistente |
| 1.10 | **Proveedor real de identidad/liveness + grant** | Sustituir las demos por un proveedor adecuado, aplicar sus garantías y emitir un permiso de alta de un solo uso. La heurística visual demo no debe promoverse a acreditación. | Sin proveedor o evidencia válida, producción falla cerrado y no puede mintear |
| 1.11 | **Índice único** en `members.wallet_address` (✅ hecho: `Database.ensure_indexes()`) y en el hash de identidad (pendiente, depende de D-2) | migración MongoDB | Imposible crear dos membresías para la misma wallet |
| 1.12 | ✅ Reemplazar `token_id = count + 1` por el `tokenId` del evento o la lectura del contrato | `blockchain_service.py` | El camino on-chain nunca inventa un ID local |
| 1.13 | **Migrar la sesión web fuera de `localStorage`** | Cookie `Secure`/`HttpOnly`/`SameSite`, protección CSRF, logout y revocación coordinados con CORS | Un XSS del frontend no puede extraer el JWT SIWE |

---

## Fase 2 — Tests y CI (1–2 semanas)

> 🟡 **Parcial** (agosto 2026). 2.1: suite de `contracts/test/` (31 tests, incluye la
> regresión del orden checks-effects-interactions en `mintMembership`). 2.2: suite de
> `backend/tests/` con 157 tests, sin red ni Mongo real. 2.3:
> `backend_test.py` y `test_result.md` eliminados. 2.4: `.github/workflows/ci.yml` corre
> backend, contratos, slither, auditoría crítica de npm, `pip-audit` estricto y
> build del frontend en cada PR; las Actions están fijadas por SHA. 2.5: `slither --fail-medium
> --exclude-dependencies` en verde. 2.6: `requirements.txt` con versiones exactas.
> Dependabot quedó configurado para los cinco directorios/ecosistemas. Mobile pasa
> TypeScript, 15 tests, lint y auditoría npm localmente; el workflow incorpora esos
> mismos gates en un nuevo job estático. Pendientes: lint backend, cobertura formal web/backend, build/release
> nativo de mobile, branch protection, secret scanning recurrente y migración de los
> toolchains legacy que concentran los avisos altos de dependencias.

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

---

## Fase 3 — Gobernanza verificable (2–3 semanas)

Objetivo: cerrar C-3, A-4, A-5, A-9 y M-10.

> **Estado 01-08-2026:** 3.2–3.5 y 3.7 implementados para propuestas. 3.1 usa MongoDB
> provisionalmente y cuarentena demo/legacy en producción; el verificador on-chain
> todavía falla cerrado con `NotImplementedError`. El módulo de elecciones de
> representantes sigue sin papeletas EIP-712 y votar se bloquea en producción.
> Pendientes: firma de elecciones, atomicidad/reconciliación del tally, 3.6
> (tesorería real) y 3.8 (Redis).

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 3.1 | **Verificación de membresía para votar**: consultar `hasMembership(address)` on-chain (con caché corta) antes de aceptar un voto o una propuesta | Una dirección sin SBT recibe 403 |
| 3.2 | 🟡 **Votos firmados**: propuestas ya firman EIP-712, persisten mensaje/firma y exponen papeletas para reverificación; falta llevar el mismo esquema a elecciones | Cualquier tercero puede recomputar el resultado sin confiar en el servidor |
| 3.3 | 🟡 **Protección de replay real**: nonce único e índice compuesto implementados para propuestas; falta elecciones | Reenviar un voto firmado da error |
| 3.4 | **Activar el antifraude** ya escrito: llamar `check_rapid_voting` y `check_delegation_chain` desde los endpoints | Los tests de patrones sospechosos pasan |
| 3.5 | **Peso de voto por delegación**: `cast_vote` calcula el peso real a partir de las delegaciones recibidas | Delegar cambia el resultado de forma medible |
| 3.6 | **Tesorería real**: leer balances de un Safe multisig vía API o RPC; precio de ETH desde un oráculo o API de precios, no hardcodeado | Ningún número de tesorería es una constante en el código |
| 3.7 | ✅ **Enrutado y montaje de la UI de gobernanza**: `/` (landing), `/unete` (onboarding) y `/dashboard/{propuestas,elecciones,delegacion,tesoreria}` | Las secciones de gobernanza son alcanzables |
| 3.8 | Mover el rate limiter y el antifraude a Redis | Los límites sobreviven a reinicios y funcionan con varias instancias |
| 3.9 | ✅ **Hecho (julio 2026)** — el middleware usa `asyncio.sleep`; el event loop ya no se bloquea | Sin bloqueo del event loop bajo carga |
| 3.10 | **Tally transaccional o derivado**: evitar que una caída entre insertar la papeleta y sumar el resultado produzca divergencia | El resultado siempre puede reconstruirse desde papeletas válidas |

---

## Fase 4 — Identidad real (4–8 semanas, dependiente de terceros)

Objetivo: cerrar C-4 en su raíz, A-3 y A-8. Los tiempos dependen de organismos externos, no del equipo.

| # | Tarea | Nota |
|---|---|---|
| 4.1 | **Integración real de ClaveÚnica** (OIDC): solicitar acceso al sandbox de la División de Gobierno Digital, implementar el flujo `authorization_code` + PKCE, validar `id_token`, mapear `RUN` del claim | El trámite administrativo es el camino crítico: iniciarlo en la Fase 0, no aquí |
| 4.2 | **Lectura NFC real de la cédula**: implementar PACE (no BAC) sobre ISO-DEP; capturar CAN o MRZ por OCR; verificar la firma del SOD contra la CSCA chilena | Es la tarea de mayor dificultad técnica del proyecto. Evaluar SDK comercial vs implementación propia |
| 4.3 | 🟡 El código ya importa `react-native-quick-crypto` directamente; validar autolinking, 3DES y rendimiento en builds/dispositivos Android e iOS reales | Prerrequisito de 4.2 |
| 4.4 | 🟡 **Parcial** — contratos de API y pantalla Wallet existen; gates locales/CI pasan, pero faltan PACE y un build/release nativo reproducible. El backend público ejecuta una versión anterior | Mantener la app como experimental hasta cerrar P-7 |
| 4.5 | Liveness con proveedor especializado (iProov, Onfido, FaceTec) en lugar de un LLM de visión general | Un LLM no es un sistema de detección de vida certificado; no resiste ataques de presentación |

---

## Fase 5 — Descentralización y producción (continuo)

| # | Tarea |
|---|---|
| 5.1 | Asignar `DEFAULT_ADMIN_ROLE` a un Safe multisig, separar minter/pauser/revoker y retirar privilegios de la EOA |
| 5.2 | Definir y publicar el proceso de revocación: quién puede pedirla, con qué causal, con qué apelación. El cooldown de 3 días ya existe en el contrato; falta la gobernanza que lo legitime |
| 5.3 | Publicar los guardrails actuales y evaluar si Render free tier es adecuado para un SLA real |
| 5.4 | Observabilidad: Sentry/OpenTelemetry, métricas y alertas; elegir e instalar el stack (Prometheus no está en requirements) |
| 5.5 | Auditoría externa del contrato antes de cualquier despliegue en mainnet |
| 5.6 | Evaluación de impacto en protección de datos (Ley 21.719), privacidad/términos/estatutos publicados y consentimiento versionado |
| 5.7 | Elegir red mediante ADR y desplegar en mainnet solo con contrato auditado y verificado |

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
