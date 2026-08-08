# Producción en Sepolia — qué falta y cómo comprobarlo

Estado verificado el 07-08-2026 y recomprobado el 08-08-2026 contra el código y
contra la cadena, no contra la documentación.

La conclusión corta: **el backend ya no bloquea el alta.** Lo que falta es
configuración de despliegue, tres decisiones que no le tocan a un agente, y
**una pieza de código real: el cliente móvil no está conectado al camino de
minteo** (P-102, abajo).

---

## Lo que ya funciona

Comprobado de extremo a extremo con una cédula chilena física:

```
POST /api/auth/cedula/verify   → 200   Autenticación Pasiva contra ancla CSCA real
                                       identity_grant + membership_grant emitidos
POST /api/wallet/challenge     → 200   SIWE
POST /api/wallet/verify        → 200   firma verificada
GET  /api/membership/member/…  → 200
```

Y en la cadena, `0x6C6C7D0ceC1b7267cB2fa146519FBF9ef6319d56` (Sepolia,
chain 11155111) responde a la ABI actual: el backend le lee `membershipScope()`,
no está pausado, y la wallet del relayer tiene `ROOT_MANAGER_ROLE`.

`totalSupply()` es 0 porque nadie ha minteado todavía (recomprobado el
08-08-2026). El relayer `0x118d2C9e…` tiene ~0,0480 ETH, suficiente para
mintear.

---

## Configuración que falta

Ninguna de estas la puede poner un agente: son secretos, dominios e
infraestructura.

### Requisitos (sin ellos el arranque avisa y los endpoints devuelven 503)

| Variable | Qué exige el código | Dónde se comprueba |
| --- | --- | --- |
| `MONGO_URL` | URI `mongodb://` o `mongodb+srv://` real; en producción se rechaza `localhost` | `readiness.py:89` |
| `SECRET_KEY` | ≥32 caracteres y distinta de `dev-secret-key` | `readiness.py:103` |
| `IDENTITY_PEPPER` | ≥32 caracteres | `readiness.py:111` |
| `IDENTITY_ISSUER_PRIVATE_KEY` | llave Ethereum válida (se construye con `eth_account`) | `readiness.py:117` |
| `PII_ENCRYPTION_KEY` | clave Fernet | `readiness.py:47` |

**Cuidado con `IDENTITY_PEPPER`:** de él se deriva el `subject_key` de cada
persona. Cambiarlo después de dar de alta a alguien hace que esa misma cédula
se registre como si fuera otra persona distinta. Se pone una vez y no se rota
sin plan de migración.

### Bloqueadores de configuración

| Variable | Valor para producción | Por qué |
| --- | --- | --- |
| `DEBUG` | `false` | — |
| `CORS_ORIGINS` | orígenes exactos, nunca `*` | — |
| `SIGNED_BALLOTS_REQUIRED` | `true` | sin esto se aceptarían votos sin firma verificable |
| `SIWE_DOMAIN` | el dominio público exacto | debe coincidir con lo que firma la wallet |
| `SIWE_URI` | HTTPS, coherente con `SIWE_DOMAIN` | — |
| `REDIS_URL` | instancia real | sin ella el rate limit cuenta por proceso: con dos instancias, el límite efectivo se dobla |
| `IDENTITY_PROVIDER` | `cedula-nfc` | hoy vale `clave-unica-demo`, que no es un proveedor civil implementado |
| `MEMBERSHIP_SOURCE` | `onchain` | `mongo` es provisional; producción solo confía en la cadena |
| `MINT_MODE` | `disabled` | correcto y deliberado: el minteo real va por `/membership/mint-zk`, que no consulta esta variable |

### Cómo comprobar que quedó bien

```bash
curl -s https://TU-DOMINIO/health/ready | python3 -m json.tool
```

Debe responder **200** con `"production_ready": true`. Con 503, el propio JSON
dice qué falta en `missing`, `blockers` y `minting.zk_relayer.blockers`.

---

## Lo que el código ya no bloquea (corregido el 07-08-2026)

Dos puertas cerradas que ya no correspondían:

1. **`production_ready` era inalcanzable por construcción.** `ready` exigía que
   `/membership/mint` estuviera disponible, pero ese endpoint tiene sus tres
   modos bloqueados en producción a propósito. Ningún despliegue podía dar
   verde. Ahora en producción se exige el relayer ZK, que es el camino real.
