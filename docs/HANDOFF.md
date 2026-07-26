# Handoff — DAO Ciudadana

**Para:** Claude Fable 5 (o cualquier agente/desarrollador que retome el proyecto)
**De:** auditoría del 26 de julio de 2026
**Estado del repositorio:** `main` @ `f2902ca`
**Documentos hermanos:** [`AUDIT.md`](./AUDIT.md) · [`ROADMAP.md`](./ROADMAP.md)

---

## Lee esto primero

Este proyecto **parece** terminado y **no lo está**. La UI es pulida, la estructura del código es buena y hay un contrato desplegado en Sepolia. Eso puede llevar a asumir que solo faltan detalles. No es así.

Los tres hechos que tienes que interiorizar antes de tocar una línea:

1. **`totalSupply()` del contrato en Sepolia devuelve 0.** Nunca se minteó un SBT. Todo lo que la app llama "membresía" son documentos de MongoDB con hashes de transacción inventados por `uuid4()`.
2. **Ningún endpoint de la API pide autenticación.** Un `curl` crea membresías, propuestas y votos ilimitados.
3. **El backend de producción está suspendido.** Render devuelve 503 y el frontend de Netlify apunta ahí.

Si empiezas por añadir funcionalidades nuevas, vas a construir sobre una base que afirma cosas falsas. Empieza por hacer verdadero lo que ya existe.

---

## Mapa del repositorio

```
DAO-Ciudadano/
├── backend/                    FastAPI + MongoDB (Motor)
│   ├── main.py                 punto de entrada REAL
│   ├── server.py               ⚠️ app legacy duplicada, NO se usa — borrar
│   └── app/
│       ├── core/               config, database, security, middleware
│       ├── models/schemas.py   todos los modelos Pydantic
│       ├── routers/            auth, wallet, membership, dashboard, governance
│       └── services/           auth_service, blockchain_service (⚠️ ambos con mocks)
├── frontend/                   React 19 + CRA/craco + Tailwind + Radix
│   └── src/
│       ├── components/
│       │   ├── onboarding/     flujo principal (el que se usa)
│       │   ├── governance/     ⚠️ construido pero NO montado en ninguna ruta
│       │   └── ui/             shadcn/Radix
│       ├── context/            OnboardingContext — estado de todo el flujo
│       ├── hooks/              useWallet (real), useNFC (real), useSBTContract (⚠️ huérfano)
│       ├── contracts/          ABI mantenida a mano — ⚠️ desincronizada
│       └── lib/api.js          capa axios
├── contracts/                  Hardhat + OpenZeppelin 5
│   ├── contracts/DAOCiudadanaSBT.sol
│   ├── scripts/deploy.js
│   └── test/                   ⚠️ NO EXISTE — cero tests
├── mobile/                     React Native 0.83 + NFC
│   └── src/services/           ⚠️ apiService incompatible con la API; nfcService es un esqueleto
└── docs/                       AUDIT.md · ROADMAP.md · HANDOFF.md (este archivo)
```

---

## Datos operativos

| Elemento | Valor |
|---|---|
| Contrato SBT (Sepolia) | `0x813fd379F715107b2451553d97f29408d8185f0e` |
| Owner del contrato | `0x154484aff9f6864db17141c6eec62568b8f5ac9b` (EOA — llave privada no está en el repo) |
| `totalSupply()` actual | `0` |
| Backend producción | `https://dao-ciudadana-api.onrender.com` — **suspendido (503)** |
| Frontend producción | Netlify — `regal-dieffenbachia-6e9194.netlify.app` |
| Base de datos | MongoDB, `DB_NAME=dao_ciudadana` |
| Red objetivo declarada | Polygon (README) — pero el despliegue real está en Sepolia |

**Advertencia:** la llave privada del owner no está en el repositorio (correcto). Sin ella no se puede mintear on-chain ni transferir la propiedad del contrato. **Confirma con el dueño del proyecto si esa llave existe y está a resguardo antes de planificar la Fase 1.** Si se perdió, hay que redesplegar el contrato — lo cual, al ser `totalSupply() == 0`, no cuesta nada. Es un buen momento para hacerlo bien.

---

## Cómo levantar el proyecto

No hay `.env.example` en el repositorio (tarea 0.1 del roadmap). Estas son las variables que el código lee:

**`backend/.env`**
```
MONGO_URL=mongodb://localhost:27017
DB_NAME=dao_ciudadana
SECRET_KEY=<generar>
CORS_ORIGINS=http://localhost:3000
DEBUG=true
EMERGENT_LLM_KEY=<opcional; sin esto el liveness devuelve 0.85 fijo>
```

**`frontend/.env`**
```
REACT_APP_BACKEND_URL=http://localhost:8000
REACT_APP_SBT_CONTRACT_POLYGON=<opcional>
```

**`contracts/.env`** — ver `contracts/ENV_SETUP.md`
```
SEPOLIA_RPC_URL=
PRIVATE_KEY=            # sin prefijo 0x, NUNCA commitear
ETHERSCAN_API_KEY=
```

```bash
# backend
cd backend && pip install -r requirements.txt && uvicorn main:app --reload --port 8000
# ⚠️ emergentintegrations NO está en requirements.txt pero auth.py intenta importarlo (falla suave)

# frontend
cd frontend && yarn install && yarn start

# contratos
cd contracts && npm install && npx hardhat compile
```

---

## Trampas concretas del código

Cosas que te van a costar tiempo si no las sabes de antemano:

1. **`backend/server.py` no se usa.** Es una app FastAPI completa y duplicada de una versión anterior. `main.py` es el punto de entrada real. No la edites por error: bórrala.

2. **Hay dos implementaciones de minteo que no se hablan.** `routers/membership.py` tiene la lógica inline (sin verificación de duplicados) y es la que se ejecuta. `services/blockchain_service.py` tiene una versión mejor (con verificación) que **nadie llama**. Al arreglar el minteo, unifica en el servicio.

3. **La ABI del frontend está escrita a mano y está mal.** El evento real es `MembershipMinted(address indexed, uint256 indexed, string, uint256)`; `SBTContract.js` declara `(address indexed, uint256, string)`. Firma distinta → `parseLog` nunca encuentra el evento. Genera la ABI desde `artifacts/` en el build en vez de mantenerla a mano.

4. **`mintMembership` es `onlyOwner`,** pero `useSBTContract.js` lo llama con el signer del usuario. Ese camino siempre revertiría. Es la decisión D-1 del roadmap: resuélvela antes de escribir código de minteo.

5. **El módulo antifraude existe, está bien escrito y nunca se ejecuta.** `fraud_detector`, `generate_nonce` y `hash_vote_data` se importan en `governance.py` y no se invocan. No los reescribas: cablealos.

6. **`generate_short_hash()` es `sha256(x)[:16]` sin sal.** Con RUT chilenos (~30 M de valores) es reversible en segundos. No lo uses para nada que vaya on-chain ni a un log.

7. **La app móvil tiene cinco contratos de API rotos** (nombres de campo distintos, rutas inexistentes). No es que falle a veces: no completa ningún flujo. Ver tabla A-6 en `AUDIT.md`.

8. **La pantalla `Wallet` de la app móvil no existe** pero dos pantallas navegan hacia ella. Crash garantizado.

9. **`ensure_sample_transactions()` escribe datos falsos en la base de producción** cada vez que se consulta la tesorería y la colección está vacía. Bórrala antes que nada.

10. **El rate limiter llama a `time.sleep()` dentro de un middleware async.** Congela el event loop para todas las peticiones concurrentes, no solo la del atacante.

---

## Por dónde empezar — primeras cinco sesiones sugeridas

**Sesión 1 — Fase 0 completa.** Es mecánica, no requiere decisiones y deja el repo honesto: quitar cifras inventadas, borrar `server.py`, sacar los artifacts del control de versiones, crear los `.env.example`, arreglar los defaults de `DEBUG` y `CORS_ORIGINS`, actualizar el README. Un solo PR.

**Sesión 2 — Tests del contrato (2.1).** No depende de ninguna decisión pendiente y es la red de seguridad para todo lo demás. El contrato ya está escrito; escribir sus tests además te obliga a leerlo con atención, que es la mejor forma de conocerlo.

**Sesión 3 — Resolver D-1, D-2 y D-3 con el dueño del proyecto.** No son decisiones técnicas que puedas tomar solo: definen quién custodia llaves, qué se publica en un registro inmutable y qué garantías ofrece la gobernanza. Documenta la decisión en un ADR dentro de `docs/`.

