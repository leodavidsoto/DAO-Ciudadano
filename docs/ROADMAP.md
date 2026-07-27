# Plan de implementación — DAO Ciudadana

**Base:** hallazgos de [`AUDIT.md`](./AUDIT.md) sobre el commit `f2902ca`.
**Principio rector:** cada fase deja el sistema en un estado más honesto que la anterior. Nada que se muestre al usuario debe afirmar algo que el sistema no puede probar.

---

## Decisiones de arquitectura que hay que tomar antes de escribir código

> 📌 **Recomendaciones concretas en [`adr/0001-decisiones-fase-1.md`](./adr/0001-decisiones-fase-1.md)**,
> con opciones, riesgo residual de cada una y qué desbloquea aprobarlas. Pendiente de decisión.

Estas tres decisiones bloquean todo lo demás. No son opcionales y no tienen respuesta por defecto.

### D-1 · ¿Quién mintea el SBT?

| Opción | Cómo funciona | A favor | En contra |
|---|---|---|---|
| **A. Server-side (custodial)** | El backend firma con una wallet owner y llama `mintMembership`. Es lo que el contrato ya soporta (`onlyOwner`). | Cero fricción para el usuario, no necesita gas ni entender Web3. Coherente con el contrato actual. | El backend custodia una llave privada con poder de acuñar. Punto único de fallo. Exige HSM o KMS. |
| **B. Client-side con firma** | El backend emite un voucher firmado (EIP-712); el usuario llama `mintWithVoucher` y paga su gas. Requiere modificar el contrato. | El backend nunca custodia llaves con fondos. El usuario controla su transacción. | Fricción alta: el ciudadano necesita ETH de gas. Barrera de adopción real en un proyecto cívico. |
| **C. Híbrido con meta-transacciones** | El usuario firma un mensaje sin gas; un relayer lo ejecuta y paga. | Combina lo mejor de A y B. | Más piezas: relayer, protección contra abuso del relayer, ERC-2771. |

**Recomendación:** empezar con **A** (es lo que el contrato ya permite, y desbloquea la Fase 1 sin redeploy), con la llave en un KMS gestionado y un `MINTER_ROLE` separado del `owner`. Migrar a **C** cuando haya volumen.
Si se elige B o C hay que **redesplegar el contrato** — decidirlo ahora evita hacerlo dos veces.

### D-2 · ¿Qué se escribe on-chain como `identityHash`?

El esquema actual (`sha256(RUT)[:16]`) es reversible por fuerza bruta y no puede ir a un registro público. Alternativas:

- **HMAC-SHA256(RUT, pepper)** con el pepper en KMS, nunca en el repositorio ni en la base. Simple y suficiente para impedir enumeración. **Recomendada para la Fase 1.**
- **Compromiso Pedersen / commitment con nonce aleatorio por usuario**, guardando el nonce cifrado. Permite pruebas de pertenencia sin revelar el RUT.
- **Prueba de conocimiento cero** (Semaphore, zk-proof de pertenencia al padrón). Es el destino correcto a largo plazo para un sistema de voto anónimo, pero no es un punto de partida realista.

Sea cual sea: **usar 32 bytes completos, no 16 hex truncados**, y `bytes32` en el contrato en vez de `string` (ahorra gas y evita comparaciones de strings).

### D-3 · ¿La gobernanza es on-chain u off-chain?

Hoy es 100 % off-chain en MongoDB: las propuestas, los votos y la tesorería viven en una base que el operador puede editar. Eso no es una DAO, es un formulario.

- **Off-chain con firma verificable** (estilo Snapshot): cada voto es un mensaje firmado por la wallet, se almacena el mensaje y la firma, cualquiera puede reverificar. Barato, sin gas, auditable. **Recomendado para la Fase 3.**
- **On-chain completo** (OpenZeppelin Governor + tesorería en Safe): máxima garantía, costo de gas por voto, complejidad alta.

**Recomendación:** off-chain firmado ahora, con la tesorería en un **Safe multisig real** desde el principio — una tesorería inventada es peor que no tener tesorería.

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

