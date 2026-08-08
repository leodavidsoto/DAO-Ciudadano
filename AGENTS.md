# AGENTS.md — Reglas de trabajo

Instrucciones para cualquier agente de IA que trabaje en este repositorio (Codex, Claude, Copilot u otro).

**Contexto completo antes de tocar código:** [`docs/HANDOFF.md`](./docs/HANDOFF.md) · [`docs/AUDIT.md`](./docs/AUDIT.md) · [`docs/ROADMAP.md`](./docs/ROADMAP.md)

**Tu ámbito de trabajo** no depende de qué modelo seas, sino del carril que te
asignen: ver [«Trabajo en paralelo con varios agentes»](#trabajo-en-paralelo-con-varios-agentes)
más abajo. (Hasta el 08-08-2026 el reparto era por proveedor —Claude en backend
y contratos, Codex en frontend y móvil—; se sustituyó porque el problema real
nunca fue quién eres, sino qué ficheros tocas a la vez que otro.)

---

## Qué es este proyecto

Plataforma de membresía ciudadana chilena: verificación de identidad que emite un Soulbound Token no transferible como credencial de participación en una DAO, con gobernanza (propuestas, votos, delegación, elecciones de representantes).

**Estado:** piloto técnico endurecido, todavía no apto para identidad civil ni
minteo de producción. Léelo en `HANDOFF.md` antes de asumir capacidades.

---

## Los cuatro hechos que definen el estado actual

1. **Ya hay un despliegue compatible en Sepolia**, en
   `0x6C6C7D0ceC1b7267cB2fa146519FBF9ef6319d56`: responde a la ABI actual y el
   backend le lee `membershipScope()` y aprueba raíces. Su `totalSupply()` es 0
   porque nadie ha minteado todavía, no porque esté roto. El contrato
   *histórico* `0x813fd379…` usa otra ABI y **no debe configurarse**.
2. **Minteo y acciones mutantes de gobernanza exigen SIWE y actuar como la propia wallet.** En
   producción solo se confía en membresías on-chain verificadas
   (`MEMBERSHIP_SOURCE=onchain`, ya operativo).
3. **La identidad civil real ya funciona por cédula NFC**, verificada contra una
   cédula chilena física y anclas CSCA reales del Registro Civil: el servidor
   repite la Autenticación Pasiva y emite los grants. ClaveÚnica sigue sin
   configurar, y liveness y RUT/email siguen siendo demos que devuelven 503 con
   `APP_ENV=production`.
4. **Hay una llave de proveedor expuesta en el historial Git público.** No copies
   su valor: debe revocarse/rotarse y auditarse según `docs/SECURITY_RUNBOOK.md`.

Verifícalo tú mismo — el contrato compatible tiene bytecode, el histórico
responde con otra ABI:

```bash
curl -s -X POST https://ethereum-sepolia-rpc.publicnode.com \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"eth_getCode","params":["0x6C6C7D0ceC1b7267cB2fa146519FBF9ef6319d56","latest"],"id":1}'
```

Qué falta para producción y cómo comprobarlo: [`docs/PRODUCCION_SEPOLIA.md`](./docs/PRODUCCION_SEPOLIA.md)

---

## Reglas innegociables

1. **Nunca inventes datos para rellenar una interfaz.** Si un dato no existe, devuelve `null` y muestra un estado vacío honesto. Este repositorio ya tuvo un dashboard con 1432 miembros falsos y una tesorería ficticia sembrada en la base de datos; ambos se eliminaron. No los reintroduzcas, ni siquiera como *placeholder* de demo.

2. **Cuando arregles un mock, borra el mock.** No lo dejes como fallback silencioso. Así fue como el liveness terminó devolviendo `0.85` fijo en producción sin que nadie lo notara.

3. **No marques nada como completo si no ejecutaste el camino real.** Si no lograste correr los tests o el build, dilo explícitamente.

4. **Verifica contra el código y la cadena, no contra la documentación.** El README llegó a afirmar cosas que el código contradecía.

5. **No simules capacidades que no existen.** `chain_service.has_membership` lanza `ChainReadError` cuando el RPC falla en vez de devolver `False`, y la votación privada MACI declara `private_voting: false`: es mejor que falle explícito a que mienta.

6. **Todo cambio en `contracts/` necesita tests antes del merge.** Sin excepción: es un contrato de identidad civil.

7. **La lógica de negocio va en `services/`,** no en los routers. Los routers validan, delegan y responden.

8. **Secretos jamás al repositorio.** `.gitignore` cubre `*.env`; verifícalo con `git check-ignore` antes de commitear configuración.

9. **Commits pequeños y descriptivos.** El historial tiene entradas antiguas como `auto-commit for <uuid>` que no dicen nada. No continúes esa práctica.

10. **Si encuentras un hallazgo nuevo, regístralo** con ubicación `archivo:línea` y severidad. Si trabajas en paralelo con otros agentes, va en `docs/hallazgos/<tarea>.md`, no directamente en `docs/AUDIT.md` (ver «Trabajo en paralelo»).

11. **Valida contra la especificación, no contra tu propio fixture.** Si implementas un protocolo definido por un tercero —ICAO 9303, ISO/IEC 9796-2, EIP-712, Groth16— usa vectores de prueba publicados por esa especificación. Tres veces en este repositorio unos tests en verde confirmaron una implementación equivocada, porque el fixture repetía la misma suposición que el código: **P-97** (formato del CAN), **P-101** (posición del RUN en la MRZ) y el commit `bdb78cf` (PKCS1v15 donde ICAO exige ISO/IEC 9796-2, que habría rechazado todos los chips reales con 96 líneas de tests en verde). Ningún fixture demuestra que la realidad sea como el fixture. Si no hay vectores publicados, dilo explícitamente en vez de fabricar confianza.

12. **No renombres una función para que parezca que hace más de lo que hace.** Hubo un `submit_batch_on_chain()` que no tocaba la cadena: marcaba filas en Mongo y devolvía un conteo. Si algo no está implementado, que el nombre y la respuesta lo digan.

---

## Convenciones

- **Idioma:** código, nombres e identificadores y comentarios en **inglés**; textos de interfaz, documentación y mensajes de commit en **español**.
- **Backend:** `core` / `models` / `routers` / `services`. Pydantic v2. Los modelos de gobernanza viven inline en sus routers.
- **Frontend:** alias `@/` configurado en `craco.config.js`. Componentes en `.jsx`, utilidades en `.js`. Cada carpeta de componentes exporta desde su `index.js`.
- **Estado:** `OnboardingContext` para el flujo de alta. No introduzcas Redux ni Zustand.
- **Estilos:** identidad cívica en todo el sitio — fondo claro, azul `#003897`,
  rojo `#CB2C27`, tinta `#0B2545`, Poppins (títulos) + Open Sans (texto).
  La landing usa `styles/landing.css`; el interior (dashboard y `/unete`) usa
  `styles/civic.css` con clases `civic-*`. Reutiliza esas antes de crear nuevas.
  `App.css` y `styles/premium.css` conservan el tema cyberpunk histórico y sus
  clases `cyber-*`: quedan neutralizadas dentro de `.civic-app` y **no deben
  usarse en pantallas nuevas**.
- **Contratos:** Solidity 0.8.20, OpenZeppelin 5, errores personalizados en lugar de strings de revert.
- **Direcciones:** siempre normalizadas a minúsculas antes de guardar o consultar.

---

## Comandos

```bash
# Backend
cd backend && pip install -r requirements-dev.txt
uvicorn main:app --reload --port 8000
pytest -q                                   # 614 tests (08-08-2026)
python -m pip_audit -r requirements.txt --strict

# Frontend
cd frontend && npm ci
npm start
npm run build
CI=true npx craco test --watchAll=false     # 90 tests — craco, NO jest directo

# Mobile
cd mobile && npm test                       # 76 tests

# Contratos
cd contracts && npm ci
npx hardhat test                            # 59 tests
npx hardhat coverage
```

**Usa el runner correcto en el frontend.** Invocar `jest` directamente sobre
`frontend/` falla con un error del parser de Babel porque se salta la
configuración de CRA. No es un test roto; es el comando equivocado.

**Dependencias:** `requirements.txt` es solo producción y está mínimo a propósito (Render free: 512 MB y arranque en frío). `requirements-dev.txt` añade tests y linters, y es lo que instala el CI. `python-multipart` y `pymongo` no aparecen en ningún `import` pero son obligatorias — están documentadas en el propio archivo.

**CI:** GitHub Actions con 6 jobs (backend pytest + `pip-audit`, contratos
Hardhat + auditoría npm, slither, tests/build estricto del frontend + auditoría
npm, E2E Playwright y gates estáticos/test/auditoría de mobile).
Las Actions están fijadas por SHA. El ruleset «main protegida» **ya existe y
está activo**: exige pull request, prohíbe borrado y non-fast-forward, y hace
obligatorios cuatro checks — `Backend · pytest`, `Contracts · hardhat test`,
`Contracts · slither` y `Frontend · build`. Los jobs de mobile corren pero no
bloquean el merge.

---

## Trabajo en paralelo con varios agentes

Este repositorio se trabaja con varios agentes a la vez. Dos veces ha pasado que
dos de ellos editaran los mismos ficheros y dejaran la suite en rojo, y una vez
que el trabajo de un agente casi se pierde por vivir sin commitear en un
worktree desatendido. Estas reglas existen por eso.

### Carriles con dueño único

Cada agente concurrente posee un conjunto de ficheros. **Nunca dos agentes en el
mismo carril, y como máximo tres carriles a la vez.**

| Carril | Ficheros |
|---|---|
| `identidad` | `backend/app/services/{cedula_nfc,passive_auth,active_auth,aa_challenge,csca_*}.py`, `backend/app/routers/cedula.py` y sus tests |
| `movil` | `mobile/src/**`, `mobile/scripts/**` |
| `nativo` | `mobile/android/**`, `mobile/ios/**` |
| `contratos-zk` | `contracts/**`, `circuits/**` |
| `web` | `frontend/**`, `e2e/**` |
| `gobernanza` | `backend/app/routers/{governance,elections}.py`, `backend/app/services/governance_service.py` |

`movil` y `nativo` van separados **a propósito**: es exactamente donde
colisionaron los agentes de anti-replay y de minteo.

### Ficheros calientes

`mobile/src/services/nfcService.ts`, `mobile/android/.../PassportReaderModule.kt`,
`mobile/ios/.../PassportReader.swift` y `backend/app/core/config.py` los tocan
varios carriles por naturaleza. Solo los edita el carril que los posee en ese
momento; si otro los necesita, lo pide en vez de editarlos.

### Los agentes no editan `AUDIT.md`, `ROADMAP.md` ni `HANDOFF.md`

Escribe tus hallazgos en `docs/hallazgos/<tarea>.md` con `archivo:línea` y
severidad; el orquestador los funde. Son tres documentos de estado global y
cada agente ve solo su trozo: un agente llegó a sustituir las 2.101 líneas de
`AUDIT.md` por tres suyas.

### Rama por tarea, y commit antes de terminar

`tarea/<slug>` desde `main`. **No uses worktrees desatendidos.** Un encargo no
está terminado hasta que su trabajo está commiteado y empujado: lo que vive
solo en el directorio de trabajo lo borra un `git worktree prune` sin preguntar.

### Definición de «terminado»

1. Las suites afectadas en verde, citando el comando exacto que usaste.
2. El camino real ejecutado, no solo los tests.
3. Hallazgos registrados en `docs/hallazgos/<tarea>.md`.
4. Commiteado y empujado en su rama.
5. Nada descrito como «producción» mientras `circuits/artifact-manifest.json`
   declare `trustedSetup: single-host-development-integration`: quien corrió esa
   ceremonia de una sola parte puede falsificar pruebas.

---

## Antes de escribir código nuevo

Hay tres decisiones de arquitectura con implementaciones provisionales que deben
ratificarse por ADR antes de producción. Detalle en `docs/ROADMAP.md`:

- **D-1** ✅ **resuelta.** ADR-001 la cierra como Account Abstraction, y la
  Enmienda 1 (08-08-2026) acota que el móvil mintea por el relayer
  (`/membership/mint-zk`) porque ERC-4337 + Safe sigue sin credenciales de
  Pimlico ni Safe desplegada. El camino custodial se eliminó y no vuelve. Queda
  abierto quién paga el gas a largo plazo y separar el admin del relayer.
- **D-2** ¿qué se escribe on-chain como `identityHash`? HMAC-SHA256 completo está
  implementado para altas nuevas, pero falta KMS/rotación y migración legacy.
- **D-3** ¿la gobernanza es on-chain o off-chain con firmas verificables? Las
  propuestas usan EIP-712; elecciones y tally transaccional siguen pendientes.

No son decisiones que un agente deba tomar solo: definen custodia de llaves privadas y qué se publica de forma permanente sobre cada ciudadano. Consúltalas con el dueño del proyecto y deja un ADR en `docs/`.

---

## Orden de trabajo

```
Fase 0  Higiene y verdad          ✅ completa
Fase 1  Auth + minteo real        🟡 identidad, ADR y despliegue resueltos; falta que el móvil mintee
Fase 2  Tests y CI                🟡 ruleset activo y 839 tests verdes en local; falta release nativo y coverage
Fase 3  Gobernanza verificable    🟡 propuestas y elecciones firmadas; el tally MACI está roto (D-3)
Fase 4  Identidad real            🟡 cédula NFC funcionando; faltan Master List, CRL/OCSP y ClaveÚnica
Fase 5  Descentralización         ❌ pendiente
```

Lo que hoy separa el piloto de una demo son dos cosas: **que la app móvil pueda
mintear** y **que la cédula resista un replay**. El resto es configuración,
trámites con terceros o decisiones del dueño.

Criterios de aceptación por fase en `docs/ROADMAP.md`.
