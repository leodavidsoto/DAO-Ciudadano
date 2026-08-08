# Prompt — Multi-wallet y WalletConnect en la web

> Pégale esto a un agente nuevo en `/Users/mac/DAO-Ciudadano`.
>
> **Carril:** `web` (`frontend/**`, `e2e/**`). No toques `mobile/**` ni
> `backend/**`: hay otro encargo en el carril `movil` ahora mismo.

---

Lee `AGENTS.md` antes de tocar código, en especial «Trabajo en paralelo con
varios agentes» y las reglas 11 y 12. Trabajas en una rama `tarea/multiwallet`
desde `main`.

## El problema

Un ciudadano se da de alta con su cédula en la app móvil, que le genera una
billetera y le mintea el SBT. Cuando quiere entrar a la web desde su
computadora, no puede: `frontend/src/hooks/useWallet.js` exige MetaMask
literalmente. Comprueba `isMetaMask === true` en `:103`, `:232` y `:325`, y
`:398` bloquea la restauración de sesión sin él.

Resultado: quien tiene su identidad en el móvil no tiene forma de usarla en la
web salvo instalar MetaMask e importar ahí su semilla.

## Qué hay que construir

Sustituir la detección manual de MetaMask por **wagmi + Reown AppKit**
(antes Web3Modal), que da dos cosas de una vez:

1. **Cualquier extensión inyectada** (Rabby, Brave, Coinbase, Frame…) mediante
   el conector `injected` y EIP-6963. Hoy todas fallan aunque cumplan EIP-1193.
2. **WalletConnect por QR**, que es el camino real desde el móvil: el
   ciudadano escanea el código con la app y firma el SIWE con la llave que ya
   está en el Keychain del teléfono, sin que la llave salga de ahí.

**Alcance de este encargo: solo la web.** El lado móvil de WalletConnect
—implementar `@reown/walletkit` en React Native— es un encargo aparte y hoy
colisiona con el carril `movil`. Cuando termines, la web ofrecerá el QR y lo
podrán usar wallets móviles existentes; la app propia se conectará después.

**No construyas una extensión de navegador propia.** Se evaluó y se descartó:
`mobile/src/services/walletService.ts:30` genera un mnemónico BIP-39 estándar y
`WalletScreen.tsx:241` se lo muestra al ciudadano, así que esas 12 palabras ya
se importan en MetaMask, Rabby o cualquier wallet existente. Una extensión
propia añadiría custodia de llaves y obligación de auditoría a cambio de nada.

## Las cuatro trampas de este encargo

Estas son las que te van a costar tiempo si no las sabes antes.

### 1. La CSP va a bloquear WalletConnect, y no la abras a lo bruto

`frontend/netlify.toml:47` tiene una CSP cerrada:

```
connect-src 'self' https://api.estamosdao.cl;
frame-src 'none'; img-src 'self' data: blob:;
```

WalletConnect necesita al menos el relay por WebSocket, la API del explorador
de wallets para los logos, y —si usas Verify— un iframe. **Averigua los
orígenes exactos que pide la versión que instales** y añádelos uno a uno, con
un comentario que diga para qué es cada uno. No sustituyas por `*`, no añadas
`unsafe-inline` a `script-src`, y no toques `frame-ancestors 'none'`.

Comprueba el resultado en el navegador, no en la teoría: una CSP mal puesta no
rompe el build, rompe la conexión en producción y en la consola.

### 2. Preserva P-52 — es un hallazgo de autorización, no un detalle

Lee P-52 en `docs/AUDIT.md`. Resumen: el flujo guardaba solo dirección y red, y
al firmar caía a `globalThis.ethereum`; la instancia que estableció la sesión
SIWE no quedaba fijada hasta la firma. Se corrigió haciendo que **la instancia
EIP-1193 viaje explícitamente en memoria, sin fallback global**, y revalidando
cuenta y red antes de construir y firmar.

`DashboardPage.jsx` ya pasa `eip1193Provider` y `chainId` explícitos a los
componentes de gobernanza. **Ese contrato no se rompe.** Si wagmi te tienta a
leer el proveedor de un contexto global en el momento de firmar, no lo hagas
sin revalidar antes cuenta y red contra lo que se autenticó.

El E2E que lo fija sustituye el proveedor global después del SIWE y comprueba
que ninguna solicitud de firma se desvía. **Ese test tiene que seguir pasando**;
si la migración lo invalida, reescríbelo para que pruebe lo mismo con wagmi, no
lo borres.

### 3. Hace falta una credencial que quizá no exista

AppKit exige un `projectId` de Reown Cloud. Sin él no hay WalletConnect. Este
proyecto ya tiene dos frentes parados por credenciales que nadie pidió
(Pimlico, ClaveÚnica): **si no la tienes, dilo y para**, no dejes un
`projectId` de ejemplo ni un mock. Que el camino inyectado funcione sin
`projectId` y que el QR falle cerrado con un mensaje honesto.

Va como `REACT_APP_WALLETCONNECT_PROJECT_ID` (convención CRA) y documentada en
`frontend/.env.example`.

### 4. `viem` está clavado en `2.45.0`, sin `^`

`frontend/package.json` fija `"viem": "2.45.0"` exacto. wagmi lo trae como
peer; si tu versión de wagmi exige otra, **no desclaves viem sin comprobar qué
depende de él** (`frontend/src/lib/` usa viem y ethers 6 a la vez). Y el CI
tiene un gate de `npm audit` en el job «Frontend · build»: si el árbol nuevo
mete avisos, el merge se bloquea. Compruébalo antes de darlo por hecho.

## Lo que no cambia

- **El backend no se toca.** SIWE sigue siendo el mismo challenge/verify. Firme
  quien firme —extensión o teléfono por QR—, el mensaje se liga al dominio de
  la web, así que `SIWE_DOMAIN` y `SIWE_URI` (`backend/app/core/config.py:84-85`)
  siguen siendo los de la web y no cambian.
- La identidad civil, el minteo y la gobernanza no entran aquí.
- La estética: reutiliza las clases `civic-*` de `styles/civic.css`. Las
  `cyber-*` están neutralizadas y no se usan en pantallas nuevas.

## Criterios de aceptación

Verificables, no opiniones:

1. `CI=true npx craco test --watchAll=false` en verde. Hoy son 90 tests; di
   cuántos quedan y por qué cambió el número. **Usa `craco`, no `jest` directo**
   — jest solo se salta la configuración de CRA y falla con un error del parser
   de Babel que no es un test roto.
2. Con una extensión inyectada que **no** sea MetaMask, el alta y el SIWE se
   completan. Si no tienes una a mano, dilo explícitamente en vez de darlo por
   bueno.
3. El modal muestra el QR de WalletConnect, o falla con un mensaje honesto si
   falta el `projectId`.
4. La CSP nueva está en `netlify.toml` con un comentario por origen añadido, y
   comprobada en un navegador real: cero errores de CSP en consola al conectar.
5. El E2E de P-52 sigue demostrando que la firma no se desvía a otro proveedor.
6. `npm audit` sin avisos nuevos respecto a `main`.

## Cuando termines

- Hallazgos en `docs/hallazgos/multiwallet-web.md`, con `archivo:línea` y
  severidad. **No edites `AUDIT.md`, `ROADMAP.md` ni `HANDOFF.md`.**
- Commitea y empuja en tu rama. Un encargo no está terminado hasta que su
  trabajo está commiteado.
- Si algo de lo de arriba resulta ser falso al mirarlo, **dilo en vez de
  adaptarte en silencio**. En este repositorio ya ha pasado tres veces que unos
  tests en verde confirmaran una suposición equivocada.
