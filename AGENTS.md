# AGENTS.md — Reglas de trabajo

Instrucciones para cualquier agente de IA que trabaje en este repositorio (Codex, Claude, Copilot u otro).

**Contexto completo antes de tocar código:** [`docs/HANDOFF.md`](./docs/HANDOFF.md) · [`docs/AUDIT.md`](./docs/AUDIT.md) · [`docs/ROADMAP.md`](./docs/ROADMAP.md)

---

## Qué es este proyecto

Plataforma de membresía ciudadana chilena: verificación de identidad que emite un Soulbound Token no transferible como credencial de participación en una DAO, con gobernanza (propuestas, votos, delegación, elecciones de representantes).

**Estado:** a mitad de camino entre simulado y real. Léelo en `HANDOFF.md` antes de asumir capacidades.

---

## Los tres hechos que definen el estado actual

1. **`totalSupply()` del contrato en Sepolia = 0.** Ningún SBT se ha minteado on-chain. Las "membresías" son documentos de MongoDB.
2. **Ningún endpoint exige autenticación.** Hay control de membresía en gobernanza, pero no de identidad: el backend cree la dirección que le manden en el cuerpo de la petición.
3. **La verificación de identidad es simulada.** ClaveÚnica, NFC y liveness devuelven datos fabricados.

Verifícalo tú mismo:

```bash
curl -s -X POST https://ethereum-sepolia-rpc.publicnode.com \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"eth_call","params":[{"to":"0x813fd379F715107b2451553d97f29408d8185f0e","data":"0x18160ddd"},"latest"],"id":1}'
```

---

## Reglas innegociables

1. **Nunca inventes datos para rellenar una interfaz.** Si un dato no existe, devuelve `null` y muestra un estado vacío honesto. Este repositorio ya tuvo un dashboard con 1432 miembros falsos y una tesorería ficticia sembrada en la base de datos; ambos se eliminaron. No los reintroduzcas, ni siquiera como *placeholder* de demo.

2. **Cuando arregles un mock, borra el mock.** No lo dejes como fallback silencioso. Así fue como el liveness terminó devolviendo `0.85` fijo en producción sin que nadie lo notara.

3. **No marques nada como completo si no ejecutaste el camino real.** Si no lograste correr los tests o el build, dilo explícitamente.

4. **Verifica contra el código y la cadena, no contra la documentación.** El README llegó a afirmar cosas que el código contradecía.

5. **No simules capacidades que no existen.** `OnChainMembershipVerifier` lanza `NotImplementedError` a propósito: es mejor que falle explícito a que mienta.

6. **Todo cambio en `contracts/` necesita tests antes del merge.** Sin excepción: es un contrato de identidad civil.

7. **La lógica de negocio va en `services/`,** no en los routers. Los routers validan, delegan y responden.

8. **Secretos jamás al repositorio.** `.gitignore` cubre `*.env`; verifícalo con `git check-ignore` antes de commitear configuración.

9. **Commits pequeños y descriptivos.** El historial tiene entradas antiguas como `auto-commit for <uuid>` que no dicen nada. No continúes esa práctica.

10. **Si encuentras un hallazgo nuevo, añádelo a `docs/AUDIT.md`** con ubicación `archivo:línea` y severidad. Mantén el documento vivo.

---

## Convenciones

- **Idioma:** código, nombres e identificadores y comentarios en **inglés**; textos de interfaz, documentación y mensajes de commit en **español**.
- **Backend:** `core` / `models` / `routers` / `services`. Pydantic v2. Los modelos de gobernanza viven inline en sus routers.
- **Frontend:** alias `@/` configurado en `craco.config.js`. Componentes en `.jsx`, utilidades en `.js`. Cada carpeta de componentes exporta desde su `index.js`.
- **Estado:** `OnboardingContext` para el flujo de alta. No introduzcas Redux ni Zustand.
- **Estilos:** Tailwind con tema cyberpunk propio en `styles/premium.css`. Reutiliza las clases `cyber-*` antes de crear nuevas.
- **Contratos:** Solidity 0.8.20, OpenZeppelin 5, errores personalizados en lugar de strings de revert.
- **Direcciones:** siempre normalizadas a minúsculas antes de guardar o consultar.

---

## Comandos

```bash
# Backend
cd backend && pip install -r requirements-dev.txt
uvicorn main:app --reload --port 8000
pytest -q                                   # 72 tests

# Frontend
cd frontend && npm install --legacy-peer-deps
npm start
npm run build

# Contratos
cd contracts && npm install
npx hardhat test                            # 29 tests
npx hardhat coverage
```

**Dependencias:** `requirements.txt` es solo producción y está mínimo a propósito (Render free: 512 MB y arranque en frío). `requirements-dev.txt` añade tests y linters, y es lo que instala el CI. `python-multipart` y `pymongo` no aparecen en ningún `import` pero son obligatorias — están documentadas en el propio archivo.

**CI:** GitHub Actions con 4 jobs (backend pytest, contratos hardhat, slither, build del frontend). Debe quedar en verde antes de mergear.

---

## Antes de escribir código nuevo

Hay tres decisiones de arquitectura sin resolver que bloquean la Fase 1 (autenticación y minteo real). Detalle en `docs/ROADMAP.md`:

- **D-1** ¿quién mintea el SBT — backend custodial, voucher firmado por el usuario, o relayer?
- **D-2** ¿qué se escribe on-chain como `identityHash`? El esquema actual es reversible por fuerza bruta.
- **D-3** ¿la gobernanza es on-chain o off-chain con firmas verificables?

No son decisiones que un agente deba tomar solo: definen custodia de llaves privadas y qué se publica de forma permanente sobre cada ciudadano. Consúltalas con el dueño del proyecto y deja un ADR en `docs/`.

---

## Orden de trabajo

```
Fase 0  Higiene y verdad          ✅ completa
Fase 1  Auth + minteo real        ❌ bloqueante — requiere D-1 y D-2
Fase 2  Tests y CI                ✅ completa
Fase 3  Gobernanza verificable    🟡 3.1, 3.4, 3.5, 3.7 hechos · faltan 3.2, 3.3, 3.6, 3.8
Fase 4  Identidad real            ❌ limitada por terceros (ClaveÚnica, PACE)
Fase 5  Descentralización         ❌ pendiente
```

Criterios de aceptación por fase en `docs/ROADMAP.md`.