| # | Tarea | Detalle | Criterio de aceptación |
|---|---|---|---|
| 1.1 | **Sesión basada en firma de wallet (SIWE / EIP-4361)** | El backend emite un nonce, el usuario firma con MetaMask, el backend valida y emite un JWT con expiración corta + refresh. Sustituye el login por RUT+email. | `POST /api/auth/siwe/nonce` y `/verify` funcionando; el JWT contiene `sub = address` |
| 1.2 | **Dependencia `require_auth` en FastAPI** | Aplicada a mint, propuestas, voto y delegación. El `voter_address` deja de venir del body: se toma del token. | Ningún endpoint mutante acepta una dirección arbitraria del cliente |
| 1.3 | **Rehacer el hash de identidad** | `HMAC-SHA256(RUT, pepper)` con pepper en KMS. Migrar a `bytes32` en el contrato. Purgar los hashes antiguos de la base. | Ningún hash reversible por diccionario queda almacenado |
| 1.4 | **Cifrar la PII en reposo** | RUT y email cifrados con clave gestionada; índices sobre el HMAC, no sobre el valor en claro. Definir política de retención. | Un volcado de la base no expone RUT en claro |
| 1.5 | **Minteo real on-chain** | Implementar `BlockchainService.mint_sbt` con `web3.py`: construir, firmar y enviar la transacción; esperar el recibo; extraer `tokenId` del evento; persistir `tx_hash` y `block_number` reales. Manejar `AlreadyHasMembership` e `IdentityAlreadyUsed`. | `totalSupply()` en Sepolia aumenta con cada alta |
| 1.6 | **Añadir `MINTER_ROLE`** | Migrar de `Ownable` a `AccessControl` para separar quién acuña de quién administra. Requiere redeploy. | El owner y el minter son direcciones distintas |
| 1.7 | **Eliminar el mock de wallet** | Borrar `POST /api/wallet/connect` y `generate_mock_address()`. La conexión ya la hace MetaMask en el cliente. | `OnboardingContext.connectWallet` usa `useWallet`, no la API |
| 1.8 | **Corregir la ABI del frontend** | Regenerarla desde `artifacts/` en el build en lugar de mantenerla a mano. | El evento `MembershipMinted` se parsea correctamente y `tokenId` no es `null` |
| 1.9 | **Cablear `useSBTContract`** | O se usa en el flujo, o se elimina. No dejar código muerto que sugiera una capacidad inexistente. | Sin hooks huérfanos |
| 1.10 | **Umbral de liveness** | Definir el mínimo (sugerido 0.75), rechazar por debajo, registrar el score. Sin API key configurada, **fallar** en vez de devolver 0.85. | Un score bajo bloquea el avance del onboarding |
| 1.11 | **Índice único** en `members.wallet_address` (✅ hecho: `Database.ensure_indexes()`) y en el hash de identidad (pendiente, depende de D-2) | migración MongoDB | Imposible crear dos membresías para la misma wallet |
| 1.12 | Reemplazar `token_id = count + 1` por el `tokenId` devuelto por el contrato | `membership.py:32` | El ID off-chain siempre coincide con el on-chain |

---

## Fase 2 — Tests y CI (1–2 semanas)

> ✅ **Completada** (julio 2026). 2.1: suite de `contracts/test/` (29 tests, incluye la
> regresión del orden checks-effects-interactions en `mintMembership`). 2.2: suite de
> `backend/tests/` con `pytest` + `mongomock` (46 tests, sin red ni Mongo real). 2.3:
> `backend_test.py` y `test_result.md` eliminados. 2.4: `.github/workflows/ci.yml` corre
> backend, contratos, slither y build del frontend en cada PR. 2.5: `slither --fail-medium
> --exclude-dependencies` en verde. 2.6: `requirements.txt` con versiones exactas.
> La cobertura formal (≥90 %/≥70 %) queda por medir e imponer en CI.

Objetivo: cerrar C-5 y hacer que las fases siguientes no rompan lo anterior.

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 2.1 | Suite de tests del contrato en `contracts/test/`: minteo, unicidad por wallet, rechazo de `identityHash` repetido, intento de transferencia (debe revertir), pausado, ciclo completo de revocación con cooldown, permisos | Cobertura ≥ 90 % en `DAOCiudadanaSBT.sol` |
| 2.2 | Tests de integración del backend con `pytest` + `mongomock` o contenedor efímero: autenticación, mint, voto, límites de tasa | Cobertura ≥ 70 % en `routers/` y `services/` |
| 2.3 | Reescribir `backend_test.py`, que hoy apunta a un host de preview inexistente, o eliminarlo | Sin tests que apunten a infraestructura muerta |
| 2.4 | GitHub Actions: lint + tests de contrato + tests de backend + build del frontend en cada PR | Un PR que rompe tests no se puede mergear |
| 2.5 | `slither` sobre el contrato en CI | Sin hallazgos de severidad alta |
| 2.6 | Fijar versiones exactas en `requirements.txt` | Builds reproducibles |

---

## Fase 3 — Gobernanza verificable (2–3 semanas)

Objetivo: cerrar C-3, A-4, A-5, A-9 y M-10.

| # | Tarea | Criterio de aceptación |
|---|---|---|
> **Estado 26-07-2026:** 3.1, 3.4, 3.5 y 3.7 implementados. La verificación de membresía
> usa MongoDB con la interfaz lista para conmutar a on-chain (`MEMBERSHIP_SOURCE`). Añadido
> fuera de plan: módulo de elecciones de representantes. Pendientes: 3.2 (votos firmados
> EIP-712), 3.3 (nonce anti-replay), 3.6 (tesorería real), 3.8 (Redis) y 3.9.