**Sesión 4 — Autenticación (1.1, 1.2).** SIWE + JWT, y proteger todos los endpoints mutantes. A partir de aquí el sistema deja de ser escribible por cualquiera.

**Sesión 5 — Minteo real (1.5).** Con `web3.py` en el backend. Al final de esta sesión `totalSupply()` deja de ser 0 y el proyecto hace, por primera vez, lo que dice hacer.

---

## Convenciones a respetar

- **Idioma:** código, nombres de variables y comentarios en inglés; mensajes al usuario, documentación y commits en español. El repositorio ya sigue este patrón.
- **Backend:** la lógica de negocio va en `services/`, no en `routers/`. Los routers validan, delegan y responden. Ya hay deriva de esta regla en `membership.py` — corrígela, no la imites.
- **Modelos:** todos los Pydantic viven en `models/schemas.py`, excepto los de gobernanza que están inline en `governance.py`. Unificar sería una mejora.
- **Frontend:** alias `@/` configurado en `craco.config.js` y `jsconfig.json`. Componentes en `.jsx`, utilidades en `.js`. Cada carpeta de componentes tiene su `index.js` de exportación.
- **Estado:** `OnboardingContext` centraliza el flujo. No introduzcas Redux ni Zustand para esto.
- **Estilos:** Tailwind con tema cyberpunk propio en `styles/premium.css`. Reutiliza las clases `cyber-*` existentes antes de crear nuevas.
- **Contratos:** Solidity 0.8.20, OpenZeppelin 5, errores personalizados en lugar de strings de revert. El contrato actual es un buen modelo a seguir.

---

## Reglas de trabajo para el agente que retome esto

1. **No inventes datos para que la UI se vea bien.** Este proyecto ya tiene ese problema y es su hallazgo más grave después de la falta de autenticación. Si un dato no existe, devuelve `null` y que la interfaz muestre un estado vacío honesto.

2. **No marques una tarea como completa si el camino real no se ejecutó.** El precedente aquí es `test_result.md`, que documenta un protocolo de testing elaborado sin un solo resultado registrado.

3. **Verifica contra la fuente, no contra la documentación.** El README de este repositorio afirma varias cosas que el código contradice. Antes de dar por sentada una capacidad, búscala en el código y, si es on-chain, consúltala por RPC.

4. **Cuando arregles un mock, elimina el mock.** No dejes la ruta simulada como fallback silencioso: es exactamente así como el liveness terminó devolviendo 0.85 fijo en producción.

5. **Todo cambio en `contracts/` requiere tests antes del merge.** No hay excepción razonable: es un contrato de identidad civil.

6. **Los secretos nunca al repositorio.** `.gitignore` ya cubre `*.env`; verifícalo con `git check-ignore` antes de cada commit que toque configuración.

7. **Cambios pequeños y verificables.** El historial de este repo tiene commits llamados "Auto-generated changes" y "auto-commit for <uuid>" que hacen imposible saber qué cambió y por qué. No continúes esa práctica.

8. **Si encuentras un hallazgo nuevo, añádelo a `AUDIT.md`** con su ubicación `archivo:línea` y su severidad. Mantén el documento vivo.

---

## Lo que está bien y hay que conservar

No reescribas el proyecto. Estas piezas son sólidas:

- **`DAOCiudadanaSBT.sol`** — soulbound correctamente implementado en `_update`, errores personalizados, `ReentrancyGuard`, revocación con cooldown de 3 días, y `_usedIdentityHashes` que deliberadamente no se limpia al quemar para impedir el re-registro. Es buen trabajo. Solo le faltan tests, `AccessControl` y `bytes32` en vez de `string`.
- **La estructura del backend** — `core`/`models`/`routers`/`services` bien separados.
- **La validación de RUT** (`auth.py:220`) — módulo 11 con dígito verificador, correcta.
- **`useWallet` + `WalletStep`** — integración real de MetaMask que maneja ausencia de wallet, cambio de red y reconexión.
- **La identidad visual** — coherente y cuidada en todo el flujo.

El trabajo pendiente no es de arquitectura. Es hacer real lo que hoy está simulado, y poner una puerta donde hoy no hay ninguna.