2. **Un bloqueador fijo decía que el minteo «aún no consume una verificación de
   identidad de un solo uso».** Dejó de ser cierto con ROADMAP 1.10 / P-4.
   Informaba de un motivo falso.

Ninguna de las dos correcciones abre nada: producción sigue fallando cerrada
sin sondeo de cadena, sin `ROOT_MANAGER_ROLE` o con el RPC caído. Hay tests que
lo fijan (`test_readiness.py`).

---

## Lo que sigue abierto de verdad

### P-102 (alta) — la app móvil no puede mintear

`mobile/src/services/apiService.ts:121` llama a `POST /membership/mint`, cuyos
tres modos están bloqueados en producción a propósito. La app llega hasta el
`membership_grant` y ahí se queda, así que **quien lee su cédula con el teléfono
no obtiene membresía**. El camino real es `/membership/mint-zk`.

La web no comparte este camino: usa ERC-4337 + Safe. En curso, con la decisión
ya tomada (relayer + prueba Groth16 en WebView local): ver
`docs/PROMPT_MINTEO_MOVIL.md` y la Enmienda 1 del ADR-001.

### Antes del primer minteo: es irreversible para esa cédula

El contrato nunca limpia `_usedNullifiers`, ni siquiera al revocar
(`DAOCiudadanaSBT.sol:280`). `executeRevocation` quema el SBT y libera la
wallet, pero **la cédula no puede volver a mintear jamás en ese despliegue**, y
ni el admin puede deshacerlo (P-103). Es la propiedad anti-doble-minteo, no un
defecto.

Decide antes de la primera prueba end-to-end si gastas una cédula real o
despliegas un contrato aparte para pruebas. Desplegar es barato en Sepolia y
`contracts/` ya tiene los scripts — pero recuerda que `membershipScope` se
deriva de `address(this)`, así que las credenciales de un despliegue no valen
en otro.

### El minteo del piloto no es "producción", aunque funcione

`circuits/artifact-manifest.json` declara `productionReady: false` y
`trustedSetup: "single-host-development-integration"`. Quien corrió esa
ceremonia puede falsificar pruebas. Sirve para el piloto en testnet; no lo
llames producción en ningún commit, documento ni pantalla.

### P-98 (alta) — BouncyCastle bajado a 1.64

`mobile/android/app/build.gradle` volvió a `bcprov-jdk15on:1.64`, lo que
reintroduce **CVE-2023-33201**. El comentario del propio archivo sigue
explicando por qué se había fijado 1.74, así que ahora contradice al código.

Es plausible que el downgrade fuera necesario para que `PACEKeySpec.createMRZKey`
funcione, pero nadie lo midió. **No publiques un APK con esto sin decidirlo.**

### Decisiones de arquitectura (D-1, D-2, D-3)

`AGENTS.md` dice explícitamente que no las tome un agente solo, porque definen
custodia de llaves privadas y qué queda publicado de forma permanente sobre
cada ciudadano:

- **D-1** ¿quién mintea el SBT? Hoy es un relayer que patrocina el gas. Eso
  implica que la DAO paga y que su wallet tiene `ROOT_MANAGER_ROLE`.
- **D-2** ¿qué se escribe on-chain como `identityHash`? Falta KMS y rotación.
- **D-3** gobernanza. **El tally MACI sigue roto**: los propios tests afirman
  que una prueba auténtica del circuito es rechazada por `publishTally`
  (`contracts/test/MACI.test.js`). `private_voting: false` no es un ajuste
  pendiente, es un hecho.

### Lo que no está configurado y quizá no haga falta

- **ClaveÚnica** — sin credenciales. Con la cédula NFC funcionando, puede que
  no sea bloqueante para el piloto.
- **`TREASURY_SAFE_ADDRESS`** — la tesorería queda no disponible.

---

## Cómo se verificó esto

```bash
# Enumerar qué falta, sin adivinar
cd backend && APP_ENV=production ./.venv/bin/python -c "
from app.core import readiness
s = readiness.status()
print([m['key'] for m in s['missing']]); print(s['blockers'])"

# El contrato responde a la ABI actual
curl -s -X POST https://ethereum-sepolia-rpc.publicnode.com \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"eth_getCode","params":["0x6C6C7D0ceC1b7267cB2fa146519FBF9ef6319d56","latest"],"id":1}'
```
