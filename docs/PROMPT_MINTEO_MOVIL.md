# Prompt — Minteo móvil en producción

> Pégale esto a un agente nuevo en `/Users/mac/DAO-Ciudadano`.

---

Lee `AGENTS.md` antes de tocar código. Trabajas en la rama `codex/produccion-ci`.

## El problema

La app móvil completa el alta civil (lee la cédula por NFC, el servidor repite la
Autenticación Pasiva y emite `identity_grant` + `membership_grant`) y **ahí se
queda**. No puede mintear en producción.

`mobile/src/services/apiService.ts:122` llama a `POST /membership/mint`. Ese
endpoint tiene sus **tres** modos bloqueados en producción a propósito
(`backend/app/core/readiness.py`, función `minting_status`):

- `disabled` → bloqueado
- `demo` → «no permitido con APP_ENV=production»
- `onchain` → «ya no existe en /membership/mint; el minteo real va por /membership/mint-zk»

El cliente web sí mintea: `frontend/src/lib/api.js:206` → `mintWithProof()` →
`frontend/src/lib/erc4337.js` → `POST /erc4337/prepare-mint` y `/submit-mint`.
Es no custodial: firma el ciudadano, el backend no tiene la llave.

## Tu tarea

Que el minteo funcione desde la app móvil en producción, sin custodia.

## La decisión que tienes que tomar primero (y consultar)

Hay dos caminos y **no son equivalentes**. Decídelo con el dueño antes de
escribir código; toca D-1 en `docs/ROADMAP.md`, que `AGENTS.md` dice
explícitamente que no debe decidir un agente solo:

**A · `POST /membership/mint-zk`** — el relayer envía la prueba y **paga el gas
de la DAO**. Ya existe y funciona (`backend/app/routers/membership.py:221`), con
idempotencia y reconciliación resueltas. Exige sesión SIWE de la misma wallet.

**B · ERC-4337 + Safe**, igual que el web. El ciudadano paga o lo patrocina un
paymaster. Reutiliza los contratos de API que ya existen.

Ambos necesitan lo mismo y ahí está el trabajo real: **generar una prueba
Groth16 en el dispositivo**. `frontend/src/lib/zk.js` lo hace con snarkjs y los
artefactos `verify_identity.wasm` / `verify_identity_final.zkey`. En React
Native no hay WASM del navegador: investiga antes de comprometerte a un diseño
(módulo nativo con rapidsnark, `react-native-wasm`, o delegar la prueba). Mide
tiempo y memoria en un teléfono real, no en el emulador.

**No propongas que el backend genere la prueba con el secreto del ciudadano.**
Eso convierte el sistema en custodial y anula el sentido del circuito.

## Lo que ya tienes hecho

- `mobile/src/services/walletService.ts` — wallet real en el dispositivo
  (`ethers.Wallet.createRandom()`, BIP-39, guardada en Keychain/Keystore).
- `mobile/src/context/OnboardingContext.tsx` — los grants viven aquí, en
  memoria, y `hasUsableGrant()` ya comprueba su caducidad.
- `mobile/src/screens/SuccessScreen.tsx` — avanza solo a `Wallet` cuando hay un
  grant vivo. Cubierto por tests.
- `POST /api/identity/identity-credential` — emite la credencial y el witness de
  Merkle que alimenta el circuito.

## Archivos que vas a tocar

```
mobile/src/services/apiService.ts       mintSBT() apunta al endpoint muerto
mobile/src/screens/WalletScreen.tsx     la pantalla donde acaba el flujo
mobile/src/services/walletService.ts    la wallet ya existe
frontend/src/lib/zk.js                  LÉELO: el mismo circuito, ya resuelto en web
frontend/src/lib/erc4337.js             LÉELO si eliges el camino B
backend/app/routers/membership.py:221   mint-zk, si eliges el camino A
```

## Reglas que no puedes saltarte

- `AGENTS.md` regla 1: si un dato no existe, `null` y estado vacío honesto.
  Nunca un `tokenId` inventado ni un `tx_hash` de mentira.
- `AGENTS.md` regla 3: no marques nada como completo sin ejecutar el camino
  real. «Los tests pasan» no es lo mismo que «minteó en Sepolia».
- Regla 2: si arreglas un mock, bórralo. No lo dejes de respaldo silencioso.
- Todo hallazgo nuevo va a `docs/AUDIT.md` con `archivo:línea` y severidad.

## Aviso sobre los tests

Esta semana cayeron dos supuestos que llevaban meses en verde (P-97, el formato
del CAN; P-101, la posición del RUN). En los dos casos **el fixture reproducía
el error en vez de detectarlo**, así que cientos de tests en verde no vieron
nada. Cuando escribas un test que involucre datos de la cadena o del chip,
pregúntate qué lo haría fallar si tu suposición fuera falsa.

## Criterios de aceptación

1. Una wallet creada en el teléfono mintea contra el contrato real de Sepolia
   `0x6C6C7D0ceC1b7267cB2fa146519FBF9ef6319d56`, y su `totalSupply()` pasa de 0 a 1.
2. `GET /api/membership/member/{address}` devuelve esa membresía.
3. El backend nunca ve el secreto de identidad del ciudadano.
4. Un segundo intento con el mismo nullifier no gasta gas dos veces.
5. `cd mobile && npx jest && npx tsc --noEmit && npx eslint .` en verde.
6. Si el minteo falla, la app dice por qué; no se queda en un spinner eterno.

Cuando termines, deja el estado real en `docs/AUDIT.md`, incluido lo que **no**
lograste probar.
