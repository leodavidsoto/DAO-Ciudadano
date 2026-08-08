# Handoff Antigravity — Sesión 2, 06-ago-2026

**Para:** Claude y Codex (agentes locales) — code review en la próxima sesión
**Elaborado por:** Antigravity (orquestador) con subagentes
**Rama:** `codex/produccion-ci` · base `8fce6b3`
**Hora de inicio:** 2026-08-06T03:07 CLT

---

## Desde dónde retomamos

Los dos agentes locales (Claude terminal + Codex terminal) se quedaron sin
tokens durante una sesión de orquestación que llevaba 4 agentes en paralelo.
El estado al momento de la interrupción:

### Lo que habían completado (commits existentes)

| Commit | Autor | Resumen |
|---|---|---|
| `8fce6b3` | Claude | fix: apply code review recommendations (hermetic testing, explicit failure) |
| `7e3c8df` | Claude | docs: actualizar ROADMAP con la dirección del contrato en Sepolia |
| `85309b3` | Claude | chore: persist pending configs for redis and sourcify |
| `6c681f4` | Claude | docs: actualizar HANDOFF.md con sesión de orquestación 06-08-2026 |
| `0db034b` | Claude | feat(core): completar autenticación pasiva ICAO, parche de memoria JNI en Mobile y setup MACI |

### Lo que quedó sin commit (5 archivos modificados)

El agente Claude estaba implementando **revocación real de JWT** para cerrar
completamente la tarea 1.13 (migrar sesión fuera de `localStorage`). El
trabajo quedó a medias:

| Archivo | Cambio | Estado |
|---|---|---|
| `backend/app/core/database.py` | Índice único `jti` + colección `revoked_tokens` | ✅ Código correcto |
| `backend/app/core/retention.py` | Regla de retención TTL para tokens revocados | ✅ Código correcto |
| `backend/app/routers/deps.py` | `read_token` de sync → `await` async | ✅ Código correcto |
| `backend/app/routers/wallet.py` | `/logout` ahora revoca el JWT + importa `Header` | ✅ Código correcto |
| `backend/app/services/siwe_service.py` | `read_token` async + consulta blacklist, `revoke_token` nueva | ✅ Código correcto |

**No había tests dedicados** para la revocación de JWT. Un subagente fue
despachado para crearlos.

### Estado verificado por el orquestador

| Verificación | Resultado |
|---|---|
| Backend tests (543) | ✅ Todos pasan con los cambios sin commit |
| Frontend build (`craco build`) | ✅ Compila correctamente |
| Contract tests (45) | ✅ Todos pasan |
| Contrato histórico `0x813fd3…` `totalSupply()` | `0` (incompatible, no usar) |
| Contrato nuevo `0x6C6C7D…` `totalSupply()` | `0` (compatible, sin minteo aún) |
| MACICoordinator `0x1CC2…` | Desplegado y con clave del coordinador configurada |
| TallyVerifier `0x3817…` | Desplegado |

---

## Trabajo despachado a subagentes

### Subagente 1: Backend JWT Revocation (Claude-domain)

**Tareas:**
1. ✅ Verificar que los 543 tests pasan con los cambios sin commit
2. Crear tests dedicados para la revocación de JWT
3. Verificar formateo (black/flake8)
4. Hacer commit: `feat(auth): revocación real de JWT en logout (tarea 1.13)`

### Subagente 2: Frontend Cookie Migration (Codex-domain)

**Tareas:**
1. Analizar `useWallet.js` — cómo maneja el token actualmente
2. Migrar a `session_transport: "cookie"` en `/api/wallet/verify`
3. Restaurar sesión con `GET /api/wallet/session` en vez de localStorage
4. Configurar axios con `withCredentials: true` y header `X-CSRF-Token`
5. Verificar build y hacer commit

---

## Lo que queda por verificar en la próxima sesión (code review)

### Para Claude (backend + contratos)

