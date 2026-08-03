# Suite E2E ZK + MACI

Esta suite levanta el frontend real en un puerto alternativo y recorre en
Chromium la emisión de una credencial ZK subsidiada y el envío de una papeleta
MACI. El backend, Pimlico, los contratos y la wallet EIP-1193 son fixtures
locales interceptados por Playwright: **el resultado no demuestra un despliegue,
una identidad civil, una ceremonia confiable ni una transacción real**.

El cliente sí carga los artefactos de desarrollo publicados por `frontend/`,
genera y verifica la prueba Groth16 localmente, deriva una Safe, firma la
UserOperation con una llave de prueba y cifra el comando MACI en el navegador.
La sesión se obtiene recorriendo challenge + firma EIP-191 + verify del fixture;
el JWT nunca se preinyecta ni queda expuesto a JavaScript. El fixture usa un
origen API separado para comprobar la cookie `HttpOnly`, el token CSRF en
memoria y el logout remoto. Ese límite también demuestra que el mensaje MACI
cifrado sale sin cookie, CSRF ni Bearer.
Las aserciones comprueban que el grant/witness de identidad no cruza el límite
de minteo y que la urna anónima no recibe bearer, wallet ni preferencia plana.
También recuperan el owner desde la única firma EIP-712 `SafeOp` solicitada a la
wallet y fijan su dominio al módulo Safe4337 aprobado y su mensaje al EntryPoint
v0.7; una firma opaca o generada por el backend no satisface la prueba.
Después de SIWE, la suite sustituye `window.ethereum` por un provider trampa:
permite lecturas RPC públicas, pero demuestra que ninguna solicitud de firma se
desvía de la instancia EIP-1193 fijada durante la sesión.
Además, el runner reconstruye el formato `snarkjs` desde el calldata Solidity y
verifica la prueba independientemente; luego descifra el ciphertext con la
llave coordinadora determinista del fixture y valida el comando y su firma.

Playwright arranca el frontend mediante `npm start`, por lo que su lifecycle
`prestart` valida el manifiesto y sincroniza los artefactos canónicos desde
`circuits/build/` antes de compilar. La suite no depende de un `public/zk`
preexistente.

```bash
cd e2e
npm ci
npx playwright install chromium
npm test
```

El frontend usa `127.0.0.1:3005` por defecto. Para cambiarlo:

```bash
E2E_FRONTEND_PORT=3015 npm test
```
