# CLAUDE.md — Contexto operativo para agentes

Instrucciones para cualquier agente de IA que trabaje en este repositorio.
Documentación completa en [`docs/HANDOFF.md`](./docs/HANDOFF.md) · [`docs/AUDIT.md`](./docs/AUDIT.md) · [`docs/ROADMAP.md`](./docs/ROADMAP.md).

---

## Qué es este proyecto

Plataforma de membresía ciudadana chilena: verificación de identidad (ClaveÚnica / NFC de cédula / biometría) que emite un Soulbound Token no transferible como credencial de participación en una DAO.

**Estado real (26-07-2026):** funcionalidad central simulada. Léelo antes de asumir capacidades.

---

## Los tres hechos que definen el estado actual

1. **`totalSupply()` del contrato en Sepolia = 0.** Ningún SBT se ha minteado nunca. Las "membresías" son documentos de MongoDB con `tx_hash` generados por `uuid4()`.
2. **Ningún endpoint exige autenticación.** No se emite JWT en ninguna parte pese a tener las librerías instaladas.
3. **El backend de producción está suspendido** (Render, 503).

Verifícalo tú mismo antes de planificar:

```bash
curl -s -X POST https://ethereum-sepolia-rpc.publicnode.com \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"eth_call","params":[{"to":"0x813fd379F715107b2451553d97f29408d8185f0e","data":"0x18160ddd"},"latest"],"id":1}'
```

---

## Estructura

| Ruta | Qué es | Advertencia |
|---|---|---|
| `backend/main.py` | Punto de entrada real | — |
| `backend/app/services/` | Lógica de negocio | `auth_service` y `blockchain_service` contienen mocks |
| `backend/app/routers/membership.py` | Minteo | Duplica lógica del servicio, sin validar duplicados |
| `frontend/src/context/OnboardingContext.jsx` | Estado del flujo completo | Usa los mocks del backend, no los hooks Web3 reales |
| `frontend/src/hooks/useSBTContract.js` | Interacción on-chain | **Huérfano: nadie lo importa** |
| `frontend/src/contracts/SBTContract.js` | ABI a mano | **Desincronizada con el contrato desplegado** |
| `frontend/src/components/governance/` | UI de gobernanza | **No montada en ninguna ruta** |
| `contracts/contracts/DAOCiudadanaSBT.sol` | Contrato SBT | Bien diseñado, **cero tests** |
| `contracts/test/` | — | **No existe** |
| `mobile/src/services/apiService.ts` | Cliente API móvil | **Cinco contratos rotos: ningún flujo funciona** |
| `mobile/src/services/nfcService.ts` | Lectura NFC | Esqueleto: PACE/BAC sin implementar |

---

## Reglas de trabajo

1. **Nunca inventes datos para rellenar una interfaz.** Si un dato no existe, devuelve `null` y muestra un estado vacío. Este repositorio ya tiene `max(total_members, 1432)` en el dashboard y una tesorería ficticia sembrada en la base — no amplíes ese patrón, elimínalo.

2. **Cuando arregles un mock, borra el mock.** No lo dejes como fallback silencioso. Así fue como el liveness quedó devolviendo `0.85` fijo en producción.

3. **Verifica contra el código y la cadena, no contra el README.** El README afirma cosas que el código contradice (ver tabla de contradicciones en `AUDIT.md`).

4. **Todo cambio en `contracts/` necesita tests antes del merge.** Sin excepción: es un contrato de identidad civil.

5. **La lógica de negocio va en `services/`,** no en los routers. `membership.py` ya se desvía de esta regla; corrígelo, no lo imites.

6. **Idioma:** código y comentarios en inglés, mensajes al usuario y commits en español.

7. **Secretos jamás al repositorio.** Verifica con `git check-ignore` antes de commitear configuración.

8. **Commits descriptivos.** El historial tiene entradas como `auto-commit for <uuid>` que no dicen nada. No continúes esa práctica.

9. **Si encuentras un hallazgo nuevo, añádelo a `docs/AUDIT.md`** con ubicación `archivo:línea` y severidad.

---

## Antes de escribir código nuevo

Hay tres decisiones de arquitectura sin resolver que bloquean el desarrollo (detalle en `docs/ROADMAP.md`):

- **D-1** ¿quién mintea el SBT — backend custodial, usuario con voucher firmado, o relayer?
- **D-2** ¿qué se escribe on-chain como `identityHash`? (el esquema actual es reversible por fuerza bruta)
- **D-3** ¿la gobernanza es on-chain o off-chain con firmas verificables?

No son decisiones que un agente deba tomar solo: definen custodia de llaves, qué se publica de forma permanente en un registro público y qué garantías reales ofrece la DAO. Consúltalas con el dueño del proyecto y deja un ADR en `docs/`.

---

## Orden de trabajo recomendado

```
Fase 0  Higiene y verdad          ← empezar aquí, no requiere decisiones
Fase 1  Auth + minteo real        ← bloqueante, requiere D-1 y D-2
Fase 2  Tests y CI                ← puede ir en paralelo desde Fase 1
Fase 3  Gobernanza verificable    ← requiere D-3
Fase 4  Identidad real            ← limitado por terceros (ClaveÚnica, PACE)
Fase 5  Descentralización         ← continuo
```

Detalle completo con criterios de aceptación en `docs/ROADMAP.md`.

---

## Comandos

```bash
# backend
cd backend && pip install -r requirements.txt && uvicorn main:app --reload --port 8000
pytest                                    # suite con mongomock, no requiere MongoDB real

# frontend (el lockfile es package-lock.json: usar npm, no yarn)
cd frontend && npm ci && npm start

# contratos
cd contracts && npm ci && npx hardhat compile
npx hardhat test                          # suite de la tarea 2.1
npx hardhat run scripts/deploy.js --network sepolia
```

Desde la Fase 0 hay `.env.example` en `backend/`, `frontend/` y `contracts/`. Variables documentadas en `docs/HANDOFF.md`.