| 3.1 | **Verificación de membresía para votar**: consultar `hasMembership(address)` on-chain (con caché corta) antes de aceptar un voto o una propuesta | Una dirección sin SBT recibe 403 |
| 3.2 | **Votos firmados**: cada voto es un mensaje EIP-712 firmado por el votante; se almacena mensaje + firma; endpoint público de reverificación | Cualquier tercero puede recomputar el resultado sin confiar en el servidor |
| 3.3 | **Protección de replay real**: usar el `nonce` que ya viaja en `VoteRequest` y validarlo contra los ya consumidos | Reenviar un voto firmado da error |
| 3.4 | **Activar el antifraude** ya escrito: llamar `check_rapid_voting` y `check_delegation_chain` desde los endpoints | Los tests de patrones sospechosos pasan |
| 3.5 | **Peso de voto por delegación**: `cast_vote` calcula el peso real a partir de las delegaciones recibidas | Delegar cambia el resultado de forma medible |
| 3.6 | **Tesorería real**: leer balances de un Safe multisig vía API o RPC; precio de ETH desde un oráculo o API de precios, no hardcodeado | Ningún número de tesorería es una constante en el código |
| 3.7 | **Enrutado y montaje de la UI de gobernanza**: añadir `react-router-dom` en `App.js` con rutas `/`, `/governance`, `/treasury`, `/profile` | Los cuatro componentes huérfanos son alcanzables |
| 3.8 | Mover el rate limiter y el antifraude a Redis | Los límites sobreviven a reinicios y funcionan con varias instancias |
| 3.9 | ✅ **Hecho (julio 2026)** — el middleware usa `asyncio.sleep`; el event loop ya no se bloquea | Sin bloqueo del event loop bajo carga |

---

## Fase 4 — Identidad real (4–8 semanas, dependiente de terceros)

Objetivo: cerrar C-4 en su raíz, A-3 y A-8. Los tiempos dependen de organismos externos, no del equipo.

| # | Tarea | Nota |
|---|---|---|
| 4.1 | **Integración real de ClaveÚnica** (OIDC): solicitar acceso al sandbox de la División de Gobierno Digital, implementar el flujo `authorization_code` + PKCE, validar `id_token`, mapear `RUN` del claim | El trámite administrativo es el camino crítico: iniciarlo en la Fase 0, no aquí |
| 4.2 | **Lectura NFC real de la cédula**: implementar PACE (no BAC) sobre ISO-DEP; capturar CAN o MRZ por OCR; verificar la firma del SOD contra la CSCA chilena | Es la tarea de mayor dificultad técnica del proyecto. Evaluar SDK comercial vs implementación propia |
| 4.3 | Corregir el bundling de `crypto` en React Native: `resolver.extraNodeModules` en `metro.config.js` apuntando a `react-native-quick-crypto` | Prerrequisito de 4.2 |
| 4.4 | ✅ **Hecho (julio 2026)** — los cinco contratos de `apiService.ts` alineados con el backend, pantalla `Wallet` creada y registrada (consulta de membresía), URL base apuntando a entorno de desarrollo (el backend de producción sigue suspendido, M-15) | Sin esto la app no completa ningún flujo |
| 4.5 | Liveness con proveedor especializado (iProov, Onfido, FaceTec) en lugar de un LLM de visión general | Un LLM no es un sistema de detección de vida certificado; no resiste ataques de presentación |

---

## Fase 5 — Descentralización y producción (continuo)

| # | Tarea |
|---|---|
| 5.1 | Migrar el `owner` del contrato de una EOA a un Safe multisig (cierra M-11) |
| 5.2 | Definir y publicar el proceso de revocación: quién puede pedirla, con qué causal, con qué apelación. El cooldown de 3 días ya existe en el contrato; falta la gobernanza que lo legitime |
| 5.3 | ✅ **Configurado (julio 2026)** — evaluación hecha: Fly.io eliminó su capa gratuita y Koyeb cerró la suya, así que el destino es **Render free + MongoDB Atlas M0**. `render.yaml` con `plan: free`, `Dockerfile` portable para migrar sin reescribir, dependencias de producción recortadas y arranque que no bloquea esperando a Mongo. Falta el paso manual de crear el servicio y el clúster (guía en `backend/DEPLOY.md`) |
| 5.4 | Observabilidad: Sentry para errores, métricas Prometheus, alertas. (`prometheus-client` se retiró de `requirements.txt` por no estar importado; hay que volver a añadirlo cuando se instrumente de verdad) |
| 5.5 | Auditoría externa del contrato antes de cualquier despliegue en mainnet |
| 5.6 | Evaluación de impacto en protección de datos (Ley 21.719) y política de privacidad publicada |
| 5.7 | Despliegue en mainnet (Polygon, según el README) con contrato auditado y verificado |

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

**Ruta crítica:** D-1 → 1.1 → 1.5 → 2.1. Hasta que 1.5 esté listo, el producto no hace lo que dice hacer.

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
