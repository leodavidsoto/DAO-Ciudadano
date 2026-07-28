# Handoff — DAO Ciudadana

**Para:** Codex, Claude, o cualquier persona que retome el proyecto
**Actualizado:** 27 de julio de 2026 · commit `374a86c`
**Hermanos:** [`AUDIT.md`](./AUDIT.md) · [`ROADMAP.md`](./ROADMAP.md) · [`adr/0001-decisiones-fase-1.md`](./adr/0001-decisiones-fase-1.md) · [`../AGENTS.md`](../AGENTS.md)

---

## Lee esto primero

El proyecto cambió de naturaleza en la última tanda de trabajo. Si leíste una versión anterior de este documento, **descártala**: decía que no había autenticación, que el minteo era ficticio y que la PII estaba en claro. Las tres cosas están resueltas en código.

Lo que **sí** sigue siendo cierto, y es lo que tienes que interiorizar:

1. **`totalSupply()` en Sepolia sigue devolviendo 0.** El código para mintear on-chain existe y está probado, pero nadie ha desplegado el contrato nuevo ni configurado la llave del minter. Hasta que eso pase, el backend corre en modo demo explícito.
2. **El contrato desplegado no es el del repositorio.** El que está en Sepolia es la versión anterior: `Ownable`, `identityHash` como `string`, y sin el arreglo de checks-effects-interactions. La ABI del frontend ya no le corresponde.
3. **El frontend no migró.** No hace el handshake de sesión ni firma papeletas. Por eso `SIGNED_BALLOTS_REQUIRED` está en `false`.

En una frase: **el backend ya hace lo que el producto promete; falta desplegarlo y que el frontend lo use.**

```bash
# Compruébalo tú mismo
curl -s -X POST https://ethereum-sepolia-rpc.publicnode.com \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"eth_call","params":[{"to":"0x813fd379F715107b2451553d97f29408d8185f0e","data":"0x18160ddd"},"latest"],"id":1}'
```

---

## Qué es el proyecto

Plataforma de membresía ciudadana chilena. Una persona verifica su identidad y recibe un **Soulbound Token** no transferible que acredita su pertenencia a una DAO. Con esa membresía propone, vota, delega su voto y elige representantes.

---

## Estado por área

| Área | Estado | Detalle |
|---|---|---|
| **Autenticación** | ✅ Implementada | Sesiones por firma de wallet (EIP-4361). La dirección sale del token, nunca del cuerpo. |
| **Contrato SBT** | ✅ Código listo | `AccessControl` con `MINTER_ROLE` separado de `ADMIN_ROLE`, `identityHash` en `bytes32`. **32 tests.** ⚠️ Sin desplegar. |
| **Minteo on-chain** | ✅ Código listo | Firma y envía la transacción, espera recibo, lee el `tokenId` del evento. ⚠️ Deshabilitado hasta configurar RPC + contrato + llave. |
| **Identidad (hash)** | ✅ Implementada | HMAC-SHA256 con pepper, 32 bytes. Falla cerrado sin pepper. |
| **PII en reposo** | ✅ Cifrada | Fernet + índices ciegos para consultar sin descifrar. |
| **Gobernanza** | ✅ Funcional | Propuestas, votos con peso por delegación, elecciones de representantes, papeletas firmadas EIP-712. |
| **Dashboard** | ✅ Montado | `/dashboard` con 5 secciones. |
| **Despliegue** | 🟡 Parcial | Backend en Render + Atlas, frontend en Netlify, CI con 4 jobs. Faltan las variables de la Fase 1. |
| **Frontend Web3** | ❌ Sin migrar | No pide token de sesión ni firma papeletas. |
| **Identidad real** | ❌ Simulada | ClaveÚnica y NFC devuelven datos fabricados (Fase 4, depende de terceros). |
| **App móvil** | ⚠️ Parcial | API alineada, pero la lectura PACE del chip no está implementada. |

---

## Lo que necesita una persona, no un agente

Nada de la Fase 1 funciona en producción hasta que alguien haga esto. Requiere credenciales y responsabilidad real.

### 1. Redesplegar el contrato

Sigue siendo **gratis**: `totalSupply()` es 0, no hay nada que migrar. Arrastra tres cambios de una vez — `AccessControl`, `bytes32` y el arreglo del hallazgo N-2.

```bash
cd contracts
# ADMIN_ADDRESS debería ser un Safe multisig, no una EOA
ADMIN_ADDRESS=0x... MINTER_ADDRESS=0x... npx hardhat run scripts/deploy.js --network sepolia
```

El script **exige** ambas direcciones y no usa al desplegador por defecto: conceder control total a la llave que casualmente ejecuta el script es como una DAO acaba dependiendo del portátil de una persona.

### 2. Generar los secretos