1. **Revisar la revocación de JWT:**
   - ¿`read_token()` consulta la blacklist en CADA request? Impacto en latencia
   - ¿La colección `revoked_tokens` tiene TTL de MongoDB (`expireAfterSeconds`)
     además de la regla de retención del barrido manual?
   - ¿`revoke_token` funciona si el token ya expiró? (un token expirado no
     debería decodificarse — ¿se silencia el error correctamente?)
   - ¿El import circular `from ..services import siwe_service` en `wallet.py`
     dentro de la función es correcto? (funciona, pero es un patrón a revisar)

2. **Tests de integración pendientes:**
   - Test que verifica que un token revocado devuelve 401 en un endpoint protegido
   - Test que un logout desde un navegador no afecta la sesión de otro
   - Test que el TTL de retención coincide con `SESSION_TOKEN_EXPIRE_SECONDS`

3. **Hallazgos para AUDIT.md:**
   - P-XX: La consulta a `revoked_tokens` en cada request añade una lectura
     MongoDB por petición autenticada. Si la colección crece, necesita el
     índice TTL de MongoDB para auto-purgarse (no solo el barrido manual).

### Para Codex (frontend + mobile)

1. **Revisar la migración de cookies:**
   - ¿Se eliminó completamente `localStorage.setItem` para el token?
   - ¿`getCsrfToken()` maneja correctamente el caso de cookie ausente?
   - ¿El interceptor de 401 limpia el estado de wallet correctamente?
   - ¿`WalletSessionProvider` restaura la sesión al montar?

2. **E2E fixture:**
   - `e2e/tests/support/e2e-fixture.js:348` simula `/api/wallet/verify` con
     solo `{token, address}`. Debe actualizarse para fijar cookies + CSRF.

3. **Mobile:**
   - La app móvil usa `session_transport: "token"` (no cookies).
     Verificar que sigue funcionando con el refactor.

---

## Inventario on-chain (verificado 06-ago-2026 03:08 CLT)

| Elemento | Dirección | Estado |
|---|---|---|
| DAOCiudadanaSBT (vigente) | `0x6C6C7D0ceC1b7267cB2fa146519FBF9ef6319d56` | Verificado Sourcify, `totalSupply=0` |
| Groth16Verifier | `0x179e2bbfBe6dCFA610a5a30B81d5A6C0eb19dDd7` | Desplegado |
| MACICoordinator | `0x1CC218883dBeFf6aB8b4933723DF23B8F69336a6` | Clave configurada |
| TallyVerifier | `0x3817516c4fa354c9F24f6deCE0eA636048c54D87` | Desplegado |
| Contrato histórico (NO USAR) | `0x813fd379F715107b2451553d97f29408d8185f0e` | Incompatible |

---

## Próximos pasos por impacto (sin cambio respecto al ROADMAP)

1. ~~Desplegar contrato SBT compatible en Sepolia~~ → **HECHO** (`0x6C6C…`)
2. Validar antifraude contra Redis real → tests usan `fakeredis[lua]`
3. Anclaje poll↔propuesta on-chain (MACI D-3)
4. Build nativo iOS
5. Ceremonia multi-parte ZK
6. Identidad civil (ClaveÚnica/CSCA) → bloqueado por terceros
7. Branch protection en main → acción externa GitHub

---

## Fase del ROADMAP

```
Fase 0  Higiene y verdad          ✅ completa
Fase 1  Auth + minteo real        🟡 SIWE/cookies/revocación listos; faltan identidad, despliegue público
Fase 2  Tests y CI                🟡 543 backend + 45 contratos + 15 mobile; faltan coverage, lint CI, branch protection
Fase 3  Gobernanza verificable    🟡 propuestas EIP-712; faltan elecciones firmadas, tally, MACI
Fase 4  Identidad real            ❌ bloqueada por terceros
Fase 5  Descentralización         ❌ pendiente
```
