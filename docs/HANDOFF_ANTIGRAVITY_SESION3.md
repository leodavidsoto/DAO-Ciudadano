# Handoff Sesión 3 — DAO Ciudadana (Checkpoint)

Este documento registra el estado de los flujos desarrollados por los 3 agentes locales (Claude/Codex) antes de agotar sus tokens de sesión, y por los 3 subagentes paralelos de Antigravity. Este handoff sirve para reanudar el trabajo en nuevas sesiones sin pérdida de contexto.

**Actualizado en la sesión 4:** los tres hilos quedaron cerrados y con sus puertas
en verde. Lo que sigue distingue lo que se ejecutó de lo que solo se afirmó.

---

## 1. Agente Backend (Claude 1) — Emisión de Grants de Identidad ✅

**Logro:** el servicio `membership_grant.py` emite un JWT de un solo uso que
autoriza el minteo (ROADMAP 1.10 y P-4): el servidor emite y certifica, el
cliente ya no se autodeclara nivel de aseguramiento.

**Cerrado en la sesión 4:** no quedaba código pendiente, solo verificarlo.

- `tests/test_membership_grant.py` — 17 tests, pasan.
- `test_clave_unica.py` y `test_cedula_nfc.py` ya afirman la emisión del grant
  en la respuesta de autenticación, su sujeto, su nivel y su reemisión idéntica
  al repetir el callback.
- **Suite completa: 566 tests, todos pasan** (`cd backend && ./.venv/bin/python -m pytest -q`).

## 2. Agente Contratos/ZK (Claude 2) — MACI On-chain ✅ (con bloqueador conocido)

**Ejecutado en la sesión 4:** `npx hardhat test` → **59 tests, todos pasan**
(`MACI.test.js` aporta 14).

Ojo con lo que esos tests dicen: el bloque *«frontera rota entre publishTally y
maci_tally.circom»* afirma que **una prueba auténtica es rechazada por
`publishTally`**. El bloqueador **D-3 está codificado como test**, no resuelto.
La tarea `maci:tally` (`contracts/tasks/maci-tally.js`, registrada en
`hardhat.config.js`) reproduce el fallo y sale con estado 1. Ese es el próximo
frente real: reconciliar las señales públicas del circuito con las que el
contrato espera.

## 3. Agente Mobile/Frontend (Codex) — Flujo PACE NFC ✅

**Cerrado en la sesión 4.** El agente se interrumpió a mitad de la pantalla de
éxito y dejó el flujo roto en un punto que ninguna prueba cubría:
`OnboardingProvider` nunca se montaba en `App.tsx`, así que el `useOnboarding()`
de `ScanScreen` lanzaba en cuanto se abría el escáner. Arreglado, más:

- `App.tsx` monta el proveedor sobre el navegador y `RootStackParamList`
  declara `grantIssued`.
- `SuccessScreen`: se eliminó el estado `autoAdvancing`, que duplicaba a
  `readyToMint` y solo podía quedar obsoleto. El aviso y el temporizador se
  derivan ahora del mismo valor.
- Cobertura nueva para la frontera que se acababa de abrir: envío de los
  archivos en crudo (no del veredicto local), rechazo 401 mostrando las razones
  del servidor, 503 sin culpar al ciudadano, error de red con reintento, y el
  avance automático solo con un grant vivo (no basta el flag de la ruta, y un
  grant vencido no avanza).
- **Puertas: 74 tests pasan, `tsc --noEmit` limpio, `eslint .` con 0 errores**
  (quedan avisos preexistentes de estilos en línea).

El camino completo queda: chip → `readChileanIDPACE` → `POST /api/auth/cedula/verify`
→ grants al `OnboardingContext` → `SuccessScreen` avanza al minteo.

---

## Aportes paralelos de los Subagentes Antigravity — estado **verificado**

La versión anterior de este documento los daba por «listos para fusionarse».
Comprobado contra las ramas y los worktrees, eso no es exacto:

| Módulo | Estado real |
| --- | --- |
| **Autenticación Activa (AA)** | Commit `bdb78cf` en `subagent-Backend-Cryptographer-backend-agent-43808001`, **sin fusionar**. |
| **MACI Relayer** | **Sin commitear.** Su rama no tiene commits propios; `maci_relayer.py`, `test_maci_relayer.py` y cambios en `governance.py` y `docs/AUDIT.md` viven solo en el árbol de trabajo del subagente. Se pierden si se limpia el worktree. |
| **E2E Playwright** | Commit `5f2a315` en `subagent-E2E-Playwright-Engineer-frontend-agent-b8413b59`, **sin fusionar**. Su mensaje dice «public EIP-712 voting», no votación anónima. |

Ninguno de los tres está en `codex/produccion-ci`: `active_auth.py` y
`maci_relayer.py` no existen en `backend/app/services/`. Antes de fusionarlos
hay que ejecutar sus tests en esta rama, no fiarse del reporte del subagente.

*(Nota: los cambios de los agentes locales hasta el commit `c529299` están asegurados; lo de la sesión 4 sigue sin commitear.)*