```bash
# Pepper del hash de identidad — el secreto de mayor valor del sistema
python -c "import secrets; print(secrets.token_urlsafe(48))"

# Clave de cifrado de PII — separada del pepper a propósito
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Configurar en Render

| Variable | Nota |
|---|---|
| `IDENTITY_PEPPER` | Si se filtra, las identidades ya acuñadas quedan reversibles **de forma retroactiva y sin rotación posible**. |
| `PII_ENCRYPTION_KEY` | Perderla hace ilegibles los registros existentes. |
| `MINTER_PRIVATE_KEY` | Llave con `MINTER_ROLE`. Idealmente en un KMS, no en una variable de entorno. |
| `SBT_CONTRACT_ADDRESS` | La dirección del contrato **nuevo**. |
| `SEPOLIA_RPC_URL` | Habilita el minteo on-chain. |

Sin `IDENTITY_PEPPER` o `PII_ENCRYPTION_KEY`, el backend **falla cerrado** en vez de degradar a algo inseguro. Es intencional.

---

## Mapa del repositorio

```
backend/app/
├── core/
│   ├── identity.py      HMAC del RUT con pepper (D-2) + índice ciego
│   ├── crypto.py        cifrado Fernet de PII en reposo
│   ├── errors.py        report(): log con id de correlación, sin filtrar detalle
│   └── database.py      índices de integridad + arranque no bloqueante
├── routers/
│   ├── session.py       challenge/verify de firma de wallet
│   ├── deps.py          current_address · ensure_acts_as_self · require_integrity_indexes
│   ├── auth.py          ⚠️ ClaveÚnica y NFC simulados (Fase 4)
│   ├── governance.py    propuestas, votos firmados, delegación, tesorería
│   ├── elections.py     elecciones de representantes
│   └── membership.py    minteo
└── services/
    ├── siwe_service.py         nonces, recuperación de firma, JWT
    ├── chain_service.py        web3: firma y envía la transacción
    ├── ballot_service.py       EIP-712 + consumo de nonce
    ├── blockchain_service.py   orquesta minteo on-chain / demo
    ├── governance_service.py   voting_power, ciclo de elecciones
    └── membership_verifier.py  Mongo | on-chain (sin implementar a propósito)
```

**132 tests de backend, 32 de contrato.** CI con 4 jobs.

---

## Trampas concretas

1. **`OnChainMembershipVerifier` lanza `NotImplementedError` a propósito.** No lo "arregles" devolviendo `True`: eso reintroduce la capacidad fingida que el proyecto está eliminando.

2. **`generate_short_hash` no sirve para identificadores personales.** Está marcada. Usa `app.core.identity.identity_hash`.

3. **`app/services/__init__.py` exporta las instancias**, que tapan los submódulos. Para parchear en tests: `importlib.import_module("app.services.blockchain_service")`.

4. **`python-multipart` y `pymongo` no aparecen en ningún `import`** pero son obligatorias. Documentadas en `requirements.txt`.

5. **El CI instala `requirements-dev.txt`**, no `requirements.txt`.

6. **La ABI del frontend se genera**, no se edita: `cd frontend && npm run sync:abi`. Editarla a mano ya causó un bug real (A-2).

7. **Los índices únicos son la garantía, no las comprobaciones previas** de los routers: dos peticiones concurrentes pueden pasar ambas un `find_one`. Si un índice obligatorio falta, las escrituras devuelven 503.

8. **El arranque no bloquea** esperando índices (cold start de Atlas), pero `/health` distingue `healthy` de `degraded`.

9. **`CORS_ORIGINS` y `REACT_APP_BACKEND_URL` se cambian juntas**, o el navegador bloquea todo sin error visible. Para previews de Netlify existe `CORS_ORIGIN_REGEX`.

10. **Los procesos en segundo plano no sobreviven** entre comandos en entornos de sandbox.

---

## Riesgos declarados, no resueltos

Están en el ADR y se repiten aquí porque es fácil olvidarlos:

- **El operador puede emitir membresías a voluntad.** Es la consecuencia de elegir minteo custodial (D-1). Conviene decirlo en público en vez de insinuar una descentralización que no existe.
- **Si el pepper se filtra, lo ya acuñado queda reversible retroactivamente.** Lo on-chain no se puede rotar.
- **Las firmas impiden fabricar votos, no censurarlos.** Una papeleta omitida no deja rastro. La mitigación —raíz de Merkle periódica on-chain— está pendiente.

---

## Por dónde seguir

**Desbloqueado y de mayor valor:** migrar el frontend. Sin eso, la autenticación y las papeletas firmadas existen pero nadie las usa.

- Handshake de sesión: `POST /api/session/challenge` → firmar con `personal_sign` → `POST /api/session/verify` → guardar el token y mandarlo como `Authorization: Bearer`.
- Firmar papeletas con `signTypedData` usando el dominio y tipos de `ballot_service.typed_data`. Luego poner `SIGNED_BALLOTS_REQUIRED=true`.

**También desbloqueado:**

- **3.6** tesorería real desde un Safe. El backend ya responde `configured: false` honestamente.
- **3.8** mover rate limiter y antifraude a Redis: hoy viven en memoria de proceso.
- **5.1** pasar el admin del contrato a un multisig.
- **4.2/4.3** lectura PACE del chip y polyfill de `crypto` en Metro.

**Con plazo ajeno al equipo:** el trámite de acceso al sandbox de ClaveÚnica. Bloquea toda la Fase 4 y no lo controla el equipo. Conviene iniciarlo ya.

---

## Cómo trabajar aquí

Reglas completas en [`AGENTS.md`](../AGENTS.md). Las tres que más importan:

1. **Nunca inventes datos para rellenar una interfaz.** Este repositorio tuvo un dashboard con 1432 miembros falsos y una tesorería con un "Grant Ethereum Foundation" ficticio sembrado en la base. Si un dato no existe, `null` y estado vacío honesto.

2. **No marques nada como completo si no ejecutaste el camino real.** El precedente es un `test_result.md` que documentaba un protocolo de testing elaborado sin un solo resultado registrado.

3. **Verifica contra la fuente.** El README llegó a afirmar cosas que el código contradecía. Si algo es on-chain, consúltalo por RPC.
